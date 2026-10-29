import os
import re
import hashlib
from typing import List, Dict, Any, Optional, Set, Tuple
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
    HAS_PIL_NUMPY = True
except ImportError:
    HAS_PIL_NUMPY = False

from app.validation.base import BaseValidator, ValidationContext
from app.validation.models import (
    ValidationIssue,
    Severity,
    ErrorCode,
)


def normalize_text_for_comparison(text: str) -> str:
    """Cleans and normalizes text for duplication and similarity checks."""
    if not text:
        return ""
    # Strip LaTeX delimiters, punctuation, and extra whitespace
    t = re.sub(r'[\$(){}\[\]\\\+\-\*/=_\^.,:;?!"\'`~]', ' ', str(text).lower())
    t = re.sub(r'\s+', ' ', t).strip()
    return t


# ─────────────────────────────────────────────────────────────────────────────
# 1. Question Validator
# ─────────────────────────────────────────────────────────────────────────────
class QuestionValidator(BaseValidator):
    """Validates presence, integrity, completeness, and text structure of questions."""

    TRUNCATION_PATTERNS = [
        re.compile(r'\b(when|is|that|equal to|given by|of the|such that|where|in which|if the|then the)\s*$', re.IGNORECASE),
        re.compile(r'\b(અને|કે|જ્યારે|તો|નું મૂલ્ય|બરાબર|જેમાં|જો)\s*$', re.IGNORECASE),
    ]

    def validate(self, question: Any, context: ValidationContext) -> List[ValidationIssue]:
        issues = []
        raw_text = getattr(question, "translated_question", "") or getattr(question, "original_question", "") or ""
        q_num = str(getattr(question, "question_number", "1"))

        # 1. Check for missing/empty question text
        if not raw_text or not raw_text.strip():
            issues.append(
                ValidationIssue(
                    code=ErrorCode.QUESTION_EMPTY.value,
                    severity=Severity.CRITICAL.value,
                    field="question",
                    message="Question text is empty or missing.",
                )
            )
            return issues

        stripped = raw_text.strip()

        # 2. Check for very short / incomplete question text
        if len(stripped) < 6:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.QUESTION_INCOMPLETE.value,
                    severity=Severity.ERROR.value,
                    field="question",
                    message=f"Question text is unusually short ({len(stripped)} chars): '{stripped}'",
                )
            )

        # 3. Check for truncated endings
        for pat in self.TRUNCATION_PATTERNS:
            if pat.search(stripped) and not stripped.endswith(('?', '.', ':', '।')):
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.QUESTION_TRUNCATED.value,
                        severity=Severity.WARNING.value,
                        field="question",
                        message=f"Question text appears truncated at end: '...{stripped[-30:]}'",
                    )
                )
                break

        # 4. Check for duplicate questions in current document
        norm_txt = normalize_text_for_comparison(stripped)
        if len(norm_txt) > 20:
            if norm_txt in context.seen_texts:
                prev_q = context.seen_texts[norm_txt]
                if prev_q != q_num:
                    issues.append(
                        ValidationIssue(
                            code=ErrorCode.POSSIBLE_DUPLICATE_QUESTION.value,
                            severity=Severity.WARNING.value,
                            field="question",
                            message=f"Question text is identical or very similar to Q{prev_q}.",
                            details={"duplicate_of": prev_q},
                        )
                    )
            else:
                context.seen_texts[norm_txt] = q_num

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 2. MCQ Options Validator
# ─────────────────────────────────────────────────────────────────────────────
class MCQValidator(BaseValidator):
    """Validates MCQ option existence, non-emptiness, deduplication, and order."""

    def validate(self, question: Any, context: ValidationContext) -> List[ValidationIssue]:
        issues = []
        q_type = str(getattr(question, "question_type", "MCQ") or "MCQ").upper()
        if "NUMERIC" in q_type or "INTEGER" in q_type or "NAT" in q_type:
            return issues  # Numerical questions do not require MCQ options

        options = getattr(question, "options", None)
        expected_keys = context.expected_option_labels or ["A", "B", "C", "D"]

        if not options:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.MISSING_OPTION.value,
                    severity=Severity.CRITICAL.value,
                    field="options",
                    message=f"No options found for MCQ question. Expected {', '.join(expected_keys)}.",
                )
            )
            return issues

        # Normalise options dictionary
        opt_dict = {}
        if isinstance(options, dict):
            opt_dict = options
        elif isinstance(options, list):
            for item in options:
                if isinstance(item, dict):
                    k = str(item.get("key", "")).upper()
                    if k:
                        opt_dict[k] = item

        seen_option_contents: Dict[str, str] = {}
        present_keys = []

        for exp_key in expected_keys:
            opt_obj = opt_dict.get(exp_key)
            if opt_obj is None:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.MISSING_OPTION.value,
                        severity=Severity.ERROR.value,
                        field=f"options.{exp_key}",
                        message=f"Option {exp_key} is missing.",
                        details={"missing_key": exp_key},
                    )
                )
                continue

            present_keys.append(exp_key)

            # Retrieve text and image flags
            orig_txt = ""
            trans_txt = ""
            has_img = False
            img_url = None

            if isinstance(opt_obj, dict):
                orig_txt = str(opt_obj.get("original", "") or "")
                trans_txt = str(opt_obj.get("translated", "") or "")
                has_img = bool(opt_obj.get("has_image", False))
                img_url = opt_obj.get("image_url")
            else:
                orig_txt = str(getattr(opt_obj, "original", "") or "")
                trans_txt = str(getattr(opt_obj, "translated", "") or "")
                has_img = bool(getattr(opt_obj, "has_image", False))
                img_url = getattr(opt_obj, "image_url", None)

            content = trans_txt.strip() or orig_txt.strip()

            # Empty option check
            if not content and not has_img and not img_url:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.EMPTY_OPTION.value,
                        severity=Severity.ERROR.value,
                        field=f"options.{exp_key}",
                        message=f"Option {exp_key} is empty (no text and no diagram).",
                        details={"empty_key": exp_key},
                    )
                )
            elif content:
                # Check for option mixing (e.g. Q11 or question text leaked into option)
                if re.match(r'^(?:Q(?:uestion)?\s*\d+[\.:\s]|(?:પ્રશ્ન|प्रश्न)\s*\d+)', content, re.IGNORECASE):
                    issues.append(
                        ValidationIssue(
                            code=ErrorCode.OPTION_MIXING_ERROR.value,
                            severity=Severity.ERROR.value,
                            field=f"options.{exp_key}",
                            message=f"Option {exp_key} contains question number/header text: '{content[:40]}...'",
                        )
                    )

                # Duplicate option text check
                norm_opt = normalize_text_for_comparison(content)
                if norm_opt and len(norm_opt) >= 1:
                    if norm_opt in seen_option_contents:
                        prev_key = seen_option_contents[norm_opt]
                        issues.append(
                            ValidationIssue(
                                code=ErrorCode.DUPLICATE_OPTION.value,
                                severity=Severity.WARNING.value,
                                field=f"options.{exp_key}",
                                message=f"Option {exp_key} has duplicate content identical to Option {prev_key}: '{content}'",
                                details={"duplicate_keys": [prev_key, exp_key]},
                            )
                        )
                    else:
                        seen_option_contents[norm_opt] = exp_key

        # Option Order validation
        if len(present_keys) >= 2:
            sorted_keys = sorted(present_keys)
            if present_keys != sorted_keys:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.OPTION_ORDER_ERROR.value,
                        severity=Severity.WARNING.value,
                        field="options",
                        message=f"Option keys are not in sequential order: {present_keys}",
                    )
                )

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 3. Answer Validator
# ─────────────────────────────────────────────────────────────────────────────
class AnswerValidator(BaseValidator):
    """Validates answer presence and consistency against MCQ options."""

    def validate(self, question: Any, context: ValidationContext) -> List[ValidationIssue]:
        issues = []
        ans = getattr(question, "answer", None)
        q_type = str(getattr(question, "question_type", "MCQ") or "MCQ").upper()
        is_numeric = "NUMERIC" in q_type or "INTEGER" in q_type or "NAT" in q_type

        if not ans or not str(ans).strip():
            # If answer is missing, record error
            issues.append(
                ValidationIssue(
                    code=ErrorCode.ANSWER_MISSING.value,
                    severity=Severity.WARNING.value,
                    field="answer",
                    message="Answer key is missing.",
                )
            )
            return issues

        ans_str = str(ans).strip().upper()

        if not is_numeric:
            expected_keys = [k.upper() for k in (context.expected_option_labels or ["A", "B", "C", "D"])]
            # Check if answer is a single valid option label
            if ans_str not in expected_keys:
                # Sometimes answer might be "(A)" or "Option A"
                clean_m = re.search(r'([A-E])', ans_str)
                if not clean_m or clean_m.group(1) not in expected_keys:
                    issues.append(
                        ValidationIssue(
                            code=ErrorCode.INVALID_ANSWER.value,
                            severity=Severity.ERROR.value,
                            field="answer",
                            message=f"Answer '{ans}' is invalid. Expected one of {expected_keys}.",
                            details={"answer": str(ans)},
                        )
                    )

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 4. LaTeX Validator
# ─────────────────────────────────────────────────────────────────────────────
class LatexValidator(BaseValidator):
    """Validates LaTeX math delimiters, curly braces balance, and syntax."""

    def _check_string_latex(self, text: str, field_name: str) -> List[ValidationIssue]:
        issues = []
        if not text:
            return issues

        # 1. Check unbalanced single dollars ($...$)
        # Strip escaped dollars first
        cleaned = text.replace(r'\$', '')
        # Count double dollars
        double_dollar_count = cleaned.count('$$')
        without_double = cleaned.replace('$$', '')
        single_dollar_count = without_double.count('$')

        if single_dollar_count % 2 != 0:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.LATEX_UNCLOSED.value,
                    severity=Severity.ERROR.value,
                    field=field_name,
                    message=f"Unclosed single-dollar LaTeX delimiter in {field_name}.",
                )
            )

        if double_dollar_count % 2 != 0:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.LATEX_DELIMITER_ERROR.value,
                    severity=Severity.ERROR.value,
                    field=field_name,
                    message=f"Unclosed double-dollar ($$) LaTeX delimiter in {field_name}.",
                )
            )

        # 2. Check mismatched \( and \) or \[ and \]
        open_paren_math = text.count(r'\(')
        close_paren_math = text.count(r'\)')
        if open_paren_math != close_paren_math:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.LATEX_DELIMITER_ERROR.value,
                    severity=Severity.ERROR.value,
                    field=field_name,
                    message=f"Mismatched LaTeX \\( and \\) delimiters in {field_name}.",
                )
            )

        open_bracket_math = text.count(r'\[')
        close_bracket_math = text.count(r'\]')
        if open_bracket_math != close_bracket_math:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.LATEX_DELIMITER_ERROR.value,
                    severity=Severity.ERROR.value,
                    field=field_name,
                    message=f"Mismatched LaTeX \\[ and \\] delimiters in {field_name}.",
                )
            )

        # 3. Check balanced curly braces inside LaTeX blocks
        # Extract all math blocks: $$...$$, $...$, \(...\), \[...\]
        math_blocks = re.findall(r'\$\$(.*?)\$\$|\$(.*?)\$|\\\((.*?)\\\)|\\\[(.*?)\\\]', text, re.DOTALL)
        for group in math_blocks:
            math_expr = next((g for g in group if g), "")
            if not math_expr:
                continue

            open_braces = 0
            close_braces = 0
            for i, ch in enumerate(math_expr):
                if ch == "{" and (i == 0 or math_expr[i - 1] != "\\"):
                    open_braces += 1
                elif ch == "}" and (i == 0 or math_expr[i - 1] != "\\"):
                    close_braces += 1

            if open_braces != close_braces:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.LATEX_BRACE_ERROR.value,
                        severity=Severity.ERROR.value,
                        field=field_name,
                        message=f"Unbalanced braces in LaTeX expression '${math_expr[:35]}...' ({open_braces} open vs {close_braces} close).",
                        details={"expression": math_expr},
                    )
                )

            # Check broken commands like \frac{ without closing or dangling backslash
            if re.search(r'\\[a-zA-Z]+\s*$', math_expr):
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.LATEX_SUSPICIOUS.value,
                        severity=Severity.WARNING.value,
                        field=field_name,
                        message=f"Truncated LaTeX command at end of expression: '${math_expr[-20:]}'",
                    )
                )

        return issues

    def validate(self, question: Any, context: ValidationContext) -> List[ValidationIssue]:
        issues = []
        q_text = getattr(question, "translated_question", "") or getattr(question, "original_question", "") or ""
        issues.extend(self._check_string_latex(q_text, "question"))

        options = getattr(question, "options", None)
        if isinstance(options, dict):
            for opt_k, opt_v in options.items():
                if opt_v:
                    o_txt = getattr(opt_v, "translated", "") or getattr(opt_v, "original", "") or ""
                    issues.extend(self._check_string_latex(o_txt, f"options.{opt_k}"))
        elif isinstance(options, list):
            for opt_item in options:
                if isinstance(opt_item, dict):
                    k = opt_item.get("key", "")
                    o_txt = opt_item.get("translated", "") or opt_item.get("original", "") or ""
                    issues.extend(self._check_string_latex(o_txt, f"options.{k}"))

        sol_text = getattr(question, "solution", "") or ""
        if sol_text:
            issues.extend(self._check_string_latex(sol_text, "solution"))

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 5. Image & Diagram Validator
# ─────────────────────────────────────────────────────────────────────────────
class ImageValidator(BaseValidator):
    """Validates diagram expectation in text, image file existence, bounding boxes, and blankness."""

    FIGURE_KEYWORDS = [
        re.compile(r'\b(shown in (?:the )?figure|refer to (?:the )?(?:figure|diagram)|in the given (?:figure|diagram)|circuit diagram|schematic|graph below|plot below)\b', re.IGNORECASE),
        re.compile(r'\b(આકૃતિમાં દર્શાવ્યા|આપેલ પરિપથ|આકૃતિ|પરિપથ મુજબ|આલેખ પરથી|દર્શાવેલ પરિપથ)\b', re.IGNORECASE),
        re.compile(r'\b(चित्र में|दिए गए चित्र|परिपथ|आरेख)\b', re.IGNORECASE),
    ]

    def _parse_bbox(self, box: Any) -> Optional[Tuple[float, float, float, float]]:
        if not box:
            return None
        try:
            if isinstance(box, dict):
                if "box_2d" in box and len(box["box_2d"]) >= 4:
                    return tuple(float(x) for x in box["box_2d"][:4])
                elif "bbox" in box and len(box["bbox"]) >= 4:
                    return tuple(float(x) for x in box["bbox"][:4])
                elif "coords" in box and len(box["coords"]) >= 4:
                    return tuple(float(x) for x in box["coords"][:4])
                else:
                    return (
                        float(box.get("ymin", box.get("top", 0))),
                        float(box.get("xmin", box.get("left", 0))),
                        float(box.get("ymax", box.get("bottom", 0))),
                        float(box.get("xmax", box.get("right", 0))),
                    )
            elif isinstance(box, (list, tuple)) and len(box) >= 4:
                return tuple(float(x) for x in box[:4])
            elif isinstance(box, str):
                nums = re.findall(r'[-+]?\d*\.?\d+', box)
                if len(nums) >= 4:
                    return tuple(float(x) for x in nums[:4])
        except Exception:
            pass
        return None

    def _check_image_blankness_and_hash(self, img_path: Path, q_num: str, context: ValidationContext) -> List[ValidationIssue]:
        issues = []
        if not img_path.exists() or not HAS_PIL_NUMPY:
            return issues

        try:
            with Image.open(img_path) as pil_img:
                w, h = pil_img.size
                if w < 20 or h < 20:
                    issues.append(
                        ValidationIssue(
                            code=ErrorCode.IMAGE_CROP_TOO_SMALL.value,
                            severity=Severity.ERROR.value,
                            field="image",
                            message=f"Cropped image dimensions are too small ({w}x{h} px).",
                        )
                    )
                    return issues

                # Blank pixel analysis
                gray = pil_img.convert('L')
                arr = np.array(gray)
                dark_pixels = np.sum(arr < 235)
                total_pixels = arr.size
                dark_ratio = dark_pixels / max(1, total_pixels)

                if dark_ratio < 0.005:  # Less than 0.5% non-white ink
                    issues.append(
                        ValidationIssue(
                            code=ErrorCode.IMAGE_CROP_MOSTLY_BLANK.value,
                            severity=Severity.ERROR.value,
                            field="image",
                            message=f"Cropped image is mostly blank/empty ({round((1 - dark_ratio) * 100, 1)}% white pixels).",
                        )
                    )

                # MD5 hash check for duplicate images
                with open(img_path, "rb") as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()

                if file_hash in context.image_hashes:
                    context.image_hashes[file_hash].append(q_num)
                    prev_qs = [q for q in context.image_hashes[file_hash] if q != q_num]
                    if prev_qs:
                        issues.append(
                            ValidationIssue(
                                code=ErrorCode.POSSIBLE_DUPLICATE_IMAGE.value,
                                severity=Severity.INFO.value,
                                field="image",
                                message=f"This image file is identical to image used in Q{', Q'.join(prev_qs)}.",
                                details={"duplicate_with_questions": prev_qs},
                            )
                        )
                else:
                    context.image_hashes[file_hash] = [q_num]

        except Exception as e:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.IMAGE_EXTRACTION_ERROR.value,
                    severity=Severity.WARNING.value,
                    field="image",
                    message=f"Failed to inspect image file: {e}",
                )
            )

        return issues

    def validate(self, question: Any, context: ValidationContext) -> List[ValidationIssue]:
        issues = []
        q_num = str(getattr(question, "question_number", "1"))
        q_text = getattr(question, "translated_question", "") or getattr(question, "original_question", "") or ""
        has_q_image = bool(getattr(question, "has_question_image", False))
        img_url = getattr(question, "image_url", None)
        img_box = getattr(question, "image_box", None)

        # 1. Check if question text mentions diagram but no image was extracted
        text_requires_image = any(pat.search(q_text) for pat in self.FIGURE_KEYWORDS)
        if text_requires_image and not has_q_image and not img_url:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.IMAGE_MISSING.value,
                    severity=Severity.ERROR.value,
                    field="image",
                    message="Question text explicitly refers to a figure/diagram, but no image was extracted.",
                )
            )

        # 2. Check bounding box validity if present
        if img_box:
            bbox = self._parse_bbox(img_box)
            if bbox is None:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.IMAGE_CROP_INVALID.value,
                        severity=Severity.ERROR.value,
                        field="image_box",
                        message="Image bounding box format is invalid.",
                    )
                )
            else:
                ymin, xmin, ymax, xmax = bbox
                if ymax <= ymin or xmax <= xmin:
                    issues.append(
                        ValidationIssue(
                            code=ErrorCode.IMAGE_CROP_INVALID.value,
                            severity=Severity.ERROR.value,
                            field="image_box",
                            message=f"Invalid bounding box boundaries: [{ymin}, {xmin}, {ymax}, {xmax}].",
                        )
                    )
                else:
                    max_c = max(ymin, xmin, ymax, xmax)
                    # Normalized 0..1 coordinates
                    if max_c <= 1.05:
                        w_norm = xmax - xmin
                        h_norm = ymax - ymin
                        if w_norm < 0.015 or h_norm < 0.015:
                            issues.append(
                                ValidationIssue(
                                    code=ErrorCode.IMAGE_CROP_TOO_SMALL.value,
                                    severity=Severity.ERROR.value,
                                    field="image_box",
                                    message=f"Bounding box is suspiciously small: {round(w_norm*100, 1)}% x {round(h_norm*100, 1)}% of page.",
                                )
                            )
                        elif w_norm > 0.95 and h_norm > 0.92:
                            issues.append(
                                ValidationIssue(
                                    code=ErrorCode.IMAGE_CROP_TOO_LARGE.value,
                                    severity=Severity.WARNING.value,
                                    field="image_box",
                                    message="Bounding box spans almost entire page (suspicious full-page capture).",
                                )
                            )
                    elif max_c <= 1005.0:
                        w_norm = (xmax - xmin) / 1000.0
                        h_norm = (ymax - ymin) / 1000.0
                        if w_norm < 0.015 or h_norm < 0.015:
                            issues.append(
                                ValidationIssue(
                                    code=ErrorCode.IMAGE_CROP_TOO_SMALL.value,
                                    severity=Severity.ERROR.value,
                                    field="image_box",
                                    message="Bounding box is suspiciously small.",
                                )
                            )
                        elif w_norm > 0.95 and h_norm > 0.92:
                            issues.append(
                                ValidationIssue(
                                    code=ErrorCode.IMAGE_CROP_TOO_LARGE.value,
                                    severity=Severity.WARNING.value,
                                    field="image_box",
                                    message="Bounding box spans almost entire page.",
                                )
                            )

        # 3. Check physical image file existence & content on disk
        if img_url:
            img_name = str(img_url).split("/")[-1]
            base_dir = Path(context.images_dir) if context.images_dir else (Path(__file__).resolve().parent.parent.parent / "extracted_images")
            img_path = base_dir / img_name
            if not img_path.exists():
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.IMAGE_EXTRACTION_ERROR.value,
                        severity=Severity.ERROR.value,
                        field="image",
                        message=f"Extracted image file '{img_name}' not found on server disk.",
                    )
                )
            else:
                issues.extend(self._check_image_blankness_and_hash(img_path, q_num, context))

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 6. OCR & Text Quality Validator
# ─────────────────────────────────────────────────────────────────────────────
class OCRValidator(BaseValidator):
    """Detects suspicious OCR garbage patterns and excessive symbol corruption."""

    GARBAGE_PATTERNS = [
        re.compile(r'[@#%^~`_]{4,}'),
        re.compile(r'[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]'),  # Replacement character or non-printable ASCII
        re.compile(r'(?:[?]{4,}|[!]{4,})'),
    ]

    def validate(self, question: Any, context: ValidationContext) -> List[ValidationIssue]:
        issues = []
        raw_text = getattr(question, "translated_question", "") or getattr(question, "original_question", "") or ""

        for pat in self.GARBAGE_PATTERNS:
            m = pat.search(raw_text)
            if m:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.OCR_SUSPICIOUS.value,
                        severity=Severity.WARNING.value,
                        field="question",
                        message=f"Suspicious OCR symbol sequence detected: '{m.group(0)[:15]}'",
                    )
                )
                break

        return issues


