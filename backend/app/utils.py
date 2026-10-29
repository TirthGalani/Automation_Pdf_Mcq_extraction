import io
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
from PIL import Image as PILImage
import openpyxl
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from app.models import ExtractionResult
from app.logger import get_logger

logger = get_logger("utils")

IMAGES_DIR = Path(__file__).resolve().parent.parent / "extracted_images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def repair_json_escapes(raw: str) -> str:
    r"""
    Robustly repairs unescaped LaTeX backslashes inside JSON string literals.
    Handles LaTeX macros like \alpha, \beta, \frac, \sqrt, \text, \theta, \times, etc.
    """
    if not raw:
        return raw

    # 1. Clean markdown code fences if present anywhere in text
    cleaned = raw.strip()
    code_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', cleaned)
    if code_match:
        cleaned = code_match.group(1).strip()
    elif cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    # Known LaTeX commands that start with standard JSON escape letters (\b, \f, \n, \r, \t)
    latex_collisions = [
        "frac", "beta", "bar", "begin", "bmatrix", "bold", "boldsymbol", "bullet", "bot",
        "theta", "times", "tau", "tan", "text", "tilde", "to", "top", "triangle", "true",
        "rho", "right", "rangle", "rightarrow", "Rightarrow", "Re", "root",
        "nu", "nabla", "neq", "not", "notin", "nearrow", "nwarrow",
        "alpha", "approx", "ast", "aleph", "angle", "arg",
        "gamma", "geq", "gg",
        "delta", "Delta", "deg", "div", "dot", "ddot",
        "epsilon", "eta", "equiv", "exists", "exp",
        "zeta",
        "iota", "int", "infty", "in", "iff", "im", "index",
        "kappa",
        "lambda", "Lambda", "left", "langle", "leq", "ll", "lim", "log", "ln",
        "mu", "mp", "mid", "matrix", "max", "min",
        "xi",
        "pi", "Pi", "phi", "Phi", "pm", "prod", "partial", "perp", "pmatrix",
        "sigma", "Sigma", "sqrt", "sum", "sim", "simeq", "subset", "subseteq", "sin", "sec",
        "upsilon",
        "chi",
        "psi", "Psi",
        "omega", "Omega", "oint", "oplus", "otimes",
        "vec", "vee", "wedge", "widehat", "widetilde",
        "hat", "over", "underline", "quad", "qquad"
    ]

    # Fix known LaTeX collision macros starting with \b, \f, \t, \r, \n
    for macro in latex_collisions:
        cleaned = re.sub(r'(?<!\\)\\' + macro, r'\\\\' + macro, cleaned)

    # Fix any other unescaped single backslash not followed by valid JSON escape character
    cleaned = re.sub(r'(?<!\\)\\(?![/\\\"bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', cleaned)

    return cleaned


