import re
from typing import List, Dict, Any, Optional, Union
from pathlib import Path

from app.validation.base import BaseValidator, ValidationContext
from app.validation.models import (
    ValidationIssue,
    ValidationChecks,
    QuestionValidation,
    ValidationSummary,
    Severity,
    QualityStatus,
    ErrorCode,
)
from app.validation.validators import (
    QuestionValidator,
    MCQValidator,
    AnswerValidator,
    LatexValidator,
    ImageValidator,
    OCRValidator,
    SolutionValidator,
    TranslationValidator,
)


class QualityValidationEngine:
    """Master Quality Validation & Error Detection Engine for MCQ extractions."""

    def __init__(self, validators: Optional[List[BaseValidator]] = None):
        self.validators = validators or [
            QuestionValidator(),
            MCQValidator(),
            AnswerValidator(),
            LatexValidator(),
            ImageValidator(),
            OCRValidator(),
            SolutionValidator(),
            TranslationValidator(),
        ]

    def _extract_numeric_qnum(self, q_num: Any) -> Optional[int]:
        m = re.search(r'\d+', str(q_num))
        if m:
            try:
                return int(m.group(0))
            except Exception:
                pass
        return None

    def analyze_sequence_gaps(self, questions: List[Any]) -> Tuple[List[int], List[int], List[str]]:
        """
        Detects missing question numbers, duplicate numbers, and sequence anomalies.
        Returns (missing_numbers, duplicate_numbers, extra_numbers)
        """
        nums = []
        seen = set()
        duplicates = []

        for q in questions:
            q_str = str(getattr(q, "question_number", ""))
            n = self._extract_numeric_qnum(q_str)
            if n is not None:
                if n in seen:
                    duplicates.append(n)
                else:
                    seen.add(n)
                nums.append(n)

        missing = []
        extra = []
        if nums:
            sorted_unique = sorted(list(seen))
            min_n = sorted_unique[0]
            max_n = sorted_unique[-1]
            
            # If standard 1-based test paper
            expected_start = 1 if min_n <= 2 else min_n
            for expected_num in range(expected_start, max_n + 1):
                if expected_num not in seen:
                    missing.append(expected_num)

        return missing, duplicates, extra

    def validate_question(self, question: Any, context: ValidationContext) -> QuestionValidation:
        """Validates a single question across all registered validator rules."""
        issues: List[ValidationIssue] = []

        for val in self.validators:
            try:
                sub_issues = val.validate(question, context)
                if sub_issues:
                    issues.extend(sub_issues)
            except Exception as e:
                issues.append(
                    ValidationIssue(
                        code="VALIDATOR_INTERNAL_ERROR",
                        severity=Severity.WARNING.value,
                        field="validator",
                        message=f"Validator error ({val.__class__.__name__}): {e}",
                    )
                )

        # Build Checks boolean summary
        checks = ValidationChecks(
            question=not any(i.field in ("question", "translated_question") and i.severity in (Severity.CRITICAL.value, Severity.ERROR.value) for i in issues),
            mcq=not any("option" in i.field and i.severity in (Severity.CRITICAL.value, Severity.ERROR.value) for i in issues),
            latex=not any("latex" in i.code.lower() and i.severity in (Severity.CRITICAL.value, Severity.ERROR.value) for i in issues),
            image=not any("image" in i.field and i.severity in (Severity.CRITICAL.value, Severity.ERROR.value) for i in issues),
            answer=not any(i.field == "answer" and i.severity in (Severity.CRITICAL.value, Severity.ERROR.value) for i in issues),
            solution=not any(i.field == "solution" and i.severity in (Severity.CRITICAL.value, Severity.ERROR.value) for i in issues),
            translation=not any("translation" in i.code.lower() for i in issues),
        )

        # Determine overall question QualityStatus
        has_critical = any(i.severity == Severity.CRITICAL.value for i in issues)
        has_error = any(i.severity == Severity.ERROR.value for i in issues)
        has_warning = any(i.severity == Severity.WARNING.value for i in issues)

        if has_critical:
            status = QualityStatus.CRITICAL.value
        elif has_error:
            status = QualityStatus.FAULT.value
        elif has_warning:
            status = QualityStatus.WARNING.value
        else:
            status = QualityStatus.PERFECT.value

        # Calculate Score (0-100)
        score = 100.0
        for i in issues:
            if i.severity == Severity.CRITICAL.value:
                score -= 30.0
            elif i.severity == Severity.ERROR.value:
                score -= 15.0
            elif i.severity == Severity.WARNING.value:
                score -= 5.0
        score = max(0.0, min(100.0, score))

        return QuestionValidation(
            status=status,
            score=round(score, 1),
            checks=checks,
            errors=issues,
        )

    def validate_extraction_result(
        self,
        result: Any,
        images_dir: Optional[str] = None,
    ) -> ValidationSummary:
        """Validates all questions in an ExtractionResult and populates summary statistics."""
        questions = getattr(result, "questions", []) or []
        summary = ValidationSummary()
        summary.total_questions = len(questions)

        if not questions:
            return summary

        context = ValidationContext(
            file_name=getattr(result, "file_name", ""),
            total_pages=getattr(result, "total_pages_scanned", 1),
            source_language=getattr(result, "source_language", "Original"),
            target_language=getattr(result, "target_language", "Original"),
            all_questions=questions,
            images_dir=images_dir,
        )

        # 1. Sequence & Number Gap Analysis
        missing_nums, dup_nums, extra_nums = self.analyze_sequence_gaps(questions)
        summary.missing_questions = len(missing_nums)
        summary.missing_question_numbers = missing_nums
        summary.extra_questions = len(extra_nums)
        summary.extra_question_numbers = extra_nums

        total_score_sum = 0.0

        for q in questions:
            q_val = self.validate_question(q, context)
            
            # Attach validation result to question item (dict or pydantic model)
            if hasattr(q, "validation"):
                setattr(q, "validation", q_val)
            elif isinstance(q, dict):
                q["validation"] = q_val.model_dump()

            total_score_sum += q_val.score

            # Tally question level statuses
            if q_val.status == QualityStatus.PERFECT.value:
                summary.perfect_questions += 1
            elif q_val.status == QualityStatus.WARNING.value:
                summary.warning_questions += 1
            elif q_val.status == QualityStatus.FAULT.value:
                summary.faulty_questions += 1
            elif q_val.status == QualityStatus.CRITICAL.value:
                summary.critical_questions += 1

            # Check if this question has LaTeX math
            q_text = str(getattr(q, "translated_question", "") or getattr(q, "original_question", "") or "")
            has_latex = "$" in q_text or r"\(" in q_text or r"\[" in q_text
            if has_latex:
                summary.latex_questions += 1

            has_q_image = bool(getattr(q, "has_question_image", False) or getattr(q, "image_url", None))
            if has_q_image:
                summary.total_images_expected_or_found += 1

            # Tally error categories
            q_has_mcq_fault = False
            q_has_latex_fault = False
            q_has_image_fault = False

            for err in q_val.errors:
                code = err.code

                # MCQ errors
                if code == ErrorCode.MISSING_OPTION.value:
                    summary.missing_options += 1
                    q_has_mcq_fault = True
                    k = err.details.get("missing_key") if err.details else None
                    if not k and "." in err.field:
                        k = err.field.split(".")[-1].upper()
                    if k in summary.missing_options_breakdown:
                        summary.missing_options_breakdown[k] += 1

                elif code == ErrorCode.EMPTY_OPTION.value:
                    summary.empty_options += 1
                    q_has_mcq_fault = True
                    k = err.details.get("empty_key") if err.details else None
                    if not k and "." in err.field:
                        k = err.field.split(".")[-1].upper()
                    if k in summary.empty_options_breakdown:
                        summary.empty_options_breakdown[k] += 1

                elif code == ErrorCode.DUPLICATE_OPTION.value:
                    summary.duplicate_options += 1
                    q_has_mcq_fault = True

                elif code == ErrorCode.INVALID_ANSWER.value:
                    summary.invalid_answers += 1
                    q_has_mcq_fault = True

                # LaTeX errors
                elif code == ErrorCode.LATEX_UNCLOSED.value:
                    summary.latex_unclosed += 1
                    q_has_latex_fault = True
                elif code == ErrorCode.LATEX_BRACE_ERROR.value:
                    summary.latex_brace_errors += 1
                    q_has_latex_fault = True
                elif code == ErrorCode.LATEX_DELIMITER_ERROR.value:
                    summary.latex_delimiter_errors += 1
                    q_has_latex_fault = True
                elif code == ErrorCode.LATEX_RENDER_ERROR.value:
                    summary.latex_render_errors += 1
                    q_has_latex_fault = True

                # Image errors
                elif code == ErrorCode.IMAGE_MISSING.value:
                    summary.missing_images += 1
                    q_has_image_fault = True
                elif code in (
                    ErrorCode.IMAGE_CROP_INVALID.value,
                    ErrorCode.IMAGE_CROP_TOO_SMALL.value,
                    ErrorCode.IMAGE_CROP_TOO_LARGE.value,
                    ErrorCode.IMAGE_CROP_OUT_OF_BOUNDS.value,
                    ErrorCode.IMAGE_CROP_MOSTLY_BLANK.value,
                    ErrorCode.IMAGE_CROP_SUSPICIOUS.value,
                ):
                    summary.image_crop_errors += 1
                    q_has_image_fault = True
                elif code == ErrorCode.IMAGE_EXTRACTION_ERROR.value:
                    summary.image_extraction_errors += 1
                    q_has_image_fault = True
                elif code == ErrorCode.POSSIBLE_DUPLICATE_IMAGE.value:
                    summary.duplicate_images += 1

                # OCR & Duplicate Question
                elif code == ErrorCode.OCR_SUSPICIOUS.value:
                    summary.ocr_warnings += 1
                elif code in (ErrorCode.DUPLICATE_QUESTION.value, ErrorCode.POSSIBLE_DUPLICATE_QUESTION.value):
                    summary.duplicate_questions += 1

            if q_has_mcq_fault:
                summary.mcq_faults += 1
            if q_has_latex_fault:
                summary.latex_faults += 1
            if q_has_image_fault:
                summary.image_faults += 1

        summary.valid_latex = max(0, summary.latex_questions - summary.latex_faults)
        summary.valid_images = max(0, summary.total_images_expected_or_found - summary.image_faults)

        if summary.total_questions > 0:
            summary.quality_score = round(total_score_sum / summary.total_questions, 1)
        else:
            summary.quality_score = 100.0

        return summary