# ─────────────────────────────────────────────────────────────────────────────
# 7. Solution & Translation Validator
# ─────────────────────────────────────────────────────────────────────────────
class SolutionValidator(BaseValidator):
    """Validates solution text and consistency."""

    def validate(self, question: Any, context: ValidationContext) -> List[ValidationIssue]:
        issues = []
        sol = getattr(question, "solution", "") or ""
        if sol and len(sol.strip()) > 0:
            # Check if solution contains question mixing
            if re.match(r'^(?:Q(?:uestion)?\s*\d+[\.:\s]|(?:પ્રશ્ન|प्रश्न)\s*\d+)', sol.strip(), re.IGNORECASE):
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.SOLUTION_MIXING.value,
                        severity=Severity.WARNING.value,
                        field="solution",
                        message=f"Solution text starts with a question header: '{sol[:35]}...'",
                    )
                )

        return issues


class TranslationValidator(BaseValidator):
    """Validates translation completeness when translation is enabled."""

    def validate(self, question: Any, context: ValidationContext) -> List[ValidationIssue]:
        issues = []
        src_lang = str(getattr(question, "original_language", "") or context.source_language or "").lower()
        tgt_lang = str(getattr(question, "target_language", "") or context.target_language or "").lower()

        # If translation was specifically requested and languages differ
        if tgt_lang and tgt_lang != "original" and src_lang and src_lang != "original" and tgt_lang != src_lang:
            trans_q = getattr(question, "translated_question", "") or ""
            if not trans_q or not trans_q.strip():
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.TRANSLATION_MISSING.value,
                        severity=Severity.WARNING.value,
                        field="translated_question",
                        message=f"Translation to {tgt_lang} is missing for this question.",
                    )
                )

        return issues