def extract_json_from_response(text: str) -> Dict[str, Any]:
    """Robustly extracts and parses JSON from Gemini/Gemma response text, handling raw LaTeX backslashes and reasoning tokens."""
    if not text:
        return {"questions": []}

    # 0. Primary strategy for reasoning/thinking models (e.g. Gemma 4 26B, DeepSeek):
    # Search for markdown code blocks anywhere in text, evaluating the last/cleanest JSON block first
    code_matches = re.findall(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if code_matches:
        for block in reversed(code_matches):
            blk_clean = block.strip()
            for cand in [repair_json_escapes(blk_clean), blk_clean]:
                try:
                    parsed = json.loads(cand, strict=False)
                    if isinstance(parsed, dict) and "questions" in parsed and isinstance(parsed["questions"], list) and len(parsed["questions"]) > 0:
                        if not all(q.get("original_question") == "..." for q in parsed["questions"] if isinstance(q, dict)):
                            return parsed
                    if isinstance(parsed, list) and len(parsed) > 0:
                        if isinstance(parsed[0], dict) and "questions" in parsed[0]:
                            flat_qs = []
                            for page in parsed:
                                if isinstance(page, dict) and "questions" in page and isinstance(page["questions"], list):
                                    flat_qs.extend(page["questions"])
                            if flat_qs and not all(q.get("original_question") == "..." for q in flat_qs if isinstance(q, dict)):
                                return {"questions": flat_qs}
                        if not all(isinstance(q, dict) and q.get("original_question") == "..." for q in parsed):
                            return {"questions": parsed}
                    if isinstance(parsed, dict):
                        for alt_key in ["mcqs", "data", "items", "results"]:
                            if alt_key in parsed and isinstance(parsed[alt_key], list) and len(parsed[alt_key]) > 0:
                                return {"questions": parsed[alt_key]}
                except Exception:
                    pass

    # 0.5 Specifically search for JSON object with "questions": [...] in the text
    q_obj_match = re.search(r'(\{\s*"questions"\s*:\s*\[[\s\S]*?\]\s*\})', text)
    if q_obj_match:
        cand = q_obj_match.group(1).strip()
        for c in [repair_json_escapes(cand), cand]:
            try:
                parsed = json.loads(c, strict=False)
                if isinstance(parsed, dict) and "questions" in parsed and len(parsed["questions"]) > 0:
                    if not all(q.get("original_question") == "..." for q in parsed["questions"] if isinstance(q, dict)):
                        return parsed
            except Exception:
                pass

    repaired = repair_json_escapes(text)

    # 1. Try repaired parse directly
    try:
        parsed = json.loads(repaired, strict=False)
        if isinstance(parsed, list):
            if len(parsed) > 0 and isinstance(parsed[0], dict) and "questions" in parsed[0]:
                flat_qs = []
                for page in parsed:
                    if isinstance(page, dict) and "questions" in page and isinstance(page["questions"], list):
                        flat_qs.extend(page["questions"])
                return {"questions": flat_qs}
            return {"questions": parsed}
        if isinstance(parsed, dict):
            if "questions" in parsed:
                return parsed
            for alt_key in ["mcqs", "data", "items", "results"]:
                if alt_key in parsed and isinstance(parsed[alt_key], list):
                    return {"questions": parsed[alt_key]}
            return parsed
    except Exception:
        pass

    # 2. Try raw text directly in case repair wasn't needed
    try:
        raw_stripped = text.strip()
        if raw_stripped.startswith("```json"):
            raw_stripped = raw_stripped[7:]
        elif raw_stripped.startswith("```"):
            raw_stripped = raw_stripped[3:]
        if raw_stripped.endswith("```"):
            raw_stripped = raw_stripped[:-3]
        parsed = json.loads(raw_stripped.strip(), strict=False)
        if isinstance(parsed, list):
            if len(parsed) > 0 and isinstance(parsed[0], dict) and "questions" in parsed[0]:
                flat_qs = []
                for page in parsed:
                    if isinstance(page, dict) and "questions" in page and isinstance(page["questions"], list):
                        flat_qs.extend(page["questions"])
                return {"questions": flat_qs}
            return {"questions": parsed}
        if isinstance(parsed, dict):
            if "questions" in parsed:
                return parsed
            for alt_key in ["mcqs", "data", "items", "results"]:
                if alt_key in parsed and isinstance(parsed[alt_key], list):
                    return {"questions": parsed[alt_key]}
            return parsed
    except Exception:
        pass

    # 2.5 Truncated JSON repair: if output was cut mid-JSON by token limit,
    # attempt to close open brackets/braces to salvage all complete questions.
    for attempt_text in [repaired, text.strip()]:
        # Strip markdown fences
        t = attempt_text.strip()
        if t.startswith("```json"):
            t = t[7:]
        elif t.startswith("```"):
            t = t[3:]
        if t.endswith("```"):
            t = t[:-3]
        t = t.strip()

        # Only attempt repair if text looks like truncated JSON (starts with { or [ but doesn't parse)
        if not (t.startswith("{") or t.startswith("[")):
            continue
        try:
            json.loads(t, strict=False)
            continue  # Already valid, skip repair
        except Exception:
            pass

        # Find the last complete question object boundary by finding last "}," or "}" before truncation
        last_complete = -1
        for marker in ['},', '}']:
            pos = t.rfind(marker)
            if pos > 0:
                last_complete = pos + len(marker)
                break

        if last_complete > 0:
            truncated = t[:last_complete].rstrip().rstrip(',')
            # Count open brackets/braces and close them
            open_braces = truncated.count('{') - truncated.count('}')
            open_brackets = truncated.count('[') - truncated.count(']')
            closed = truncated + ']' * max(0, open_brackets) + '}' * max(0, open_braces)
            try:
                parsed = json.loads(closed, strict=False)
                if isinstance(parsed, list):
                    if len(parsed) > 0 and isinstance(parsed[0], dict) and "questions" in parsed[0]:
                        flat_qs = []
                        for page in parsed:
                            if isinstance(page, dict) and "questions" in page and isinstance(page["questions"], list):
                                flat_qs.extend(page["questions"])
                        if flat_qs:
                            logger.info(f"[JSON Repair] Recovered {len(flat_qs)} questions from truncated JSON")
                            return {"questions": flat_qs}
                    elif len(parsed) > 0:
                        logger.info(f"[JSON Repair] Recovered {len(parsed)} items from truncated JSON array")
                        return {"questions": parsed}
                elif isinstance(parsed, dict):
                    qs = parsed.get("questions", [])
                    if isinstance(qs, list) and len(qs) > 0:
                        logger.info(f"[JSON Repair] Recovered {len(qs)} questions from truncated JSON object")
                        return parsed
                    for alt_key in ["mcqs", "data", "items", "results"]:
                        if alt_key in parsed and isinstance(parsed[alt_key], list):
                            logger.info(f"[JSON Repair] Recovered {len(parsed[alt_key])} items from truncated JSON")
                            return {"questions": parsed[alt_key]}
            except Exception:
                pass

    # 3. Regex match outermost JSON object {...}
    obj_match = re.search(r'(\{[\s\S]*\})', repaired)
    if obj_match:
        try:
            parsed = json.loads(obj_match.group(1), strict=False)
            if isinstance(parsed, dict):
                if "questions" in parsed:
                    return parsed
                for alt_key in ["mcqs", "data", "items", "results"]:
                    if alt_key in parsed and isinstance(parsed[alt_key], list):
                        return {"questions": parsed[alt_key]}
                return parsed
        except Exception:
            pass

    # 4. Regex match bare JSON array [...]
    arr_match = re.search(r'(\[[\s\S]*\])', repaired)
    if arr_match:
        try:
            parsed_arr = json.loads(arr_match.group(1), strict=False)
            if isinstance(parsed_arr, list):
                if len(parsed_arr) > 0 and isinstance(parsed_arr[0], dict) and "questions" in parsed_arr[0]:
                    flat_qs = []
                    for page in parsed_arr:
                        if isinstance(page, dict) and "questions" in page and isinstance(page["questions"], list):
                            flat_qs.extend(page["questions"])
                    return {"questions": flat_qs}
                return {"questions": parsed_arr}
        except Exception:
            pass

    # 5. Regex search for "questions": [...]
    q_match = re.search(r'\"questions\"\s*:\s*(\[[\s\S]*?\])\s*[,}]', repaired)
    if q_match:
        try:
            qs = json.loads(q_match.group(1), strict=False)
            return {"questions": qs}
        except Exception:
            pass

    # 6. Fallback: Rescue individual question objects from truncated JSON by balancing braces
    rescued = []
    matches = [m.start() for m in re.finditer(r'\"question_number\"\s*:', repaired)]
    for i in range(len(matches)):
        start_idx = repaired.rfind('{', 0, matches[i])
        if start_idx == -1: continue
        
        open_braces = 0
        in_string = False
        escape = False
        valid_end = -1
        
        for j in range(start_idx, len(repaired)):
            c = repaired[j]
            if escape:
                escape = False
                continue
            if c == '\\':
                escape = True
            elif c == '"':
                in_string = not in_string
            elif not in_string:
                if c == '{': open_braces += 1
                elif c == '}':
                    open_braces -= 1
                    if open_braces == 0:
                        valid_end = j + 1
                        break
                        
        if valid_end != -1:
            chunk = repaired[start_idx:valid_end]
            try:
                q_obj = json.loads(chunk, strict=False)
                if isinstance(q_obj, dict) and "question_number" in q_obj:
                    rescued.append(q_obj)
            except Exception:
                pass
                
    if rescued:
        return {"questions": rescued}

    return {"questions": []}


def split_question_and_options(text: str) -> Tuple[str, Dict[str, str]]:
    """
    Separates question stem from embedded options (e.g. (a), (b), (c), (d) or (A), (B), (C), (D) or (1), (2), (3), (4)).
    Returns (cleaned_stem, extracted_options_dict).
    If no sequential options are found, returns (text.strip(), {}).
    """
    if not text:
        return "", {}

    # CRITICAL: Do NOT split options from stem if this is a Match the List / Column-I problem,
    # because (A), (B), (C), (D) inside Column-I are column entries, NOT the MCQ choices!
    is_matching_text = bool(re.search(
        r'(?i)\b(?:column[\s\-_]*[i1a]|list[\s\-_]*[i1a]|match\s+the\s+(?:column|list)|match\s+column|જોડકા|જોડો|મેળવો)\b',
        text
    ))
    search_text = text
    offset = 0
    if is_matching_text:
        # Check if real choice options appear AFTER Column-II (e.g. Codes: (A) P->1...)
        m_col2 = re.search(r'(?i)\b(?:column[\s\-_]*(?:ii|2|b)|list[\s\-_]*(?:ii|2|b)|કૉલમ[\s\-_]*(?:૨|2|ii|II))\b', text)
        if m_col2:
            after_col2 = text[m_col2.end():]
            m_opts_marker = re.search(r'(?i)(?:\n\s*(?:options?|codes?|વિકલ્પો|કોડ)\s*[:\.\-]?|\n\s*\([a-dA-D]\)\s+[p-tP-T1-4])', after_col2)
            if m_opts_marker:
                offset = m_col2.end() + m_opts_marker.start()
                search_text = text[offset:]
            else:
                return text.strip(), {}
        else:
            return text.strip(), {}

    # Match option markers like (a), (b), (A), (B), [A], [B], (1), (2), [1], [2], A., B., 1., 2., A), B)
    # Parenthesized or bracketed markers can appear after whitespace or start of line, with optional space before content
    pattern = r'(?m)(?:^|[\r\n]+|\s+)(?:[\(\[]\s*([a-dA-D1-4અબકડक-घ])\s*[\)\]]\s*|(?:^|[\r\n]+|\s{2,}|\t)([a-dA-D1-4અબકડक-घ])[\.\:\)]\s*)'
    matches = list(re.finditer(pattern, search_text))

    if len(matches) < 2:
        return text.strip(), {}

    num_map = {'1': 'A', '2': 'B', '3': 'C', '4': 'D', 'અ': 'A', 'બ': 'B', 'ક': 'C', 'ડ': 'D', 'क': 'A', 'ખ': 'B', 'ग': 'C', 'घ': 'D'}
    valid_seq = ["A", "B", "C", "D"]
    keys = []
    for m in matches:
        raw_k = (m.group(1) or m.group(2) or "").upper()
        k = num_map.get(raw_k, raw_k)
        keys.append(k)

    # Must contain at least A and (B or C or D) or at least 2 valid distinct keys in order
    if not (("A" in keys and ("B" in keys or "C" in keys or "D" in keys)) or len(set(keys) & set(valid_seq)) >= 2):
        return text.strip(), {}

    first_opt_idx = offset + matches[0].start()
    stem = text[:first_opt_idx].strip()
    # Strip any leading answer tag that leaked from previous question (e.g. "Ans: B" or "[Ans. B]")
    stem = re.sub(
        r'^\s*(?:\[\s*ans[^\n\]]*\]|\(?\s*ans(?:wer)?[\s\:\.\=\-]*\s*[\(\[]?[a-dA-D0-9\(\)]+[\)\]]?\)?)\s*',
        '',
        stem,
        flags=re.IGNORECASE
    ).strip()

    extracted_opts: Dict[str, str] = {}
    for i, m in enumerate(matches):
        raw_k = (m.group(1) or m.group(2) or "").upper()
        k = num_map.get(raw_k, raw_k)
        if k not in valid_seq:
            continue
        start_pos = offset + m.end()
        end_pos = offset + matches[i + 1].start() if i + 1 < len(matches) else len(text)
        opt_text = text[start_pos:end_pos].strip()

        # If it's the last option, strip any trailing answer tag like "Ans: (b)", "[Ans. B]", "Ans: C"
        if i == len(matches) - 1:
            opt_text = re.sub(r'\s*(?:\[\s*Ans[^\n\]]*\]|\(?\s*Ans(?:wer)?[\s\:\.\=\-]*\s*[\(\[]?[a-dA-D0-9\(\)]+[\)\]]?\)?)\s*$', '', opt_text, flags=re.IGNORECASE).strip()

        # Clean leading option identifiers if present
        opt_text = clean_option_text(opt_text)
        if k not in extracted_opts or len(opt_text) > len(extracted_opts[k]):
            extracted_opts[k] = opt_text

    return stem, extracted_opts


def extract_matching_columns(text: str, options: Any = None) -> Tuple[str, str]:
    """
    Extracts Column-I (Column A / List-I) and Column-II (Column B / List-II)
    from question stem text or options when it is a Matching Column question.
    Returns (column_i_text, column_ii_text).
    """
    if not text:
        return "", ""

    # Look for line-level Column-I / List-I header blocks first (e.g. "\nColumn-I:" or "\nList-I:")
    col1_pat = r'(?im)(?:^|\n)\s*(?:column[\s\-_]*(?:i\b|1\b|a\b)|list[\s\-_]*(?:i\b|1\b|a\b)|કૉલમ[\s\-_]*(?:i|૧|1|a)|વિભાગ[\s\-_]*(?:i|૧|1|a))\s*[:\.\-]?'
    col2_pat = r'(?im)(?:^|\n)\s*(?:column[\s\-_]*(?:ii\b|2\b|b\b)|list[\s\-_]*(?:ii\b|2\b|b\b)|કૉલમ[\s\-_]*(?:ii|૨|2|b)|વિભાગ[\s\-_]*(?:ii|૨|2|b))\s*[:\.\-]?'

    m_col1 = list(re.finditer(col1_pat, text))
    m_col2 = list(re.finditer(col2_pat, text))

    col_i = ""
    col_ii = ""

    # Use the best matching pair
    if m_col1 and m_col2:
        # Pick the pair where c1 comes before c2 and there is substantial text
        best_pair = None
        for c1 in m_col1:
            for c2 in m_col2:
                if c1.end() < c2.start():
                    content = text[c1.end():c2.start()].strip()
                    if content and len(content) > 2:
                        best_pair = (c1, c2)
        if not best_pair:
            best_pair = (m_col1[0], m_col2[0])

        c1, c2 = best_pair
        col_i_raw = text[c1.end():c2.start()].strip(" :-\t\r\n")
        after_col2 = text[c2.end():].strip(" :-\t\r\n")
        m_opts_end = re.search(r'(?i)(?:\n\s*(?:options?|codes?|વિકલ્પો|કોડ)\s*[:\.\-]?|\n\s*\([a-dA-D]\)\s+[A-Za-z0-9])', after_col2)
        if m_opts_end:
            col_ii_raw = after_col2[:m_opts_end.start()].strip()
        else:
            col_ii_raw = after_col2.strip()
        col_i = col_i_raw
        col_ii = col_ii_raw
    else:
        # Fallback to inline pattern if line-level didn't match
        col1_pat_inline = r'(?i)(?:column[\s\-_]*(?:i\b|1\b|a\b)|list[\s\-_]*(?:i\b|1\b|a\b)|કૉલમ[\s\-_]*(?:i|૧|1|a)|વિભાગ[\s\-_]*(?:i|૧|1|a))'
        col2_pat_inline = r'(?i)(?:column[\s\-_]*(?:ii\b|2\b|b\b)|list[\s\-_]*(?:ii\b|2\b|b\b)|કૉલમ[\s\-_]*(?:ii|૨|2|b)|વિભાગ[\s\-_]*(?:ii|૨|2|b))'
        m1 = list(re.finditer(col1_pat_inline, text))
        m2 = list(re.finditer(col2_pat_inline, text))
        if len(m1) > 1 and len(m2) > 1:
            c1, c2 = m1[-1], m2[-1]
            if c1.end() < c2.start():
                col_i = text[c1.end():c2.start()].strip(" :-\t\r\n")
                col_ii = text[c2.end():].strip(" :-\t\r\n")

    # Fallback: if options dictionary contains (A), (B), (C), (D) that look like Column-I entries
    if not col_i and options and isinstance(options, dict):
        opt_texts = []
        for k in ["A", "B", "C", "D"]:
            v = options.get(k)
            t = _safe_opt_val(v, "translated") or _safe_opt_val(v, "original") or (v if isinstance(v, str) else "")
            if t:
                opt_texts.append(f"({k}) {clean_option_text(str(t))}")
        if opt_texts and any(kw in text.lower() for kw in ["list", "column", "match", "જોડકા", "જોડો"]):
            col_i = "\n".join(opt_texts)

    return col_i.strip(), col_ii.strip()


def is_genuine_question_diagram(
    question_text: str,
    has_options: bool,
    image_url: Optional[str],
    has_opt_images: bool = False
) -> bool:
    """Returns False if a question is purely textual/mathematical with text options
    and has NO diagram/figure references in its text.
    If options have diagrams (has_opt_images=True), or question text references a figure/circuit/etc.,
    or image_url is provided for an authentic diagram, returns True."""
    if not image_url:
        return False

    # If options themselves are images, and there is a question diagram, BOTH must be considered and preserved!
    if has_opt_images:
        return True

    fig_keywords = [
        "figure", "diagram", "circuit", "graph", "chart", "curve", "drawing", "plot",
        "shown in", "as shown", "given below", "refer to", "in the figure", "in the diagram",
        "look at the", "following figure", "below figure", "setup", "network", "arrangement",
        "reaction", "scheme", "structure", "truth table", "waveform", "pulley", "prism",
        "block", "wedge", "spring", "mirror", "lens", "ray", "spectrum",
        "stage", "stages", "phase", "phases", "identify", "cell", "cycle", "division",
        "chromosome", "labeled", "labelled", "parts", "part", "indicate", "indicated",
        "represent", "represented", "denote", "denoted", "a, b, c", "a, b, c, d",
        "આકૃતિ", "ચિત્ર", "પરિપથ", "દર્શાવ્યા", "દર્શાવેલ", "નીચે આપેલ", "નીચેની", "આપેલ",
        "આલેખ", "ગોઠવણ", "તબક્કો", "તબક્કા", "કોષચક્ર", "વિભાજન", "રંગસૂત્ર", "સમવિભાજન",
        "અર્ધીકરણ", "ઓળખો", "નિર્દેશિત", "ભાગ", "ભાગો", "ચક્ર"
    ]
    txt_lower = (question_text or "").lower()
    if any(kw in txt_lower for kw in fig_keywords):
        return True
    # If the question has text options, no diagram keyword, and no option diagrams:
    # it is a pure text/formula problem — do NOT show an image!
    if has_options:
        return False
    return True


def is_box_duplicate_of_options(q_box: Any, opts: Dict[str, Any]) -> bool:
    """
    Returns True ONLY if q_box is an accidental duplicate of one of the option boxes,
    or if q_box solely encloses the option boxes with no question stem diagram.
    Returns False when q_box represents a genuine question stem diagram (even if options also have images).
    """
    if not q_box or not opts:
        return False

    def parse_box(b):
        if not b:
            return None
        if isinstance(b, dict):
            b_list = b.get("box_2d") or b.get("bbox") or b.get("coords")
            if isinstance(b_list, (list, tuple)) and len(b_list) >= 4:
                return [float(x) for x in b_list[:4]]
            return [
                float(b.get("ymin", b.get("top", 0))),
                float(b.get("xmin", b.get("left", 0))),
                float(b.get("ymax", b.get("bottom", 0))),
                float(b.get("xmax", b.get("right", 0)))
            ]
        elif isinstance(b, (list, tuple)) and len(b) >= 4:
            return [float(x) for x in b[:4]]
        elif isinstance(b, str):
            import re
            nums = re.findall(r'[-+]?\d*\.?\d+', b)
            if len(nums) >= 4:
                return [float(x) for x in nums[:4]]
        return None

    qb = parse_box(q_box)
    if not qb or qb[2] <= qb[0] or qb[3] <= qb[1]:
        return False

    opt_boxes = []
    for opt in opts.values():
        box = getattr(opt, "image_box", None)
        if not box and isinstance(opt, dict):
            box = opt.get("image_box") or opt.get("box_2d") or opt.get("diagram_box") or opt.get("bbox")
        ob = parse_box(box)
        if ob and ob[2] > ob[0] and ob[3] > ob[1]:
            opt_boxes.append(ob)

    if not opt_boxes:
        return False

    # Check 1: Does q_box almost exactly match any single option box? (IoU > 0.85)
    for ob in opt_boxes:
        inter_ymin = max(qb[0], ob[0])
        inter_xmin = max(qb[1], ob[1])
        inter_ymax = min(qb[2], ob[2])
        inter_xmax = min(qb[3], ob[3])
        if inter_ymax > inter_ymin and inter_xmax > inter_xmin:
            inter_area = (inter_ymax - inter_ymin) * (inter_xmax - inter_xmin)
            q_area = (qb[2] - qb[0]) * (qb[3] - qb[1])
            ob_area = (ob[2] - ob[0]) * (ob[3] - ob[1])
            union_area = q_area + ob_area - inter_area
            if union_area > 0 and (inter_area / union_area) > 0.85:
                return True

    # Check 2: If q_box ends before options or starts above option diagrams, it is a genuine question stem diagram!
    min_opt_y = min(ob[0] for ob in opt_boxes)
    threshold = 15 if max(qb) > 1.5 else 0.015
    if qb[2] <= min_opt_y + threshold or qb[0] < min_opt_y - threshold:
        # q_box is located above the option diagrams (Question Image)! NEVER delete it!
        return False

    # Check 3: Only if q_box tightly wraps solely around all option diagrams with no question diagram above them:
    max_opt_y = max(ob[2] for ob in opt_boxes)
    diff_thresh = 20 if max(qb) > 1.5 else 0.02
    if len(opt_boxes) >= 2 and abs(qb[0] - min_opt_y) <= diff_thresh and abs(qb[2] - max_opt_y) <= diff_thresh:
        return True

    return False




# ── Mathematical PUA (Private Use Area) Glyphs & Formula Repair ────────────────

PUA_MATH_MAP = {
    0xf02d: '-',         # minus sign
    0xf02b: '+',         # plus
    0xf03d: '=',         # equals
    0xf028: '(',         # left paren
    0xf029: ')',         # right paren
    0xf05b: '[',         # left bracket
    0xf05d: ']',         # right bracket
    0xf07b: '{',         # left brace
    0xf07d: '}',         # right brace
    0xf02f: '/',         # slash / division
    0xf02c: ',',         # comma
    0xf02e: '.',         # period
    0xf03a: ':',         # colon
    0xf03b: ';',         # semicolon
    0xf03c: '<',         # less than
    0xf03e: '>',         # greater than
    0xf0ae: ' \u2192 ',  # right arrow ->
    0xf0ac: ' \u2194 ',  # left right arrow <->
    0xf0de: ' \u21d2 ',  # implies =>
    0xf0d8: ' \u21d0 ',  # left arrow <=
    0xf0df: ' \u21d4 ',  # if and only if <=>
    0xf0a5: ' \u221e ',  # infinity
    0xf0b1: ' \u00b1 ',  # plus minus +/-
    0xf0b2: ' \u2264 ',  # <=
    0xf0b3: ' \u2265 ',  # >=
    0xf0d7: ' \u00d7 ',  # multiplication *
    0xf0f7: ' \u00f7 ',  # division /
    0xf0b9: ' \u2260 ',  # not equal !=
    0xf0bb: ' \u2248 ',  # approximately equal ~=
    0xf061: '\u03b1',    # alpha
    0xf062: '\u03b2',    # beta
    0xf063: '\u03c7',    # chi
    0xf064: '\u03b4',    # delta
    0xf065: '\u03b5',    # epsilon
    0xf066: '\u03c6',    # phi
    0xf067: '\u03b3',    # gamma
    0xf068: '\u03b7',    # eta
    0xf069: '\u03b9',    # iota
    0xf06b: '\u03ba',    # kappa
    0xf06c: '\u03bb',    # lambda
    0xf06d: '\u03bc',    # mu
    0xf06e: '\u03bd',    # nu
    0xf070: '\u03c0',    # pi
    0xf071: '\u03b8',    # theta
    0xf072: '\u03c1',    # rho
    0xf073: '\u03c3',    # sigma
    0xf074: '\u03c4',    # tau
    0xf077: '\u03c9',    # omega
    0xf079: '\u03c8',    # psi
    0xf0c7: ' \u2229 ',  # intersection
    0xf0c8: ' \u222a ',  # union
    0xf0ce: ' \u2208 ',  # element of
    0xf0cf: ' \u2209 ',  # not element of
    0xf0bf: ' \u222b ',  # integral
    0xf0e5: ' \u2211 ',  # summation
    0xf0d5: ' \u220f ',  # product
    0xf0d6: ' \u221a ',  # square root
}


def clean_pua_math_symbols(text: str) -> str:
    """Translates Private Use Area (PUA) MathType and Symbol font glyphs into standard Unicode/ASCII math characters."""
    if not text:
        return ""
    chars = []
    for ch in text:
        code = ord(ch)
        if code in PUA_MATH_MAP:
            chars.append(PUA_MATH_MAP[code])
        elif 0xf020 <= code <= 0xf07e:
            chars.append(chr(code - 0xf000))
        elif 0xe000 <= code <= 0xf8ff:
            chars.append(" ")
        elif ch == '\ufffd':
            chars.append(" ")
        else:
            chars.append(ch)
    return "".join(chars)


def _balance_latex_braces(math_str: str) -> str:
    """Balances unescaped open and close curly braces in LaTeX expressions."""
    open_count = 0
    close_count = 0
    for idx, ch in enumerate(math_str):
        if ch == '{' and (idx == 0 or math_str[idx-1] != '\\'):
            open_count += 1
        elif ch == '}' and (idx == 0 or math_str[idx-1] != '\\'):
            close_count += 1
    if open_count > close_count:
        math_str = math_str + ('}' * (open_count - close_count))
    return math_str


def split_matrix_row_elements(row_str: str) -> List[str]:
    """Splits a single matrix or determinant row string into column elements, respecting parentheses and braces and unicode minuses."""
    row_str = re.sub(r'[\u2212\u2013\u2014\u2012\u2015]', '-', str(row_str))
    tokens = []
    current = []
    p_depth = 0
    b_depth = 0
    i = 0
    s = row_str.strip().strip('|').strip('[').strip(']').strip()
    while i < len(s):
        c = s[i]
        if c == '(':
            p_depth += 1
        elif c == ')':
            p_depth = max(0, p_depth - 1)
        elif c == '{':
            b_depth += 1
        elif c == '}':
            b_depth = max(0, b_depth - 1)
        elif c == '&':
            tok = ''.join(current).strip()
            if tok:
                tokens.append(tok)
            current = []
            i += 1
            continue
        elif c in (',', ';') and p_depth == 0 and b_depth == 0:
            tok = ''.join(current).strip()
            if tok:
                tokens.append(tok)
            current = []
            i += 1
            continue
        elif c in (' ', '\t') and p_depth == 0 and b_depth == 0:
            if i + 1 < len(s) and s[i+1] in (' ', '\t'):
                while i < len(s) and s[i] in (' ', '\t'):
                    i += 1
                tok = ''.join(current).strip()
                if tok:
                    tokens.append(tok)
                current = []
                continue
        current.append(c)
        i += 1
    tok = ''.join(current).strip()
    if tok:
        tokens.append(tok)
    return tokens


def auto_format_matrices(text: str) -> str:
    """Auto-detects multi-line or flattened matrix & determinant representations and converts them to standard LaTeX \\begin{bmatrix}/\\begin{vmatrix}."""
    if not text:
        return ""

    # Normalize unicode minuses (e.g. \u2212 -> -)
    res = re.sub(r'[\u2212\u2013\u2014\u2012\u2015]', '-', str(text))

    # Helper to split matrix tokens respecting nested braces {} and parentheses ()
    def _split_flat_tokens(raw_str: str) -> List[str]:
        tokens = []
        current = []
        depth = 0
        p_depth = 0
        for char in raw_str:
            if char == '{':
                depth += 1
                current.append(char)
            elif char == '}':
                depth = max(0, depth - 1)
                current.append(char)
            elif char == '(':
                p_depth += 1
                current.append(char)
            elif char == ')':
                p_depth = max(0, p_depth - 1)
                current.append(char)
            elif char in (',', ';', ' ', '\t', '\n') and depth == 0 and p_depth == 0:
                tok = ''.join(current).strip()
                if tok:
                    tokens.append(tok)
                current = []
            else:
                current.append(char)
        tok = ''.join(current).strip()
        if tok:
            tokens.append(tok)
        return tokens

    # 1. Multi-line determinants: | sin(A+B+C) sin A cos A \n -sin A tan(A+B+C) tan A \n ... |
    def repl_multiline_det(m):
        inner = m.group(1).strip()
        lines = [l.strip() for l in inner.split('\n') if l.strip()]
        if len(lines) >= 2:
            row_strs = []
            for l in lines:
                toks = split_matrix_row_elements(l)
                row_strs.append(' & '.join(toks))
            return r'\begin{vmatrix} ' + ' \\\\ '.join(row_strs) + r' \end{vmatrix}'
        return m.group(0)

    # 2. Multi-line bracketed rows: [ 1 0 -1 -2 \n 3 2 1 0 \n 5 4 3 2 ]
    def repl_multiline_mat(m):
        inner = m.group(1).strip()
        lines = [l.strip() for l in inner.split('\n') if l.strip()]
        if len(lines) >= 2:
            row_strs = []
            for l in lines:
                toks = split_matrix_row_elements(l)
                row_strs.append(' & '.join(toks))
            return r'\begin{bmatrix} ' + ' \\\\ '.join(row_strs) + r' \end{bmatrix}'
        return m.group(0)

    # 3. Single-line flattened matrix [ ... ] (4, 6, 8, 9, 12, 16, 20, 25 items)
    def repl_flat(m):
        raw = m.group(1).strip()
        # Avoid matching citations like [JEE Main 2020] or [Ans: A] or word tags
        if re.match(r'^(?:JEE|NEET|AIEEE|CBSE|Online|Ans|Shift|Hint|Page|Chapter|Image|Diagram)\b', raw, re.I):
            return m.group(0)

        tokens = _split_flat_tokens(raw)

        # Unglue glued 2-digit OCR artifacts when total count is 3, 7, 8, 10, 11
        if len(tokens) == 3 and any(len(t) >= 2 and not t.startswith('-') for t in tokens):
            exp = []
            for t in tokens:
                if len(t) == 2 and t.isdigit():
                    exp.extend([t[0], t[1]])
                else:
                    exp.append(t)
            if len(exp) == 4:
                tokens = exp
        elif len(tokens) == 4 and tokens[3] == '12':
            tokens[3] = '2'
        elif len(tokens) in (7, 8):
            exp = []
            for t in tokens:
                if len(t) == 2 and t.isdigit():
                    exp.extend([t[0], t[1]])
                else:
                    exp.append(t)
            if len(exp) == 9:
                tokens = exp
        elif len(tokens) in (10, 11):
            exp = []
            for t in tokens:
                if re.match(r'^-?\d{2}$', t):
                    exp.extend([t[:-1], t[-1]])
                else:
                    exp.append(t)
            if len(exp) == 12:
                tokens = exp

        # Filter out plain non-math sentences in brackets
        math_element_count = sum(1 for t in tokens if re.match(r'^(?:[+-]?\d+(?:\.\d+)?|\\?[a-zA-Z][a-zA-Z0-9]*|\\frac\{[^{}]*\}\{[^{}]*\}|\\sqrt\{[^{}]*\}|\\alpha|\\beta|\\gamma|\\delta|\\theta|\\lambda|\\mu|\\pi|\\omega|\\sigma|\\Delta)$', t))
        if len(tokens) < 3 or (math_element_count / len(tokens)) < 0.6:
            return m.group(0)

        n = len(tokens)
        if n == 4:  # 2x2
            r1 = ' & '.join(tokens[0:2])
            r2 = ' & '.join(tokens[2:4])
            return f'\\begin{{bmatrix}} {r1} \\\\ {r2} \\end{{bmatrix}}'
        elif n == 9:  # 3x3
            r1 = ' & '.join(tokens[0:3])
            r2 = ' & '.join(tokens[3:6])
            r3 = ' & '.join(tokens[6:9])
            return f'\\begin{{bmatrix}} {r1} \\\\ {r2} \\\\ {r3} \\end{{bmatrix}}'
        elif n == 12:  # 3x4 (3 rows of 4 columns)
            r1 = ' & '.join(tokens[0:4])
            r2 = ' & '.join(tokens[4:8])
            r3 = ' & '.join(tokens[8:12])
            return f'\\begin{{bmatrix}} {r1} \\\\ {r2} \\\\ {r3} \\end{{bmatrix}}'
        elif n == 6:  # 2x3
            r1 = ' & '.join(tokens[0:3])
            r2 = ' & '.join(tokens[3:6])
            return f'\\begin{{bmatrix}} {r1} \\\\ {r2} \\end{{bmatrix}}'
        elif n == 8:  # 2x4
            r1 = ' & '.join(tokens[0:4])
            r2 = ' & '.join(tokens[4:8])
            return f'\\begin{{bmatrix}} {r1} \\\\ {r2} \\end{{bmatrix}}'
        elif n == 16:  # 4x4
            r1 = ' & '.join(tokens[0:4])
            r2 = ' & '.join(tokens[4:8])
            r3 = ' & '.join(tokens[8:12])
            r4 = ' & '.join(tokens[12:16])
            return f'\\begin{{bmatrix}} {r1} \\\\ {r2} \\\\ {r3} \\\\ {r4} \\end{{bmatrix}}'
        return m.group(0)

    # 4. Single-line flattened determinants | ... | (4, 9, 16 items)
    def repl_flat_det(m):
        raw = m.group(1).strip()
        tokens = _split_flat_tokens(raw)
        math_element_count = sum(1 for t in tokens if re.match(r'^(?:[+-]?\d+(?:\.\d+)?|\\?[a-zA-Z][a-zA-Z0-9]*|\\frac\{[^{}]*\}\{[^{}]*\}|\\sqrt\{[^{}]*\}|\\alpha|\\beta|\\gamma|\\delta|\\theta|\\lambda|\\mu|\\pi|\\omega|\\sigma|\\Delta)$', t))
        if len(tokens) < 4 or (math_element_count / len(tokens)) < 0.6:
            return m.group(0)
        n = len(tokens)
        if n == 4:  # 2x2
            r1 = ' & '.join(tokens[0:2])
            r2 = ' & '.join(tokens[2:4])
            return f'\\begin{{vmatrix}} {r1} \\\\ {r2} \\end{{vmatrix}}'
        elif n == 9:  # 3x3
            r1 = ' & '.join(tokens[0:3])
            r2 = ' & '.join(tokens[3:6])
            r3 = ' & '.join(tokens[6:9])
            return f'\\begin{{vmatrix}} {r1} \\\\ {r2} \\\\ {r3} \\end{{vmatrix}}'
        elif n == 16:  # 4x4
            r1 = ' & '.join(tokens[0:4])
            r2 = ' & '.join(tokens[4:8])
            r3 = ' & '.join(tokens[8:12])
            r4 = ' & '.join(tokens[12:16])
            return f'\\begin{{vmatrix}} {r1} \\\\ {r2} \\\\ {r3} \\\\ {r4} \\end{{vmatrix}}'
        return m.group(0)

    # First handle multi-line determinants
    res = re.sub(r'\|\s*([^|]*?\n[^|]*?)\s*\|', repl_multiline_det, res)
    # Then handle multi-line matrices
    res = re.sub(r'\[\s*([0-9a-zA-Z\\+\-\.\s]*\n[0-9a-zA-Z\\+\-\.\s]*)\s*\]', repl_multiline_mat, res)
    # Then handle single-line flattened matrices [ ... ] (brackets with 3 to 180 chars)
    res = re.sub(r'\[([^\[\]\n]{3,180})\]', repl_flat, res)
    # Then handle single-line flattened determinants | ... | (bars with 3 to 180 chars)
    res = re.sub(r'\|([^|\n]{3,180})\|', repl_flat_det, res)

    # Format adjugate operators e.g. |A||adjA| or |adj A|
    res = re.sub(r'\|A\|\|\s*adj\s*A\|', r'$|A|\\,|\\text{adj } A|$', res, flags=re.IGNORECASE)
    res = re.sub(r'(?<!\$)\|\s*adj\s*\(?([A-Za-z])\)?\s*\|(?!\$)', r'$|\\text{adj } \1|$', res, flags=re.IGNORECASE)
    return res


def _wrap_bare_latex_spans(plain_text: str) -> str:
    """Detects bare LaTeX commands (e.g. \\frac, \\sqrt, \\alpha, \\theta, \\int, \\begin{bmatrix}, superscripts/subscripts) outside $ delimiters and wraps them in $...$."""
    if not plain_text:
        return ""
    result = []
    i = 0
    while i < len(plain_text):
        # 1. Handle complete \begin{env} ... \end{env} environments (e.g. bmatrix, pmatrix, vmatrix, matrix, cases, aligned)
        if plain_text.startswith(r'\begin{', i):
            env_m = re.match(r'\\begin\{([a-zA-Z0-9\*]+)\}', plain_text[i:])
            if env_m:
                env_name = env_m.group(1)
                end_tag = f"\\end{{{env_name}}}"
                end_pos = plain_text.find(end_tag, i + len(env_m.group(0)))
                if end_pos != -1:
                    full_env = plain_text[i:end_pos + len(end_tag)]
                    result.append(f"${full_env}$")
                    i = end_pos + len(end_tag)
                    continue

        if plain_text[i] == '\\' and i + 1 < len(plain_text) and plain_text[i + 1].isalpha():
            start_i = i
            j = i
            depth = 0
            while j < len(plain_text):
                c = plain_text[j]
                if c == '{' and (j == 0 or plain_text[j - 1] != '\\'):
                    depth += 1
                    j += 1
                    continue
                if c == '}' and (j == 0 or plain_text[j - 1] != '\\'):
                    if depth > 0:
                        depth -= 1
                        j += 1
                        if depth == 0:
                            # Lookahead for consecutive { or [ or _ or ^ (but NOT consecutive underscores __)
                            peek = j
                            while peek < len(plain_text) and plain_text[peek] == ' ':
                                peek += 1
                            if peek < len(plain_text):
                                if plain_text[peek] in '{[' or plain_text[peek] == '^' or (plain_text[peek] == '_' and (peek + 1 == len(plain_text) or plain_text[peek + 1] != '_')) or plain_text.startswith(r'\limits', peek) or plain_text.startswith(r'\to', peek):
                                    j = peek
                                    continue
                            break
                        continue
                    break
                if depth > 0:
                    j += 1
                    continue
                # depth == 0
                if c == '\\' and j + 1 < len(plain_text) and plain_text[j + 1].isalpha():
                    j += 1
                    while j < len(plain_text) and plain_text[j].isalpha():
                        j += 1
                    peek = j
                    while peek < len(plain_text) and plain_text[peek] == ' ':
                        peek += 1
                    if peek < len(plain_text):
                        if plain_text[peek] in '{[' or plain_text[peek] == '^' or (plain_text[peek] == '_' and (peek + 1 == len(plain_text) or plain_text[peek + 1] != '_')) or plain_text.startswith(r'\limits', peek) or plain_text.startswith(r'\to', peek):
                            j = peek
                            continue
                    break
                if c == '^' or (c == '_' and (j + 1 == len(plain_text) or plain_text[j + 1] != '_')):
                    j += 1
                    while j < len(plain_text) and plain_text[j] == ' ':
                        j += 1
                    if j < len(plain_text) and plain_text[j] == '{':
                        continue
                    elif j < len(plain_text) and (plain_text[j].isalnum() or plain_text[j] in '+-'):
                        j += 1
                        while j < len(plain_text) and plain_text[j].isalnum():
                            j += 1
                        continue
                    break
                if c.isalnum() or c in '.+-*=()|[]\'/':
                    j += 1
                    continue
                if c == ' ':
                    peek = j + 1
                    while peek < len(plain_text) and plain_text[peek] == ' ':
                        peek += 1
                    if peek < len(plain_text):
                        if peek + 1 < len(plain_text) and plain_text[peek] == '_' and plain_text[peek + 1] == '_':
                            break  # stop before fill in blank underline
                        if plain_text[peek] == '\\' or plain_text[peek] in '{[=+-*^/()|' or (plain_text[peek].isalnum() and peek + 1 < len(plain_text) and plain_text[peek + 1] in ' =+-*^/()|'):
                            j = peek
                            continue
                    break
                break
            cmd_expr = plain_text[start_i:j].strip()
            # Strip trailing blank underscores or text rules out of math delimiters
            cmd_expr = re.sub(r'\\text\{\s*(?:\\?_)+\s*\}$', '', cmd_expr).strip()
            cmd_expr = re.sub(r'\\underline\{\s*\}\s*$', '', cmd_expr).strip()
            cmd_expr = re.sub(r'(?:\\?_){2,}$', '', cmd_expr).strip()
            cmd_expr = _balance_latex_braces(cmd_expr)
            if cmd_expr:
                result.append(f"${cmd_expr}$")
            i = j
        else:
            result.append(plain_text[i])
            i += 1
    res = "".join(result)
    # Also wrap standalone power / scientific notation e.g. 10^{-3} or 10^-5 outside math mode
    res = re.sub(r'(?<!\$)\b([0-9]+(?:\.[0-9]+)?\s*[\^_](?:\{[^{}]+\}|[0-9a-zA-Z\-]+))(?!\$)', r'$\1$', res)
    return res


def normalize_and_repair_latex(text: str) -> str:
    """
    Normalizes and repairs LaTeX math expressions across questions, options, and solutions:
    1. Normalizes corrupted double-backslashes (e.g. \\\\frac -> \\frac, \\\\Omega -> \\Omega).
    2. Separates glued Greek macros (e.g. \\DeltaR -> \\Delta R).
    3. Wraps bare LaTeX math expressions in $...$ if not already delimited.
    4. Ensures all LaTeX curly braces are balanced without throwing errors.
    5. Merges adjacent inline math delimiters ($A$$B$ -> $A B$).
    6. Ensures fill-in-the-blank underscores are formatted cleanly without KaTeX errors.
    """
    if not text:
        return ""
    res = auto_format_matrices(str(text))

    # 1. Normalize corrupted double-backslashes
    res = re.sub(r'\\\\([a-zA-Z{}\[\]().,])', r'\\\1', res)

    # 2. Fix combined macros like \DeltaR -> \Delta R
    greek_macros = (
        'Alpha|Beta|Gamma|Delta|Epsilon|Zeta|Eta|Theta|Iota|Kappa|Lambda|Mu|Nu|Xi|Pi|Rho|Sigma|Tau|Upsilon|Phi|Chi|Psi|Omega|'
        'alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega'
    )
    res = re.sub(rf'\\({greek_macros})([A-Z0-9])', r'\\\1 \2', res)

    # 3. Normalize limits, sums, products, and operators to use \limits (renders conditions directly underneath)
    res = re.sub(r'\\lim\s*(?!\\limits)\s*_\s*\{', r'\\lim\\limits_{', res)
    res = re.sub(r'\\lim\s*(?!\\limits)\s*_\s*([a-zA-Z0-9\\]+)', r'\\lim\\limits_{\1}', res)
    # Normalize ASCII arrow -> or \rightarrow to \to inside limits (supporting nested braces like fractions)
    def _clean_limit_arrows(text):
        out = []
        i = 0
        while i < len(text):
            if text.startswith(r'\lim\limits_{', i):
                start = i
                i += len(r'\lim\limits_{')
                depth = 1
                while i < len(text) and depth > 0:
                    if text[i] == '{' and (i == 0 or text[i-1] != '\\'):
                        depth += 1
                    elif text[i] == '}' and (i == 0 or text[i-1] != '\\'):
                        depth -= 1
                    i += 1
                lim_block = text[start:i]
                lim_block = re.sub(r'\s*(?:->|-->|\\rightarrow)\s*', r' \\to ', lim_block)
                out.append(lim_block)
            else:
                out.append(text[i])
                i += 1
        return ''.join(out)
    res = _clean_limit_arrows(res)

    # Normalize sum, prod, max, min, sup, inf to use \limits
    res = re.sub(r'\\sum\s*(?!\\limits)\s*_\s*\{', r'\\sum\\limits_{', res)
    res = re.sub(r'\\prod\s*(?!\\limits)\s*_\s*\{', r'\\prod\\limits_{', res)
    res = re.sub(r'\\(?:max|min|sup|inf|colim)\s*(?!\\limits)\s*_\s*\{', lambda m: m.group(0).replace('_', r'\limits_'), res)

    # 3b. Normalize fill-in-the-blank lines (strip nested \text{\rule...} or \underline{...})
    res = re.sub(r'\\text\{\s*\\(?:rule|underline)\s*\{[^}]*\}\s*(?:\{[^}]*\})?\s*\}', r'______', res)
    res = re.sub(r'\\underline\{\s*(?:\\hspace\{[^}]*\}|\\quad|\\qquad|\\phantom\{[^}]*\}|\s*)*\}', r'______', res)
    res = re.sub(r'\\text\{\s*(?:\\?_)+\s*\}', r'______', res)
    res = re.sub(r'\\rule\{[^{}]*\}\{[^{}]*\}', r'______', res)

    # 4. Balance braces and wrap bare LaTeX commands
    parts = []
    last_idx = 0
    delimit_pat = re.compile(r'\$\$([\s\S]+?)\$\$|\$([^\$\n]+?)\$')

    for m in delimit_pat.finditer(res):
        pre_seg = res[last_idx:m.start()]
        if pre_seg:
            parts.append(_wrap_bare_latex_spans(pre_seg))
        inner_math = m.group(1) or m.group(2) or ''
        is_block = bool(m.group(1))

        # Handle blanks inside math delimiters so they don't produce KaTeX subscript errors
        inner_math = re.sub(r'\\text\{\s*(?:\\?_)+\s*\}', r'\\underline{\\quad\\quad\\quad}', inner_math)
        inner_math = re.sub(r'(?:\\?_){2,}', r'\\underline{\\quad\\quad\\quad}', inner_math)

        balanced_inner = _balance_latex_braces(inner_math.strip())
        if is_block:
            parts.append(f"$${balanced_inner}$$")
        else:
            parts.append(f"${balanced_inner}$")
        last_idx = m.end()

    if last_idx < len(res):
        tail_seg = res[last_idx:]
        parts.append(_wrap_bare_latex_spans(tail_seg))

    combined = "".join(parts)
    # Merge adjacent $...$$...$ into a single $...$
    combined = re.sub(r'\$([^\$\n]+)\$\s*\$([^\$\n]+)\$', r'$\1 \2$', combined)
    return combined


def repair_broken_math_text(text: str) -> str:
    """
    Repairs broken mathematical text extracted from PDFs:
    1. Maps MathType / Symbol font Private Use Area glyphs (e.g. \\uf02d -> -).
    2. Detects and collapses unnatural vertical single-character / short-token line breaks.
    3. Keeps formulas, limits, and equations inline and horizontal.
    4. Normalizes and validates LaTeX formatting with balanced braces and clean delimiters.
    """
    if not text:
        return ""

    cleaned = clean_pua_math_symbols(str(text))
    cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')
    cleaned = auto_format_matrices(cleaned)

    lines = [l.strip() for l in cleaned.split('\n')]
    if len(lines) <= 1:
        # Single line: just clean excessive spaces
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)
        return normalize_and_repair_latex(cleaned.strip())

    non_empty = [l for l in lines if l]
    if not non_empty:
        return ""

    # Check if lines look fragmented into vertical single-token streams
    # (e.g. '2', 'x', '2', 'x', '8', 'lim', '3', '-', 'is', '-')
    short_math_keywords = {
        'lim', 'is', 'to', 'then', 'if', 'and', 'for', 'equal', 'value', 'of',
        'sin', 'cos', 'tan', 'sec', 'cot', 'cosec', 'log', 'ln', 'dx', 'dt', 'dy', 'dz',
        'find', 'the', 'at', 'where', 'when', 'let', 'as', 'with'
    }
    short_lines_count = sum(
        1 for l in non_empty
        if len(l) <= 4 or l.lower() in short_math_keywords or re.match(r'^[a-zA-Z0-9\+\-\*\/\=\(\)\[\]\^\\_]+$', l)
    )

    is_fragmented = (len(non_empty) >= 3 and (short_lines_count / len(non_empty)) >= 0.35)

    if is_fragmented:
        # Collapse fragmented tokens into horizontal text
        collapsed_tokens = []
        for l in lines:
            if not l:
                continue
            collapsed_tokens.append(l)
        cleaned = " ".join(collapsed_tokens)
    else:
        # Standard line repair: merge lines where previous or current line is an operator or fragment
        rebuilt_lines = []
        for l in lines:
            if not l:
                if rebuilt_lines and rebuilt_lines[-1] != "":
                    rebuilt_lines.append("")
                continue
            if not rebuilt_lines or rebuilt_lines[-1] == "":
                rebuilt_lines.append(l)
            else:
                prev = rebuilt_lines[-1]
                if (len(prev) <= 3 or
                    prev[-1] in ('+', '-', '*', '/', '=', '(', '[', '{', '<', '>', ',', ':', '^') or
                    l[0] in ('+', '-', '*', '/', '=', ')', ']', '}', '<', '>', ',', ':', '^') or
                    l.lower() in ('is', 'equal to', 'is equal to', 'then', 'then value of')):
                    rebuilt_lines[-1] = f"{prev} {l}"
                else:
                    rebuilt_lines.append(l)
        cleaned = "\n".join(rebuilt_lines)

    # Normalize spaces and spacing around operators
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r'\n\s*\n+', '\n\n', cleaned)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)

    return normalize_and_repair_latex(cleaned.strip())


def clean_question_text(text: str) -> str:
    """
    Cleans question text by stripping genuine trailing or leading exam citations,
    shift tags, exam years, and embedded options (a), (b), (c), (d).
    Repairs broken mathematical formatting and Private Use Area font glyphs.
    Preserves all authentic scientific conditions, parameters (e.g. (where g = 10 m/s^2), (Take pi = 3.14)),
    mathematical brackets, equations, and trailing questions.
    """
    if not text:
        return ""
    cleaned = text.strip()

    # Strip any leading answer tag that leaked from the previous question (e.g. "Ans: B" or "[Ans. B]")
    cleaned = re.sub(
        r'^\s*(?:\[\s*ans[^\n\]]*\]|\(?\s*ans(?:wer)?[\s\:\.\=\-]*\s*[\(\[]?[a-dA-D0-9\(\)]+[\)\]]?\)?)\s*',
        '',
        cleaned,
        flags=re.IGNORECASE
    ).strip()

    # Strip any trailing answer tag at the end (e.g. "Ans: C" or "[Ans. C]")
    cleaned = re.sub(
        r'\s*(?:\[\s*ans[^\n\]]*\]|\(?\s*ans(?:wer)?[\s\:\.\=\-]*\s*[\(\[]?[a-dA-D0-9\(\)]+[\)\]]?\)?)\s*$',
        '',
        cleaned,
        flags=re.IGNORECASE
    ).strip()

    # First repair any broken multi-line math or PUA symbols
    cleaned = repair_broken_math_text(cleaned)

    # Strip embedded options from question stem if present
    # CRITICAL SAFEGUARD: Do NOT truncate with split_question_and_options if text contains multiple sub-parts
    # unless it is an ordering, statement, arrangement question, or all options appear after the subparts.
    has_subparts = bool(re.search(
        r'(?:\(|\[|\b)(?:i{1,3}|iv|v|vi{0,3}|ix|x)(?:\)|\]|\.)[\s\S]+?(?:\(|\[|\b)(?:ii|iii|iv|v|vi{0,3}|ix|x)(?:\)|\]|\.)',
        cleaned,
        re.IGNORECASE
    ))
    is_ordering_or_statement = bool(re.search(
        r'(?i)\b(?:arrange|order|ascending|descending|statements?|following|which of|consider|match|list|ક્રમ|વિધાનો|ગોઠવો|જોડકા)\b',
        cleaned
    ))
    if not has_subparts or is_ordering_or_statement:
        stem, extracted = split_question_and_options(cleaned)
        if stem and len(stem) >= 3 and extracted:
            cleaned = stem
    elif has_subparts:
        # Check if subparts have their own separate options; if not, split options cleanly
        subpart_matches = list(re.finditer(r'(?:\(|\[|\b)(?:i{1,3}|iv|v|vi{0,3}|ix|x)(?:\)|\]|\.)', cleaned, re.IGNORECASE))
        first_opt_m = re.search(r'(?m)(?:^|[\r\n]+|\s+)\(([a-dA-D1-4અબકડक-घ])\)\s+', cleaned)
        if first_opt_m and subpart_matches and first_opt_m.start() > subpart_matches[-1].end():
            stem, extracted = split_question_and_options(cleaned)
            if stem and len(stem) >= 3 and extracted:
                cleaned = stem

    # Strip leading Topic, Method, and Section headers that appear above question stems
    # (e.g. "Variable Seperable Method :", "Miscellaneous", "Homogeneous Differential Equations :", "Level - 1", "Exercise 1.1")
    topic_header_patterns = [
        # Miscellaneous / Miscellaneous Exercise / विविध / સ્વાધ્યાય
        r'^\s*(?:miscellaneous(?:\s+(?:exercise|problems?|questions?|examples?|type))?|વિવિધ(?:\s+(?:દાખલાઓ|પ્રશ્નો))?)\s*[:\.\-]?\s*',
        # Specific STEM Methods: Variable Separable Method, Homogeneous, Linear, Exact, etc.
        r'^\s*(?:variable\s+sep[ea]rable\s+method|homogeneous\s+differential\s+equations?|linear\s+differential\s+equations?|exact\s+differential\s+equations?|bernoulli(?:\'s)?\s+equation|integrat(?:ing\s+factor|ion\s+by\s+parts|ion\s+by\s+substitution)|partial\s+fractions?)\s*[:\.\-]?\s*',
        # Generic Type/Level/Section/Exercise/Topic headers
        r'^\s*(?:(?:type|level|topic|section|part|exercise|method|પ્રકાર|વિભાગ|ભાગ|સ્વાધ્યાય)[\s\-_]*(?:[0-9]+(?:\.[0-9]+)?|[ivxIVX]+|[a-zA-Z]))\s*[:\.\-]?\s*',
        # Paragraph/Passage header: e.g. "Paragraph for Question Nos. 6 to 8", "Passage - 1"
        r'^\s*(?:paragraph|passage)\s+(?:type\s+)?(?:for\s+question\s+(?:nos\.?|numbers?|no\.?)\s*[\d\s,to\-and]+)?\s*[:\.\-]?\s*',
    ]
    for pat in topic_header_patterns:
        if re.search(pat, cleaned, flags=re.IGNORECASE):
            cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE).strip()
            # If an embedded question number was right after the topic header (e.g. "1. Solve..."), strip it too
            cleaned = re.sub(r'^\s*(?:Q|Question|પ્રશ્ન)?\s*\d+[\.\:\-\)]\s*', '', cleaned, flags=re.IGNORECASE).strip()

    exam_names = r'JEE(?:\s+Main|\s+Adv|\s+Advanced)?|NEET|AIEEE|GUJCET|CBSE|AIIMS|AIPMT|ISEET|BITSAT|IIT|NCERT|GATE|JAM'

    citation_patterns = [
        # Explicit Exam Name with 4-digit Year / Shift / Date in brackets at end of question: e.g. [JEE Main 2019, 12 April I], (NEET 2021), [AIEEE 2004]
        rf'\s*[\(\[]\s*(?:{exam_names})\b[^\)\]]*?(?:19\d\d|20\d\d)[^\)\]]*[\)\]]\s*$',
        # Online Exam with Date and Year: [Online April 9, 2013] or (Online 12 Jan 2019)
        r'\s*[\(\[]\s*Online\b[^\)\]]*?(?:19\d\d|20\d\d)[^\)\]]*[\)\]]\s*$',
        # Standalone Exam Name tag in brackets at end: [JEE Main], [NEET], [AIEEE], (GUJCET)
        rf'\s*[\(\[]\s*(?:{exam_names})\s*[\)\]]\s*$',
        # Explicit Year + Exam Name: [2019 Main], (2018 NEET), [2013 Online]
        rf'\s*[\(\[]\s*(?:19|20)\d\d\s+(?:{exam_names}|Online|Shift)[^\)\]]*[\)\]]\s*$',
        # Standalone date + shift with 4-digit year: e.g. [12 Jan 2019, Shift 1] or (10 April 2019, Shift II)
        r'\s*[\(\[]\s*\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(?:19|20)\d\d\s*,?\s*Shift[^\)\]]*[\)\]]\s*$',

        # Leading Exam tags: e.g. [JEE Main 2020] or (NEET 2021) at start of question
        rf'^\s*[\(\[]\s*(?:{exam_names})\b[^\)\]]*?(?:19\d\d|20\d\d)[^\)\]]*[\)\]]\s*[:\.\-]?\s*',
        rf'^\s*[\(\[]\s*(?:{exam_names})\s*[\)\]]\s*[:\.\-]?\s*',
    ]

    for pat in citation_patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE).strip()

    return cleaned


def clean_option_text(text: str, has_image: bool = False) -> str:
    """
    Cleans option text by removing leading option identifiers like (A), (1), (a), A., 1., etc.
    Repairs broken mathematical formatting and Private Use Area font glyphs.
    If the option contains an image or image references (e.g. [Image], [Diagram], image.png),
    cleans out image references so the text column never contains image artifacts.
    If the option is purely an image with no distinct text, returns empty string "".
    """
    if not text:
        return ""
    txt = str(text).strip()
    # First repair any broken multi-line math or PUA symbols
    txt = repair_broken_math_text(txt)

    # Strip leading prefixes like (a), (b), (A), (B), [A], [B], (1), (2), [1], [2], (i), (ii), 1., A., etc. (Strictly never strip decimal numbers like 9.8 or 1.5)
    txt = re.sub(r'^\s*(?:[\(\[]\s*(?:[a-dA-D1-4અબકડक-घ]|i{1,3}|iv|v)\s*[\)\]]|(?:[a-dA-D1-4અબકડक-घ]|i{1,3}|iv|v)\s*[\:\)]|(?:[a-dA-D1-4અબકડक-घ]|i{1,3}|iv|v)\.(?!\d))\s*', '', txt).strip()

    # Pattern for standalone image references / placeholders
    placeholder_pattern = r'^\s*[\(\[]?\s*(?:image|diagram|figure|diagram image|see image|see diagram|option\s*[a-d]\s*image|આકૃતિ|ચિત્ર)[\)\]]?\s*$'
    if re.match(placeholder_pattern, txt, re.IGNORECASE):
        return ""

    # If text is a file path or URL
    if txt.lower().startswith(("/api/images/", "http://", "https://", "extracted_images/")) or txt.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        return ""

    # Remove any inline image tags like [Image], (Diagram), etc.
    txt = re.sub(r'[\(\[]\s*(?:image|diagram|figure|see image|see diagram|આકૃતિ|ચિત્ર)\s*[\)\]]', '', txt, flags=re.IGNORECASE).strip()

    # If option has an image and after cleaning nothing or only punctuation/placeholder or isolated label remains:
    if has_image and (not txt or len(txt) <= 3 or re.match(placeholder_pattern, txt, re.IGNORECASE) or re.match(r'^(?:[a-dA-D1-4\.\(\)\[\]\-_: ]+|image|diagram|figure|આકૃતિ|ચિત્ર)$', txt, re.IGNORECASE)):
        return ""

    return txt


def clean_solution_text(text: str) -> str:
    """
    Cleans solution text by repairing broken mathematical notation and PUA glyphs.
    Preserves all steps, calculations, equations, and explanatory content.
    """
    if not text:
        return ""
    return repair_broken_math_text(str(text).strip())


def _safe_opt_val(opt: Any, field: str, default: Any = "") -> Any:
    """Safely retrieves a field from an OptionDetail model or dictionary."""
    if not opt:
        return default
    if isinstance(opt, dict):
        return opt.get(field, default)
    return getattr(opt, field, default)


OPTION_NORM_MAP = {
    '1': 'A', '2': 'B', '3': 'C', '4': 'D',
    'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D',
    'A.': 'A', 'B.': 'B', 'C.': 'C', 'D.': 'D',
    'અ': 'A', 'બ': 'B', 'ક': 'C', 'ડ': 'D',
    'ક.': 'C', 'ખ': 'B', 'ગ': 'C', 'ઘ': 'D',
    'क': 'A', 'ख': 'B', 'ग': 'C', 'घ': 'D',
    'I': 'A', 'II': 'B', 'III': 'C', 'IV': 'D',
}


def normalize_option_key(raw_k: Optional[str]) -> str:
    """Normalizes option keys (e.g. '(A)', '(1)', '(અ)', '(બ)', '(ક)', '(ડ)', '(क)', 'II') strictly to 'A', 'B', 'C', 'D'."""
    if not raw_k:
        return ''
    s = re.sub(r'[\(\)\[\]\.\:\s]', '', str(raw_k)).strip()
    return OPTION_NORM_MAP.get(s, OPTION_NORM_MAP.get(s.upper(), s.upper()))


def sanitize_mcq_answer(
    ans: Optional[str],
    question_text: str = "",
    solution_text: str = ""
) -> str:
    """Strictly guarantees that an MCQ answer is ONLY a valid option letter ('A', 'B', 'C', 'D' or multi 'A, B').
    Rejects long sentences, question stems, equations, or paragraphs."""
    if ans:
        raw = str(ans).strip()
        # Direct option key check
        norm = normalize_option_key(raw)
        if norm in ["A", "B", "C", "D"]:
            return norm

        # Multi-correct check e.g. "A, B" or "A, C, D"
        if re.match(r'^[A-D](?:\s*,\s*[A-D])+$', raw.upper()):
            return re.sub(r'\s*,\s*', ', ', raw.upper())

        # Extract from raw string if it has text around it e.g. "Ans: (C)" or "[Ans. B]"
        extracted = extract_answer_from_text(raw)
        if extracted in ["A", "B", "C", "D"]:
            return extracted

    # Fallback to solution text or question text
    if solution_text:
        sol_extracted = extract_answer_from_text(solution_text)
        if sol_extracted in ["A", "B", "C", "D"]:
            return sol_extracted

    if question_text:
        q_extracted = extract_answer_from_text(question_text)
        if q_extracted in ["A", "B", "C", "D"]:
            return q_extracted

    return ""


def _get_opt_by_key(opts: Any, key: str) -> Optional[Any]:
    """Safely retrieves option A, B, C, or D from dict or list representation."""
    if not opts:
        return None
    target_k = key.upper().strip()
    if isinstance(opts, dict):
        if target_k in opts:
            return opts[target_k]
        for k_raw, v in opts.items():
            if normalize_option_key(str(k_raw)) == target_k:
                return v
    if isinstance(opts, list):
        for idx, o in enumerate(opts):
            if isinstance(o, dict):
                k_val = str(o.get("key") or o.get("option") or o.get("label") or "").strip()
                if normalize_option_key(k_val) == target_k:
                    return o
            elif target_k in ["A", "B", "C", "D"] and idx == ["A", "B", "C", "D"].index(target_k):
                return o
    return None


def extract_pure_stem_and_options(
    raw_q: str,
    opts: Any,
    question_number: Any = None,
    global_id: int = 1,
) -> Tuple[str, Any, Any, Any, Any]:
    """
    Extracts a 100% pure question stem and ensures Option A, B, C, D are separated
    strictly into their own columns.
    Guarantees that NO option text or option labels ever leak into the Question column.
    """
    opts = opts or {}
    opt_a = _get_opt_by_key(opts, "A")
    opt_b = _get_opt_by_key(opts, "B")
    opt_c = _get_opt_by_key(opts, "C")
    opt_d = _get_opt_by_key(opts, "D")

    raw_text = (raw_q or "").strip()
    clean_stem, extracted_opts = split_question_and_options(raw_text)

    # Check if raw text is a Match the Column / Matrix Match question
    is_matching_text = bool(re.search(
        r'(?i)\b(?:column[\s\-_]*[i1a]|list[\s\-_]*[i1a]|match\s+the\s+(?:column|list)|match\s+column|જોડકા|જોડો|મેળવો)\b',
        raw_text
    ))

    # Determine initial stem
    stem_candidate = clean_stem if (clean_stem and extracted_opts) else raw_text
    q_text = clean_question_text(stem_candidate)

    # Populate any missing options from extracted_opts
    if extracted_opts:
        if not (_safe_opt_val(opt_a, "translated") or _safe_opt_val(opt_a, "original") or (isinstance(opt_a, str) and opt_a.strip())):
            opt_a = extracted_opts.get("A", "")
        if not (_safe_opt_val(opt_b, "translated") or _safe_opt_val(opt_b, "original") or (isinstance(opt_b, str) and opt_b.strip())):
            opt_b = extracted_opts.get("B", "")
        if not (_safe_opt_val(opt_c, "translated") or _safe_opt_val(opt_c, "original") or (isinstance(opt_c, str) and opt_c.strip())):
            opt_c = extracted_opts.get("C", "")
        if not (_safe_opt_val(opt_d, "translated") or _safe_opt_val(opt_d, "original") or (isinstance(opt_d, str) and opt_d.strip())):
            opt_d = extracted_opts.get("D", "")

    # For non-matching questions, enforce absolute purity of q_text:
    if not is_matching_text and q_text:
        # 1. If opt_a text is known, search for where it or its marker begins in q_text and slice before it
        opt_a_str = clean_option_text(str(_safe_opt_val(opt_a, "translated") or _safe_opt_val(opt_a, "original") or (opt_a if isinstance(opt_a, str) else "")).strip())
        if opt_a_str and len(opt_a_str) >= 2:
            lead_snippet = opt_a_str[:min(len(opt_a_str), 25)].strip()
            m_a = re.search(
                r'(?m)(?:^|[\r\n]+|\s+)(?:[\(\[]\s*(?:[aA1અक])\s*[\)\]]|(?:[aA1અक])[\.\:\)])\s*' + re.escape(lead_snippet),
                q_text
            )
            if m_a and m_a.start() >= 4:
                q_text = q_text[:m_a.start()].strip()

        # 2. Check if q_text still contains a sequential option pattern e.g. (A)...(B)... or (1)...(2)...
        t_stem, t_opts = split_question_and_options(q_text)
        if t_opts and t_stem and len(t_stem) >= 4:
            q_text = t_stem
            if not (_safe_opt_val(opt_a, "translated") or _safe_opt_val(opt_a, "original")):
                opt_a = t_opts.get("A", opt_a)
            if not (_safe_opt_val(opt_b, "translated") or _safe_opt_val(opt_b, "original")):
                opt_b = t_opts.get("B", opt_b)
            if not (_safe_opt_val(opt_c, "translated") or _safe_opt_val(opt_c, "original")):
                opt_c = t_opts.get("C", opt_c)
            if not (_safe_opt_val(opt_d, "translated") or _safe_opt_val(opt_d, "original")):
                opt_d = t_opts.get("D", opt_d)
        else:
            # 3. Aggressively strip any trailing option marker sequence at the end of q_text
            m_trail = re.search(
                r'(?m)(?:^|[\r\n]+|\s{2,}|\t|\s+)(?:[\(\[]\s*[aA1અक]\s*[\)\]]|[aA1અक][\.\:\)])\s+[\s\S]*?(?:[\(\[]\s*[bB2બख]\s*[\)\]]|[bB2બख][\.\:\)])\s+',
                q_text
            )
            if m_trail and m_trail.start() >= 10:
                q_text = q_text[:m_trail.start()].strip()

        # 4. Strip any dangling trailing option marker (e.g. trailing "(A)" or "[1]" at end of stem)
        q_text = re.sub(r'[\s,;\-]+(?:[\(\[]\s*[a-dA-D1-4]\s*[\)\]]|[a-dA-D1-4][\.\:\)])$', '', q_text).strip()

    if not q_text:
        q_text = clean_stem or raw_text or f"Question {question_number or global_id}"

    return q_text, opt_a, opt_b, opt_c, opt_d


def clean_numeric_answer(ans_str: Optional[str]) -> str:
    """Cleans numeric/integer/NAT answers (e.g. '(0)' -> '0', '(0003)' -> '0003', '[42]' -> '42', 'Ans: 5' -> '5', '(1/2)' -> '1/2', '4.5 m/s' -> '4.5').
    Strictly guarantees that:
    - Pure letters (A, B, C, D, etc.) are REJECTED and return empty string "" (never converted to 1-4).
    - Returns ONLY pure numbers, decimals, fractions, or negative numbers (preserving leading zeros like 0003).
    - Strips all physical units (m/s, kg, cm, Joules, etc.) and answer prefixes."""
    if not ans_str:
        return ""
    s = str(ans_str).strip()
    if s.lower() in ["null", "none", "n/a", "-", "", "undefined", "false"]:
        return ""

    # Strip leading "Ans:", "Answer:", "Key:", "=", ":", "જવાબ:", "ઉત્તર:"
    s = re.sub(r'^(?:ans(?:wer)?|જવાબ|ઉત્તર|key)\s*(?:is|:|:=|-|\.|\/|=)?\s*', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r'^[=:]\s*', '', s).strip()

    # Reject if it is purely an option letter e.g. "A", "B", "C", "D", "(A)", "[b]", "અ", "બ"
    if re.match(r'^[\(\[]?\s*([a-dA-D]|અ|બ|ક|ડ|क|ख|ग|घ)\s*[\)\]]?$', s):
        return ""

    # Strip wrapping parentheses/brackets/braces e.g. (0), [42], {5}, (0003), (-5), (1/2)
    m_wrap = re.match(r'^[\(\[\{]\s*([+-]?\d+(?:\.\d+)?|[+-]?\d+\s*\/\s*\d+)\s*[\)\]\}]$', s)
    if m_wrap:
        return m_wrap.group(1).replace(" ", "").strip()

    # Interval or coordinate answer e.g. (-15/2, 30) or (-\infty, -15/2)
    if "(" in s or "[" in s or "\\cup" in s or "\\infty" in s or "," in s:
        if re.search(r'\d', s) and not re.search(r'^[a-zA-Z\s]+$', s):
            return s.strip()

    # Pure number / decimal / fraction
    m_num = re.match(r'^[+-]?\d+(?:\.\d+)?(?:\s*\/\s*\d+)?$', s)
    if m_num:
        return m_num.group(0).replace(" ", "").strip()

    # Extract number with units e.g. "4.5 m/s", "12 kg", "x = 42", "approx 3.14", "Ans = 2"
    m_extract = re.search(r'(?:^|[^\w\.])([+-]?\d+(?:\.\d+)?|[+-]?\d+\s*\/\s*\d+)(?=[^\w\.]|$)', s)
    if m_extract:
        val = m_extract.group(1).replace(" ", "").strip()
        if re.search(r'\d', val):
            return val

    # If it contains any digits, strip common units and clean
    if re.search(r'\d', s):
        cleaned = re.sub(r'(?i)\s*(?:m\/s|m\/s\^2|cm|mm|km|kg|gm|g|joules?|j|newtons?|n|watts?|w|volts?|v|ohms?|hz|sec|s|rad|deg|°)\b', '', s).strip()
        cleaned = re.sub(r'^[a-zA-Z\s\=\:\~]+', '', cleaned).strip()
        if cleaned and re.search(r'\d', cleaned):
            return cleaned

    return ""


def clean_topic_title(raw_topic: Optional[str]) -> str:
    """Cleans and normalizes topic titles while strictly enforcing 2-level section numbering
    (e.g. '1.1', '1.2', '1.3', '1.1 Introduction', 'Topic 1.1: Coulomb's Law' -> '1.1 Coulomb's Law').
    Strictly reduces/collapses 3-level sub-topics (e.g. '1.1.1', '1.1.2', '1.2.1') to 2-level (e.g. '1.1', '1.2')."""
    if not raw_topic:
        return ""
    s = str(raw_topic).strip()

    # Match 3+ level subtopics like 1.1.1, 1.1.2, 1.1.3, 1.2.1, 1.2.2, 5.1.3 -> collapse to 2-level (1.1, 1.2, 5.1)
    sub3_match = re.match(r'^(?:Topic|Section|મુદ્દો|વિભાગ|ટોપિક)?\s*(\d+\.\d+|[૦-૯]+\.[૦-૯]+|[०-९]+\.[०-९]+)(?:\.\d+|\.[૦-૯]+|\.[०-९]+)+\s*[:\-\.]?\s*(.*)$', s, re.I)
    if sub3_match:
        sec_num = sub3_match.group(1).strip()
        sec_rest = sub3_match.group(2).strip()
        if sec_rest:
            return f"{sec_num} {sec_rest}"
        return sec_num

    # Match 2-level section numbers like 1.1, 1.2, 1.3, 1.4, 5.1, 5.2
    sec_match = re.match(r'^(?:Topic|Section|મુદ્દો|વિભાગ|ટોપિક)?\s*(\d+\.\d+|[૦-૯]+\.[૦-૯]+|[०-९]+\.[०-९]+)(?!\.\d+)\s*[:\-\.]?\s*(.*)$', s, re.I)
    if sec_match:
        sec_num = sec_match.group(1).strip()
        sec_rest = sec_match.group(2).strip()
        if sec_rest:
            return f"{sec_num} {sec_rest}"
        return sec_num

    # Otherwise strip generic Topic / Section prefixes e.g. Topic 1: -> Title
    cleaned = re.sub(
        r'^\s*(?:Topic|Section|મુદ્દો|વિભાગ|પ્રકરણ|ટોપિક|ટાસ્ક)?[\s\-_:]*(?:\d+|[૦-૯]+|[०-९]+)?[\s\-_:\.]+\s*',
        '',
        s,
        flags=re.IGNORECASE
    ).strip()
    return cleaned if cleaned else s


def generate_topic_description(topic_name: str, raw_desc: Optional[str] = None, chapter_name: Optional[str] = None) -> str:
    """Generates an authentic, grammatically natural topic description in the same language as the topic (specifically Gujarati when Gujarati text is present).
    Guarantees no English boilerplate text is output for Gujarati topics."""
    t_clean = str(topic_name or "").strip()
    c_clean = str(chapter_name or "").strip()
    r_desc = str(raw_desc or "").strip()

    is_gujarati = bool(re.search(r'[\u0A80-\u0AFF]', t_clean + " " + c_clean))
    is_hindi = bool(re.search(r'[\u0900-\u097F]', t_clean + " " + c_clean))

    if r_desc:
        has_guj_desc = bool(re.search(r'[\u0A80-\u0AFF]', r_desc))
        has_hin_desc = bool(re.search(r'[\u0900-\u097F]', r_desc))
        is_boilerplate = any(b in r_desc.lower() for b in [
            "curriculum concepts", "core concepts", "fundamental principles",
            "properties and behavior", "page ", "importance of", "nature of",
            "uncertainty in", "laws of", "theory", "concept", "calculations"
        ])
        if is_gujarati and has_guj_desc and not is_boilerplate:
            return r_desc
        if is_hindi and has_hin_desc and not is_boilerplate:
            return r_desc
        if not is_gujarati and not is_hindi and r_desc and not is_boilerplate:
            return r_desc

    # Strip section number prefix (e.g. "1.1 ", "1.10 ")
    t_stem = re.sub(r'^(?:[૦-૯\d]+\.[૦-૯\d]+\.?\s*|\b\d+\s*[\.\:\-]\s*)', '', t_clean).strip()
    if not t_stem:
        t_stem = t_clean

    if is_gujarati:
        if any(w in t_stem for w in ["મહત્વ", "ઉપયોગિતા", "જરૂરિયાત"]):
            return f"{t_stem} અને તેની મૂળભૂત સંકલ્પનાઓની વિસ્તૃત સમજ"
        elif any(w in t_stem for w in ["નિયમો", "નિયમ", "સિદ્ધાંત", "સિદ્ધાંતો"]):
            return f"{t_stem} અને તેના પાયાના ખ્યાલોની સમજૂતી"
        elif any(w in t_stem for w in ["ગુણધર્મો", "સ્વભાવ", "લાક્ષણિકતાઓ"]):
            return f"{t_stem} અને તેની મુખ્ય લાક્ષણિકતાઓની વિગતવાર સમજ"
        elif any(w in t_stem for w in ["માપન", "ગણતરી", "સમીકરણ", "તત્ત્વયોગમિતિ"]):
            return f"{t_stem} અને તેના પ્રાયોગિક ઉપયોગો તેમજ ગણતરીઓની સમજ"
        else:
            return f"{t_stem} અંગેના મુખ્ય સિદ્ધાંતો અને પાયાની સંકલ્પનાઓની સમજ"
    elif is_hindi:
        return f"{t_stem} के मुख्य सिद्धांत और आधारभूत अवधारणाओं की समझ"
    else:
        return f"Fundamental concepts, core principles, and applications of {t_stem}"


def is_generic_topic_name(name: str, chapter_name: str = "", file_name: str = "") -> bool:
    """Returns True if a topic name is generic, dummy, empty, or equals chapter name (indicating Common Data)."""
    if not name:
        return True
    n = name.strip().lower()
    # If topic has section number like 1.1, 1.2, 1.3, 2.1, it is a genuine textbook section and NEVER generic!
    if re.search(r'\d+\.\d+|[૦-૯]+\.[૦-૯]+|[०-९]+\.[०-९]+', n):
        return False
    ch = (chapter_name or "").strip().lower()
    fn = (file_name or "").strip().lower()
    if n in ["general", "none", "null", "common", "default", "all", "chapter", "topic", "section", "પ્રકરણ", "સામાન્ય", "મુખ્ય", "swadhyay", "exercise", "unknown", ""]:
        return True
    if re.match(r'^(?:topic|section|part|ch|chapter|unit|પ્રકરણ|વિભાગ)[\s\-_]*\d*$', n):
        return True
    if ch and (n == ch or n in ch or ch in n):
        return True
    if fn and (n == fn or n in fn):
        return True
    return False


def _extract_topics_and_mapping(results: List[ExtractionResult]) -> Tuple[List[Dict[str, Any]], Dict[str, Any], bool]:
    """Collects and normalizes genuine unique 2-level topics across results (e.g. 1.1, 1.2, 1.3, 1.4).
    Strictly forbids 3-level subtopics (1.1.1, 1.1.2, 1.2.1) and maps any subtopic to its parent 2-level topic.
    For Common Data (no genuine topic breakdown), returns has_topics=False so NO Topics sheet or Topic ID column is produced."""
    all_topics: List[Dict[str, Any]] = []
    seen_sec_nums: Dict[str, int] = {}  # "1.1" -> index in all_topics
    seen_topic_keys: Dict[str, Any] = {}

    def extract_sec_num(txt: str) -> Optional[str]:
        m = re.search(r'\b(\d+\.\d+|[૦-૯]+\.[૦-૯]+|[०-९]+\.[०-९]+)\b(?!\.\d+)', txt)
        return m.group(1) if m else None

    # 1. Collect from ExtractionResult.topics
    for res in results:
        res_topics = getattr(res, "topics", []) or []
        is_from_textbook = getattr(res, "has_textbook", False) or len(res_topics) >= 2
        for t in res_topics:
            t_dict = t if isinstance(t, dict) else t.model_dump()
            raw_t_name = str(t_dict.get("topic") or "").strip()
            if not raw_t_name:
                continue
            t_name = clean_topic_title(raw_t_name)
            if not t_name:
                continue
            # Disallow 3-level topics (e.g. 1.1.1, 1.1.2)
            if re.search(r'\b\d+\.\d+\.\d+\b', t_name):
                continue
            if not is_from_textbook and is_generic_topic_name(t_name, getattr(res, "chapter_name", ""), getattr(res, "file_name", "")):
                continue

            sec_num = extract_sec_num(t_name) or extract_sec_num(str(t_dict.get("id") or ""))
            tid = sec_num if sec_num else (t_dict.get("id") or (len(all_topics) + 1))
            ch_num = t_dict.get("chapter_number") or getattr(res, "chapter_number", "") or ""
            ch_name = t_dict.get("chapter_name") or getattr(res, "chapter_name", "") or ""
            desc_text = generate_topic_description(t_name, raw_desc=t_dict.get("description"), chapter_name=ch_name)

            if sec_num and sec_num in seen_sec_nums:
                existing_idx = seen_sec_nums[sec_num]
                if len(t_name) > len(all_topics[existing_idx]["topic"]):
                    all_topics[existing_idx]["topic"] = t_name
                    all_topics[existing_idx]["description"] = desc_text
            else:
                k = t_name.lower()
                if k not in seen_topic_keys:
                    seen_topic_keys[k] = tid
                    if sec_num:
                        seen_sec_nums[sec_num] = len(all_topics)
                    all_topics.append({
                        "id": tid,
                        "chapter_number": ch_num,
                        "chapter_name": ch_name,
                        "topic": t_name,
                        "description": desc_text
                    })

    # 2. Collect from QuestionItem.topic (only if genuine and non-generic)
    for res in results:
        is_from_textbook = getattr(res, "has_textbook", False)
        for q in res.questions:
            raw_t_name = str(getattr(q, "topic", "") or "").strip()
            if not raw_t_name:
                continue
            t_name = clean_topic_title(raw_t_name)
            if not t_name:
                continue
            # Normalize q.topic to clean 2-level version
            q.topic = t_name

            sec_num = extract_sec_num(t_name) or extract_sec_num(str(getattr(q, "topic_id", "") or ""))
            if sec_num:
                q.topic_id = sec_num

            if not is_from_textbook and is_generic_topic_name(t_name, getattr(res, "chapter_name", ""), getattr(res, "file_name", "")):
                continue

            tid = sec_num if sec_num else (getattr(q, "topic_id", None) or (len(all_topics) + 1))
            ch_num = getattr(q, "chapter_number", None) or getattr(res, "chapter_number", "") or ""
            ch_name = getattr(q, "chapter_name", None) or getattr(res, "chapter_name", "") or ""
            desc_text = generate_topic_description(t_name, chapter_name=ch_name)

            if sec_num and sec_num in seen_sec_nums:
                existing_idx = seen_sec_nums[sec_num]
                if len(t_name) > len(all_topics[existing_idx]["topic"]):
                    all_topics[existing_idx]["topic"] = t_name
            else:
                if t_name.lower() not in seen_topic_keys:
                    seen_topic_keys[t_name.lower()] = tid
                    if sec_num:
                        seen_sec_nums[sec_num] = len(all_topics)
                    all_topics.append({
                        "id": tid,
                        "chapter_number": ch_num,
                        "chapter_name": ch_name,
                        "topic": t_name,
                        "description": desc_text
                    })

    # Filter out single generic topic artifacts for common data (unless from textbook or multiple topics)
    any_textbook = any(getattr(res, "has_textbook", False) for res in results) or len(all_topics) >= 2
    if not any_textbook:
        valid_topics = [t for t in all_topics if not is_generic_topic_name(t.get("topic", ""), t.get("chapter_name", ""))]
    else:
        valid_topics = all_topics

    if not valid_topics:
        return [], {}, False

    # Natural sort topics by section number (1.1, 1.2, 1.3... 1.10, 2.1...)
    def _topic_sort_key(t):
        t_id_str = str(t.get("id") or "")
        t_str = str(t.get("topic") or "")
        m = re.search(r'(\d+)(?:\.(\d+))?', t_id_str) or re.search(r'(\d+)(?:\.(\d+))?', t_str)
        if m:
            p1 = int(m.group(1)) if m.group(1) else 0
            p2 = int(m.group(2)) if m.group(2) else 0
            return (p1, p2)
        return (999, 999)

    valid_topics.sort(key=_topic_sort_key)

    # Assign clean sequential integer IDs (1, 2, 3, 4...)
    for idx, t in enumerate(valid_topics, start=1):
        old_id = str(t.get("id") or "")
        t["id"] = idx
        t["_orig_id"] = old_id

    # Build comprehensive lookup mapping dictionary
    lookup_map: Dict[str, Any] = {}
    for t in valid_topics:
        tid = t["id"]
        t_title = t["topic"]
        lookup_map[t_title.lower()] = tid
        s_m = re.search(r'\b(\d+\.\d+|[૦-૯]+\.[૦-૯]+|[०-९]+\.[०-९]+)\b', t_title)
        if s_m:
            lookup_map[s_m.group(1).lower()] = tid
            lookup_map[s_m.group(1)] = tid
        orig_id = t.get("_orig_id")
        if orig_id:
            lookup_map[orig_id.lower()] = tid
            lookup_map[orig_id] = tid
        lookup_map[str(tid).lower()] = tid
        lookup_map[str(tid)] = tid

    # Clean up internal key
    for t in valid_topics:
        t.pop("_orig_id", None)

    # Back-fill topic names & integer IDs into questions
    for res in results:
        for q in getattr(res, "questions", []):
            raw_q_topic = str(getattr(q, "topic", "") or "").strip()
            raw_q_tid = str(getattr(q, "topic_id", "") or "").strip()
            clean_q_t = clean_topic_title(raw_q_topic)
            if clean_q_t:
                q.topic = clean_q_t
            sec_q = extract_sec_num(clean_q_t) or extract_sec_num(raw_q_tid)
            if sec_q and sec_q in lookup_map:
                q.topic_id = lookup_map[sec_q]
                for vt in valid_topics:
                    if vt["id"] == q.topic_id or str(vt["topic"]).startswith(str(sec_q)):
                        q.topic = vt["topic"]
                        break
            elif raw_q_tid and raw_q_tid in lookup_map:
                q.topic_id = lookup_map[raw_q_tid]
            elif clean_q_t and clean_q_t.lower() in lookup_map:
                q.topic_id = lookup_map[clean_q_t.lower()]

    has_topics = len(valid_topics) > 0
    return valid_topics, lookup_map, has_topics


def sort_questions_naturally(questions: List[Any]) -> List[Any]:
    """Sorts questions naturally by (page_number, question_number, sub_question_order) to ensure strict sequential
    reading order across pages and columns: P1-Q1, P1-Q2... P1-Q27(i), P1-Q27(ii)... etc."""
    roman_map = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10}

    def extract_page_and_num(q):
        is_dict = isinstance(q, dict)
        q_num = q.get('question_number') if is_dict else getattr(q, 'question_number', None)
        page_num = q.get('page_number', 1) if is_dict else getattr(q, 'page_number', 1)
        q_str = str(q_num or '').strip()

        # Match base number and sub-part (e.g. 27(i), 27(ii), 27.1, 27a)
        m = re.search(r'(\d+)\s*(?:[\.\-_/\(]\s*([ivxlcdm]+|[a-z]|\d+)\s*[\)]?)?', q_str, re.IGNORECASE)
        if m:
            q_int = int(m.group(1))
            sub_val = m.group(2)
            if sub_val:
                sub_lower = sub_val.lower()
                if sub_lower in roman_map:
                    sub_order = roman_map[sub_lower]
                elif sub_lower.isdigit():
                    sub_order = int(sub_lower)
                else:
                    sub_order = ord(sub_lower[0]) if len(sub_lower) == 1 else 999
            else:
                sub_order = 0
        else:
            m_digits = re.search(r'\d+', q_str)
            q_int = int(m_digits.group(0)) if m_digits else 999999
            sub_order = 0

        p_int = int(page_num) if page_num is not None else 1
        return (p_int, q_int, sub_order, q_str)

    return sorted(questions, key=extract_page_and_num)


def format_solution_text(solution_text: str) -> str:
    """Formats step-by-step solution text cleanly with LaTeX math and newline breaks for equations and steps."""
    if not solution_text:
        return ""
    text = solution_text.strip()

    # CRITICAL FIX 1: Normalize double backslashes (Gemini outputs \\frac, \\Omega etc.)
    # \\command → \command  (but preserve \\ that means newline in LaTeX, i.e. standalone \\)
    text = re.sub(r'\\\\([a-zA-Z])', r'\\\1', text)

    # CRITICAL FIX 2: Fix invalid combined macros from Gemini output
    # \DeltaR → \Delta R, \OmegaX → \Omega X, \thetaV → \theta V  etc.
    text = re.sub(
        r'\\(Delta|Gamma|Lambda|Sigma|Omega|Phi|Pi|Psi|Theta|'
        r'alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|'
        r'lambda|mu|nu|xi|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)'
        r'([A-Z])',
        r'\\\1 \2', text
    )

    # 0a. Strip any leading question-number echoes like "5." "Q5:" "Q.5:" "Sol.5:" at the start
    text = re.sub(r'^\s*(?:Q(?:uestion)?\.?\s*\d+\s*[:\.\-\)]|Sol(?:ution)?\.?\s*\d*\s*[:\.\-]?)\s*', '', text, flags=re.IGNORECASE)

    # 0b. Remove artificial "Step 1:", "Step 2:", "Step 3:", etc. from every line (any format)
    text = re.sub(r'(?im)^\s*step[\s\-]*\d+\s*[:\.\-\)]?\s*', '', text)
    text = re.sub(r'\n\s*step[\s\-]*\d+\s*[:\.\-\)]?\s*', '\n', text, flags=re.IGNORECASE)

    # 1. Convert bare arrow symbols (=> and →) to LaTeX \Rightarrow
    # Use lambda to avoid re.sub template parsing issues with \Rightarrow
    text = re.sub(r'(?<!\$)\s*(=>|→)\s*', lambda m: '\n$\\Rightarrow$ ', text)
    # Wrap bare \Rightarrow (outside $...$) in $...$
    text = re.sub(r'(?<!\$)\\Rightarrow(?!\s*\$)', lambda m: '\n$\\Rightarrow$ ', text)

    # 2. Clean up 3+ blank lines → max 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def results_to_dataframe(results: List[ExtractionResult], marks: Optional[int] = None) -> pd.DataFrame:
    """Flattens extracted question results into the exact standard exam platform format,
    dynamically switching to the 21-column Paragraph format or 21-column Matching Column format
    when JEE Advanced / comprehension questions are present."""
    all_topics, seen_topic_keys, has_topics = _extract_topics_and_mapping(results)

    has_paragraph = any(
        bool(getattr(q, "paragraph", "") or getattr(q, "paragraph_image_url", ""))
        for res in results for q in getattr(res, "questions", [])
    )
    has_matching = any(
        bool(getattr(q, "column_i", "") or getattr(q, "column_ii", "") or (getattr(q, "question_type", "") or "").upper() == "MATCH THE LIST" or any(kw in (getattr(q, "translated_question", "") or getattr(q, "original_question", "")).lower() for kw in ["match the list", "match the column", "column-i", "list-i", "કૉલમ-i", "જોડકા"]))
        for res in results for q in getattr(res, "questions", [])
    )

    rows = []
    global_id = 1
    last_para_seen = None

    for res in results:
        sorted_qs = sort_questions_naturally(res.questions)
        for q in sorted_qs:
            raw_q = (q.translated_question or q.original_question or "").strip()
            q_text, opt_a, opt_b, opt_c, opt_d = extract_pure_stem_and_options(
                raw_q=raw_q,
                opts=q.options,
                question_number=q.question_number,
                global_id=global_id,
            )

            a_url = _safe_opt_val(opt_a, "image_url")
            a_has_img = bool(a_url or _safe_opt_val(opt_a, "has_image"))
            a_img = (a_url.split("/")[-1] if a_url else ("Yes" if a_has_img else ""))

            b_url = _safe_opt_val(opt_b, "image_url")
            b_has_img = bool(b_url or _safe_opt_val(opt_b, "has_image"))
            b_img = (b_url.split("/")[-1] if b_url else ("Yes" if b_has_img else ""))

            c_url = _safe_opt_val(opt_c, "image_url")
            c_has_img = bool(c_url or _safe_opt_val(opt_c, "has_image"))
            c_img = (c_url.split("/")[-1] if c_url else ("Yes" if c_has_img else ""))

            d_url = _safe_opt_val(opt_d, "image_url")
            d_has_img = bool(d_url or _safe_opt_val(opt_d, "has_image"))
            d_img = (d_url.split("/")[-1] if d_url else ("Yes" if d_has_img else ""))
            q_img = (q.image_url.split("/")[-1] if getattr(q, "image_url", None) else ("Yes" if getattr(q, "has_question_image", False) else ""))
            ans_img = (q.answer_image_url.split("/")[-1] if q.answer_image_url else "")
            sol_img = (q.solution_image_url.split("/")[-1] if q.solution_image_url else ("Yes" if q.has_solution_image else ""))

            a_text = clean_option_text(str(_safe_opt_val(opt_a, "translated") or _safe_opt_val(opt_a, "original") or (opt_a if isinstance(opt_a, str) else "")), has_image=a_has_img)
            b_text = clean_option_text(str(_safe_opt_val(opt_b, "translated") or _safe_opt_val(opt_b, "original") or (opt_b if isinstance(opt_b, str) else "")), has_image=b_has_img)
            c_text = clean_option_text(str(_safe_opt_val(opt_c, "translated") or _safe_opt_val(opt_c, "original") or (opt_c if isinstance(opt_c, str) else "")), has_image=c_has_img)
            d_text = clean_option_text(str(_safe_opt_val(opt_d, "translated") or _safe_opt_val(opt_d, "original") or (opt_d if isinstance(opt_d, str) else "")), has_image=d_has_img)

            has_any_opt_text = bool(a_text or b_text or c_text or d_text)
            has_any_opt_img = bool(a_has_img or b_has_img or c_has_img or d_has_img)

            q_type_upper = (getattr(q, "question_type", "") or "").upper()
            is_matching = is_matching_question(q) or is_advance_matching_question(q) or any(k in q_type_upper for k in ["MATCH", "MATRIX", "COLUMN", "LIST"])
            is_explicit_num = any(k in q_type_upper for k in ["NUMER", "INTEGER", "NAT"])
            cleaned_num = clean_numeric_answer(q.answer)
            is_num_ans = bool(cleaned_num)
            is_letter_ans = bool(normalize_option_key(q.answer) in ["A", "B", "C", "D"] or re.match(r'^[A-D](?:\s*,\s*[A-D])+$', str(q.answer or "").strip().upper()))
            is_num_type = (is_explicit_num or (
                not has_any_opt_text and not has_any_opt_img
            ) or (is_num_ans and not is_letter_ans and not has_any_opt_text)) and not is_matching

            if is_num_type:
                continue

            if not (has_any_opt_text or has_any_opt_img or is_matching):
                continue

            is_dummy_stem = len(q_text) < 4 or bool(re.match(r'^\s*Q?\d+[\.\:\-\)]?\s*$', q_text))
            if is_dummy_stem and not (has_any_opt_text or has_any_opt_img) and not (q.has_question_image or q.image_url):
                continue

            # 2. STRICT ANSWER CHECK: MCQs without answers are NOT included in Excel
            norm = normalize_option_key(q.answer)
            if norm in ["A", "B", "C", "D"]:
                final_ans = norm
            elif re.match(r'^[A-D](?:\s*,\s*[A-D])+$', str(q.answer or "").strip().upper()):
                final_ans = str(q.answer or "").strip().upper()
            elif str(q.answer or "").strip().upper() not in ["", "NONE", "NULL", "-", "--", "?", "UNKNOWN", "NA", "N/A"]:
                ans_str = str(q.answer or "").strip()
                if ans_str in ["1", "2", "3", "4"]:
                    final_ans = {"1": "A", "2": "B", "3": "C", "4": "D"}[ans_str]
                elif ans_str in ["અ", "બ", "ક", "ડ"]:
                    final_ans = {"અ": "A", "બ": "B", "ક": "C", "ડ": "D"}[ans_str]
                elif ans_str in ["क", "ख", "ग", "घ"]:
                    final_ans = {"क": "A", "ખ": "B", "ग": "C", "घ": "D"}[ans_str]
                else:
                    final_ans = ans_str
            else:
                final_ans = None

            if not final_ans:
                fallback_ans = extract_answer_from_text(getattr(q, "solution", "")) or extract_answer_from_text(q_text) or extract_answer_from_text(raw_q)
                if fallback_ans:
                    final_ans = fallback_ans

            if not final_ans or str(final_ans).strip().lower() in ["", "none", "null", "-", "--", "?", "unknown", "na", "n/a"]:
                final_ans = ""

            final_type = "Match the Column" if is_matching else "MCQ"
            assigned_id = global_id

            # Resolve Subject
            assigned_subj = getattr(q, "subject", None) or getattr(res, "subject", "")
            if not assigned_subj or str(assigned_subj).strip().lower() in ["general", "none", "null", ""]:
                from app.extractor import detect_document_subject
                all_q_corpus = " ".join([
                    str(getattr(item, "translated_question", "") or getattr(item, "original_question", "")) + " " + str(getattr(item, "solution", "") or "")
                    for item in getattr(res, "questions", [])
                ])
                assigned_subj = detect_document_subject(all_q_corpus, file_name=getattr(res, "file_name", ""), chapter_name=str(getattr(res, "chapter_name", "")))

            formatted_sol = format_solution_text(q.solution or "")
            diff_num = getattr(q, "difficulty", 0) or 0
            q_marks_val = marks if marks is not None else (getattr(q, "marks", 4) or 4)

            if has_paragraph:
                # 21-Column Paragraph format
                is_head = getattr(q, "is_paragraph_head", None)
                p_text = str(getattr(q, "paragraph", "") or "").strip()
                p_img_url = getattr(q, "paragraph_image_url", "")
                p_img = (p_img_url.split("/")[-1] if p_img_url else "")

                if is_head is None:
                    is_head = bool((p_text or p_img) and (p_text != last_para_seen if p_text else True))

                if is_head:
                    row_para = p_text
                    row_para_img = p_img
                    last_para_seen = p_text or "has_img"
                elif p_text or p_img:
                    row_para = ""
                    row_para_img = ""
                else:
                    row_para = ""
                    row_para_img = ""
                    last_para_seen = None

                row_dict = {
                    "ID": assigned_id,
                    "Paragraph": row_para,
                    "Question": q_text,
                    "Type": final_type,
                    "Option A": a_text,
                    "Option B": b_text,
                    "Option C": c_text,
                    "Option D": d_text,
                    "Answer": final_ans,
                    "Marks": q_marks_val,
                    "Difficulty": diff_num,
                    "Subject": assigned_subj,
                    "Paragraph Image": row_para_img,
                    "Question Image": q_img,
                    "Answer Image": ans_img,
                    "Option A Image": a_img,
                    "Option B Image": b_img,
                    "Option C Image": c_img,
                    "Option D Image": d_img,
                    "Solution": formatted_sol,
                    "Solution Image": sol_img,
                }
            elif has_matching:
                # 21-Column Matching Column format
                col_i_text = str(getattr(q, "column_i", "") or "").strip()
                col_ii_text = str(getattr(q, "column_ii", "") or "").strip()
                if not col_i_text or not col_ii_text:
                    ext_col_i, ext_col_ii = extract_matching_columns(raw_q, opts)
                    if not col_i_text:
                        col_i_text = ext_col_i
                    if not col_ii_text:
                        col_ii_text = ext_col_ii
                col_i_a_img = getattr(q, "column_i_a_image_url", "").split("/")[-1] if getattr(q, "column_i_a_image_url", "") else ""
                col_i_b_img = getattr(q, "column_i_b_image_url", "").split("/")[-1] if getattr(q, "column_i_b_image_url", "") else ""
                col_i_c_img = getattr(q, "column_i_c_image_url", "").split("/")[-1] if getattr(q, "column_i_c_image_url", "") else ""
                col_i_d_img = getattr(q, "column_i_d_image_url", "").split("/")[-1] if getattr(q, "column_i_d_image_url", "") else ""

                row_dict = {
                    "ID": assigned_id,
                    "Question": q_text,
                    "Column-I": col_i_text,
                    "Column-II": col_ii_text,
                    "Type": final_type,
                    "Option A": a_text,
                    "Option B": b_text,
                    "Option C": c_text,
                    "Option D": d_text,
                    "Answer": final_ans,
                    "Marks": q_marks_val,
                    "Difficulty": diff_num,
                    "Subject": assigned_subj,
                    "Question Image": q_img,
                    "Answer Image": ans_img,
                    "Column-I A Image": col_i_a_img,
                    "Column-I B Image": col_i_b_img,
                    "Column-I C Image": col_i_c_img,
                    "Column-I D Image": col_i_d_img,
                    "Solution": formatted_sol,
                    "Solution Image": sol_img,
                }
            else:
                # Standard format
                row_dict = {
                    "ID": assigned_id,
                    "Question": q_text,
                    "Type": final_type,
                    "Option A": a_text,
                    "Option B": b_text,
                    "Option C": c_text,
                    "Option D": d_text,
                    "Answer": final_ans,
                    "Marks": q_marks_val,
                    "Difficulty": diff_num,
                }
                if has_topics:
                    q_topic_name = str(getattr(q, "topic", "") or "").strip().lower()
                    q_topic_id = getattr(q, "topic_id", None)
                    if q_topic_id is not None and str(q_topic_id).strip():
                        assigned_topic_id = q_topic_id
                    elif q_topic_name and q_topic_name in seen_topic_keys:
                        assigned_topic_id = seen_topic_keys[q_topic_name]
                    elif len(all_topics) == 1:
                        assigned_topic_id = all_topics[0]["id"]
                    else:
                        assigned_topic_id = ""
                    row_dict["Topic ID"] = assigned_topic_id
                else:
                    row_dict["Subject"] = assigned_subj

                row_dict.update({
                    "Question Image": q_img,
                    "Answer Image": ans_img,
                    "Option A Image": a_img,
                    "Option B Image": b_img,
                    "Option C Image": c_img,
                    "Option D Image": d_img,
                    "Solution": formatted_sol,
                    "Solution Image": sol_img,
                })

            rows.append(row_dict)
            global_id += 1

    return pd.DataFrame(rows)


def export_to_csv_bytes(results: List[ExtractionResult], marks: Optional[int] = None) -> bytes:
    """Exports extraction results to CSV encoded in UTF-8 with BOM for Excel compatibility."""
    df = results_to_dataframe(results, marks=marks)
    output = io.StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig')
    return output.getvalue().encode('utf-8-sig')


def natural_sort_key_helper(q: Any) -> Tuple[int, int, int]:
    """Helper to sort questions naturally by (page_number, question_number, sub_order)."""
    is_dict = isinstance(q, dict)
    q_num = q.get('question_number') if is_dict else getattr(q, 'question_number', None)
    page_num = q.get('page_number', 1) if is_dict else getattr(q, 'page_number', 1)
    q_str = str(q_num or '').strip()
    m = re.search(r'(\d+)\s*(?:[\.\-_/\(]\s*([ivxlcdm]+|[a-z]|\d+)\s*[\)]?)?', q_str, re.IGNORECASE)
    roman_map = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10}
    if m:
        q_int = int(m.group(1))
        sub_val = m.group(2)
        sub_order = roman_map.get(sub_val.lower(), 0) if sub_val else 0
        return (int(page_num or 1), q_int, sub_order)
    m_digits = re.search(r'\d+', q_str)
    return (int(page_num or 1), int(m_digits.group(0)) if m_digits else 9999, 0)


def ensure_paragraph_extracted(q: Any) -> None:
    """If a question has paragraph/passage content embedded in question_text, separates it into q.paragraph."""
    if getattr(q, "paragraph", None) and str(q.paragraph).strip():
        return
    raw_q = str(getattr(q, "translated_question", "") or getattr(q, "original_question", "") or "").strip()
    m_para = re.search(
        r'(?is)^\s*(?:paragraph|passage|વિભાગ\s*-\s*[૦-૯\d]+)?\s*(?:for\s+question\s+(?:nos\.?|numbers?|no\.?)\s*[\d\s,to\-and]+|[^\n\r]+passage[^\n\r]*)\s*[:\.\-]?\s*\n+([\s\S]+?)(?=\n+\s*(?:(?:Q|Question|પ્રશ્ન)?\s*\d+[\.\:\-\)]|\(?\d+\)[\.\:\-]?\s+|Q\.\d+))',
        raw_q
    )
    if m_para:
        p_content = m_para.group(0).strip()
        remaining_stem = raw_q[m_para.end():].strip()
        if remaining_stem:
            q.paragraph = p_content
            q.translated_question = remaining_stem
            q.original_question = remaining_stem


def is_paragraph_question(q) -> bool:
    """Checks if a QuestionItem is a paragraph / comprehension passage question."""
    if bool(str(getattr(q, "paragraph", "") or "").strip() or getattr(q, "paragraph_image_url", "")):
        return True
    q_type = (getattr(q, "question_type", "") or "").upper()
    if any(k in q_type for k in ["PARAGRAPH", "PASSAGE", "COMPREHENSION"]):
        return True
    raw_text = (getattr(q, "translated_question", "") or getattr(q, "original_question", "") or "").lower()
    return any(kw in raw_text for kw in ["paragraph for question", "passage for question", "read the following passage", "comprehension type", "paragraph -", "passage -"])


def is_matching_question(q) -> bool:
    """Checks if a QuestionItem is a match-the-column / match-the-list question."""
    if bool(str(getattr(q, "column_i", "") or "").strip() or str(getattr(q, "column_ii", "") or "").strip()):
        return True
    q_type = (getattr(q, "question_type", "") or "").upper()
    if any(k in q_type for k in ["MATCH THE LIST", "MATCH THE COLUMN", "MATCH_THE_COLUMN", "MATRIX MATCH", "MATCHING"]):
        return True
    raw_text = (getattr(q, "translated_question", "") or getattr(q, "original_question", "") or "").lower()
    return any(kw in raw_text for kw in ["match the list", "match the column", "column-i", "list-i", "કૉલમ-i", "જોડકા", "matrix match"])


def is_advance_matching_question(q) -> bool:
    """
    Checks if a match-the-column question is a genuine JEE Advanced Matrix Match.
    JEE Main match-the-column questions are standard 1-to-1 MCQs with Option A, B, C, D (e.g. A-I, B-II, C-III, D-IV).
    JEE Advanced matrix match questions feature:
    - Multi-matching where one item maps to 2+ targets (e.g. A -> P, Q, R; B -> P, S)
    - Explicit 'Matrix Match' or 'JEE Advanced' in question stem
    """
    if not is_matching_question(q):
        return False

    stem = ((getattr(q, "translated_question", "") or "") + " " + (getattr(q, "original_question", "") or "")).lower()
    if any(kw in stem for kw in ["matrix match", "matrix-match", "jee advanced", "jee (advanced)", "iit jee", "iit-jee"]):
        return True
    if any(kw in stem for kw in ["jee main", "jee (main)", "aieee"]):
        return False

    # Check answer for multi-mapping inside a single pair, e.g. "A->P,Q; B->R" or "A-P,Q"
    ans = str(getattr(q, "answer", "") or "").strip()
    if re.search(r'[A-Da-d]\s*(?:->|–|—|-|:)\s*[P-Tp-t1-5]\s*,\s*[P-Tp-t1-5]', ans):
        return True

    opts = getattr(q, "options", {}) or {}
    has_multi_match = False

    for k in ["A", "B", "C", "D"]:
        opt = opts.get(k)
        opt_text = ""
        if isinstance(opt, dict):
            opt_text = str(opt.get("translated") or opt.get("original") or "")
        elif hasattr(opt, "original") or hasattr(opt, "translated"):
            opt_text = str(getattr(opt, "translated", "") or getattr(opt, "original", "") or "")
        elif opt:
            opt_text = str(opt)

        if not opt_text:
            continue

        # Check for multi-mapping inside a single pair, e.g. "A -> P, Q"
        if re.search(r'[A-Da-d]\s*(?:->|–|—|-|:)\s*\(?\s*[P-Tp-t1-5]\s*,\s*[P-Tp-t1-5]', opt_text):
            has_multi_match = True
            break

    if has_multi_match:
        return True

    return False


def is_advance_paper(target: Any) -> bool:
    """
    Scans and strictly determines whether an extracted PDF paper is a genuine JEE Advanced paper.
    
    Returns:
        True  -> Strictly if verified as a genuine JEE Advanced paper (qualifies for 3 separate Excel files: Questions, Paragraph Type, Match the list).
        False -> For JEE Main, NEET, Board, or standard chapter tests (qualifies for ONLY 1 single Excel file).
    """
    if target is None:
        return False

    # If a list of ExtractionResult or objects
    if isinstance(target, list):
        if not target:
            return False
        return any(is_advance_paper(item) for item in target)

    # If a string (e.g. filename)
    if isinstance(target, str):
        file_name = target
        chap_name = ""
        questions = []
    elif isinstance(target, dict):
        file_name = str(target.get("file_name", "") or "")
        chap_name = str(target.get("chapter_name", "") or "")
        questions = target.get("questions", []) or []
    else:
        file_name = str(getattr(target, "file_name", "") or "")
        chap_name = str(getattr(target, "chapter_name", "") or "")
        questions = getattr(target, "questions", []) or []

    # 1. STRICT JEE MAIN / NEET / BOARD CHECK FIRST:
    # If filename or chapter name explicitly indicates JEE Main / AIEEE / NTA / NEET / CBSE / GSEB / Board,
    # it is NEVER JEE Advanced.
    is_main_fn = bool(re.search(r'(?i)(?:^|[^a-zA-Z0-9])(?:main|mains|jee_main|jee-main|jeemain|aieee|nta|neet|board|cbse|gseb)(?:[^a-zA-Z0-9]|$)', file_name))
    is_adv_fn = bool(re.search(r'(?i)(?:^|[^a-zA-Z0-9])(?:advance|advanced|adv|jee_adv|jee-adv|iit)(?:[^a-zA-Z0-9]|$)', file_name))
    if is_main_fn and not is_adv_fn:
        return False

    is_main_chap = bool(re.search(r'(?i)(?:^|[^a-zA-Z0-9])(?:jee\s*main|jee\s*\(main\)|aieee|mains|nta\s*jee|neet|cbse|board)(?:[^a-zA-Z0-9]|$)', chap_name))
    is_adv_chap = bool(re.search(r'(?i)(?:^|[^a-zA-Z0-9])(?:jee\s*advanced|jee\s*\(advanced\)|iit\s*jee|jee\s*adv)(?:[^a-zA-Z0-9]|$)', chap_name))
    if is_main_chap and not is_adv_chap:
        return False

    # 2. Inspect questions
    questions = getattr(target, "questions", []) or []
    if not questions:
        return is_adv_fn or is_adv_chap

    # Question text corpus check for paper title / exam indicator
    all_qs = questions[:40]
    corpus = " ".join([
        (getattr(q, "original_question", "") or "") + " " + (getattr(q, "translated_question", "") or "")
        for q in all_qs
    ])

    is_main_corpus = bool(re.search(r'(?i)\b(?:jee\s*main|jee\s*\(main\)|aieee|nta\s*jee|nta\s*score)\b', corpus))
    is_adv_corpus = bool(re.search(r'(?i)\b(?:jee\s*advanced|jee\s*\(advanced\)|iit\s*jee|jee\s*adv)\b', corpus))
    if is_main_corpus and not is_adv_corpus:
        return False

    # 3. Explicit JEE Advanced in title / filename / chapter / corpus
    if is_adv_fn or is_adv_chap or is_adv_corpus:
        return True

    # 4. Genuine JEE Advanced Multi-Correct Questions
    # (JEE Advanced uniquely features "One or more than one correct" format)
    has_multi_correct_type = any(
        re.search(r'(?i)\b(?:one\s+or\s+more\s+than\s+one|more\s+than\s+one\s+option|multiple\s+correct)\b', (getattr(q, "original_question", "") or "") + " " + (getattr(q, "translated_question", "") or ""))
        for q in questions
    )
    if has_multi_correct_type:
        return True

    # 5. Genuine JEE Advanced Matrix Match with multi-mapping
    if any(is_advance_matching_question(q) for q in questions):
        return True

    # Default to False: Standard JEE Main / single Excel file
    return False


def _populate_excel_sheet(ws, headers: List[str], items: List[Tuple[Any, Any]], sheet_type: str = "standard", all_topics: Optional[List[Dict[str, Any]]] = None, seen_topic_keys: Optional[Dict[str, Any]] = None, marks: Optional[int] = None):
    """Populates an openpyxl worksheet with formatted header, question data rows, and embedded images."""
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    cell_font = Font(name="Arial", size=10)
    border_thin = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    ws.append(headers)
    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align_center
        cell.border = border_thin
    ws.row_dimensions[1].height = 28

    col_letter_map = {header: get_column_letter(idx + 1) for idx, header in enumerate(headers)}
    current_row = 2
    last_para_seen = None
    valid_row_count = 0

    for global_id, (q, res) in enumerate(items, start=1):
        raw_q = (q.translated_question or q.original_question or "").strip()
        q_text, opt_a, opt_b, opt_c, opt_d = extract_pure_stem_and_options(
            raw_q=raw_q,
            opts=q.options,
            question_number=q.question_number,
            global_id=global_id,
        )

        a_has_img = bool(_safe_opt_val(opt_a, "image_url") or _safe_opt_val(opt_a, "has_image"))
        b_has_img = bool(_safe_opt_val(opt_b, "image_url") or _safe_opt_val(opt_b, "has_image"))
        c_has_img = bool(_safe_opt_val(opt_c, "image_url") or _safe_opt_val(opt_c, "has_image"))
        d_has_img = bool(_safe_opt_val(opt_d, "image_url") or _safe_opt_val(opt_d, "has_image"))

        a_text = clean_option_text(str(_safe_opt_val(opt_a, "translated") or _safe_opt_val(opt_a, "original") or (opt_a if isinstance(opt_a, str) else "")), has_image=a_has_img)
        b_text = clean_option_text(str(_safe_opt_val(opt_b, "translated") or _safe_opt_val(opt_b, "original") or (opt_b if isinstance(opt_b, str) else "")), has_image=b_has_img)
        c_text = clean_option_text(str(_safe_opt_val(opt_c, "translated") or _safe_opt_val(opt_c, "original") or (opt_c if isinstance(opt_c, str) else "")), has_image=c_has_img)
        d_text = clean_option_text(str(_safe_opt_val(opt_d, "translated") or _safe_opt_val(opt_d, "original") or (opt_d if isinstance(opt_d, str) else "")), has_image=d_has_img)

        has_any_opt_text = bool(a_text or b_text or c_text or d_text)
        has_any_opt_img = bool(a_has_img or b_has_img or c_has_img or d_has_img)
        has_options = has_any_opt_text or has_any_opt_img

        q_type_upper = (getattr(q, "question_type", "") or "").upper()
        is_matching = (sheet_type == "matching") or is_matching_question(q) or is_advance_matching_question(q) or any(k in q_type_upper for k in ["MATCH", "MATRIX", "COLUMN", "LIST"])
        is_explicit_num = any(k in q_type_upper for k in ["NUMER", "INTEGER", "NAT"])
        cleaned_num = clean_numeric_answer(q.answer)
        is_numeric = is_explicit_num or (not has_options and bool(cleaned_num or str(getattr(q, "answer", "")).strip()))

        # If this is dedicated matching sheet, only process matching questions
        if sheet_type == "matching" and not is_matching:
            continue
        # If this is paragraph sheet, only process paragraph questions
        if sheet_type == "paragraph" and not is_paragraph_question(q):
            continue

        # Determine Question Type and Answer
        final_ans = None
        if is_numeric and not has_options and sheet_type != "matching":
            final_type = "Numeric"
            # Numeric questions: Options A-D are left blank
            a_text, b_text, c_text, d_text = "", "", "", ""
            opt_a_val, opt_b_val, opt_c_val, opt_d_val = "", "", "", ""
            # Numerical answer strictly shows numeric value
            final_ans = cleaned_num or str(q.answer or "").strip()
            if not final_ans or str(final_ans).lower() in ["", "none", "null", "-", "--", "?", "unknown", "na", "n/a"]:
                fallback_num = extract_answer_from_text(getattr(q, "solution", "")) or extract_answer_from_text(q_text)
                final_ans = clean_numeric_answer(fallback_num) or fallback_num
            if not final_ans or str(final_ans).lower() in ["", "none", "null", "-", "--", "?", "unknown", "na", "n/a"]:
                final_ans = ""
        else:
            final_type = "Match the Column" if is_matching else "MCQ"

            # If Match the Column in standard sheet, embed Column-I and Column-II in question text for complete visibility
            if is_matching and sheet_type != "matching":
                col_i_text = str(getattr(q, "column_i", "") or "").strip()
                col_ii_text = str(getattr(q, "column_ii", "") or "").strip()
                if not col_i_text or not col_ii_text:
                    ext_col_i, ext_col_ii = extract_matching_columns(raw_q, q.options)
                    col_i_text = col_i_text or ext_col_i
                    col_ii_text = col_ii_text or ext_col_ii
                if col_i_text and col_ii_text:
                    col_sample = col_i_text.splitlines()[0].strip().lower() if col_i_text.splitlines() else col_i_text[:15].lower()
                    if not col_sample or col_sample not in q_text.lower():
                        q_text = f"{q_text}\n\n[Column-I]\n{col_i_text}\n\n[Column-II]\n{col_ii_text}"

            # STRICT RULE FOR MCQ & MATCHING: Answer MUST ONLY be 'A', 'B', 'C', or 'D' (never a number/text)
            norm = normalize_option_key(q.answer)
            if norm in ["A", "B", "C", "D"]:
                final_ans = norm
            elif re.match(r'^[A-D](?:\s*,\s*[A-D])+$', str(q.answer or "").strip().upper()):
                final_ans = re.sub(r'\s+', ' ', str(q.answer or "").strip().upper())
            else:
                raw_ans_str = str(q.answer or "").strip()
                # 1. Map numbered index 1->A, 2->B, 3->C, 4->D
                if raw_ans_str in ["1", "2", "3", "4"]:
                    final_ans = {"1": "A", "2": "B", "3": "C", "4": "D"}[raw_ans_str]
                # 2. Map Gujarati letters: અ->A, બ->B, ક->C, ડ->D
                elif raw_ans_str in ["અ", "A", "(A)", "A."]:
                    final_ans = "A"
                elif raw_ans_str in ["બ", "B", "(B)", "B."]:
                    final_ans = "B"
                elif raw_ans_str in ["ક", "C", "(C)", "C."]:
                    final_ans = "C"
                elif raw_ans_str in ["ડ", "D", "(D)", "D."]:
                    final_ans = "D"
                # 3. Map Hindi/Devanagari letters: क->A, ख->B, ग->C, घ->D
                elif raw_ans_str in ["क", "अ"]:
                    final_ans = "A"
                elif raw_ans_str in ["ख", "ब"]:
                    final_ans = "B"
                elif raw_ans_str in ["ग", "स"]:
                    final_ans = "C"
                elif raw_ans_str in ["घ", "द"]:
                    final_ans = "D"
                # 4. Check if raw answer matches option text or matching permutation
                else:
                    opt_map = {"A": a_text.lower(), "B": b_text.lower(), "C": c_text.lower(), "D": d_text.lower()}
                    matched_k = None
                    clean_raw_l = raw_ans_str.lower()
                    # Permutation matcher for matching questions
                    def norm_perm(s: str) -> str:
                        return re.sub(r'[^a-z0-9ivxlc]', '', s.lower())
                    norm_raw_perm = norm_perm(clean_raw_l)

                    for ok, ov in opt_map.items():
                        if ov and (clean_raw_l == ov or (len(norm_raw_perm) > 4 and norm_perm(ov) == norm_raw_perm)):
                            matched_k = ok
                            break
                    if matched_k:
                        final_ans = matched_k
                    else:
                        # 5. Check if option has is_correct=True
                        if isinstance(q.options, dict):
                            for ok, ov in q.options.items():
                                if getattr(ov, "is_correct", False) or (isinstance(ov, dict) and ov.get("is_correct")):
                                    final_ans = str(ok).upper()
                                    break
                        if not final_ans:
                            # 6. Fallback: extract letter from solution text if authentic solution exists
                            sol_raw = getattr(q, "solution", "") or ""
                            sol_letter = extract_answer_from_text(sol_raw) or extract_answer_from_text(q_text)
                            if sol_letter and sol_letter in ["A", "B", "C", "D"]:
                                final_ans = sol_letter
                            else:
                                final_ans = ""  # Leave blank if not printed in document (never guess "A")


        valid_row_count += 1
        diff_num = int(q.difficulty) if q.difficulty is not None else 0
        assigned_id = valid_row_count
        row_marks_val = marks if marks is not None else (getattr(q, "marks", 4) or 4)

        subj_val = getattr(q, "subject", None) or getattr(res, "subject", "")
        if not subj_val or str(subj_val).strip().lower() in ["general", "none", "null", ""]:
            from app.extractor import detect_document_subject
            all_q_corpus = " ".join([
                str(getattr(item, "translated_question", "") or getattr(item, "original_question", "")) + " " + str(getattr(item, "solution", "") or "")
                for item in getattr(res, "questions", [])
            ])
            subj_val = detect_document_subject(all_q_corpus, file_name=getattr(res, "file_name", ""), chapter_name=str(getattr(res, "chapter_name", "")))

        # Determine image cell values
        q_has_img = bool(q.image_url or getattr(q, "has_question_image", False))
        q_genuine = is_genuine_question_diagram(q_text, has_any_opt_text, q.image_url, has_opt_images=has_any_opt_img)
        q_img_val = (q.image_url.split("/")[-1] if q.image_url else ("Yes" if q_has_img else "")) if q_genuine else ""

        a_url = _safe_opt_val(opt_a, "image_url")
        b_url = _safe_opt_val(opt_b, "image_url")
        c_url = _safe_opt_val(opt_c, "image_url")
        d_url = _safe_opt_val(opt_d, "image_url")

        opt_a_val = (a_url.split("/")[-1] if a_url else ("Yes" if a_has_img else "")) if final_type != "Numeric" else ""
        opt_b_val = (b_url.split("/")[-1] if b_url else ("Yes" if b_has_img else "")) if final_type != "Numeric" else ""
        opt_c_val = (c_url.split("/")[-1] if c_url else ("Yes" if c_has_img else "")) if final_type != "Numeric" else ""
        opt_d_val = (d_url.split("/")[-1] if d_url else ("Yes" if d_has_img else "")) if final_type != "Numeric" else ""

        ans_img_url = getattr(q, "answer_image_url", None)
        ans_img_val = ans_img_url.split("/")[-1] if ans_img_url else ""

        is_verified_sol = bool(getattr(q, "solution_verified", True) and getattr(q, "verification_status", "") not in ["mismatch", "no_solution"] and getattr(q, "solution", ""))
        if not is_verified_sol:
            sol_img_url = None
            sol_img_val = ""
            sol_text_formatted = ""
        else:
            sol_img_url = getattr(q, "solution_image_url", None)
            sol_img_val = sol_img_url.split("/")[-1] if sol_img_url else ("Yes" if getattr(q, "has_solution_image", False) else "")

            # Format solution text cleanly - only if authentic solution exists
            raw_sol_text = str(getattr(q, "solution", "") or "").strip()
            if raw_sol_text and raw_sol_text.lower() not in ["", "none", "null", "-", "--", "na", "n/a", "?"]:
                sol_text_formatted = format_solution_text(raw_sol_text)
                if is_matching and getattr(q, "column_i", "") and getattr(q, "column_ii", "") and not any(k in sol_text_formatted for k in ["->", "→", "–", "—"]):
                    # If solution is brief, enrich with exact column mapping clarity
                    sol_text_formatted = f"Correct Match: Option ({final_ans})\n" + sol_text_formatted
            else:
                sol_text_formatted = ""

        is_head = False
        if sheet_type == "paragraph":
            is_head = getattr(q, "is_paragraph_head", None)
            p_text = str(getattr(q, "paragraph", "") or "").strip()
            p_img_url = getattr(q, "paragraph_image_url", "")
            if is_head is None:
                is_head = bool((p_text or p_img_url) and (p_text != last_para_seen if p_text else True))

            if is_head:
                row_para = p_text
                last_para_seen = p_text or "has_img"
            elif p_text or p_img_url:
                row_para = ""
            else:
                row_para = ""
                last_para_seen = None

            row_data = [
                assigned_id,
                row_para,
                q_text,
                final_type,
                a_text,
                b_text,
                c_text,
                d_text,
                final_ans,
                row_marks_val,
                diff_num,
                subj_val,
                (p_img_url.split("/")[-1] if p_img_url else "") if is_head else "",  # Paragraph Image
                q_img_val,  # Question Image
                ans_img_val,  # Answer Image
                opt_a_val,  # Option A Image
                opt_b_val,  # Option B Image
                opt_c_val,  # Option C Image
                opt_d_val,  # Option D Image
                sol_text_formatted,
                sol_img_val,  # Solution Image
            ]
        elif sheet_type == "matching":
            col_i_text = str(getattr(q, "column_i", "") or "").strip()
            col_ii_text = str(getattr(q, "column_ii", "") or "").strip()
            if not col_i_text or not col_ii_text:
                ext_col_i, ext_col_ii = extract_matching_columns(raw_q, q.options)
                if not col_i_text:
                    col_i_text = ext_col_i
                if not col_ii_text:
                    col_ii_text = ext_col_ii
            row_data = [
                assigned_id,
                q_text,
                col_i_text,
                col_ii_text,
                final_type,
                a_text,
                b_text,
                c_text,
                d_text,
                final_ans,
                row_marks_val,
                diff_num,
                subj_val,
                q_img_val,  # Question Image
                ans_img_val,  # Answer Image
                getattr(q, "column_i_a_image_url", "").split("/")[-1] if getattr(q, "column_i_a_image_url", None) else "",  # Column-I A Image
                getattr(q, "column_i_b_image_url", "").split("/")[-1] if getattr(q, "column_i_b_image_url", None) else "",  # Column-I B Image
                getattr(q, "column_i_c_image_url", "").split("/")[-1] if getattr(q, "column_i_c_image_url", None) else "",  # Column-I C Image
                getattr(q, "column_i_d_image_url", "").split("/")[-1] if getattr(q, "column_i_d_image_url", None) else "",  # Column-I D Image
                sol_text_formatted,
                sol_img_val,  # Solution Image
            ]
        elif sheet_type == "topics":
            q_topic_name = str(getattr(q, "topic", "") or "").strip().lower()
            q_topic_id = getattr(q, "topic_id", None)
            col_topic_val = ""
            if q_topic_id is not None and str(q_topic_id).strip():
                col_topic_val = q_topic_id
            elif q_topic_name and seen_topic_keys and q_topic_name in seen_topic_keys:
                col_topic_val = seen_topic_keys[q_topic_name]
            elif all_topics:
                for t_item in all_topics:
                    t_str = str(t_item.get("topic", "")).lower()
                    if t_str and (t_str in q_topic_name or q_topic_name in t_str):
                        col_topic_val = t_item.get("id", 1)
                        break
                if not col_topic_val:
                    col_topic_val = all_topics[0].get("id", 1)

            row_data = [
                assigned_id,
                q_text,
                final_type,
                a_text,
                b_text,
                c_text,
                d_text,
                final_ans,
                row_marks_val,
                diff_num,
                col_topic_val,
                q_img_val,  # Question Image
                ans_img_val,  # Answer Image
                opt_a_val,  # Option A Image
                opt_b_val,  # Option B Image
                opt_c_val,  # Option C Image
                opt_d_val,  # Option D Image
                sol_text_formatted,
                sol_img_val,  # Solution Image
            ]
        else:  # standard
            row_data = [
                assigned_id,
                q_text,
                final_type,
                a_text,
                b_text,
                c_text,
                d_text,
                final_ans,
                row_marks_val,
                diff_num,
                subj_val,
                q_img_val,  # Question Image
                ans_img_val,  # Answer Image
                opt_a_val,  # Option A Image
                opt_b_val,  # Option B Image
                opt_c_val,  # Option C Image
                opt_d_val,  # Option D Image
                sol_text_formatted,
                sol_img_val,  # Solution Image
            ]


        cleaned_row_data = []
        for item in row_data:
            if isinstance(item, str):
                cleaned_row_data.append(re.sub(r'[\000-\010]|[\013-\014]|[\016-\037]', '', item))
            else:
                cleaned_row_data.append(item)

        ws.append(cleaned_row_data)
        row_has_image = False

        def embed_cell_image(img_url: Optional[str], col_letter: str, row_num: int):
            nonlocal row_has_image
            if not img_url:
                return
            img_filename = img_url.split("/")[-1]
            img_path = IMAGES_DIR / img_filename
            if img_path.exists() and img_path.stat().st_size > 0:
                try:
                    with PILImage.open(img_path) as pil_img:
                        w, h = pil_img.size
                        if w > 0 and h > 0:
                            max_w, max_h = 140.0, 80.0
                            scale = min(max_w / w, max_h / h, 1.0)
                            new_w = max(10, int(w * scale))
                            new_h = max(10, int(h * scale))

                            xl_img = OpenpyxlImage(str(img_path))
                            xl_img.width = new_w
                            xl_img.height = new_h
                            ws.add_image(xl_img, f"{col_letter}{row_num}")
                            row_has_image = True
                except Exception as e:
                    logger.warning(f"Error embedding image {img_filename}: {e}")

        # Embed Paragraph Image only on head row of group
        if is_head and getattr(q, "paragraph_image_url", None) and "Paragraph Image" in col_letter_map:
            embed_cell_image(q.paragraph_image_url, col_letter_map["Paragraph Image"], current_row)

        # Embed Question Image only if genuine diagram (not text math / formula problem)
        has_any_opt_text = bool(a_text or b_text or c_text or d_text)
        has_any_opt_img = bool(
            _safe_opt_val(opt_a, "image_url") or _safe_opt_val(opt_a, "has_image")
            or _safe_opt_val(opt_b, "image_url") or _safe_opt_val(opt_b, "has_image")
            or _safe_opt_val(opt_c, "image_url") or _safe_opt_val(opt_c, "has_image")
            or _safe_opt_val(opt_d, "image_url") or _safe_opt_val(opt_d, "has_image")
        )
        if q.image_url and "Question Image" in col_letter_map and is_genuine_question_diagram(q_text, has_any_opt_text, q.image_url, has_opt_images=has_any_opt_img):
            embed_cell_image(q.image_url, col_letter_map["Question Image"], current_row)

        # Embed Answer Image
        if q.answer_image_url and "Answer Image" in col_letter_map:
            embed_cell_image(q.answer_image_url, col_letter_map["Answer Image"], current_row)

        # Embed Column-I Images
        if getattr(q, "column_i_a_image_url", None) and "Column-I A Image" in col_letter_map:
            embed_cell_image(q.column_i_a_image_url, col_letter_map["Column-I A Image"], current_row)
        if getattr(q, "column_i_b_image_url", None) and "Column-I B Image" in col_letter_map:
            embed_cell_image(q.column_i_b_image_url, col_letter_map["Column-I B Image"], current_row)
        if getattr(q, "column_i_c_image_url", None) and "Column-I C Image" in col_letter_map:
            embed_cell_image(q.column_i_c_image_url, col_letter_map["Column-I C Image"], current_row)
        if getattr(q, "column_i_d_image_url", None) and "Column-I D Image" in col_letter_map:
            embed_cell_image(q.column_i_d_image_url, col_letter_map["Column-I D Image"], current_row)

        # Embed Option Images
        opt_a_img = _safe_opt_val(opt_a, "image_url")
        if opt_a_img and "Option A Image" in col_letter_map:
            embed_cell_image(opt_a_img, col_letter_map["Option A Image"], current_row)
        opt_b_img = _safe_opt_val(opt_b, "image_url")
        if opt_b_img and "Option B Image" in col_letter_map:
            embed_cell_image(opt_b_img, col_letter_map["Option B Image"], current_row)
        opt_c_img = _safe_opt_val(opt_c, "image_url")
        if opt_c_img and "Option C Image" in col_letter_map:
            embed_cell_image(opt_c_img, col_letter_map["Option C Image"], current_row)
        opt_d_img = _safe_opt_val(opt_d, "image_url")
        if opt_d_img and "Option D Image" in col_letter_map:
            embed_cell_image(opt_d_img, col_letter_map["Option D Image"], current_row)

        # Embed Solution Image
        if q.solution_image_url and "Solution Image" in col_letter_map:
            embed_cell_image(q.solution_image_url, col_letter_map["Solution Image"], current_row)

        # Apply cell styles
        center_headers = {"ID", "Type", "Answer", "Marks", "Difficulty", "Topic ID", "Subject"}
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=current_row, column=col_idx)
            cell.font = cell_font
            cell.border = border_thin
            h_name = headers[col_idx - 1]
            if h_name in center_headers:
                cell.alignment = align_center
            else:
                cell.alignment = align_left

        ws.row_dimensions[current_row].height = 75 if row_has_image else 26
        current_row += 1

    # Set column widths
    base_col_widths = {
        "ID": 8,
        "Paragraph": 48,
        "Question": 48,
        "Column-I": 28,
        "Column-II": 28,
        "Type": 10,
        "Option A": 26,
        "Option B": 26,
        "Option C": 26,
        "Option D": 26,
        "Answer": 10,
        "Marks": 8,
        "Difficulty": 10,
        "Topic ID": 14,
        "Subject": 14,
        "Paragraph Image": 22,
        "Question Image": 22,
        "Answer Image": 14,
        "Column-I A Image": 20,
        "Column-I B Image": 20,
        "Column-I C Image": 20,
        "Column-I D Image": 20,
        "Option A Image": 20,
        "Option B Image": 20,
        "Option C Image": 20,
        "Option D Image": 20,
        "Solution": 36,
        "Solution Image": 22,
    }
    for idx, header in enumerate(headers):
        c_letter = get_column_letter(idx + 1)
        ws.column_dimensions[c_letter].width = base_col_widths.get(header, 16)


def _add_topics_worksheet(wb, all_topics: List[Dict[str, Any]], as_first_sheet: bool = True) -> None:
    """Creates a styled 'Topics' worksheet containing all extracted textbook topics at the FIRST position (Sheet 1)."""
    if not all_topics:
        return
    if as_first_sheet:
        ws_topics = wb.create_sheet(title="Topics", index=0)
    else:
        ws_topics = wb.create_sheet(title="Topics")
    topic_headers = ["id", "chapter number", "chapter name", "topic", "description"]
    ws_topics.append(topic_headers)

    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    cell_font = Font(name="Arial", size=10)
    border_thin = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    for col_num in range(1, len(topic_headers) + 1):
        cell = ws_topics.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align_center
        cell.border = border_thin
    ws_topics.row_dimensions[1].height = 28

    for t_idx, t in enumerate(all_topics, start=2):
        cleaned_topic_name = clean_topic_title(t.get("topic", ""))
        desc_val = generate_topic_description(
            topic_name=cleaned_topic_name,
            raw_desc=t.get("description", ""),
            chapter_name=t.get("chapter_name", "")
        )
        row_vals = [
            t.get("id", t_idx - 1),
            t.get("chapter_number", ""),
            t.get("chapter_name", ""),
            cleaned_topic_name,
            desc_val,
        ]
        cleaned_t_vals = [
            re.sub(r'[\000-\010]|[\013-\014]|[\016-\037]', '', str(v)) if isinstance(v, str) else v
            for v in row_vals
        ]
        ws_topics.append(cleaned_t_vals)
        for c_idx in range(1, len(topic_headers) + 1):
            c_cell = ws_topics.cell(row=t_idx, column=c_idx)
            c_cell.font = cell_font
            c_cell.border = border_thin
            if c_idx in [1, 2]:
                c_cell.alignment = align_center
            else:
                c_cell.alignment = align_left
        ws_topics.row_dimensions[t_idx].height = 24

    topic_widths = {
        "A": 10,  # id
        "B": 18,  # chapter number
        "C": 28,  # chapter name
        "D": 32,  # topic
        "E": 45,  # description
    }
    for col_letter, width in topic_widths.items():
        ws_topics.column_dimensions[col_letter].width = width

    if as_first_sheet:
        wb.active = 0


def export_single_sheet_excel_bytes(results: List[ExtractionResult], category: str = "questions", marks: Optional[int] = None) -> bytes:
    """Exports a single category of questions to its own dedicated standalone Excel (.xlsx) file containing ONLY 1 sheet."""
    cat_lower = str(category).lower().strip()

    # First pass: ensure any embedded paragraphs in question stems are separated into q.paragraph
    for res in results:
        for q in getattr(res, "questions", []):
            ensure_paragraph_extracted(q)

    std_items: List[Tuple[Any, Any]] = []
    raw_para_items: List[Tuple[Any, Any]] = []
    match_items: List[Tuple[Any, Any]] = []

    for res in results:
        sorted_qs = sort_questions_naturally(res.questions)
        is_adv = is_advance_paper(res)
        for q in sorted_qs:
            if is_paragraph_question(q):
                raw_para_items.append((q, res))
            elif is_adv and is_advance_matching_question(q):
                match_items.append((q, res))
            elif is_matching_question(q):
                match_items.append((q, res))
                if not is_adv:
                    std_items.append((q, res))
            else:
                std_items.append((q, res))

    wb = openpyxl.Workbook()
    ws = wb.active

    if cat_lower in ["paragraph", "passage", "paragraph type", "paragraph_type"]:
        ws.title = "Paragraph Type"
        para_headers = [
            "ID", "Paragraph", "Question", "Type", "Option A", "Option B", "Option C", "Option D",
            "Answer", "Marks", "Difficulty", "Subject", "Paragraph Image", "Question Image", "Answer Image",
            "Option A Image", "Option B Image", "Option C Image", "Option D Image",
            "Solution", "Solution Image"
        ]
        # Group questions belonging to the same paragraph strictly together
        grouped_para: Dict[str, List[Tuple[Any, Any]]] = {}
        for q, res in raw_para_items:
            p_text_raw = str(getattr(q, "paragraph", "") or "").strip()
            p_img_raw = getattr(q, "paragraph_image_url", None)
            norm_key = re.sub(r'\s+', ' ', p_text_raw[:60].lower()) if p_text_raw else None
            p_key = norm_key or p_img_raw or f"para_{id(q)}"
            if p_key not in grouped_para:
                grouped_para[p_key] = []
            grouped_para[p_key].append((q, res))

        para_items: List[Tuple[Any, Any]] = []
        for p_key, q_list in grouped_para.items():
            best_text = ""
            best_img = None
            for q_item, res_item in q_list:
                t = str(getattr(q_item, "paragraph", "") or "").strip()
                if len(t) > len(best_text):
                    best_text = t
                img = getattr(q_item, "paragraph_image_url", None)
                if img and not best_img:
                    best_img = img

            sorted_group = sorted(q_list, key=lambda pair: natural_sort_key_helper(pair[0]))
            for idx, (q_item, res_item) in enumerate(sorted_group):
                q_item.paragraph = best_text
                q_item.paragraph_image_url = best_img
                q_item.is_paragraph_head = (idx == 0)
                para_items.append((q_item, res_item))

        _populate_excel_sheet(ws, para_headers, para_items, sheet_type="paragraph", marks=marks)

    elif cat_lower in ["matching", "match", "match the list", "match the column", "match_the_list"]:
        ws.title = "Match the list"
        match_headers = [
            "ID", "Question", "Column-I", "Column-II", "Type", "Option A", "Option B", "Option C", "Option D",
            "Answer", "Marks", "Difficulty", "Subject", "Question Image", "Answer Image",
            "Column-I A Image", "Column-I B Image", "Column-I C Image", "Column-I D Image",
            "Solution", "Solution Image"
        ]
        _populate_excel_sheet(ws, match_headers, match_items, sheet_type="matching", marks=marks)

    else:  # standard "questions"
        ws.title = "Questions"
        all_topics, seen_topic_keys, has_topics = _extract_topics_and_mapping(results)
        if has_topics:
            headers = [
                "ID", "Question", "Type", "Option A", "Option B", "Option C", "Option D",
                "Answer", "Marks", "Difficulty", "Topic ID", "Question Image", "Answer Image",
                "Option A Image", "Option B Image", "Option C Image", "Option D Image",
                "Solution", "Solution Image"
            ]
            _populate_excel_sheet(ws, headers, std_items, sheet_type="topics", all_topics=all_topics, seen_topic_keys=seen_topic_keys, marks=marks)
            _add_topics_worksheet(wb, all_topics, as_first_sheet=True)
        else:
            std_headers = [
                "ID", "Question", "Type", "Option A", "Option B", "Option C", "Option D",
                "Answer", "Marks", "Difficulty", "Subject", "Question Image", "Answer Image",
                "Option A Image", "Option B Image", "Option C Image", "Option D Image",
                "Solution", "Solution Image"
            ]
            _populate_excel_sheet(ws, std_headers, std_items, sheet_type="standard", marks=marks)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_advance_excel_bundle(results: List[ExtractionResult], base_filename: str = "mcq", marks: Optional[int] = None) -> Dict[str, bytes]:
    """Generates 3 separate Excel files for JEE Advanced papers:
    1. <base>_Questions.xlsx
    2. <base>_Paragraph_Type.xlsx
    3. <base>_Match_the_list.xlsx
    """
    clean_base = Path(base_filename).stem
    clean_base = re.sub(r'_(?:mcqs?|export)$', '', clean_base, flags=re.IGNORECASE)

    return {
        f"{clean_base}_Questions.xlsx": export_single_sheet_excel_bytes(results, category="questions", marks=marks),
        f"{clean_base}_Paragraph_Type.xlsx": export_single_sheet_excel_bytes(results, category="paragraph", marks=marks),
        f"{clean_base}_Match_the_list.xlsx": export_single_sheet_excel_bytes(results, category="matching", marks=marks),
    }


def export_advance_excel_zip(results: List[ExtractionResult], base_filename: str = "mcq", marks: Optional[int] = None) -> bytes:
    """Packages the 3 separate Excel files into a single ZIP archive."""
    import zipfile
    bundle = export_advance_excel_bundle(results, base_filename=base_filename, marks=marks)
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, data in bundle.items():
            zf.writestr(fname, data)
    return zip_buf.getvalue()


def export_to_excel_bytes(results: List[ExtractionResult], category: Optional[str] = None, marks: Optional[int] = None) -> bytes:
    """Exports extraction results to an Excel (.xlsx) file.
    If category is specified ('questions', 'paragraph', 'matching'), outputs that single-sheet Excel workbook.
    If category is 'zip', outputs the 3 separate Excel files in a ZIP archive.
    Otherwise, creates the appropriate Excel workbook with Topics sheet first."""
    if category in ["questions", "standard"]:
        return export_single_sheet_excel_bytes(results, category="questions", marks=marks)
    elif category in ["paragraph", "passage", "paragraph_type"]:
        return export_single_sheet_excel_bytes(results, category="paragraph", marks=marks)
    elif category in ["matching", "match", "match_the_list"]:
        return export_single_sheet_excel_bytes(results, category="matching", marks=marks)
    elif category == "zip":
        return export_advance_excel_zip(results, marks=marks)

    all_topics, seen_topic_keys, has_topics = _extract_topics_and_mapping(results)

    # First pass: ensure any embedded paragraphs in question stems are separated into q.paragraph
    for res in results:
        for q in getattr(res, "questions", []):
            ensure_paragraph_extracted(q)

    wb = openpyxl.Workbook()

    all_items: List[Tuple[Any, Any]] = [
        (q, res)
        for res in results
        for q in sort_questions_naturally(res.questions)
    ]

    ws = wb.active
    ws.title = "Questions"

    if has_topics:
        headers = [
            "ID", "Question", "Type", "Option A", "Option B", "Option C", "Option D",
            "Answer", "Marks", "Difficulty", "Topic ID", "Question Image", "Answer Image",
            "Option A Image", "Option B Image", "Option C Image", "Option D Image",
            "Solution", "Solution Image"
        ]
        _populate_excel_sheet(ws, headers, all_items, sheet_type="topics", all_topics=all_topics, seen_topic_keys=seen_topic_keys, marks=marks)
        _add_topics_worksheet(wb, all_topics, as_first_sheet=True)
        allowed_sheets = {"Topics", "Questions"}
    else:
        headers = [
            "ID", "Question", "Type", "Option A", "Option B", "Option C", "Option D",
            "Answer", "Marks", "Difficulty", "Subject", "Question Image", "Answer Image",
            "Option A Image", "Option B Image", "Option C Image", "Option D Image",
            "Solution", "Solution Image"
        ]
        _populate_excel_sheet(ws, headers, all_items, sheet_type="standard", marks=marks)
        allowed_sheets = {"Questions"}

    # STRICT RULE: Ensure NO "Skipped Questions" or any extra sheet exists in Excel
    for sheet_name in list(wb.sheetnames):
        if sheet_name not in allowed_sheets or "skip" in sheet_name.lower():
            del wb[sheet_name]

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def extract_answer_from_text(text: Optional[str]) -> Optional[str]:
    """Robustly extracts uppercase answer keys (A, B, C, D) from solutions, explanations, answer tables, brackets, and question texts across English, Gujarati, and Hindi."""
    if not text:
        return None

    raw_text = str(text).strip()
    ans_chars = r'[A-Da-d1-4અબકડકખગઘ]|I{1,3}|IV|iv|i{1,3}'

    norm_map = {
        '1': 'A', '2': 'B', '3': 'C', '4': 'D',
        'I': 'A', 'II': 'B', 'III': 'C', 'IV': 'D',
        'અ': 'A', 'બ': 'B', 'ક': 'C', 'ડ': 'D',
        'क': 'A', 'ખ': 'B', 'ग': 'C', 'घ': 'D',
        'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D',
    }

    def _norm(raw):
        if not raw:
            return ''
        s = re.sub(r'[\(\)\[\]\.\:\s]', '', str(raw)).strip()
        return norm_map.get(s, norm_map.get(s.upper(), s.upper()))

    # 1. Trailing answer key at the very end of the text/block
    m_trailing = re.search(
        rf'(?:\[\s*(?:ans(?:wer)?|જવાબ|ઉત્તર|key)?[\s\:\.\=\-]*\s*[\(\[]?\s*({ans_chars})\s*[\)\]]?\s*\]|\(?\s*(?:ans(?:wer)?|જવાબ|ઉત્તર|key)\s*[\s\:\.\=\-]+\s*[\(\[]?\s*({ans_chars})\s*[\)\]]?\s*)\s*$',
        raw_text,
        re.IGNORECASE
    )
    if m_trailing:
        val = _norm(m_trailing.group(1) or m_trailing.group(2))
        if val in ['A', 'B', 'C', 'D']:
            return val

    # 2. Strip any leading answer tag that leaked from the bottom-right of the previous question
    clean_text = re.sub(
        rf'^\s*(?:\[\s*ans[^\n\]]*\]|\(?\s*ans(?:wer)?[\s\:\.\=]*\s*[\(\[]?\s*(?:{ans_chars})\s*[\)\]]?\)?)\s*',
        '',
        raw_text,
        flags=re.IGNORECASE
    ).strip()

    # 3. Standard patterns on clean_text
    pats = [
        rf'(?:ans(?:wer)?|જવાબ|ઉત્તર|key)\s*(?:is|:|:=|-|\.|\/|=)?\s*[\(\[]?\s*({ans_chars})\s*[\)\]]?(?:\s|$|[,\.\)])',
        rf'(?:correct\s*(?:option|choice|answer)?|સાચો\s*(?:વિકલ્પ|જવાબ))\s*(?:is|:|:=|-|\.|\/|=)?\s*[\(\[]?\s*({ans_chars})\s*[\)\]]?',
        rf'(?:option|choice|વિકલ્પ)\s*[\(\[]?\s*({ans_chars})\s*[\)\]]?(?:\s+is\s+correct|\s+સાચો\s+છે)?',
        rf'(?:hence|therefore|thus|આથી)\s*,?\s*(?:option|choice|વિકલ્પ)?\s*[\(\[]?\s*({ans_chars})\s*[\)\]]?\s*(?:is\s+correct|સાચો\s+છે)?',
        rf'\[\s*(?:ans(?:wer)?|જવાબ|ઉત્તર|key)?\s*[\.:=\-]?\s*[\(\[]?\s*({ans_chars})\s*[\)\]]?\s*\]',
        rf'\(\s*(?:ans(?:wer)?|જવાબ|ઉત્તર|key)\s*[\.:=\-]?\s*[\(\[]?\s*({ans_chars})\s*[\)\]]?\s*\)',
        rf'^\s*(?:sol(?:ution)?[\.\:\s]*)?(?:(?:Q|Question|પ્રશ્ન|\b)?\s*\d+[\.\:\-\)\s]+)?[\(\[]\s*({ans_chars})\s*[\)\]][\.\:\-\s]*',
        rf'^\s*(?:Q|Question|પ્રશ્ન|\b)?\s*\d+[\.\:\-\)\s]+[\(\[]\s*({ans_chars})\s*[\)\]](?:\s|$|[,\.\)])',
        rf'^\s*[\(\[]\s*({ans_chars})\s*[\)\]]\s*$',
        rf'(?:=>|\\Rightarrow|→|->)\s*[\(\[]?\s*({ans_chars})\s*[\)\]]?\s*$',
        rf'(?:વિકલ્પ|option)\s*({ans_chars})\s*(?:સાચો|correct)',
    ]
    for p in pats:
        m = re.search(p, clean_text, re.IGNORECASE | re.MULTILINE)
        if m:
            val = _norm(m.group(1))
            if val in ['A', 'B', 'C', 'D']:
                return val
    return None


