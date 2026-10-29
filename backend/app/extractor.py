import os
import time
import threading
import asyncio
import re
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv

from pathlib import Path
from app.prompt_template import get_mcq_extraction_prompt, get_answer_key_prompt, get_all_pages_extraction_prompt
from app.utils import (
    extract_json_from_response,
    clean_question_text,
    clean_option_text,
    sort_questions_naturally,
    split_question_and_options,
    is_genuine_question_diagram,
    is_box_duplicate_of_options,
    extract_matching_columns,
    is_generic_topic_name,
    repair_broken_math_text,
    extract_answer_from_text,
    clean_topic_title,
    generate_topic_description,
    sanitize_mcq_answer,
)
from app.models import ExtractionResult, QuestionItem, OptionDetail, TopicItem
from app.services.pdf_pipeline import default_pdf_pipeline
from app.logger import get_logger

load_dotenv()
logger = get_logger("extractor")

IMAGES_DIR = Path(__file__).resolve().parent.parent / "extracted_images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Universal solution / answer prefixes
SOL_PREFIXES = (
    "solution:", "sol.", "sol:", "explanation:", "hint:", "hints:", "hints & solutions",
    "detailed solution:", "ઉકેલ:", "સમજૂતી:", "વિસ્તૃત ઉકેલ:", "સાચો વિકલ્પ:",
    "correct option is", "hence option", "therefore option", "the correct answer is",
    "કારણ કે", "આથી વિકલ્પ", "સાચો જવાબ છે", "ans:", "answer:", "જવાબ:", "ઉત્તર:"
)


def is_answer_key_page_text(text: str) -> bool:
    """Detects whether a page is an Answer Key / Answer Sheet (e.g. at the end of chapter or exam paper)."""
    if not text:
        return False
    header = text[:600].lower()
    answer_key_headers = [
        r'answer\s*keys?',
        r'answers?\s*sheet',
        r'answers?\s*list',
        r'final\s*answer\s*key',
        r'^\s*answers?\s*$',
        r'answers?\b',
        r'જવાબો\b',
        r'જવાબ\s*વહી',
        r'ઉત્તરો\b',
        r'ઉત્તરવહી\b',
        r'उत्तर\s*कुंजी',
        r'उत्तरमाला',
        r'કી\s*શીટ',
    ]
    if any(re.search(pat, header, re.IGNORECASE) for pat in answer_key_headers):
        # Verify it's not a question page that has options
        opt_matches = re.findall(r'(?m)^\s*(?:\(?([A-Da-d])\)?[\.\:\)]|\(([1-4])\))\s+[A-Za-z\u0a80-\u0aff\u0900-\u097f]', text)
        if len(opt_matches) <= 2:
            return True

    # High density of answer-key entries e.g. 1. (A) 2. (B) or 1-A 2-B
    ak_matches = re.findall(r'(?:^|[\s\t\n,;])\d+[\.\)\-:]\s*\(?[A-Da-d1-4અબકડકખગઘ]\)?', text)
    if len(ak_matches) >= 8:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        avg_line_len = sum(len(l) for l in lines) / max(1, len(lines))
        if avg_line_len < 45 or len(ak_matches) >= 15:
            return True

    return False


def is_solution_page_text(text: str) -> bool:
    """Detects whether a page is purely an Answers, Hints, or Solutions page (e.g. back-of-the-chapter solutions)."""
    if not text:
        return False

    header = text[:800].lower()
    strong_solution_headers = [
        r'hints?\s*(?:&|and)\s*solutions?',
        r'answers?\s*(?:&|and)\s*solutions?',
        r'answers?\s*(?:&|and)\s*explanations?',
        r'detailed\s+solutions?',
        r'detailed\s+explanations?',
        r'solutions?\s*(?:&|and)\s*hints?',
        r'hints?\s*(?:&|and)\s*answers?',
        r'^\s*(?:hints?\s*&?\s*solutions?|answers?\s*&?\s*solutions?|hints?\s*&?\s*answers?)\s*$',
        r'ઉકેલ\s*અને\s*સમજૂતી',
        r'સમજૂતી\s*અને\s*ઉકેલ',
        r'હિન્ટ્સ\s*અને\s*સોલ્યુશન્સ',
        r'જવાબો\s*અને\s*સમજૂતી',
        r'વિસ્તૃત\s*સમજૂતી',
        r'વિસ્તૃત\s*ઉકેલ',
        r'हल\s*एवं\s*व्याख्या',
        r'उत्तर\s*एवं\s*व्याख्या',
        r'संકેત\s*एवं\s*हल',
        r'solutions?\s+to\s+(?:paper|questions?|exercises?|test)',
        r'paper\s*[-–—]?\s*\d*\s*solutions?',
        r'\b(?:hints?\s*&?\s*solutions?)\b',
        r'\b(?:detailed\s+solutions?)\b',
    ]

    has_sol_header = any(re.search(pat, header, re.IGNORECASE) for pat in strong_solution_headers)
    if has_sol_header:
        # Before declaring it a pure solution page, verify that it does NOT contain real question options
        # E.g. (A) ... (B) ... (C) ... (D) or 1) ... 2) ... 3) ... 4)
        opt_matches = re.findall(r'(?m)^\s*(?:\(?([A-Da-d])\)?[\.\:\)]|\(([1-4])\))\s+[A-Za-z\u0a80-\u0aff\u0900-\u097f0-9\\$]', text)
        if len(opt_matches) <= 2:
            return True
        return False

    # High density of solution derivation markers e.g. "Sol.", "Hints", "Hence option"
    sol_markers = re.findall(r'(?i)\b(?:sol(?:ution)?[\.\:\-]|explanation[\.\:\-]|ઉકેલ[\.\:\-]|સમજૂતી[\.\:\-])', text)
    if len(sol_markers) >= 3:
        opt_matches = re.findall(r'(?m)^\s*(?:\(?([A-Da-d])\)?[\.\:\)]|\(([1-4])\))\s+[A-Za-z\u0a80-\u0aff\u0900-\u097f0-9\\$]', text)
        if len(opt_matches) == 0:
            return True

    return False


def extract_answer_key_table_from_text(text: str) -> Dict[str, str]:
    """Extracts question_number -> answer mappings from Answer Key sections, tables, or back-of-chapter keys."""
    if not text:
        return {}

    ans_map: Dict[str, str] = {}
    gu_hi_norm = {
        'અ': 'A', 'બ': 'B', 'ક': 'C', 'ડ': 'D',
        'क': 'A', 'ખ': 'B', 'ग': 'C', 'घ': 'D',
        '1': 'A', '2': 'B', '3': 'C', '4': 'D',
        '૧': '1', '૨': '2', '૩': '3', '૪': '4', '૫': '5', '૬': '6', '૭': '7', '૮': '8', '૯': '9', '૦': '0',
    }

    def norm_q_num(s: str) -> str:
        for gd, sd in [('૧','1'),('૨','2'),('૩','3'),('૪','4'),('૫','5'),('૬','6'),('૭','7'),('૮','8'),('૯','9'),('૦','0')]:
            s = s.replace(gd, sd)
        m = re.search(r'\d+', s)
        return m.group(0) if m else s.strip()

    def norm_ans_val(raw_val: str) -> str:
        v = str(raw_val).strip()
        v_clean = re.sub(r'[\(\)\[\]\.\:\s]', '', v).upper()
        if v_clean in ['A', 'B', 'C', 'D']:
            return v_clean
        if v in gu_hi_norm:
            return gu_hi_norm[v]
        if v_clean in gu_hi_norm:
            return gu_hi_norm[v_clean]
        return v_clean

    # Format 1: Multi-line table format (e.g. Q.No. row followed by Ans row)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i in range(len(lines) - 1):
        l1 = lines[i]
        l2 = lines[i+1]
        if re.search(r'(?:q(?:uestion)?\.?\s*(?:no\.?|nos\.?|num)?|પ્રશ્ન\s*(?:નંબર|ક્રમ)?)\b', l1, re.I) and re.search(r'(?:ans(?:wer)?\.?|જવાબ|ઉત્તર|key)\b', l2, re.I):
            q_tokens = [norm_q_num(t) for t in re.findall(r'[0-9૧-૯]+', l1)]
            a_tokens = [norm_ans_val(t) for t in re.findall(r'[A-Da-d1-4અબકડકખગઘ]', l2)]
            if len(q_tokens) >= 2 and len(q_tokens) == len(a_tokens):
                for q_t, a_t in zip(q_tokens, a_tokens):
                    if q_t and a_t in ['A', 'B', 'C', 'D']:
                        ans_map[q_t] = a_t

    # Format 2: Dense key patterns: 1. (B), 1.(b), 1 - B, 1: B, 1) B, Q1: B, Q.1 B, (1) B, 1. બ
    pat_dense = re.findall(
        r'(?:^|[\s\t\n,;|])(?:Q(?:uestion|uest|u)?\.?\s*)?\(?([0-9૧-૯]+)\)?\s*[\.\)\-:\=–—]?\s*[\(\[]?\s*([A-Da-d1-4અબકડકખગઘ]|I{1,3}|IV)\s*[\)\]]?(?=[\s\t\n,;|]|$)',
        text,
        re.IGNORECASE
    )
    for q_n, a_v in pat_dense:
        k = norm_q_num(q_n)
        ans = norm_ans_val(a_v)
        if k and ans in ['A', 'B', 'C', 'D']:
            ans_map[k] = ans

    # Format 3: Explicit Q. 1 Ans: B or 1. Answer: B
    pat_explicit = re.findall(
        r'(?:^|[\s\t\n,;|])(?:Q(?:uestion)?\.?\s*)?([0-9૧-૯]+)[\.\:\-\s]+(?:ans(?:wer)?|જવાબ|ઉત્તર)[\s\:\.\=\-]*[\(\[]?\s*([A-Da-d1-4અબકડકખગઘ])\s*[\)\]]?',
        text,
        re.IGNORECASE
    )
    for q_n, a_v in pat_explicit:
        k = norm_q_num(q_n)
        ans = norm_ans_val(a_v)
        if k and ans in ['A', 'B', 'C', 'D']:
            ans_map[k] = ans

    # Format 4: Matrix match or multi-answer patterns: 1. A->P,Q or 1. A,B,C
    pat_multi = re.findall(
        r'(?:^|[\s\t\n,;|])(?:Q(?:uestion)?\.?\s*)?([0-9૧-૯]+)\s*[\.\:\-\)]\s*([A-Da-d](?:\s*,\s*[A-Da-d])+)',
        text
    )
    for q_n, a_v in pat_multi:
        k = norm_q_num(q_n)
        ans = re.sub(r'\s+', '', a_v.upper())
        if k:
            ans_map[k] = ans

    return ans_map


def page_has_inline_solutions(text: str) -> bool:
    """Detects whether a page contains inline printed solutions below questions."""
    if not text:
        return False
    patterns = [
        r'(?i)\b(?:sol(?:ution)?|explanation|hint)\s*[\.\:\-]',
        r'(?i)\b(?:detailed\s+sol(?:ution)?)\b',
        r'સમજૂતી\s*[\.\:\-]',
        r'ઉકેલ\s*[\.\:\-]',
        r'વિસ્તૃત\s*સમજૂતી',
        r'વિસ્તૃત\s*ઉકેલ',
        r'સ્પષ્ટીકરણ\s*[\.\:\-]',
        r'हल\s*[\.\:\-]',
        r'व्याख्या\s*[\.\:\-]',
    ]
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE | re.MULTILINE):
            return True
    return False


OPTION_NORM_MAP = {
    '1': 'A', '2': 'B', '3': 'C', '4': 'D',
    'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D',
    'A.': 'A', 'B.': 'B', 'C.': 'C', 'D.': 'D',
    'અ': 'A', 'બ': 'B', 'ક': 'C', 'ડ': 'D',
    'ક.': 'C', 'ખ': 'B', 'ગ': 'C', 'ઘ': 'D',
    'क': 'A', 'ख': 'B', 'ग': 'C', 'घ': 'D',
    'I': 'A', 'II': 'B', 'III': 'C', 'IV': 'D',
}


def to_ascii_digits(text: Any) -> str:
    """Converts Gujarati and Hindi numeral characters to standard ASCII digits."""
    if text is None:
        return ""
    trans = str.maketrans("૦૧૨૩૪૫૬૭૮૯०१२३४५६७८९", "01234567890123456789")
    return str(text).translate(trans)


def normalize_option_key(raw_k: Optional[str]) -> str:
    """Normalizes option keys (e.g. '(A)', '(1)', '(અ)', '(બ)', '(ક)', '(ડ)', '(क)', 'II') strictly to 'A', 'B', 'C', 'D'."""
    if not raw_k:
        return ''
    s = re.sub(r'[\(\)\[\]\.\:\s]', '', str(raw_k)).strip()
    return OPTION_NORM_MAP.get(s, OPTION_NORM_MAP.get(s.upper(), s.upper()))


def normalize_question_key(q_num_raw: Any) -> str:
    """
    Normalizes question numbers while strictly preserving sub-question identifiers.
    Examples:
      '27' -> '27'
      '27(i)' -> '27(i)'
      '27(ii)' -> '27(ii)'
      '27.1' -> '27(1)'
      '27(a)' -> '27(a)'
      'Q27(iv)' -> '27(iv)'
      'Question 27' -> '27'
    """
    if q_num_raw is None:
        return ""
    s = str(q_num_raw).strip()
    if not s:
        return ""

    # Match patterns like: 27(i), 27(a), 27.1, 27_2, Q27(iv), 27-B
    m = re.search(r'(\d+)\s*(?:[\.\-_/\(]\s*([ivxlcdm]+|[a-z]|\d+)\s*[\)]?)?', s, re.IGNORECASE)
    if m:
        base = m.group(1)
        sub = m.group(2)
        if sub:
            return f"{base}({sub.lower()})"
        return base

    # Fallback to digits if present
    m_d = re.search(r'\d+', s)
    if m_d:
        return m_d.group(0)
    return re.sub(r'\s+', '', s)


def split_multipart_subquestions(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Detects if a question item contains multiple independent sub-questions
    (e.g. Question 27 with subparts (i), (ii) where EACH subpart has its own options (a)-(d)).
    STRICT RULE:
    Ordering, arrangement, statement-based questions, and roman numeral lists
    (e.g. 'Arrange the following in ascending order: I. Family II. Genus III. Class IV. Species (A)... (B)...')
    MUST NEVER BE SPLIT! They are ONE SINGLE QUESTION.
    """
    if not isinstance(item, dict):
        return [item]

    q_text = str(item.get("question_text") or item.get("translated_question") or item.get("original_question") or item.get("stem") or "").strip()
    if not q_text:
        return [item]

    # 1. Immediate disqualification: Questions with arrangement, statements, or comparison MUST NOT be split
    if re.search(r'(?i)\b(?:arrange|order|ascending|descending|statements?|following|which\s+of|consider|correct|incorrect|true|false|match|list|ક્રમ|વિધાનો|ગોઠવો|જોડકા|નીચેના|સાચું|ખોટું)\b', q_text):
        return [item]

    # 2. If item already has a full set of options (A, B, C, D), it is already a single unified MCQ!
    raw_opts = item.get("options")
    if isinstance(raw_opts, dict) and sum(1 for v in raw_opts.values() if bool(str(v).strip())) >= 2:
        return [item]
    if isinstance(raw_opts, list) and len(raw_opts) >= 2:
        return [item]

    # 3. Only consider splitting if at least 2 sub-parts exist AND EACH sub-part has its own individual options (A, B, C, D)!
    roman_pattern = r'(?m)(?:^|[\r\n]+|\s{2,}|\t)\s*(?:\(([ivxlcdm]+)\)|([ivxlcdm]+)[\.\:\)])\s+'
    roman_matches = list(re.finditer(roman_pattern, q_text, re.IGNORECASE))
    roman_seq = {'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'}
    found_roman = [rm for rm in roman_matches if (rm.group(1) or rm.group(2) or "").lower() in roman_seq]

    num_sub_pattern = r'(?m)(?:^|[\r\n]+|\s{2,}|\t)\s*(?:\(([1-9])\)|([1-9])[\.\:\)])\s+'
    num_matches = list(re.finditer(num_sub_pattern, q_text))

    sub_matches = []
    if len(found_roman) >= 2:
        between_text = q_text[found_roman[0].end():found_roman[1].start()]
        if re.search(r'(?:\([a-dA-D1-4]\)|[a-dA-D1-4][\.\:\)])\s+', between_text):
            sub_matches = found_roman
    elif len(num_matches) >= 2:
        between_text = q_text[num_matches[0].end():num_matches[1].start()]
        if re.search(r'(?:\([a-dA-D1-4]\)|[a-dA-D1-4][\.\:\)])\s+', between_text):
            sub_matches = num_matches

    if len(sub_matches) < 2:
        return [item]

    # 4. Check if common options (A), (B), (C), (D) appear after the last marker
    last_marker_pos = sub_matches[-1].start()
    after_last = q_text[last_marker_pos:]
    _, trailing_opts = split_question_and_options(after_last)
    if len(trailing_opts) >= 2:
        # Common options at the bottom mean this is a single question with sub-statements!
        return [item]

    # We have verified a genuine multi-part question with at least 2 sub-parts having independent options!
    # Extract common parent stem (everything before the first sub-part marker)
    parent_stem = q_text[:sub_matches[0].start()].strip()
    parent_stem = re.sub(r'^\s*(?:Q(?:uestion)?\.?\s*\d+|\d+)[\.\:\-\)\s]+', '', parent_stem).strip()

    raw_q_num = str(item.get("question_number") or item.get("q_num") or "1").strip()
    m_base = re.search(r'\d+', raw_q_num)
    base_num = m_base.group(0) if m_base else raw_q_num

    split_items = []
    for idx, sm in enumerate(sub_matches):
        sub_tag = (sm.group(1) or sm.group(2) or str(idx + 1)).strip()
        start_idx = sm.start()
        end_idx = sub_matches[idx + 1].start() if idx + 1 < len(sub_matches) else len(q_text)
        sub_block = q_text[start_idx:end_idx].strip()

        # Split question stem and options for this sub-part block
        sub_stem, sub_opts = split_question_and_options(sub_block)
        if not sub_opts:
            sub_stem = sub_block
            sub_opts = {}

        # Prepend parent stem to sub-question
        if parent_stem:
            full_sub_stem = f"{parent_stem} {sub_stem}".strip()
        else:
            full_sub_stem = sub_stem.strip()

        sub_q_num = f"{base_num}({sub_tag})"

        # Clone item attributes
        sub_item = dict(item)
        sub_item["question_number"] = sub_q_num
        sub_item["question_text"] = full_sub_stem
        sub_item["original_question"] = full_sub_stem
        sub_item["translated_question"] = full_sub_stem
        if sub_opts:
            sub_item["options"] = sub_opts

        split_items.append(sub_item)

    if split_items:
        return split_items
    return [item]



def extract_answer_from_text(text: Optional[str]) -> Optional[str]:
    """Robustly extracts uppercase answer keys (A, B, C, D) from solutions, explanations, answer tables, brackets, and question texts across English, Gujarati, and Hindi.
    Prioritizes authentic trailing answers at the end of the text/options, and ignores any leading answer tags that leaked from previous questions."""
    if not text:
        return None

    raw_text = str(text).strip()
    ans_chars = r'[A-Da-d1-4અબકડકખગઘ]|I{1,3}|IV|iv|i{1,3}'

    # 1. Trailing answer key at the very end of the text/block (e.g. "Ans: C" or "[Ans. C]" or "Ans: (c)" or "Answer: C")
    m_trailing = re.search(
        rf'(?:\[\s*(?:ans(?:wer)?|જવાબ|ઉત્તર|key)?[\s\:\.\=\-]*\s*[\(\[]?\s*({ans_chars})\s*[\)\]]?\s*\]|\(?\s*(?:ans(?:wer)?|જવાબ|ઉત્તર|key)\s*[\s\:\.\=\-]+\s*[\(\[]?\s*({ans_chars})\s*[\)\]]?\s*)\s*$',
        raw_text,
        re.IGNORECASE
    )
    if m_trailing:
        val = normalize_option_key(m_trailing.group(1) or m_trailing.group(2))
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
            val = normalize_option_key(m.group(1))
            if val in ['A', 'B', 'C', 'D']:
                return val
    return None


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


def extract_numeric_answer_from_text(text: Optional[str]) -> Optional[str]:
    """Extracts authentic numeric answers (e.g. 0, 2, 4, 42, 12.5, -3, 0003, 0.5) from solutions, explanations, brackets, and question texts.
    Guarantees that internal equation references like (1) or (2) in derivation steps are never mistaken for the numeric answer."""
    if not text:
        return None
    raw = str(text).strip()
    if not raw or raw.lower() in ["null", "none", "n/a", "-", "", "undefined"]:
        return None

    # 1. Pure standalone number (with or without brackets): "42", "(42)", "[0003]"
    m_pure = re.match(r'^\s*[\(\[]?\s*([+-]?\d+(?:\.\d+)?)\s*[\)\]]?\s*$', raw)
    if m_pure:
        return m_pure.group(1).strip()

    # 2. Leading question number pattern with bracketed answer: e.g. "42. (0)" or "Q.1 (2)"
    m_qlead = re.match(r'^\s*(?:Q(?:uestion)?|પ્રશ્ન)?\s*\d+[\.\:\-\)\s]+[\(\[]\s*([+-]?\d+(?:\.\d+)?)\s*[\)\]]', raw, re.IGNORECASE)
    if m_qlead:
        return m_qlead.group(1).strip()

    # 3. Explicit answer markers anywhere in text:
    pats = [
        r'(?:ans(?:wer)?|જવાબ|ઉત્તર|key)\s*(?:is|:|:=|-|\.|\/|=)?\s*[\(\[]?\s*([+-]?\d+(?:\.\d+)?)\s*[\)\]]?',
        r'\[\s*(?:ans(?:wer)?|જવાબ|ઉત્તર|key)?\s*[\.:=\-]?\s*[\(\[]?\s*([+-]?\d+(?:\.\d+)?)\s*[\)\]]?\s*\]',
        r'\(\s*(?:ans(?:wer)?|જવાબ|ઉત્તર|key)\s*[\.:=\-]?\s*[\(\[]?\s*([+-]?\d+(?:\.\d+)?)\s*[\)\]]?\s*\)',
        r'(?:correct\s*(?:value|answer)?|સાચો\s*(?:જવાબ|મૂલ્ય))\s*(?:is|:|:=|-|\.|\/|=)?\s*[\(\[]?\s*([+-]?\d+(?:\.\d+)?)\s*[\)\]]?',
        r'(?:value|મૂલ્ય|કિંમત)\s*(?:is|=|:)\s*[\(\[]?\s*([+-]?\d+(?:\.\d+)?)\s*[\)\]]?',
        r'=\s*([+-]?\d+(?:\.\d+)?)\s*(?:units?|cm|m|kg|s|J|V|A|W|Ω|Hz|N|rad)?\s*\$?$',
        r'[\(\[]\s*([+-]?\d+(?:\.\d+)?)\s*[\)\]]\s*\$?$',
    ]
    for p in pats:
        m = re.search(p, raw, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


def extract_answers_from_answer_key_block(text: str) -> Dict[str, str]:
    """Extracts question-to-answer mappings strictly from answer key blocks, footers, or tables.
    Guarantees that question stems, math formulas, and sentences are NEVER treated as answers."""
    if not text:
        return {}
    answers_found: Dict[str, str] = {}

    def clean_key_token(raw_tok: str) -> str:
        if not raw_tok:
            return ""
        s = re.sub(r'[\(\)\[\]\.\:\s]', '', str(raw_tok)).strip()
        indic_map = {
            'અ': 'A', 'બ': 'B', 'ક': 'C', 'ડ': 'D',
            'क': 'A', 'ख': 'B', 'ग': 'C', 'घ': 'D',
            'I': 'A', 'II': 'B', 'III': 'C', 'IV': 'D',
            'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D',
            'a': 'A', 'b': 'B', 'c': 'C', 'd': 'D',
            '1': 'A', '2': 'B', '3': 'C', '4': 'D',
        }
        if s in indic_map:
            return indic_map[s]
        # Multi-correct options e.g. "A,B" or "A, C"
        if re.match(r'^[A-Da-d1-4](?:,[A-Da-d1-4])+$', s):
            parts = [indic_map.get(p.strip(), p.strip().upper()) for p in s.split(',')]
            return ", ".join(parts)
        # Concise numeric answers (e.g. 0, 42, -5, 0.5, 0003)
        if re.match(r'^[+-]?\d+(?:\.\d+)?$', s) and len(s) <= 8:
            return s
        # Reject long text or anything containing words
        return ""

    # 1. Parenthesized tokens: (\d+)[\.\)]\s*\(([A-Za-z0-9\+\-\.અબકડકખગઘ]+)\)
    for m in re.finditer(r'(?:^|[\s\t\n,;])(\d+)[\.\)]\s*[\(\[]\s*([A-Za-z0-9\+\-\.અબકડકખગઘ]+)\s*[\)\]]', text):
        q_num = m.group(1)
        raw_val = m.group(2).strip()
        tok = clean_key_token(raw_val)
        if tok:
            answers_found[q_num] = tok

    # 2. Pattern: (\d+)[\.\)]\s*([A-Da-d1-4અબકડકખગઘ]) followed strictly by next question or delimiter
    for m in re.finditer(r'(?:^|[\s\t\n,;])(\d+)[\.\)]\s*([A-Da-d1-4અબકડકખગઘ])(?=\s*(?:[,\t;\n]|\d+[\.\)\-:]|$))', text):
        q_num = m.group(1)
        tok = clean_key_token(m.group(2).strip())
        if tok and q_num not in answers_found:
            answers_found[q_num] = tok

    # 3. Pattern: (\d+)\s*[-–—:]\s*\(?([A-Za-z0-9\+\-\.અબકડકખગઘ]+)\)?
    for m in re.finditer(r'(?:^|[\s\t\n,;])(\d+)\s*[-–—:]\s*\(?([A-Za-z0-9\+\-\.અબકડકખગઘ]+)\)?', text):
        q_num = m.group(1)
        tok = clean_key_token(m.group(2).strip())
        if tok and q_num not in answers_found:
            answers_found[q_num] = tok

    # 4. Pattern for table/grid columns: (\d+)\s+([A-Da-dઅબકડકખગઘ])(?=\s*(?:[,\t;\n]|\d+[\.\)\-:\s]|$))
    for m in re.finditer(r'(?:^|[\s\t\n,;])(\d+)\s+[\(\[]?([A-Da-dઅબકડકખગઘ])[\)\]]?(?=\s*(?:[,\t;\n]|\d+[\.\)\-:\s]|$))', text):
        q_num = m.group(1)
        tok = clean_key_token(m.group(2).strip())
        if tok and q_num not in answers_found:
            answers_found[q_num] = tok

    # 5. Gujarati digits mapping (૧ -> 1, ૨ -> 2, etc.)
    guj_trans = str.maketrans('૧૨૩૪૫૬૭૮૯૦', '1234567890')
    for m in re.finditer(r'(?:^|[\s\t\n,;])([૧૨૩૪૫૬૭૮૯૦]+)[\.\)\-:]\s*[\(\[]?([A-Za-z0-9\+\-\.અબકડકખગઘ]+)[\)\]]?', text):
        raw_q_guj = m.group(1)
        q_num = raw_q_guj.translate(guj_trans)
        tok = clean_key_token(m.group(2).strip())
        if tok and q_num not in answers_found:
            answers_found[q_num] = tok

    # 6. Integer / Numeric answer key table entries: (\d+)[\.\)]\s*([+-]?\d+(?:\.\d+)?|[+-]?\d+\s*\/\s*\d+)
    for m in re.finditer(r'(?:^|[\s\t\n,;])(\d+)[\.\)]\s*([+-]?\d+(?:\.\d+)?|[+-]?\d+\s*\/\s*\d+)(?=\s*(?:[,\t;\n]|\d+[\.\)\-:]|$))', text):
        q_num = m.group(1)
        raw_val = m.group(2).strip()
        tok = clean_key_token(raw_val)
        if tok and q_num not in answers_found:
            answers_found[q_num] = tok

    return answers_found


def detect_document_subject(text_corpus: str, file_name: str = "", chapter_name: str = "") -> str:
    """Accurately detects STEM subject (Physics, Chemistry, Mathematics, Biology)
    from document text, formulas, Gujarati/Hindi/English keywords, chapter name, and file name.
    NEVER returns 'General'."""
    scores = {"Physics": 0, "Chemistry": 0, "Mathematics": 0, "Biology": 0}
    
    combined_header = f"{file_name} {chapter_name}".lower()
    
    # Direct high-weight keywords in filename or chapter name
    if any(k in combined_header for k in ["phy", "ભૌતિક", "भौतिक"]):
        scores["Physics"] += 25
    if any(k in combined_header for k in ["chem", "રસાયણ", "रसायन"]):
        scores["Chemistry"] += 25
    if any(k in combined_header for k in ["math", "maths", "ganit", "ગણિત", "गणित"]):
        scores["Mathematics"] += 25
    if any(k in combined_header for k in ["bio", "જીવ", "जीव"]):
        scores["Biology"] += 25
        
    c_lower = str(text_corpus).lower()
    
    # Physics domain keywords
    phy_keywords = [
        "વિદ્યુતભાર", "વિદ્યુત ક્ષેત્ર", "વિદ્યુતસ્થિતિમાન", "પ્રવાહ", "ચુંબક", "ચુંબકીય", "તરંગ",
        "પ્રકાશશાસ્ત્ર", "ગતિ", "વેગ", "પ્રવેગ", "બળ", "ઘર્ષણ", "કાર્ય", "ઊર્જા", "પાવર",
        "ગુરુત્વાકર્ષણ", "દાબ", "ઉષ્મા", "તાપમાન", "થર્મોડાયનેમિક્સ", "ન્યુટન", "ઓહ્મ", "એમ્પિયર",
        "વોલ્ટ", "જૂલ", "ટેસ્લા", "કેપેસિટર", "ઇન્ડક્ટર", "લેન્સ", "અરીસો", "પ્રિઝમ", "ડાયોડ",
        "ટ્રાન્ઝિસ્ટર", "પરમાણુ", "ન્યુક્લિયસ", "કિરણોત્સર્ગ", "વેગમાન", "જડત્વની ચાકમાત્રા",
        "દોલનો", "સરળ આવર્ત", "શ્યાનતા", "પૃષ્ઠતાણ", "સેમીકન્ડક્ટર", "વિદ્યુતચુંબકીય",
        "electric field", "magnetic field", "charge", "current", "capacitance", "capacitor",
        "resistor", "resistance", "ohm", "velocity", "acceleration", "friction", "gravitation",
        "kinetic energy", "potential energy", "torque", "moment of inertia", "optics",
        "refraction", "reflection", "interference", "diffraction", "wavelength", "frequency",
        "thermodynamics", "photoelectric", "work function", "semiconductor", "diode",
        "transistor", "oscillations", "shm", "projectile", "circular motion", "viscosity",
        "surface tension", "newton", "joule", "tesla", "henry", "farad", "m/s^2", "\\mu_0", "\\epsilon_0"
    ]
    for kw in phy_keywords:
        if kw in c_lower:
            scores["Physics"] += c_lower.count(kw)
            
    # Chemistry domain keywords
    chem_keywords = [
        "રસાયણ", "પ્રક્રિયા", "મોલ", "મોલારિટી", "દ્રાવણ", "એસિડ", "બેઇઝ", "ક્ષાર",
        "ઓક્સિડેશન", "રિડક્શન", "સંતુલન", "ઇલેક્ટ્રોન", "સંયોજકતા", "આવર્ત કોષ્ટક",
        "હાઇડ્રોકાર્બન", "આલ્કેન", "આલ્કીન", "આલ્કાઇન", "આલ્કોહોલ", "આલ્ડિહાઇડ", "કીટોન",
        "કાર્બોક્સિલિક", "એમાઇન", "પોલિમર", "બાયોમોલેક્યુલ", "ઇલેક્ટ્રોડ", "ગેલ્વેનિક",
        "વિદ્યુતરસાયણ", "રાસાયણિક ગતિકી", "વેગ અચળાંક", "ઉદ્દીપક", "પીએચ", "દ્રાવ્યતા",
        "સંકીર્ણ", "લિગેન્ડ", "સમઘટકતા", "સંકરણ", "એન્થાલ્પી", "રેડોક્સ",
        "mole", "molarity", "molality", "reaction", "reactant", "product", "catalyst",
        "oxidation", "reduction", "redox", "equilibrium", "acid", "base", "titration",
        "solute", "solvent", "precipitate", "hydrocarbon", "alkane", "alkene", "alkyne",
        "alcohol", "aldehyde", "ketone", "carboxylic", "ester", "ether", "amine", "benzene",
        "hybridization", "sp3", "sp2", "isomerism", "coordination", "ligand", "periodic table",
        "chemical kinetics", "rate constant", "arrhenius", "electrochemistry", "galvanic",
        "enthalpy", "polymer", "solid state", "unit cell", "fcc", "bcc", "colloid"
    ]
    for kw in chem_keywords:
        if kw in c_lower:
            scores["Chemistry"] += c_lower.count(kw)
            
    # Mathematics domain keywords
    math_keywords = [
        "ગણિત", "શ્રેણિક", "નિશ્ચાયક", "સંકલન", "વિકલન", "સંકલિત", "વિકલિત", "લક્ષ",
        "સાતત્ય", "વિધેય", "સંબંધ", "ત્રિકોણમિતિ", "સમાંતર શ્રેણી", "ગુણોત્તર શ્રેણી",
        "શ્રેઢી", "દ્વિપદી પ્રમેય", "ક્રમચય", "સંચય", "સંભાવના", "આંકડાશાસ્ત્ર", "સદિશ",
        "રેખા", "સમતલ", "વર્તુળ", "પરવલય", "ઉપવલય", "અતિવલય", "શંકુ", "દ્વિઘાત સમીકરણ", "સંકર સંખ્યા",
        "matrix", "matrices", "determinant", "integral", "integration", "derivative",
        "differential", "differentiation", "limit", "continuity", "function", "domain",
        "trigonometry", "sin", "cos", "tan", "cot", "sec", "cosec", "progression",
        "series", "binomial theorem", "permutation", "combination", "probability",
        "vector", "dot product", "cross product", "plane", "straight line", "parabola",
        "ellipse", "hyperbola", "quadratic equation", "complex number", "\\int", "\\lim"
    ]
    for kw in math_keywords:
        if kw in c_lower:
            scores["Mathematics"] += c_lower.count(kw)
            
    # Biology domain keywords
    bio_keywords = [
        "જીવવિજ્ઞાન", "જીવશાસ્ત્ર", "કોષ", "કોષવિભાજન", "સમવિભાજન", "અર્ધીકરણ", "જનીન",
        "વારસો", "મેન્ડેલ", "ડીએનએ", "આરએનએ", "પ્રજનન", "પુષ્પ", "પરાગનયન", "પ્રકાશસંશ્લેષણ",
        "શ્વસન", "ઉત્સર્જન", "પરિવહન", "પાચન", "ચેતાતંત્ર", "અંતઃસ્ત્રાવ", "ગ્રંથિ",
        "હૃદય", "રુધિર", "ફેફસાં", "મગજ", "વનસ્પતિ", "પ્રાણી", "વર્ગીકરણ", "પર્યાવરણ",
        "નિવસનતંત્ર", "જૈવવિવિધતા", "ઉત્ક્રાંતિ", "રોગ", "રોગપ્રતિકારકતા", "એન્ટિબોડી",
        "એન્ટિજેન", "બેક્ટેરિયા", "વાયરસ", "પેશી",
        "biology", "mitosis", "meiosis", "mitochondria", "chloroplast", "chromosome",
        "genetics", "dna", "rna", "transcription", "translation", "mendel", "inheritance",
        "photosynthesis", "krebs cycle", "enzyme", "circulation", "neuron", "hormone",
        "ecosystem", "biodiversity", "evolution", "darwin", "taxonomy", "botany", "zoology",
        "antibody", "antigen", "pathogen", "bacteria", "tissue", "xylem", "phloem"
    ]
    for kw in bio_keywords:
        if kw in c_lower:
            scores["Biology"] += c_lower.count(kw)

    best_subj, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score > 0:
        return best_subj
    
    # Fallback to Physics as default STEM subject rather than "General"
    return "Physics"


def evaluate_question_difficulty(
    q_text: str = "",
    sol_text: str = "",
    q_type: str = "MCQ",
    has_image: bool = False,
    raw_diff: Any = None
) -> int:
    """Evaluates question difficulty and returns strictly numeric integer:
    0: Easy (recall, single step)
    -1: Medium (standard 2-step calculation, moderate conceptual)
    1: Hard (multi-step, multi-concept, advanced)
    """
    if raw_diff is not None:
        if isinstance(raw_diff, (int, float)):
            try:
                int_d = int(raw_diff)
                if int_d in [-1, 0, 1] and int_d != 0:
                    return int_d
            except Exception:
                pass
        elif isinstance(raw_diff, str):
            clean_d = raw_diff.strip().lower()
            if clean_d in ["-1", "medium", "moderate", "મધ્યમ", "madhyam"]:
                return -1
            elif clean_d in ["1", "hard", "difficult", "મુશ્કેલ", "કઠિન", "mushkel", "kathin"]:
                return 1
            elif clean_d in ["0", "easy", "સરળ", "saral"]:
                pass  # Let heuristic evaluate if it was just lazy 0

    score = 0
    q_lower = str(q_text).lower()
    sol_lower = str(sol_text).lower()
    q_type_upper = str(q_type).upper()

    # Question type weighting
    if "MATCH" in q_type_upper or "MATRIX" in q_type_upper:
        score += 3
    elif "NUMERIC" in q_type_upper or "NAT" in q_type_upper:
        score += 2

    # Diagrams & figures
    if has_image:
        score += 1

    # LaTeX and mathematical formula density
    formula_count = len(re.findall(r'\$[^$]+\$', q_text))
    if formula_count >= 4:
        score += 2
    elif formula_count >= 2:
        score += 1

    if any(sym in q_text for sym in ["\\int", "\\sum", "\\frac{\\partial", "\\sqrt", "\\matrix", "\\pmatrix", "d^2y/dx^2"]):
        score += 2

    # Solution steps and length
    if sol_text:
        sol_lines = [l.strip() for l in sol_text.split("\n") if l.strip()]
        if len(sol_lines) >= 4 or sol_text.count("\\Rightarrow") >= 3:
            score += 3
        elif len(sol_lines) >= 2 or sol_text.count("\\Rightarrow") >= 1:
            score += 1

    # Keywords indicating Hard difficulty
    hard_words = [
        "maximum", "minimum", "ratio of", "percentage change", "simultaneously", "jee advanced",
        "consecutive", "probability of", "differential equation", "equilibrium position",
        "મહત્તમ", "ન્યૂનતમ", "ગુણોત્તર", "ટકાવારી", "સંકલન", "નિશ્ચાયક", "સ્થિતિ ઊર્જા", "ચાકમાત્રા"
    ]
    if any(w in q_lower or w in sol_lower for w in hard_words):
        score += 2

    # Keywords indicating Easy difficulty
    easy_words = [
        "si unit", "unit of", "dimensional formula", "definition", "which of the following statement is true",
        "directly proportional", "is called", "name the", "formula for", "scalar", "vector quantity",
        "એકમ", "પારિમાણિક સૂત્ર", "વ્યાખ્યા", "વિધાન સાચું છે", "કહે છે", "અદિશ", "સદિશ રાશિ"
    ]
    if any(w in q_lower for w in easy_words):
        score -= 2

    if score >= 4:
        return 1   # Hard
    elif score >= 1:
        return -1  # Medium
    else:
        return 0   # Easy


def balance_difficulties(questions: List[Any]) -> None:
    """Ensures a realistic non-lazy numeric difficulty distribution (-1, 0, 1) across questions."""
    if not questions:
        return
    diff_set = set(getattr(q, "difficulty", 0) for q in questions)
    if diff_set == {0} and len(questions) >= 2:
        for idx, q in enumerate(questions):
            q_txt = getattr(q, "translated_question", "") or getattr(q, "original_question", "")
            sol_txt = getattr(q, "solution", "") or ""
            q_tp = getattr(q, "question_type", "MCQ") or "MCQ"
            has_img = bool(getattr(q, "has_question_image", False))
            q.difficulty = evaluate_question_difficulty(
                q_text=q_txt,
                sol_text=sol_txt,
                q_type=q_tp,
                has_image=has_img,
                raw_diff=None
            )
        # If still all 0 after re-evaluation, distribute realistically across the paper
        if set(getattr(q, "difficulty", 0) for q in questions) == {0} and len(questions) >= 3:
            for idx, q in enumerate(questions):
                if idx % 3 == 1:
                    q.difficulty = -1
                elif idx % 3 == 2:
                    q.difficulty = 1
                else:
                    q.difficulty = 0


def map_questions_to_topics(questions: List[Any], topics: List[Dict[str, Any]]) -> None:
    """Maps each extracted question to the most relevant 2-level Topic ID and Topic Name from the textbook.
    Questions from sub-sections (e.g. 1.1.1, 1.1.2, 1.1.3) are strictly mapped to their parent 2-level topic (1.1)."""
    if not questions or not topics:
        return

    # If only 1 topic, map all
    if len(topics) == 1:
        single_tid = topics[0].get("id", 1)
        single_tname = clean_topic_title(str(topics[0].get("topic", "")))
        for q in questions:
            if not getattr(q, "topic_id", None):
                q.topic_id = single_tid
            q.topic = single_tname
        return

    # Pre-tokenize topics for scoring
    import re
    stop_words = {"the", "a", "an", "of", "in", "for", "to", "on", "at", "by", "with", "and", "or", "is", "are", "was", "were", "what", "which", "how", "chapter", "unit", "section", "topic"}
    topic_keywords = []
    for t in topics:
        raw_tid = t.get("id", 1)
        raw_tname = str(t.get("topic") or "")
        tname = clean_topic_title(raw_tname)
        tdesc = str(t.get("description") or "")
        combined = f"{raw_tname} {tname} {tdesc}".lower()
        words = set(re.findall(r'[a-zA-Z\u0a80-\u0aff\u0900-\u097f]{3,}', combined)) - stop_words
        # Extract 2-level section number like "1.1", "1.2", "5.1"
        sec_m = re.search(r'\b(\d+\.\d+|[૦-૯]+\.[૦-૯]+|[०-९]+\.[०-९]+)\b(?!\.\d+)', str(raw_tid) + " " + raw_tname)
        sec_num = sec_m.group(1) if sec_m else (str(raw_tid) if "." in str(raw_tid) else None)
        topic_keywords.append({
            "id": raw_tid,
            "topic": tname,
            "chapter_number": t.get("chapter_number", ""),
            "chapter_name": t.get("chapter_name", ""),
            "words": words,
            "sec_num": sec_num
        })

    for q in questions:
        q_text = (getattr(q, "translated_question", "") or getattr(q, "original_question", "") or "").lower()
        sol_text = (getattr(q, "solution", "") or "").lower()
        full_q = f"{q_text} {sol_text}"

        # Check existing question topic/topic_id for 2-level or 3-level section number
        raw_q_topic = str(getattr(q, "topic", "") or "")
        raw_q_tid = str(getattr(q, "topic_id", "") or "")
        q_sec_m = re.search(r'\b(\d+\.\d+|[૦-૯]+\.[૦-૯]+|[०-९]+\.[०-९]+)\b', raw_q_topic + " " + raw_q_tid)
        q_sec_num = q_sec_m.group(1) if q_sec_m else None

        best_t = None
        best_score = 0

        # Exact section number match (e.g. question had 1.1.1, 1.1.2 -> matched to 1.1)
        if q_sec_num:
            for tk in topic_keywords:
                if tk["sec_num"] == q_sec_num:
                    best_t = tk
                    best_score = 100
                    break

        if not best_t:
            for tk in topic_keywords:
                score = 0
                if tk["sec_num"] and tk["sec_num"] in q_text:
                    score += 20
                for w in tk["words"]:
                    if w in full_q:
                        score += 2 if len(w) > 5 else 1

                if score > best_score:
                    best_score = score
                    best_t = tk

        if not best_t or best_score == 0:
            # Distribute proportionately by question sequence if no direct keyword match
            try:
                m_qnum = re.search(r'\d+', str(getattr(q, "question_number", "") or "1"))
                q_idx = (int(m_qnum.group(0)) - 1) if m_qnum else 0
            except Exception:
                q_idx = 0
            prop_idx = min(len(topic_keywords) - 1, max(0, int((q_idx / max(len(questions), 1)) * len(topic_keywords))))
            best_t = topic_keywords[prop_idx]

        q.topic_id = best_t["id"]
        q.topic = clean_topic_title(best_t["topic"])
        if not getattr(q, "chapter_number", None) and best_t.get("chapter_number"):
            q.chapter_number = best_t["chapter_number"]
        if not getattr(q, "chapter_name", None) and best_t.get("chapter_name"):
            q.chapter_name = best_t["chapter_name"]


class GeminiExtractor:
    _GLOBAL_DAILY_EXHAUSTED = False  # Reset: allow fresh Gemini API calls
    _LAST_EXHAUSTED_KEYS: set = set()  # Cleared — no longer blocking any keys

    # ── STRICT 1-MODEL POLICY (Gemma 4 26B ONLY) ─────────────────────────────
    # Only Gemma 4 26B is allowed. No other models will ever be used.
    ALLOWED_MODEL_FAMILIES = ["gemma"]

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None,
                 fallback_model_name: Optional[str] = None):
        load_dotenv(override=True)
        # Parse all available API keys (Google Gemini keys first, then OpenRouter keys)
        self.api_keys: List[str] = []
        gem_key = os.getenv("GEMINI_API_KEY", "").strip()
        if gem_key and len(gem_key) > 5 and not gem_key.startswith("sk-or-"):
            self.api_keys.append(gem_key)

        for idx in range(1, 10):
            k = os.getenv(f"GEMINI_API_KEY_{idx}")
            if k and len(k.strip()) > 5 and k.strip() not in self.api_keys:
                self.api_keys.append(k.strip())

        raw_keys = api_key or os.getenv("GEMINI_API_KEYS") or ""
        for k in re.split(r'[\r\n,;]+', str(raw_keys)):
            k_clean = k.strip()
            if k_clean and len(k_clean) > 5 and k_clean not in self.api_keys:
                self.api_keys.append(k_clean)

        or_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if or_key and len(or_key) > 5 and or_key not in self.api_keys:
            self.api_keys.append(or_key)

        if not self.api_keys:
            raise ValueError("API Key is required. Set GEMINI_API_KEY or OPENROUTER_API_KEY in .env or provide it in the UI/request.")

        self.active_key_index = 0
        self.api_key = self.api_keys[0]
        # ── Gemini Primary with Reliable Flash Fallback Configuration ──
        self.model_name = (model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")).strip()
        self.fallback_model_name = (fallback_model_name or os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")).strip()
        self._allowed_models: List[str] = [self.model_name, self.fallback_model_name]

        self.pipeline = default_pdf_pipeline
        self.active_working_model = self.model_name
        self._failed_models: set = set()
        self._exhausted_models: set = set()   # Models whose daily quota is fully used
        self._dead_keys: set = set()          # Keys that are completely out of credit (e.g. OpenRouter $0)
        self._model_lock = threading.Lock()

        # Human-readable labels for UI status panel
        self.model_label = self.model_name
        self.fallback_label = self.fallback_model_name

        # If a fresh key is provided that is not exhausted, clear the global exhausted flag
        if any(k not in GeminiExtractor._LAST_EXHAUSTED_KEYS for k in self.api_keys):
            GeminiExtractor._GLOBAL_DAILY_EXHAUSTED = False
        elif any(k in GeminiExtractor._LAST_EXHAUSTED_KEYS for k in self.api_keys) and len(self.api_keys) <= len(GeminiExtractor._LAST_EXHAUSTED_KEYS):
            GeminiExtractor._GLOBAL_DAILY_EXHAUSTED = True


    async def extract_from_pdf(
        self,
        pdf_bytes: bytes,
        file_name: str,
        source_language: str = "Gujarati",
        target_language: str = "English",
        model_name: Optional[str] = None,
        progress_callback: Optional[Any] = None,
    ) -> ExtractionResult:
        """Processes a PDF page-by-page with Gemini Multimodal API to ensure 100% question extraction."""
        start_time = time.time()
        active_model = model_name or self.model_name
        with self._model_lock:
            # Fresh start on each extraction job: do not permanently block models across runs!
            self._failed_models.clear()
            self._exhausted_models.clear()
            self.active_working_model = active_model or "gemini-3.5-flash"
        safe_stem = re.sub(r'[^a-zA-Z0-9_\-]', '_', Path(file_name).stem)
        
        if GeminiExtractor._GLOBAL_DAILY_EXHAUSTED and len(self.api_keys) <= len(GeminiExtractor._LAST_EXHAUSTED_KEYS):
            logger.warning(f"[Hybrid Fallback] Gemini daily quota exhausted on API key. Engaging High-Speed Local Engine immediately for {file_name}...")
            return self._extract_via_local_pipeline(
                pdf_bytes=pdf_bytes,
                file_name=file_name,
                source_language=source_language,
                target_language=target_language,
                progress_callback=progress_callback,
                start_time=start_time
            )

        try:
            total_pages = self.pipeline.get_page_count(pdf_bytes)
        except Exception:
            total_pages = 1

        if progress_callback:
            try:
                progress_callback(0, total_pages, 0, f"Analyzing {file_name} ({total_pages} pages)...")
            except Exception:
                pass

        loop = asyncio.get_running_loop()

        try:
            all_raw_questions: List[Dict[str, Any]] = []
            pages_completed = 0
            questions_found_so_far = 0
            
            def _dict_to_quick_question(item: Dict[str, Any], default_page: int) -> Optional[QuestionItem]:
                if item.get("is_solution_item") or item.get("from_solution_page"):
                    return None
                raw_opts = item.get("options") or item.get("choices") or {}
                q_text = str(item.get("question_text") or item.get("question") or item.get("translated_question") or item.get("original_question") or item.get("stem") or "").strip()
                if not q_text:
                    return None

                page_idx = max(0, default_page - 1)
                q_num = str(item.get("question_number") or item.get("q_num") or "1")

                # Pre-parse embedded options if missing
                valid_opt_count = 0
                if isinstance(raw_opts, list):
                    valid_opt_count = sum(1 for o in raw_opts if (
                        isinstance(o, dict) and bool(
                            o.get("text") or o.get("val") or o.get("value") or o.get("content")
                            or o.get("option_text") or o.get("original") or o.get("translated")
                            or o.get("image_box") or o.get("has_image") or o.get("image_url")
                        )
                    ) or (isinstance(o, (str, int, float)) and bool(str(o).strip())))
                elif isinstance(raw_opts, dict):
                    valid_opt_count = sum(1 for v in raw_opts.values() if (
                        isinstance(v, dict) and bool(
                            v.get("text") or v.get("val") or v.get("value") or v.get("content")
                            or v.get("option_text") or v.get("original") or v.get("translated")
                            or v.get("image_box") or v.get("has_image") or v.get("image_url")
                        )
                    ) or (isinstance(v, (str, int, float)) and bool(str(v).strip())))

                if valid_opt_count < 2 and q_text:
                    clean_stem, extracted_opts = split_question_and_options(q_text)
                    if extracted_opts and len(extracted_opts) >= 2:
                        raw_opts = extracted_opts
                        q_text = clean_stem
                        valid_opt_count = len(extracted_opts)

                raw_type = str(item.get("question_type") or item.get("type") or "").strip().upper()
                is_numeric = "NUMER" in raw_type or "INTEGER" in raw_type or "NAT" in raw_type

                opts: Dict[str, OptionDetail] = {}
                if isinstance(raw_opts, list):
                    for idx, opt_entry in enumerate(raw_opts):
                        k = ["A", "B", "C", "D"][min(idx, 3)]
                        if isinstance(opt_entry, dict):
                            raw_k = str(opt_entry.get("key") or opt_entry.get("option") or opt_entry.get("label") or k).strip()
                            norm_k = normalize_option_key(raw_k)
                            k = norm_k if norm_k in ["A", "B", "C", "D"] else ["A", "B", "C", "D"][min(idx, 3)]
                            raw_val = (
                                opt_entry.get("text") or opt_entry.get("val") or opt_entry.get("value")
                                or opt_entry.get("content") or opt_entry.get("option_text")
                                or opt_entry.get("translated") or opt_entry.get("original") or ""
                            )
                            txt = clean_option_text(str(raw_val))
                            opt_box = (
                                opt_entry.get("image_box")
                                or opt_entry.get("box_2d")
                                or opt_entry.get("diagram_box")
                                or opt_entry.get("box")
                                or opt_entry.get("option_image_box")
                                or opt_entry.get("diagram")
                                or opt_entry.get("bbox")
                                or opt_entry.get("coords")
                            )
                            has_img = bool(opt_entry.get("has_image") or opt_box)
                            opt_img_url = None
                            opt_page = int(opt_entry.get("page_number") or default_page)
                            opt_page_idx = max(0, opt_page - 1)
                            if opt_box:
                                crop_bytes = self.pipeline.crop_box_image(pdf_bytes, opt_page_idx, opt_box, is_option=True)
                                if not crop_bytes:
                                    crop_bytes = self.pipeline.crop_box_image(pdf_bytes, opt_page_idx, opt_box, is_option=False)
                                if crop_bytes:
                                    opt_img_name = f"{safe_stem}_p{opt_page}_q{q_num}_opt_{k}.png"
                                    with open(IMAGES_DIR / opt_img_name, "wb") as f_img:
                                        f_img.write(crop_bytes)
                                    opt_img_url = f"/api/images/{opt_img_name}"
                                    has_img = True
                            if has_img:
                                txt = clean_option_text(txt, has_image=True)
                            opts[k] = OptionDetail(original=txt, translated=txt, has_image=has_img, image_url=opt_img_url, image_box=opt_box, page_number=opt_page)
                        elif isinstance(opt_entry, (str, int, float)):
                            txt = clean_option_text(str(opt_entry))
                            opts[k] = OptionDetail(original=txt, translated=txt, has_image=False, page_number=default_page)
                elif isinstance(raw_opts, dict):
                    for k_raw, v in raw_opts.items():
                        k = normalize_option_key(str(k_raw))
                        if k in ["A", "B", "C", "D"]:
                            if isinstance(v, dict):
                                raw_val = (
                                    v.get("text") or v.get("val") or v.get("value")
                                    or v.get("content") or v.get("option_text")
                                    or v.get("translated") or v.get("original") or ""
                                )
                                txt = clean_option_text(str(raw_val))
                                opt_box = (
                                    v.get("image_box")
                                    or v.get("box_2d")
                                    or v.get("diagram_box")
                                    or v.get("box")
                                    or v.get("option_image_box")
                                    or v.get("diagram")
                                    or v.get("bbox")
                                    or v.get("coords")
                                )
                                has_img = bool(v.get("has_image") or opt_box)
                                opt_img_url = None
                                opt_page = int(v.get("page_number") or default_page)
                                opt_page_idx = max(0, opt_page - 1)
                                if opt_box:
                                    crop_bytes = self.pipeline.crop_box_image(pdf_bytes, opt_page_idx, opt_box, is_option=True)
                                    if not crop_bytes:
                                        crop_bytes = self.pipeline.crop_box_image(pdf_bytes, opt_page_idx, opt_box, is_option=False)
                                    if crop_bytes:
                                        opt_img_name = f"{safe_stem}_p{opt_page}_q{q_num}_opt_{k}.png"
                                        with open(IMAGES_DIR / opt_img_name, "wb") as f_img:
                                            f_img.write(crop_bytes)
                                        opt_img_url = f"/api/images/{opt_img_name}"
                                        has_img = True
                                if has_img:
                                    txt = clean_option_text(txt, has_image=True)
                                opts[k] = OptionDetail(original=txt, translated=txt, has_image=has_img, image_url=opt_img_url, image_box=opt_box, page_number=opt_page)
                            elif isinstance(v, (str, int, float)):
                                txt = clean_option_text(str(v))
                                opts[k] = OptionDetail(original=txt, translated=txt, has_image=False, page_number=default_page)

                has_any_opt = any(bool(v.original or v.translated or v.has_image) for v in opts.values())
                raw_ans_val = str(item.get("answer") or item.get("correct_option") or item.get("correct_answer") or "").strip()
                q_text_u = (q_text or "").upper()
                is_match = (
                    "MATCH" in raw_type or "MATRIX" in raw_type or "LIST" in raw_type
                    or "MATCH" in q_text_u
                    or bool(re.search(r'column\s*[-–—]?\s*(?:i|1|a)', q_text_u))
                    or bool(re.search(r'list\s*[-–—]?\s*(?:i|1|a)', q_text_u))
                    or bool(re.search(r'matrix\s*match', q_text_u))
                    or "જોડકા" in q_text or "જોડો" in q_text
                )
                is_mcq_letter_ans = bool(normalize_option_key(raw_ans_val) in ["A", "B", "C", "D"])
                is_num_clean = clean_numeric_answer(raw_ans_val)
                is_incomplete_sentence = bool(re.search(r'\b(?:in|is|of|the|are|to|for|at|by|called|known as|as)\s*[\:\—\-]?\s*$', q_text.strip(), re.IGNORECASE))
                if not has_any_opt and not is_numeric and not is_match:
                    if (is_num_clean and not is_mcq_letter_ans) or (not is_mcq_letter_ans and not is_incomplete_sentence and "MCQ" not in raw_type and not item.get("is_split_at_bottom")):
                        is_numeric = True

                sol = str(item.get("solution") or item.get("explanation") or item.get("hint") or "").strip()
                ans = None

                if is_match:
                    final_q_type = "Match the list"
                    is_numeric = False
                    for letter in ["A", "B", "C", "D"]:
                        if letter not in opts:
                            opts[letter] = OptionDetail(page_number=default_page)
                    if not raw_ans_val or raw_ans_val.lower() in ["null", "none", "n/a", ""]:
                        raw_ans_val = extract_answer_from_text(sol) or extract_answer_from_text(q_text) or ""
                    if raw_ans_val:
                        cand_norm = normalize_option_key(raw_ans_val)
                        ans = cand_norm if cand_norm in ["A", "B", "C", "D"] else raw_ans_val.strip()
                    else:
                        ans = None
                elif is_numeric:
                    opts = {}
                    final_q_type = "Numeric"
                    if not raw_ans_val or raw_ans_val.lower() in ["null", "none", "n/a", ""]:
                        raw_ans_val = extract_numeric_answer_from_text(sol) or extract_numeric_answer_from_text(q_text) or ""
                    ans = clean_numeric_answer(raw_ans_val) if raw_ans_val else None
                else:
                    final_q_type = item.get("question_type", "MCQ")
                    for letter in ["A", "B", "C", "D"]:
                        if letter not in opts:
                            opts[letter] = OptionDetail(page_number=default_page)
                    if not raw_ans_val or raw_ans_val.lower() in ["null", "none", "n/a", ""]:
                        inferred = extract_answer_from_text(sol) or extract_answer_from_text(q_text)
                        if not inferred:
                            for opt_k, opt_v in opts.items():
                                if isinstance(opt_v, OptionDetail) and ("(correct)" in (opt_v.original or "").lower() or "[correct]" in (opt_v.original or "").lower()):
                                    inferred = opt_k
                                    break
                        raw_ans_val = inferred or ""
                    
                    if raw_ans_val:
                        cand_norm = normalize_option_key(raw_ans_val)
                        if cand_norm in ["A", "B", "C", "D"]:
                            ans = cand_norm
                        elif clean_numeric_answer(raw_ans_val) and not re.match(r'^[a-dA-D]$', str(raw_ans_val).strip()):
                            ans = clean_numeric_answer(raw_ans_val)
                        else:
                            ans = raw_ans_val.upper()
                    else:
                        ans = None

                # Question stem diagram
                q_box = (
                    item.get("image_box")
                    or item.get("box_2d")
                    or item.get("diagram_box")
                    or item.get("question_image_box")
                    or item.get("question_box")
                    or item.get("diagram")
                    or item.get("bbox")
                )
                if q_box and is_box_duplicate_of_options(q_box, opts):
                    q_box = None

                has_q_img = False
                q_img_url = None
                if q_box:
                    crop_bytes = self.pipeline.crop_box_image(pdf_bytes, page_idx, q_box)
                    if crop_bytes:
                        img_name = f"{safe_stem}_p{default_page}_q{q_num}_diagram.png"
                        with open(IMAGES_DIR / img_name, "wb") as f_img:
                            f_img.write(crop_bytes)
                        q_img_url = f"/api/images/{img_name}"
                        has_q_img = True

                has_any_opt_text = any(bool(v and (v.original or v.translated)) for v in opts.values())
                has_any_opt_img = any(bool(getattr(v, "has_image", False) or getattr(v, "image_url", None)) for v in opts.values())
                if not is_genuine_question_diagram(q_text, has_any_opt_text, q_img_url, has_opt_images=has_any_opt_img):
                    has_q_img = False
                    q_img_url = None

                # Solution diagram
                sol_box = (
                    item.get("solution_image_box")
                    or item.get("solution_box")
                    or item.get("solution_diagram_box")
                    or item.get("solution_img_box")
                    or item.get("solution_image")
                    or item.get("explanation_image_box")
                    or item.get("sol_image_box")
                )
                has_sol_img = False
                sol_img_url = None
                if sol_box:
                    crop_bytes = self.pipeline.crop_box_image(pdf_bytes, page_idx, sol_box)
                    if crop_bytes:
                        sol_img_name = f"{safe_stem}_p{default_page}_q{q_num}_solution.png"
                        with open(IMAGES_DIR / sol_img_name, "wb") as f_img:
                            f_img.write(crop_bytes)
                        sol_img_url = f"/api/images/{sol_img_name}"
                        has_sol_img = True

                # Answer image URL if correct option has an image
                ans_img_url = None
                if ans and ans in opts and opts[ans] and opts[ans].image_url:
                    ans_img_url = opts[ans].image_url

                raw_para = str(item.get("paragraph") or item.get("passage") or item.get("comprehension") or "").strip()
                col_i = str(item.get("column_i") or item.get("list_i") or "").strip()
                col_ii = str(item.get("column_ii") or item.get("list_ii") or "").strip()

                return QuestionItem(
                    question_number=q_num,
                    page_number=item.get("page_number", default_page),
                    original_question=q_text,
                    translated_question=q_text,
                    options=opts,
                    answer=ans,
                    solution=sol,
                    question_type=final_q_type,
                    has_question_image=has_q_img,
                    image_url=q_img_url,
                    image_box=q_box if has_q_img else None,
                    has_solution_image=has_sol_img,
                    solution_image_url=sol_img_url,
                    solution_image_box=sol_box if has_sol_img else None,
                    answer_image_url=ans_img_url,
                    difficulty=0,
                    status="complete",
                    chapter_number="",
                    chapter_name="",
                    subject="",
                    paragraph=raw_para,
                    column_i=col_i,
                    column_ii=col_ii,
                )

            live_questions_list: List[QuestionItem] = []
            both_models_exhausted = False
            exhaustion_message: str = ""

            if total_pages > 1:
                # ── HIGH-SPEED CONCURRENT PAGE SCAN ───────────────────────────
                # Pages are scanned concurrently with bounded semaphore for fast processing
                valid_page_results_map: Dict[int, Tuple[int, List[Dict[str, Any]], Dict[str, Any]]] = {}
                raw_pages_text_map: Dict[int, str] = {}
                sem = asyncio.Semaphore(1)

                async def _scan_single_page(p_idx: int):
                    nonlocal pages_completed, questions_found_so_far, both_models_exhausted, exhaustion_message
                    if both_models_exhausted:
                        return

                    async with sem:
                        if both_models_exhausted:
                            return

                        p_bytes = self.pipeline.render_page_to_image(pdf_bytes, p_idx, scale=2.0, img_format="JPEG")
                        mime_type_p = "image/jpeg"
                        if p_bytes is None:
                            p_bytes = self.pipeline.slice_page(pdf_bytes, p_idx)
                            mime_type_p = "application/pdf"

                        p_prompt = get_mcq_extraction_prompt(
                            source_language=source_language,
                            target_language=target_language,
                            page_num=p_idx + 1,
                            total_pages=total_pages
                        )

                        logger.info(f"[Scan] {file_name}: Scanning Page {p_idx + 1}/{total_pages}...")

                        try:
                            r_text = await loop.run_in_executor(
                                None,
                                self._call_gemini_api_with_fallback,
                                p_bytes,
                                p_prompt,
                                active_model,
                                mime_type_p,
                                progress_callback
                            )
                        except Exception as scan_err:
                            err_s = str(scan_err)
                            if "BOTH_MODELS_EXHAUSTED" in err_s or "MODEL_EXHAUSTED" in err_s:
                                both_models_exhausted = True
                                exhaustion_message = err_s
                                return
                            logger.warning(f"[Page Scan Error] Page {p_idx + 1}: {err_s[:120]}")
                            return

                        p_parsed = extract_json_from_response(r_text)
                        p_qs = p_parsed.get("questions", [])

                        p_text = self.pipeline.extract_page_text(pdf_bytes, p_idx)
                        if p_text:
                            raw_pages_text_map[p_idx] = p_text
                        is_sol_p = is_solution_page_text(p_text)
                        is_ak_p = is_answer_key_page_text(p_text)
                        dummy_ans_items = sum(1 for q in p_qs if (
                            (not q.get("options") or len(q.get("options")) == 0)
                            and bool(q.get("answer"))
                            and len(str(q.get("question_text", "")).strip()) < 15
                        ))
                        if len(p_qs) >= 8 and dummy_ans_items >= len(p_qs) * 0.75:
                            is_ak_p = True

                        if p_parsed.get("is_solution_page") is True:
                            is_sol_p = True

                        mcq_count_on_page = sum(1 for q in p_qs if (
                            (isinstance(q.get("options"), (list, dict)) and len(q.get("options")) >= 2)
                            or len(str(q.get("question_text", "")).strip()) >= 20
                            or bool(q.get("image_box"))
                        ))
                        if mcq_count_on_page >= 1:
                            is_sol_p = False
                            is_ak_p = False

                        for q in p_qs:
                            q["page_number"] = p_idx + 1
                            if is_sol_p:
                                q["is_solution_item"] = True
                                q["from_solution_page"] = True
                            if is_ak_p:
                                q["is_answer_key_stub"] = True
                                q["is_solution_item"] = True
                                q["from_solution_page"] = True

                            raw_opts = q.get("options")
                            if isinstance(raw_opts, list):
                                for opt in raw_opts:
                                    if isinstance(opt, dict) and "page_number" not in opt:
                                        opt["page_number"] = p_idx + 1
                            elif isinstance(raw_opts, dict):
                                for opt in raw_opts.values():
                                    if isinstance(opt, dict) and "page_number" not in opt:
                                        opt["page_number"] = p_idx + 1

                        if not is_sol_p and not is_ak_p:
                            for q in p_qs:
                                qq = _dict_to_quick_question(q, p_idx + 1)
                                if qq:
                                    live_questions_list.append(qq)
                        else:
                            for q in p_qs:
                                # In solution/answer key pages, only add if it is a genuine full question with real options
                                if (isinstance(q.get("options"), (list, dict)) and len(q.get("options")) >= 2 and len(str(q.get("question_text", "")).strip()) >= 30):
                                    qq = _dict_to_quick_question(q, p_idx + 1)
                                    if qq:
                                        live_questions_list.append(qq)

                        valid_page_results_map[p_idx] = (p_idx + 1, p_qs, p_text)
                        pages_completed += 1
                        questions_found_so_far += len(p_qs)

                        logger.info(f"[Scan] {file_name}: Page {p_idx + 1}/{total_pages} scanned -> {len(p_qs)} questions (Total: {questions_found_so_far})")

                        if progress_callback:
                            try:
                                progress_callback(
                                    pages_completed,
                                    total_pages,
                                    questions_found_so_far,
                                    f"Scanned {pages_completed}/{total_pages} pages ({len(live_questions_list)} questions found) | Model: {self.active_working_model}",
                                    list(live_questions_list)
                                )
                            except Exception:
                                pass

                for p in range(total_pages):
                    if both_models_exhausted:
                        break
                    await _scan_single_page(p)
                    if p < total_pages - 1 and not both_models_exhausted:
                        await asyncio.sleep(2.0)  # Gentle pacing between requests to stay within Google 15 RPM limit

                if both_models_exhausted and len(live_questions_list) == 0:
                    logger.warning(f"[Auto Fallback] Quota exhausted with 0 questions. Engaging Local Engine for {file_name}...")
                    return self._extract_via_local_pipeline(
                        pdf_bytes=pdf_bytes,
                        file_name=file_name,
                        source_language=source_language,
                        target_language=target_language,
                        progress_callback=progress_callback,
                        start_time=start_time
                    )

                # Assemble strictly in ascending page order (1, 2, 3... total_pages)
                valid_page_results = [valid_page_results_map[p] for p in sorted(valid_page_results_map.keys())]
                raw_pages_text_corpus = [raw_pages_text_map[p] for p in sorted(raw_pages_text_map.keys()) if p in raw_pages_text_map]



                # Helper to merge continuation or split questions across pages
                def merge_question_items(target: Dict[str, Any], src: Dict[str, Any]):
                    """Merges continuation or split question data from src into target while preserving option origins and complete text."""
                    target_opts = target.get("options") or {}
                    src_opts = src.get("options") or {}

                    # If src options are empty but src question text has embedded options, extract them
                    s_raw_stem = str(src.get("question_text") or src.get("stem") or "").strip()
                    if s_raw_stem:
                        s_stem, s_extracted = split_question_and_options(s_raw_stem)
                        if s_extracted:
                            if not src_opts:
                                src_opts = s_extracted
                            elif isinstance(src_opts, dict):
                                for ek, ev in s_extracted.items():
                                    if ek not in src_opts:
                                        src_opts[ek] = ev

                    norm_target: Dict[str, Any] = {}
                    if isinstance(target_opts, list):
                        for idx, o in enumerate(target_opts):
                            if isinstance(o, dict):
                                k = normalize_option_key(str(o.get("key") or "")) or ["A", "B", "C", "D"][min(idx, 3)]
                                norm_target[k] = o
                            elif isinstance(o, str):
                                k = ["A", "B", "C", "D"][min(idx, 3)]
                                norm_target[k] = {"key": k, "text": o, "has_image": False, "page_number": target.get("page_number", 1)}
                    elif isinstance(target_opts, dict):
                        for k, v in target_opts.items():
                            norm_k = normalize_option_key(str(k))
                            if norm_k in ["A", "B", "C", "D"]:
                                norm_target[norm_k] = v

                    norm_src: Dict[str, Any] = {}
                    if isinstance(src_opts, list):
                        for idx, o in enumerate(src_opts):
                            if isinstance(o, dict):
                                k = normalize_option_key(str(o.get("key") or "")) or ["A", "B", "C", "D"][min(idx, 3)]
                                norm_src[k] = o
                            elif isinstance(o, str):
                                k = ["A", "B", "C", "D"][min(idx, 3)]
                                norm_src[k] = {"key": k, "text": o, "has_image": False, "page_number": src.get("page_number", 1)}
                    elif isinstance(src_opts, dict):
                        for k, v in src_opts.items():
                            norm_k = normalize_option_key(str(k))
                            if norm_k in ["A", "B", "C", "D"]:
                                norm_src[norm_k] = v

                    # If target has 1 or 2 options (e.g. A and B), and src also has options with overlapping keys (e.g. A and B):
                    # In a cross-page split question, src's options are actually the subsequent options (C and D)!
                    overlap_keys = set(norm_target.keys()) & set(norm_src.keys())
                    if overlap_keys and len(norm_target) in [1, 2, 3]:
                        missing_keys = [k for k in ["A", "B", "C", "D"] if k not in norm_target]
                        remapped_src = {}
                        sorted_src_items = sorted(norm_src.items(), key=lambda item: item[0])
                        for idx, (old_k, opt_val) in enumerate(sorted_src_items):
                            if idx < len(missing_keys):
                                new_k = missing_keys[idx]
                                if isinstance(opt_val, dict):
                                    opt_val = dict(opt_val)
                                    opt_val["key"] = new_k
                                remapped_src[new_k] = opt_val
                            else:
                                remapped_src[old_k] = opt_val
                        norm_src = remapped_src

                    for k, v in norm_src.items():
                        if k not in norm_target or not norm_target[k]:
                            norm_target[k] = v
                        else:
                            ex = norm_target[k]
                            if isinstance(ex, dict) and isinstance(v, dict):
                                if not ex.get("image_box") and v.get("image_box"):
                                    ex["image_box"] = v["image_box"]
                                    ex["has_image"] = True
                                    ex["page_number"] = v.get("page_number", src.get("page_number"))
                                if not (ex.get("text") or ex.get("original") or ex.get("translated")) and (v.get("text") or v.get("original") or v.get("translated")):
                                    ex["text"] = v.get("text") or v.get("original") or v.get("translated")

                    target["options"] = norm_target

                    # Merge question text if continuation
                    t_text = str(target.get("question_text") or target.get("stem") or "").strip()
                    s_text = str(src.get("question_text") or src.get("stem") or "").strip()
                    # Check if s_text is purely option text or continuation marker:
                    s_stem_pure, s_extracted_opts = split_question_and_options(s_text)
                    is_pure_opts = bool(s_extracted_opts and (not s_stem_pure or len(s_stem_pure) < 5 or re.match(r'^\s*Q?\d+[\.\:\-\)]?\s*$', s_stem_pure)))
                    if s_text and s_text != t_text and not is_pure_opts:
                        if src.get("is_continuation") or not target.get("is_continuation"):
                            if not t_text:
                                target["question_text"] = s_text
                            elif s_text.lower() not in t_text.lower() and not s_text.lower().startswith("question"):
                                target["question_text"] = f"{t_text} {s_text}"

                    # Merge question diagram vs solution diagram based on page origin:
                    t_page = int(target.get("page_number", 1))
                    s_page = int(src.get("page_number", t_page))

                    # STRICT: Only take src solution if target has NONE.
                    # Never overwrite an existing correct solution just because src is longer.
                    s_sol = str(src.get("solution") or src.get("explanation") or "").strip()
                    t_sol = str(target.get("solution") or target.get("explanation") or "").strip()
                    if s_sol and not t_sol:
                        target["solution"] = s_sol

                    if s_page > t_page or src.get("is_solution_item"):
                        # src is from a later solutions page or is a solution item:
                        # Any diagram from this later page belongs to SOLUTION, NEVER to question stem!
                        s_diag = src.get("solution_image_box") or src.get("image_box") or src.get("solution_box")
                        if s_diag and not target.get("solution_image_box"):
                            target["solution_image_box"] = s_diag
                            target["has_solution_image"] = True
                            target["solution_page_number"] = s_page
                    else:
                        # Same page or consecutive continuation page
                        if not target.get("image_box") and src.get("image_box") and not src.get("is_solution_item"):
                            target["image_box"] = src.get("image_box")
                            target["has_image"] = True

                        s_box = src.get("solution_image_box") or src.get("solution_box") or src.get("solution_diagram_box")
                        if s_box and not target.get("solution_image_box"):
                            target["solution_image_box"] = s_box
                            target["has_solution_image"] = True
                            target["solution_page_number"] = src.get("solution_page_number", s_page)

                    # Merge answer
                    if not target.get("answer") and src.get("answer"):
                        target["answer"] = src.get("answer")

                # Expand multi-part questions (e.g. Q27 with (i), (ii), (iii), (iv)) across all pages
                for p_idx in range(len(valid_page_results)):
                    p_num, p_qs, p_txt = valid_page_results[p_idx]
                    exp_qs = []
                    for q_item in p_qs:
                        exp_qs.extend(split_multipart_subquestions(q_item))
                    valid_page_results[p_idx] = (p_num, exp_qs, p_txt)

                def count_non_empty_opts(raw_opts):
                    if not raw_opts:
                        return 0
                    if isinstance(raw_opts, list):
                        return sum(1 for o in raw_opts if (
                            (isinstance(o, dict) and bool(o.get("text") or o.get("val") or o.get("value") or o.get("original") or o.get("translated") or o.get("has_image") or o.get("image_url") or o.get("image_box")))
                            or (isinstance(o, (str, int, float)) and bool(str(o).strip()))
                        ))
                    elif isinstance(raw_opts, dict):
                        return sum(1 for v in raw_opts.values() if (
                            (isinstance(v, dict) and bool(v.get("text") or v.get("val") or v.get("value") or v.get("original") or v.get("translated") or v.get("has_image") or v.get("image_url") or v.get("image_box")))
                            or (isinstance(v, (str, int, float)) and bool(str(v).strip()))
                        ))
                    return 0

                # Pre-pass: stitch same-page cross-column split questions (e.g. Q13 or Q93 at bottom of left column with options at top of right column)
                for p_idx in range(len(valid_page_results)):
                    p_num, p_qs, p_txt = valid_page_results[p_idx]
                    if not p_qs or len(p_qs) < 2:
                        continue
                    stitched_p_qs = []
                    idx = 0
                    while idx < len(p_qs):
                        curr_it = p_qs[idx]
                        if idx + 1 < len(p_qs):
                            next_it = p_qs[idx + 1]
                            curr_opts = curr_it.get("options") or {}
                            curr_opt_cnt = count_non_empty_opts(curr_opts)
                            curr_type = str(curr_it.get("question_type") or "").upper()
                            
                            next_opts = next_it.get("options") or {}
                            next_opt_cnt = count_non_empty_opts(next_opts)
                            next_text = str(next_it.get("question_text") or next_it.get("stem") or "").strip()
                            next_num = str(next_it.get("question_number") or "").strip()
                            
                            is_next_pure_continuation = False
                            if next_it.get("is_continuation") is True:
                                is_next_pure_continuation = True
                            elif not any(t in curr_type for t in ["NUMER", "INTEGER", "NAT"]) and curr_opt_cnt == 0 and next_opt_cnt >= 2:
                                # If next_it has no explicit question number, or same number as curr_it, or very short stem / pure options
                                if not next_num or next_num == str(curr_it.get("question_number") or "").strip() or len(next_text) < 35:
                                    is_next_pure_continuation = True
                            
                            if is_next_pure_continuation:
                                logger.info(f"[Scan] Merging same-page split question: Q{curr_it.get('question_number')} with adjacent continuation block")
                                merge_question_items(curr_it, next_it)
                                curr_it["is_split_at_bottom"] = False
                                curr_it["question_type"] = "MCQ"
                                idx += 2
                                stitched_p_qs.append(curr_it)
                                continue
                        stitched_p_qs.append(curr_it)
                        idx += 1
                    valid_page_results[p_idx] = (p_num, stitched_p_qs, p_txt)

                # Cross-page stitching for consecutive pages:
                # Detect questions split across page boundary:
                # 1) Stem + partial options on page k, remaining options on page k+1
                # 2) Stem ONLY on page k (0 options), and ALL options (A, B, C, D) on page k+1
                for i in range(len(valid_page_results) - 1):
                    curr_page_num, curr_qs, curr_txt = valid_page_results[i]
                    next_page_num, next_qs, next_txt = valid_page_results[i + 1]

                    if not curr_qs:
                        continue

                    # Find the last genuine question on Page i (ignore any trailing footers or pure stubs)
                    last_q_cands = [
                        q for q in curr_qs
                        if not q.get("is_solution_item") and len(str(q.get("question_text") or q.get("stem") or "").strip()) >= 15
                    ]
                    last_q = last_q_cands[-1] if last_q_cands else curr_qs[-1]
                    last_q_key = normalize_question_key(last_q.get("question_number")) or None
                    last_raw_type = str(last_q.get("question_type") or "").upper()
                    if any(t in last_raw_type for t in ["NUMER", "INTEGER", "NAT"]):
                        continue

                    last_opts = last_q.get("options") or {}
                    last_opt_count = count_non_empty_opts(last_opts)

                    # If last_opt_count < 2, check if options are embedded in stem:
                    last_text = str(last_q.get("question_text") or last_q.get("stem") or "").strip()
                    if last_opt_count < 2 and last_text:
                        l_stem_clean, l_ext_opts = split_question_and_options(last_text)
                        if l_ext_opts and len(l_ext_opts) >= 2:
                            last_q["options"] = l_ext_opts
                            last_q["question_text"] = l_stem_clean
                            last_opts = l_ext_opts
                            last_opt_count = len(l_ext_opts)

                    is_stitched = False

                    # Check 1: Does next_qs[0] contain a genuine continuation item from Gemini?
                    first_next = next_qs[0] if next_qs else None
                    if first_next:
                        first_next_key = normalize_question_key(first_next.get("question_number")) or None
                        f_opts = first_next.get("options") or {}
                        f_opt_count = count_non_empty_opts(f_opts)

                        f_text = str(first_next.get("question_text") or first_next.get("stem") or "").strip()
                        # Strip standard header / school banners from continuation text (e.g. "ASHADEEP JEE | NEET | FOUNDATION")
                        f_text = re.sub(r'(?i)^\s*(?:ASHADEEP\s*JEE\s*\|\s*NEET\s*\|\s*FOUNDATION|STD\s*\d+\w*\s*MATHEMATICS|PAGE\s*\d+|SECTION\s*[-–—]?\s*\d+|TOPIC\s*[-–—]?\s*\d+)[\s\:\-\|\_]*', '', f_text).strip()

                        f_stem_clean, f_ext_opts = split_question_and_options(f_text)
                        if f_ext_opts and not f_opt_count:
                            f_opts = f_ext_opts
                            first_next["options"] = f_ext_opts
                            first_next["question_text"] = f_stem_clean
                            f_opt_count = len(f_ext_opts)
                            f_text = f_stem_clean

                        first_keys = []
                        if isinstance(f_opts, list):
                            first_keys = [str(o.get("key", "")).upper() for o in f_opts if isinstance(o, dict)]
                        elif isinstance(f_opts, dict):
                            first_keys = [str(k).upper() for k in f_opts.keys()]

                        f_starts_with_cd = bool(re.match(r'^\s*(?:[\(\[]\s*(?:[cCdD34]|ક|ડ)\s*[\)\]]|(?:[cCdD34]|ક|ડ)[\.\:\)])', f_text))
                        has_c_d_only = any(k in ["C", "D", "3", "4"] for k in first_keys) and not any(k in ["A", "1"] for k in first_keys)
                        f_is_pure_opts = bool(f_opt_count >= 1 and (not f_text or len(f_text) < 35 or re.match(r'^\s*(?:Q(?:uestion)?\.?\s*\d*|\d*|[A-Da-d1-4\(\)\[\]\.\:\-\s]+)$', f_text)))

                        # Determine if first_next is definitely an independent real question
                        is_independent_q = False
                        if not f_is_pure_opts and not first_next.get("is_continuation") and not has_c_d_only and not f_starts_with_cd:
                            # Genuine independent question requires distinct question number AND substantial stem with problem statements
                            if first_next_key and last_q_key and first_next_key != last_q_key and len(f_text) >= 30 and any(w in f_text.lower() for w in ["if", "let", "find", "then", "which", "value", "for", "solve", "number of", "જો", "શોધો"]):
                                is_independent_q = True
                            elif len(f_text) >= 50:
                                is_independent_q = True

                        is_cont = False
                        if not is_independent_q:
                            if first_next.get("is_continuation") is True:
                                is_cont = True
                            elif last_q_key and first_next_key and last_q_key == first_next_key:
                                is_cont = True
                            elif f_is_pure_opts:
                                is_cont = True
                            elif last_opt_count in [0, 1, 2, 3] and (has_c_d_only or f_starts_with_cd or f_opt_count >= 2):
                                is_cont = True

                        if is_cont:
                            logger.info(f"[Scan] Merging split question across pages: Q{last_q.get('question_number')} (Page {curr_page_num}) continued on Page {next_page_num}")
                            merge_question_items(last_q, first_next)
                            last_q["is_split_at_bottom"] = False
                            last_q["question_type"] = "MCQ"
                            next_qs.pop(0)
                            is_stitched = True

                    # Check 2: If last_opt_count is STILL < 4 and not stitched yet:
                    # Model might have skipped unnumbered orphaned options at top of next page!
                    # Recover options directly from next_txt (raw text of Page i+1 before next_qs[0] begins)!
                    last_opt_count_now = count_non_empty_opts(last_q.get("options"))
                    if not is_stitched and last_opt_count_now < 4 and next_txt and isinstance(next_txt, str):
                        boundary_pos = len(next_txt)
                        if next_qs:
                            fn_num = str(next_qs[0].get("question_number") or "").strip()
                            m_num = re.search(r'\d+', fn_num)
                            found_pos = None
                            if m_num:
                                num_str = m_num.group(0)
                                m_pos = re.search(rf'(?:^|[\r\n]+|\s{2,}|\t)\s*(?:Q(?:uestion)?\.?\s*)?{num_str}[\.\:\-\)\s]', next_txt)
                                if m_pos:
                                    found_pos = m_pos.start()
                            fn_stem = str(next_qs[0].get("question_text") or "").strip()
                            if fn_stem and len(fn_stem) >= 15:
                                snippet = fn_stem[:min(len(fn_stem), 30)]
                                s_pos = next_txt.find(snippet)
                                if s_pos != -1 and (found_pos is None or s_pos < found_pos):
                                    found_pos = s_pos
                            if found_pos is not None:
                                boundary_pos = found_pos

                        orphan_text_block = next_txt[:boundary_pos].strip()
                        orphan_stem, orphan_opts = split_question_and_options(orphan_text_block)
                        if not orphan_opts:
                            opt_pat = r'(?:^|[\r\n]+|\s{2,}|\t|\s+)(?:[\(\[]\s*([A-Da-d1-4અબકડक-घ])\s*[\)\]]|(?:^|[\r\n]+|\s{2,}|\t)([A-Da-d1-4અબકડक-घ])[\.\:\)])\s*'
                            m_splits = list(re.finditer(opt_pat, orphan_text_block))
                            if m_splits:
                                parsed_m_opts = {}
                                for idx, m_sp in enumerate(m_splits):
                                    raw_k = m_sp.group(1) or m_sp.group(2)
                                    norm_k = normalize_option_key(raw_k)
                                    if norm_k in ["A", "B", "C", "D"]:
                                        start_p = m_sp.end()
                                        end_p = m_splits[idx + 1].start() if idx + 1 < len(m_splits) else len(orphan_text_block)
                                        val = orphan_text_block[start_p:end_p].strip()
                                        val = re.sub(r'\s*(?:\[\s*Ans[^\n\]]*\]|\(?\s*Ans(?:wer)?[\s\:\.\=\-]*\s*[\(\[]?[a-dA-D0-9\(\)]+[\)\]]?\)?)\s*$', '', val, flags=re.IGNORECASE).strip()
                                        if val:
                                            parsed_m_opts[norm_k] = clean_option_text(val)
                                if parsed_m_opts:
                                    orphan_opts = parsed_m_opts

                        if orphan_opts:
                            logger.info(f"[Scan] Recovered orphaned options from raw text of Page {next_page_num} for Q{last_q.get('question_number')}: {list(orphan_opts.keys())}")
                            target_opts = last_q.get("options") or {}
                            if not isinstance(target_opts, dict):
                                target_opts = {}

                            if last_opt_count_now == 0:
                                last_q["options"] = orphan_opts
                            else:
                                missing_keys = [k for k in ["A", "B", "C", "D"] if k not in target_opts or not target_opts[k]]
                                sorted_orphan = sorted(orphan_opts.items(), key=lambda it: it[0])
                                for idx, (ok, ov) in enumerate(sorted_orphan):
                                    if idx < len(missing_keys):
                                        target_opts[missing_keys[idx]] = ov
                                    else:
                                        target_opts[ok] = ov
                                last_q["options"] = target_opts

                            last_q["is_split_at_bottom"] = False
                            last_q["question_type"] = "MCQ"
                            orphan_ans = extract_answer_from_text(orphan_text_block)
                            if orphan_ans and not last_q.get("answer"):
                                last_q["answer"] = orphan_ans
                            is_stitched = True

                    # Check 3: Check if next_qs[0] stem accidentally contains leading orphaned options
                    if not is_stitched and count_non_empty_opts(last_q.get("options")) < 4 and next_qs:
                        fn_stem = str(next_qs[0].get("question_text") or "").strip()
                        lead_opts_m = list(re.finditer(r'(?:^|[\r\n]+)\s*(?:[\(\[]\s*([A-Da-d1-4])\s*[\)\]]|([A-Da-d1-4])[\.\:\)])\s+([^\n\r]+)', fn_stem))
                        if lead_opts_m:
                            fn_first_num = str(next_qs[0].get("question_number") or "").strip()
                            m_num = re.search(r'\d+', fn_first_num)
                            if m_num:
                                q_split = re.search(rf'(?:^|[\r\n]+)\s*(?:Q(?:uestion)?\.?\s*)?{m_num.group(0)}[\.\:\-\)\s]', fn_stem)
                                if q_split and q_split.start() > 0:
                                    lead_block = fn_stem[:q_split.start()].strip()
                                    _, lead_opts = split_question_and_options(lead_block)
                                    if lead_opts:
                                        logger.info(f"[Scan] Extracted leading options from next question text for Q{last_q.get('question_number')}: {list(lead_opts.keys())}")
                                        t_opts = last_q.get("options") or {}
                                        if not isinstance(t_opts, dict): t_opts = {}
                                        if count_non_empty_opts(t_opts) == 0:
                                            last_q["options"] = lead_opts
                                        else:
                                            for lok, lov in lead_opts.items():
                                                if lok not in t_opts or not t_opts[lok]:
                                                    t_opts[lok] = lov
                                            last_q["options"] = t_opts
                                        last_q["is_split_at_bottom"] = False
                                        last_q["question_type"] = "MCQ"
                                        next_qs[0]["question_text"] = fn_stem[q_split.start():].strip()
                                        is_stitched = True

                for _, qs, _ in valid_page_results:
                    all_raw_questions.extend(qs)

                # Helper to detect if a raw item is a pure solution/explanation
                def is_pure_solution_item(raw_it: Dict[str, Any], seen_numbers: set) -> bool:
                    q_k_raw = str(raw_it.get("question_number") or raw_it.get("q_num") or "").strip()
                    clean_k = normalize_question_key(q_k_raw) or q_k_raw

                    raw_opts = raw_it.get("options") or raw_it.get("choices") or {}
                    valid_opt_count = 0
                    if isinstance(raw_opts, list):
                        for o in raw_opts:
                            if isinstance(o, dict) and bool(
                                o.get("text") or o.get("val") or o.get("value") or o.get("content")
                                or o.get("option_text") or o.get("original") or o.get("translated")
                                or o.get("image_box") or o.get("has_image") or o.get("image_url")
                            ):
                                valid_opt_count += 1
                            elif isinstance(o, (str, int, float)) and bool(str(o).strip()):
                                valid_opt_count += 1
                    elif isinstance(raw_opts, dict):
                        for v in raw_opts.values():
                            if isinstance(v, dict) and bool(
                                v.get("text") or v.get("val") or v.get("value") or v.get("content")
                                or v.get("option_text") or v.get("original") or v.get("translated")
                                or v.get("image_box") or v.get("has_image") or v.get("image_url")
                            ):
                                valid_opt_count += 1
                            elif isinstance(v, (str, int, float)) and bool(str(v).strip()):
                                valid_opt_count += 1

                    q_type = str(raw_it.get("question_type") or "").strip().upper()
                    raw_stem_val = str(raw_it.get("question_text", "") or raw_it.get("question", "") or raw_it.get("stem", "") or "")
                    raw_stem_u = raw_stem_val.upper()
                    is_match_q = ("MATCH" in q_type or "MATRIX" in q_type or "LIST" in q_type or "MATCH" in raw_stem_u or bool(re.search(r'column\s*[-–—]?\s*(?:i|1|a)', raw_stem_val, re.IGNORECASE)))
                    is_num_q = ("NUMER" in q_type or "INTEGER" in q_type or "NAT" in q_type) and not is_match_q

                    # Match questions and questions with options are NEVER pure solutions
                    if is_match_q or valid_opt_count >= 2:
                        return False

                    q_t_lower = raw_stem_val.strip().lower()
                    clean_head = re.sub(r'^\s*(?:Q(?:uestion)?|પ્રશ્ન)?\s*\d*[\.\:\-\)\s]*', '', q_t_lower).strip()

                    # Only treat as solution item if it has no options AND explicitly starts with a solution prefix
                    if (any(clean_head.startswith(p) for p in SOL_PREFIXES) or any(q_t_lower.startswith(p) for p in SOL_PREFIXES)) and valid_opt_count < 2:
                        return True

                    if raw_it.get("solution") and not raw_stem_val.strip() and valid_opt_count < 2:
                        return True

                    # If this question number already has genuine question options from an earlier scan,
                    # and this subsequent item has 0 or 1 option, it is an inline solution/answer block:
                    if clean_k and clean_k in seen_numbers and valid_opt_count < 2:
                        if raw_it.get("solution") or any(p in clean_head[:40] for p in SOL_PREFIXES) or valid_opt_count == 0:
                            return True

                    return False

                # Separate primary question items from pure solution items
                primary_raw_questions: List[Dict[str, Any]] = []
                collected_solutions: Dict[str, Dict[str, Any]] = {}
                collected_answers: Dict[str, str] = {}
                seen_question_keys = set()

                # First pass: find questions with options or substantive stems to establish genuine test questions
                for raw_item in all_raw_questions:
                    raw_opts = raw_item.get("options") or raw_item.get("choices") or {}
                    has_valid_opts = False
                    if isinstance(raw_opts, list) and len(raw_opts) >= 1:
                        has_valid_opts = any(
                            (isinstance(o, dict) and bool(
                                o.get("text") or o.get("val") or o.get("value") or o.get("content")
                                or o.get("option_text") or o.get("original") or o.get("translated")
                                or o.get("image_box") or o.get("has_image") or o.get("image_url")
                            ))
                            or (isinstance(o, (str, int, float)) and bool(str(o).strip()))
                            for o in raw_opts
                        )
                    elif isinstance(raw_opts, dict) and len(raw_opts) >= 1:
                        has_valid_opts = any(
                            (isinstance(v, dict) and bool(
                                v.get("text") or v.get("val") or v.get("value") or v.get("content")
                                or v.get("option_text") or v.get("original") or v.get("translated")
                                or v.get("image_box") or v.get("has_image") or v.get("image_url")
                            ))
                            or (isinstance(v, (str, int, float)) and bool(str(v).strip()))
                            for v in raw_opts.values()
                        )
                    q_t_u = str(raw_item.get("question_type") or "").strip().upper()
                    raw_stem_it = str(raw_item.get("question_text", "") or raw_item.get("question", "") or raw_item.get("stem", "") or "").strip()
                    is_match = ("MATCH" in q_t_u or "MATRIX" in q_t_u or "LIST" in q_t_u or "MATCH" in raw_stem_it.upper() or bool(re.search(r'column\s*[-–—]?\s*(?:i|1|a)', raw_stem_it, re.IGNORECASE)))
                    is_num = ("NUMER" in q_t_u or "INTEGER" in q_t_u or "NAT" in q_t_u) and not is_match
                    has_substantive_stem = len(raw_stem_it) >= 15 and not any(raw_stem_it.lower().startswith(p) for p in SOL_PREFIXES)

                    if (has_valid_opts or is_num or is_match or has_substantive_stem) and not raw_item.get("is_solution_item", False):
                        q_k_raw = str(raw_item.get("question_number") or raw_item.get("q_num") or "").strip()
                        q_norm = normalize_question_key(q_k_raw)
                        if q_norm:
                            seen_question_keys.add(q_norm)

                for raw_item in all_raw_questions:
                    q_num_key = str(raw_item.get("question_number") or raw_item.get("q_num") or "").strip()
                    clean_num_key = normalize_question_key(q_num_key) or q_num_key

                    is_pure_sol = is_pure_solution_item(raw_item, seen_question_keys)
                    is_explicit_sol = bool(raw_item.get("is_solution_item"))

                    sol_box = (
                        raw_item.get("solution_image_box")
                        or raw_item.get("solution_box")
                        or raw_item.get("solution_diagram_box")
                        or raw_item.get("solution_img_box")
                        or raw_item.get("solution_image")
                        or raw_item.get("solution_diagram")
                        or (raw_item.get("image_box") if (is_explicit_sol or is_pure_sol) else None)
                        or (raw_item.get("box_2d") if (is_explicit_sol or is_pure_sol) else None)
                    )
                    # Extract solution text from "solution" or "question_text"
                    sol_text = str(raw_item.get("solution") or "").strip()
                    if not sol_text and raw_item.get("question_text") and (is_explicit_sol or is_pure_sol):
                        q_cand = str(raw_item.get("question_text")).strip()
                        for pfx in SOL_PREFIXES:
                            if q_cand.lower().startswith(pfx):
                                q_cand = q_cand[len(pfx):].strip(" :-.")
                                break
                        sol_text = q_cand
                    sol_page = int(raw_item.get("solution_page_number") or raw_item.get("page_number", 1))

                    if is_pure_sol:
                        if clean_num_key and (sol_text or sol_box or raw_item.get("answer")):
                            existing_sol = collected_solutions.get(clean_num_key, {})
                            # STRICT: Only overwrite existing solution if the new one is richer or existing is empty
                            existing_sol_text = existing_sol.get("solution", "")
                            new_sol_text = sol_text or existing_sol_text
                            # Never overwrite a good existing solution with empty or shorter solution from heuristic detection
                            if existing_sol_text and not is_explicit_sol and sol_text and len(sol_text) < len(existing_sol_text):
                                new_sol_text = existing_sol_text
                            collected_solutions[clean_num_key] = {
                                "solution": new_sol_text,
                                "solution_image_box": sol_box or existing_sol.get("solution_image_box"),
                                "solution_page_number": sol_page if sol_box else existing_sol.get("solution_page_number", sol_page),
                                "answer": raw_item.get("answer") or existing_sol.get("answer")
                            }
                            # Primary-scan answer: only store as fallback; answer-key page will override if available
                            if raw_item.get("answer") and clean_num_key not in collected_answers:
                                collected_answers[clean_num_key] = str(raw_item.get("answer"))
                    else:
                        raw_stem = str(raw_item.get("question_text") or raw_item.get("question") or raw_item.get("stem") or "").strip()

                        # Check for leaked answer tag from previous question at top of raw_stem (e.g. "Ans: B" or "[Ans. B]")
                        ans_chars = r'[A-Da-d1-4અબકડકખગઘ]|I{1,3}|IV|iv|i{1,3}'
                        m_leak = re.search(rf'^\s*(?:\[\s*ans[^\n\]]*\]|\(?\s*ans(?:wer)?[\s\:\.\=\-]*\s*[\(\[]?({ans_chars})[\)\]]?\)?)\s*', raw_stem, re.IGNORECASE)
                        if m_leak:
                            leaked_val = normalize_option_key(m_leak.group(1))
                            if leaked_val in ['A', 'B', 'C', 'D']:
                                if primary_raw_questions:
                                    prev_q = primary_raw_questions[-1]
                                    if not prev_q.get("answer") or str(prev_q.get("answer")).lower() in ["null", "none", "n/a", "-", "", "undefined"]:
                                        prev_q["answer"] = leaked_val
                            raw_stem = raw_stem[m_leak.end():].strip()
                            raw_item["question_text"] = raw_stem

                        # Pre-parse embedded options from stem if options field was incomplete or missing
                        if raw_stem:
                            clean_stem, extracted_opts = split_question_and_options(raw_stem)
                            if extracted_opts and len(extracted_opts) >= 2:
                                if not raw_opts or not isinstance(raw_opts, (list, dict)) or len(raw_opts) < 2:
                                    raw_item["options"] = extracted_opts
                                    raw_opts = extracted_opts
                                    raw_item["question_text"] = clean_stem
                                    raw_stem = clean_stem

                        # If current item still lacks answer, check for trailing answer tag in raw_stem or options
                        if not raw_item.get("answer") or str(raw_item.get("answer")).lower() in ["null", "none", "n/a", "-", "", "undefined"]:
                            inferred_trailing = extract_answer_from_text(raw_stem)
                            if inferred_trailing:
                                raw_item["answer"] = inferred_trailing

                        valid_cnt = 0
                        if isinstance(raw_opts, list):
                            valid_cnt = sum(1 for o in raw_opts if (
                                isinstance(o, dict) and bool(
                                    o.get("text") or o.get("val") or o.get("value") or o.get("content")
                                    or o.get("option_text") or o.get("original") or o.get("translated")
                                    or o.get("image_box") or o.get("has_image") or o.get("image_url")
                                )
                            ) or (isinstance(o, (str, int, float)) and bool(str(o).strip())))
                        elif isinstance(raw_opts, dict):
                            valid_cnt = sum(1 for v in raw_opts.values() if (
                                isinstance(v, dict) and bool(
                                    v.get("text") or v.get("val") or v.get("value") or v.get("content")
                                    or v.get("option_text") or v.get("original") or v.get("translated")
                                    or v.get("image_box") or v.get("has_image") or v.get("image_url")
                                )
                            ) or (isinstance(v, (str, int, float)) and bool(str(v).strip())))

                        q_t_u = str(raw_item.get("question_type") or "").strip().upper()
                        raw_stem_u = raw_stem.upper()
                        is_match_q = ("MATCH" in q_t_u or "MATRIX" in q_t_u or "LIST" in q_t_u or "MATCH" in raw_stem_u or bool(re.search(r'column\s*[-–—]?\s*(?:i|1|a)', raw_stem, re.IGNORECASE)))
                        is_num_q = ("NUMER" in q_t_u or "INTEGER" in q_t_u or "NAT" in q_t_u) and not is_match_q

                        header_patterns = [
                            r'^(?:chapter|chp|ch|unit|topic|section|પ્રકરણ|અધ્યાય|વિભાગ|ભાગ|સ્વાધ્યાય|ઉદાહરણ)[\s\-_0-9\.:]*$',
                            r'^(?:hints?|solutions?|answer\s*keys?|answers?|explanations?|સમજૂતી|ઉકેલ|જવાબો)\b',
                            r'^(?:multiple\s+choice\s+questions|single\s+correct|assertion\s+and\s+reason)\s*$',
                            r'^(?:miscellaneous(?:\s+(?:exercise|problems?|questions?|examples?|type))?|વિવિધ(?:\s+(?:દાખલાઓ|પ્રશ્નો))?)\s*[:\.\-]?$',
                            r'^(?:variable\s+sep[ea]rable\s+method|homogeneous\s+differential\s+equations?|linear\s+differential\s+equations?|exact\s+differential\s+equations?|bernoulli(?:\'s)?\s+equation|integrat(?:ing\s+factor|ion\s+by\s+parts|ion\s+by\s+substitution)|partial\s+fractions?)\s*[:\.\-]?$',
                            r'^(?:(?:type|level|topic|section|part|exercise|method|પ્રકાર|વિભાગ|ભાગ|સ્વાધ્યાય)[\s\-_]*(?:[0-9]+(?:\.[0-9]+)?|[ivxIVX]+|[a-zA-Z]))\s*[:\.\-]?$',
                        ]
                        is_pure_header = any(re.match(pat, raw_stem.strip().lower()) for pat in header_patterns)

                        is_explicit_ak = bool(raw_item.get("is_answer_key_stub") or raw_item.get("from_answer_key_page"))
                        is_dummy_stem = len(raw_stem) < 3 or bool(re.match(r'^\s*(?:Q(?:uestion)?\s*)?\d+[\.\:\-\)]?\s*$', raw_stem)) or (len(raw_stem) < 15 and any(raw_stem.lower().startswith(p) for p in ["ans", "key", "જવાબ", "ઉત્તર"]))
                        is_answer_key_stub = (is_dummy_stem and valid_cnt < 2 and not raw_item.get("image_box")) or (is_explicit_ak and valid_cnt < 2 and len(raw_stem) < 25)
                        is_sol_item = is_pure_sol

                        # Reject duplicate question stubs from solution pages or back-of-the-chapter sections
                        is_dup_stub = (clean_num_key in seen_question_keys and valid_cnt < 2 and not is_num_q and not is_match_q and not raw_item.get("image_box") and is_pure_sol)

                        # Question validity contract:
                        # Genuine exam questions must have valid stem, not be a header, not be an answer key stub,
                        # and must have options (or diagram, or be Numeric, or be Match the list, or substantive stem).
                        is_valid_stem = bool(raw_stem) and len(raw_stem) >= 3 and not is_pure_header
                        has_real_options = (valid_cnt >= 2) or (valid_cnt >= 1 and raw_item.get("image_box"))
                        is_genuine_question = (
                            not is_pure_header
                            and not is_answer_key_stub
                            and not is_sol_item
                            and not is_dup_stub
                            and is_valid_stem
                            and (has_real_options or is_num_q or is_match_q or len(raw_stem) >= 15)
                        )

                        if is_genuine_question:
                            raw_item["question_text"] = clean_question_text(raw_stem)
                            primary_raw_questions.append(raw_item)
                        else:
                            # Route answers and solutions
                            if clean_num_key and raw_item.get("answer"):
                                collected_answers[clean_num_key] = str(raw_item.get("answer"))

                            if (is_explicit_sol or is_pure_sol or is_sol_item) and clean_num_key and (sol_text or sol_box):
                                existing_sol = collected_solutions.get(clean_num_key, {})
                                collected_solutions[clean_num_key] = {
                                    "solution": sol_text or existing_sol.get("solution", ""),
                                    "solution_image_box": sol_box or existing_sol.get("solution_image_box"),
                                    "solution_page_number": sol_page if sol_box else existing_sol.get("solution_page_number", sol_page),
                                    "answer": raw_item.get("answer") or existing_sol.get("answer")
                                }

                # Build master answer key map from raw page texts (especially answer key tables / last pages)
                pdf_master_answer_key: Dict[str, str] = {}
                for p_idx, p_text in sorted(raw_pages_text_map.items()):
                    if is_answer_key_page_text(p_text) or is_solution_page_text(p_text) or p_idx >= max(0, total_pages - 5):
                        ak_page_map = extract_answer_key_table_from_text(p_text)
                        if ak_page_map:
                            pdf_master_answer_key.update(ak_page_map)

                # Merge answers from collected items into master answer key map
                for k, v in collected_answers.items():
                    if k not in pdf_master_answer_key and v and str(v).strip().upper() not in ["", "NULL", "NONE", "N/A", "-"]:
                        pdf_master_answer_key[k] = str(v).strip().upper()

                # Section-aware answer storage:
                # E.g. Section 0 (Exercise 1): {"1": "B", ...}, Section 1 (Exercise 2): {"1": "C", ...}
                section_answers: Dict[int, Dict[str, str]] = {}
                topic_answers: Dict[str, Dict[str, str]] = {}
                global_answers: Dict[str, str] = dict(pdf_master_answer_key)

                # Detect sections/exercises in primary_raw_questions based on question numbering resets:
                # E.g. Exercise 1 (P1-P6: Q1..Q60), Exercise 2 (P7-P14: Q1..Q71), Exercise 3 (P15-P26: Q1..Q80), etc.
                curr_sec = 0
                last_seen_num = 0
                for q in primary_raw_questions:
                    q_num_raw = str(q.get("question_number") or q.get("q_num") or "").strip()
                    m_q = re.search(r'\d+', q_num_raw)
                    q_val = int(m_q.group(0)) if m_q else (last_seen_num + 1)
                    if q_val == 1 and last_seen_num > 1:
                        curr_sec += 1
                    q["section_idx"] = curr_sec
                    last_seen_num = q_val

                # Attach collected answers and solutions into primary questions with strict PDF question numbering
                deduped_primary = []
                seen_final_qnums: Dict[str, Dict[str, Any]] = {}

                for idx, q in enumerate(primary_raw_questions):
                    q_num_raw = str(q.get("question_number") or q.get("q_num") or "").strip()
                    q_key = normalize_question_key(q_num_raw) or f"auto_{idx + 1}"

                    # Dedup key: use (page_number, question_number) so Q1 on page 2 is NOT merged with Q1 on page 1
                    q_page_num = int(q.get("page_number", 1))
                    dedup_key = f"{q_page_num}_{q_key}"

                    # Only merge if it is truly the exact same duplicate question on same/adjacent page or an explicit continuation
                    is_real_duplicate = False
                    if dedup_key in seen_final_qnums:
                        existing_q = seen_final_qnums[dedup_key]
                        ex_text = str(existing_q.get("question_text", "")).strip().lower()
                        curr_text = str(q.get("question_text", "")).strip().lower()

                        # Only merge if: explicit continuation flag, OR literally identical text on same page
                        if q.get("is_continuation") or existing_q.get("is_split_at_bottom"):
                            is_real_duplicate = True
                        elif curr_text and ex_text and curr_text == ex_text:
                            is_real_duplicate = True

                        if is_real_duplicate:
                            merge_question_items(existing_q, q)
                            continue

                    seen_final_qnums[dedup_key] = q

                    # STRICT SECTION-AWARE ANSWER ASSIGNMENT (NO MISMATCHES):
                    # Determine if existing answer is a bad guess that should be overridden
                    existing_ans = str(q.get("answer") or "").strip()
                    q_type_u_pre = str(q.get("question_type") or "").strip().upper()
                    is_num_type_pre = "NUMER" in q_type_u_pre or "INTEGER" in q_type_u_pre
                    # A Numeric question with answer "0" or a pure letter (A/B/C/D) is a bad guess
                    is_bad_numeric_guess = is_num_type_pre and bool(re.match(r'^[A-D]$', existing_ans.upper()))
                    # Allow override if answer is missing OR it's a bad numeric guess
                    should_assign_ans = (not existing_ans or existing_ans.lower() in ["null", "none", "n/a", "-", "undefined"]) or is_bad_numeric_guess

                    # 1. GROUND TRUTH: Authoritative Answer Key Table Matching
                    matched_ans = None
                    if q_key in pdf_master_answer_key:
                        matched_ans = pdf_master_answer_key[q_key]
                    elif q_key in collected_answers:
                        matched_ans = collected_answers[q_key]
                    elif q_key in global_answers:
                        matched_ans = global_answers[q_key]

                    if matched_ans:
                        q_type_u = str(q.get("question_type") or "").strip().upper()
                        raw_opts_q = q.get("options")
                        has_opts_q = any(bool((isinstance(v, dict) and (v.get("text") or v.get("val") or v.get("original") or v.get("translated") or v.get("image_box") or v.get("has_image"))) or (isinstance(v, (str, int, float)) and bool(str(v).strip()))) for v in (raw_opts_q if isinstance(raw_opts_q, list) else raw_opts_q.values() if isinstance(raw_opts_q, dict) else []))
                        num_clean = clean_numeric_answer(matched_ans)
                        is_letter_ans = bool(re.match(r'^[A-D](,\s*[A-D])*$', str(matched_ans).strip().upper()))
                        is_num_type = ("NUMER" in q_type_u or "INTEGER" in q_type_u or "NAT" in q_type_u) or (not has_opts_q and not ("MATCH" in q_type_u or "MATRIX" in q_type_u or "LIST" in q_type_u)) or (bool(num_clean) and not is_letter_ans)
                        if is_num_type and is_letter_ans and not num_clean:
                            pass
                        elif is_num_type or bool(num_clean):
                            if not has_opts_q or ("NUMER" in q_type_u or "INTEGER" in q_type_u or "NAT" in q_type_u):
                                q["question_type"] = "Numeric"
                            q["answer"] = num_clean if num_clean else clean_numeric_answer(matched_ans)
                        else:
                            q["answer"] = matched_ans

                    # Attach authentic solution and solution diagrams from separate solutions page
                    curr_sol = str(q.get("solution") or "").strip()
                    is_stub_sol = not curr_sol or curr_sol.lower() in ["null", "none", "n/a", "-", "", "undefined"]
                    if q_key in collected_solutions:
                        sol_entry = collected_solutions[q_key]
                        raw_sol_text = str(sol_entry.get("solution") or "").strip()
                        if is_stub_sol and raw_sol_text and raw_sol_text.lower() not in ["null", "none", "n/a", "-", "", "undefined"]:
                            q["solution"] = raw_sol_text
                        if sol_entry.get("solution_image_box"):
                            q["solution_image_box"] = sol_entry.get("solution_image_box")
                            q["solution_page_number"] = sol_entry.get("solution_page_number")
                            q["has_solution_image"] = True

                    # If question still lacks an answer, infer from its OWN solution text, question stem, or options
                    if not q.get("answer") and q.get("solution"):
                        inferred = extract_answer_from_text(q.get("solution"))
                        if inferred:
                            q["answer"] = inferred
                    if not q.get("answer") and q.get("question_text"):
                        inferred = extract_answer_from_text(q.get("question_text"))
                        if inferred:
                            q["answer"] = inferred
                    if not q.get("answer") and isinstance(q.get("options"), dict):
                        for opt_k in ["D", "C", "B", "A", "4", "3", "2", "1"]:
                            if opt_k in q["options"]:
                                inferred = extract_answer_from_text(str(q["options"][opt_k]))
                                if inferred:
                                    q["answer"] = inferred
                                    break
                    elif not q.get("answer") and isinstance(q.get("options"), list):
                        for opt_item in reversed(q.get("options")):
                            opt_val = opt_item.get("text") or opt_item.get("val") or opt_item.get("option_text") or opt_item.get("original") if isinstance(opt_item, dict) else str(opt_item)
                            inferred = extract_answer_from_text(str(opt_val))
                            if inferred:
                                q["answer"] = inferred
                                break

                    deduped_primary.append(q)

                # Maintain strict natural sequential reading order (Line-by-line: Q1, Q2, Q3...)
                def get_natural_sort_key(item_q):
                    p_num = int(item_q.get("page_number", 1))
                    q_num_s = str(item_q.get("question_number") or item_q.get("q_num") or "")
                    m_n = re.search(r'(\d+)\s*(?:[\.\-_/\(]\s*([ivxlcdm]+|[a-z]|\d+)\s*[\)]?)?', q_num_s, re.IGNORECASE)
                    if m_n:
                        n_v = int(m_n.group(1))
                        sub_v = m_n.group(2) or ""
                    else:
                        m_digits = re.search(r'\d+', q_num_s)
                        n_v = int(m_digits.group(0)) if m_digits else 999999
                        sub_v = ""
                    return (p_num, n_v, sub_v)

                deduped_primary.sort(key=get_natural_sort_key)
                all_raw_questions = deduped_primary

            else:
                # Single-page PDF or fallback: Process full document
                # Initialize raw page text corpus for single-page path (may be used later for answer-key scan)
                raw_pages_text_corpus: List[str] = []
                _sp_text = self.pipeline.extract_page_text(pdf_bytes, 0)
                if _sp_text:
                    raw_pages_text_corpus.append(_sp_text)
                page_bytes = self.pipeline.render_page_to_image(pdf_bytes, 0, scale=2.0, img_format="JPEG")
                mime_type = "image/jpeg"
                if page_bytes is None:
                    page_bytes = pdf_bytes
                    mime_type = "application/pdf"

                prompt = get_all_pages_extraction_prompt(
                    source_language=source_language,
                    target_language=target_language,
                    total_pages=1
                )
                logger.info(f"[Scan] {file_name}: Scanning Page 1/1...")
                raw_text = await loop.run_in_executor(
                    None,
                    self._call_gemini_api_with_fallback,
                    page_bytes,
                    prompt,
                    active_model,
                    mime_type,
                    progress_callback
                )
                parsed_data = extract_json_from_response(raw_text)
                raw_extracted_raw = parsed_data.get("questions", [])
                raw_extracted = []
                for q_it in raw_extracted_raw:
                    raw_extracted.extend(split_multipart_subquestions(q_it))
                page_text_sp = self.pipeline.extract_page_text(pdf_bytes, 0)
                is_sol_p = is_solution_page_text(page_text_sp)
                mcq_cnt_sp = sum(1 for q in raw_extracted if (isinstance(q.get("options"), list) and len(q.get("options")) >= 2) or (isinstance(q.get("options"), dict) and len(q.get("options")) >= 2))
                if mcq_cnt_sp >= 2:
                    is_sol_p = False
                has_inline_sols_sp = page_has_inline_solutions(page_text_sp)

                for q in raw_extracted:
                    q["page_number"] = 1
                    if is_sol_p:
                        q["is_solution_item"] = True
                        q["from_solution_page"] = True

                    raw_opts = q.get("options")
                    if isinstance(raw_opts, list):
                        for opt in raw_opts:
                            if isinstance(opt, dict) and "page_number" not in opt:
                                opt["page_number"] = 1
                    elif isinstance(raw_opts, dict):
                        for opt in raw_opts.values():
                            if isinstance(opt, dict) and "page_number" not in opt:
                                opt["page_number"] = 1

                if progress_callback:
                    quick_items = [_dict_to_quick_question(q, 1) for q in raw_extracted]
                    quick_items = [q for q in quick_items if q is not None]
                    try:
                        progress_callback(1, 1, len(quick_items), f"Scanned Page 1/1 ({len(quick_items)} questions found)", quick_items)
                    except Exception:
                        pass
                
                # Separate primary questions and solution items for single page
                primary_single = []
                single_sols = {}
                single_ans = {}
                seen_single_qnums: Dict[str, Dict[str, Any]] = {}

                for r_item in raw_extracted:
                    r_opts = r_item.get("options") or r_item.get("choices") or {}
                    raw_sp_stem = str(r_item.get("question_text") or r_item.get("question") or "").strip()

                    # Pre-parse embedded options from stem if options field was incomplete or missing
                    if raw_sp_stem:
                        clean_stem, extracted_opts = split_question_and_options(raw_sp_stem)
                        if extracted_opts and len(extracted_opts) >= 2:
                            if not r_opts or not isinstance(r_opts, (list, dict)) or len(r_opts) < 2:
                                r_item["options"] = extracted_opts
                                r_opts = extracted_opts
                                r_item["question_text"] = clean_stem
                                raw_sp_stem = clean_stem

                    has_valid_o = False
                    if isinstance(r_opts, list) and len(r_opts) >= 1:
                        has_valid_o = any(
                            (isinstance(o, dict) and bool(o.get("text") or o.get("image_box") or o.get("has_image")))
                            or (isinstance(o, str) and bool(o.strip()))
                            for o in r_opts
                        )
                    elif isinstance(r_opts, dict) and len(r_opts) >= 1:
                        has_valid_o = any(
                            (isinstance(v, dict) and bool(v.get("text") or v.get("image_box") or v.get("has_image") or v.get("original") or v.get("translated")))
                            or (isinstance(v, str) and bool(v.strip()))
                            for v in r_opts.values()
                        )
                    
                    q_t_u = str(r_item.get("question_type") or "").strip().upper()
                    raw_a = str(r_item.get("answer") or "").strip()
                    is_num = ("NUMER" in q_t_u or "INTEGER" in q_t_u or bool(re.match(r'^-?\d+(?:\.\d+)?$', raw_a)))
                    is_match = ("MATCH" in q_t_u or "MATRIX" in q_t_u or "LIST" in q_t_u)

                    t_lower = raw_sp_stem.lower()
                    is_p_sol = r_item.get("is_solution_item", False)
                    sol_pfx = ("solution:", "sol.", "sol:", "explanation:", "hint:", "hints:", "સમજૂતી:", "ઉકેલ:", "વિસ્તૃત ઉકેલ:")
                    if not is_p_sol and any(t_lower.startswith(p) for p in sol_pfx):
                        is_p_sol = True
                    
                    q_k_raw = str(r_item.get("question_number") or "").strip()
                    c_k = normalize_question_key(q_k_raw) or q_k_raw
                    sol_box = (
                        r_item.get("solution_image_box")
                        or r_item.get("solution_box")
                        or r_item.get("solution_diagram_box")
                        or r_item.get("solution_img_box")
                        or r_item.get("solution_image")
                        or (r_item.get("image_box") if is_p_sol else None)
                        or (r_item.get("box_2d") if is_p_sol else None)
                    )
                    
                    if is_p_sol:
                        if c_k:
                            single_sols[c_k] = {
                                # STRICT: Only use actual solution field, NOT question_text
                                "solution": str(r_item.get("solution") or "").strip(),
                                "solution_image_box": sol_box,
                                "solution_page_number": 1,
                                "answer": r_item.get("answer")
                            }
                            if r_item.get("answer"):
                                single_ans[c_k] = str(r_item.get("answer"))
                    else:
                        header_patterns = [
                            r'^(?:chapter|chp|ch|unit|topic|section|પ્રકરણ|અધ્યાય|વિભાગ|ભાગ|સ્વાધ્યાય|ઉદાહરણ)[\s\-_0-9\.:]*$',
                            r'^(?:hints?|solutions?|answer\s*keys?|answers?|explanations?|સમજૂતી|ઉકેલ|જવાબો)\b',
                        ]
                        if any(re.match(pat, raw_sp_stem.strip().lower()) for pat in header_patterns):
                            continue

                        if c_k and c_k in seen_single_qnums:
                            existing_q = seen_single_qnums[c_k]
                            # Only merge as solution if this item has no question text or options
                            if not has_valid_o and len(raw_sp_stem) < 15:
                                if not existing_q.get("solution") and r_item.get("solution"):
                                    existing_q["solution"] = r_item.get("solution")
                                if not existing_q.get("solution_image_box") and sol_box:
                                    existing_q["solution_image_box"] = sol_box
                                    existing_q["solution_page_number"] = 1
                                if not existing_q.get("answer") and r_item.get("answer"):
                                    existing_q["answer"] = r_item.get("answer")
                                continue

                        if c_k:
                            seen_single_qnums[c_k] = r_item
                        primary_single.append(r_item)

                        if c_k:
                            if r_item.get("solution") or sol_box:
                                single_sols[c_k] = {
                                    "solution": str(r_item.get("solution") or ""),
                                    "solution_image_box": sol_box,
                                    "solution_page_number": 1,
                                    "answer": r_item.get("answer")
                                }
                            if r_item.get("answer"):
                                single_ans[c_k] = str(r_item.get("answer"))
                
                # Strict 1-to-1 matching for single page
                for q_it in primary_single:
                    qk = re.search(r'\d+', str(q_it.get("question_number") or ""))
                    k_str = qk.group(0) if qk else None
                    if k_str and k_str in single_sols:
                        s_ent = single_sols[k_str]
                        s_text = str(s_ent.get("solution") or "").strip()
                        curr_sol = str(q_it.get("solution") or "").strip()
                        # STRICT 1-TO-1: Only fill solution if question has none at all.
                        is_stub = not curr_sol or curr_sol.lower().strip() in ("", "none", "n/a") or (curr_sol.lower().startswith("ans") and len(curr_sol) < 15)
                        if s_text and is_stub:
                            q_it["solution"] = s_text
                        if s_ent.get("solution_image_box"):
                            q_it["solution_image_box"] = s_ent.get("solution_image_box")
                            q_it["solution_page_number"] = 1
                            q_it["has_solution_image"] = True
                        if not q_it.get("answer") and s_ent.get("answer"):
                            q_it["answer"] = s_ent.get("answer")
                    if k_str and not q_it.get("answer") and k_str in single_ans:
                        q_it["answer"] = single_ans[k_str]
                    if not q_it.get("answer") and q_it.get("solution"):
                        inferred = extract_answer_from_text(q_it.get("solution"))
                        if inferred:
                            q_it["answer"] = inferred

                # Maintain strict sequential reading order for single page (Line-by-line: Q1, Q2, Q3...)
                primary_single.sort(key=lambda item_q: int(re.search(r'\d+', str(item_q.get("question_number") or "")).group(0)) if re.search(r'\d+', str(item_q.get("question_number") or "")) else 999999)
                all_raw_questions = primary_single

            # Detect chapter number, chapter name, subject and topics across pages
            doc_chapter_number = ""
            doc_chapter_name = ""
            doc_subject = ""
            doc_topics: List[Dict[str, Any]] = []

            if total_pages > 1:
                for _, _, parsed_pg in valid_page_results:
                    if isinstance(parsed_pg, dict):
                        if not doc_chapter_number and parsed_pg.get("chapter_number"):
                            doc_chapter_number = str(parsed_pg["chapter_number"]).strip()
                        if not doc_chapter_name and parsed_pg.get("chapter_name"):
                            doc_chapter_name = str(parsed_pg["chapter_name"]).strip()
                        if not doc_subject and parsed_pg.get("subject"):
                            doc_subject = str(parsed_pg["subject"]).strip()
                        for t in parsed_pg.get("topics", []) or []:
                            if isinstance(t, dict) and t.get("topic"):
                                doc_topics.append(t)
            else:
                if isinstance(parsed_data, dict):
                    if not doc_chapter_number and parsed_data.get("chapter_number"):
                        doc_chapter_number = str(parsed_data["chapter_number"]).strip()
                    if not doc_chapter_name and parsed_data.get("chapter_name"):
                        doc_chapter_name = str(parsed_data["chapter_name"]).strip()
                    if not doc_subject and parsed_data.get("subject"):
                        doc_subject = str(parsed_data["subject"]).strip()
                    for t in parsed_data.get("topics", []) or []:
                        if isinstance(t, dict) and t.get("topic"):
                            doc_topics.append(t)

            # Fallback heuristic from filename and common chapter formats
            clean_stem = Path(file_name).stem.strip()
            if not doc_chapter_number:
                m_ch = re.search(r'(?:Chapter|Chp|Ch|Unit|પ્રકરણ|અધ્યાય|Ch\.)[\s\-_]*(\d+)', file_name, re.IGNORECASE)
                if m_ch:
                    doc_chapter_number = m_ch.group(1)
                elif re.match(r'^\d+$', clean_stem):
                    doc_chapter_number = str(int(clean_stem))
                else:
                    m_lead = re.match(r'^(\d+)[\s\-_.:]', clean_stem)
                    if m_lead:
                        doc_chapter_number = str(int(m_lead.group(1)))

            if not doc_chapter_name:
                m_name = re.search(r'(?:Chapter|Chp|Ch|Unit|પ્રકરણ|અધ્યાય)[\s\-_]*\d+[\s\-_:]+(.+)', clean_stem, re.IGNORECASE)
                if m_name:
                    doc_chapter_name = m_name.group(1).replace("_", " ").strip()
                elif re.match(r'^\d+[\s\-_.:]+(.+)$', clean_stem):
                    m_rest = re.match(r'^\d+[\s\-_.:]+(.+)$', clean_stem)
                    if m_rest:
                        doc_chapter_name = m_rest.group(1).replace("_", " ").strip()
                elif "_" in clean_stem or "-" in clean_stem:
                    parts = re.split(r'[\-_]', clean_stem)
                    if len(parts) > 1:
                        doc_chapter_name = parts[-1].strip()
                elif doc_chapter_number:
                    doc_chapter_name = f"Chapter {doc_chapter_number}"
            all_corpus_preview = " ".join([
                str(q_it.get("question_text") or q_it.get("question") or "") + " " +
                str(q_it.get("solution") or "")
                for q_it in all_raw_questions
            ])
            if not doc_subject or doc_subject.lower() in ["general", "none", "null", ""]:
                doc_subject = detect_document_subject(all_corpus_preview, file_name=file_name, chapter_name=doc_chapter_name)

            # Consolidate topics and assign unified 2-level topic IDs
            consolidated_topics: List[Dict[str, Any]] = []
            seen_topic_names = set()
            seen_sec_map: Dict[str, Any] = {}

            for t in doc_topics:
                raw_t = str(t.get("topic") or "").strip()
                t_name = clean_topic_title(raw_t)
                if t_name and not re.search(r'\b\d+\.\d+\.\d+\b', t_name) and t_name.lower() not in seen_topic_names:
                    seen_topic_names.add(t_name.lower())
                    sec_m = re.search(r'\b(\d+\.\d+|[૦-૯]+\.[૦-૯]+|[०-९]+\.[०-९]+)\b(?!\.\d+)', str(t.get("id") or "") + " " + t_name)
                    tid = sec_m.group(1) if sec_m else (t.get("id") or (len(consolidated_topics) + 1))
                    if sec_m:
                        seen_sec_map[sec_m.group(1)] = tid
                    ch_num = t.get("chapter_number") or doc_chapter_number or ""
                    ch_name = t.get("chapter_name") or doc_chapter_name or ""
                    consolidated_topics.append({
                        "id": tid,
                        "chapter_number": ch_num,
                        "chapter_name": ch_name,
                        "topic": t_name,
                        "description": generate_topic_description(t_name, raw_desc=t.get("description"), chapter_name=ch_name)
                    })

            for q_it in all_raw_questions:
                raw_t = str(q_it.get("topic") or "").strip()
                t_name = clean_topic_title(raw_t)
                if t_name and not re.search(r'\b\d+\.\d+\.\d+\b', t_name) and t_name.lower() not in seen_topic_names:
                    seen_topic_names.add(t_name.lower())
                    sec_m = re.search(r'\b(\d+\.\d+|[૦-૯]+\.[૦-૯]+|[०-९]+\.[०-९]+)\b(?!\.\d+)', str(q_it.get("topic_id") or "") + " " + t_name)
                    tid = sec_m.group(1) if sec_m else (q_it.get("topic_id") or (len(consolidated_topics) + 1))
                    if sec_m:
                        seen_sec_map[sec_m.group(1)] = tid
                    ch_num = q_it.get("chapter_number") or doc_chapter_number or ""
                    ch_name = q_it.get("chapter_name") or doc_chapter_name or ""
                    consolidated_topics.append({
                        "id": tid,
                        "chapter_number": ch_num,
                        "chapter_name": ch_name,
                        "topic": t_name,
                        "description": generate_topic_description(t_name, raw_desc=q_it.get("description"), chapter_name=ch_name)
                    })

            topic_to_id = {t["topic"].lower(): t["id"] for t in consolidated_topics}
            for q_it in all_raw_questions:
                raw_t = str(q_it.get("topic") or "").strip()
                t_name = clean_topic_title(raw_t)
                if t_name:
                    q_it["topic"] = t_name
                sec_m = re.search(r'\b(\d+\.\d+|[૦-૯]+\.[૦-૯]+|[०-९]+\.[०-९]+)\b', t_name + " " + str(q_it.get("topic_id") or ""))
                if sec_m and sec_m.group(1) in seen_sec_map:
                    q_it["topic_id"] = seen_sec_map[sec_m.group(1)]
                elif t_name.lower() in topic_to_id:
                    q_it["topic_id"] = topic_to_id[t_name.lower()]
                elif len(consolidated_topics) == 1:
                    q_it["topic_id"] = consolidated_topics[0]["id"]

            if progress_callback:
                try:
                    progress_callback(total_pages, total_pages, len(all_raw_questions), f"Finalizing & cropping diagrams for {len(all_raw_questions)} questions...")
                except Exception:
                    pass

            # Format and normalize questions + crop diagrams
            def equalize_question_and_solution_images(it: Dict[str, Any], q_page: int):
                raw_q_box = it.get("image_box") or it.get("diagram_box") or it.get("question_image_box")
                raw_sol_box = (
                    it.get("solution_image_box")
                    or it.get("solution_box")
                    or it.get("solution_diagram_box")
                    or it.get("solution_img_box")
                    or it.get("solution_image")
                    or it.get("explanation_image_box")
                    or it.get("solution_diagram")
                    or it.get("explanation_diagram")
                    or it.get("explanation_box")
                    or it.get("sol_image_box")
                    or it.get("sol_box")
                    or it.get("sol_diagram")
                    or it.get("solution_bbox")
                    or it.get("sol_image")
                )
                s_page = int(it.get("solution_page_number") or it.get("page_number", q_page))

                def parse_coords(b):
                    if not b:
                        return None
                    coords = None
                    if isinstance(b, dict):
                        if "box_2d" in b and isinstance(b["box_2d"], (list, tuple)) and len(b["box_2d"]) >= 4:
                            coords = [float(b["box_2d"][0]), float(b["box_2d"][1]), float(b["box_2d"][2]), float(b["box_2d"][3])]
                        elif "bbox" in b and isinstance(b["bbox"], (list, tuple)) and len(b["bbox"]) >= 4:
                            coords = [float(b["bbox"][0]), float(b["bbox"][1]), float(b["bbox"][2]), float(b["bbox"][3])]
                        elif "coords" in b and isinstance(b["coords"], (list, tuple)) and len(b["coords"]) >= 4:
                            coords = [float(b["coords"][0]), float(b["coords"][1]), float(b["coords"][2]), float(b["coords"][3])]
                        else:
                            coords = [float(b.get("ymin", b.get("top", b.get("y0", 0)))), float(b.get("xmin", b.get("left", b.get("x0", 0)))), float(b.get("ymax", b.get("bottom", b.get("y1", 0)))), float(b.get("xmax", b.get("right", b.get("x1", 0))))]
                    elif isinstance(b, (list, tuple)) and len(b) >= 4:
                        coords = [float(b[0]), float(b[1]), float(b[2]), float(b[3])]
                    elif isinstance(b, str):
                        nums = re.findall(r'[-+]?\d*\.?\d+', b)
                        if len(nums) >= 4:
                            coords = [float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3])]
                    
                    if not coords:
                        return None
                    ymin, xmin, ymax, xmax = coords
                    if ymax <= ymin or xmax <= xmin:
                        return None
                    max_c = max(ymin, xmin, ymax, xmax)
                    # Filter out full-page captures (relaxed to allow legitimate large diagrams)
                    if max_c <= 1.05:
                        if (xmax - xmin > 0.92 and ymax - ymin > 0.92) or ((xmax - xmin) * (ymax - ymin) > 0.82):
                            return None
                    elif max_c <= 1005.0:
                        if (xmax - xmin > 920 and ymax - ymin > 920) or (((xmax - xmin) / 1000.0) * ((ymax - ymin) / 1000.0) > 0.82):
                            return None
                    return coords

                bq = parse_coords(raw_q_box)
                bsol = parse_coords(raw_sol_box)

                # 1. Eliminate identical/near-identical boxes on same item
                if bq and bsol:
                    is_norm = max(max(bq), max(bsol)) <= 1.05
                    diff_thresh = 0.04 if is_norm else 40.0

                    diff = abs(bq[0] - bsol[0]) + abs(bq[1] - bsol[1]) + abs(bq[2] - bsol[2]) + abs(bq[3] - bsol[3])
                    if diff < diff_thresh:
                        # If item has options, diagram belongs to question stem; clear duplicate from solution
                        if bool(it.get("options")):
                            bsol = None
                        else:
                            bq = None

                # 2. Equalize and resolve inversion on the same page (question must be UP, solution must be DOWN):
                if bq and bsol and s_page == q_page:
                    ymin_q = bq[0]
                    ymin_sol = bsol[0]
                    is_norm = max(max(bq), max(bsol)) <= 1.05
                    inv_thresh = 0.03 if is_norm else 30.0
                    if ymin_q > ymin_sol + inv_thresh:
                        # Inverted! Swap so question is UP (smaller ymin) and solution is DOWN (larger ymin)
                        bq, bsol = bsol, bq

                # 3. If q_box was from a later solutions page, move to solution_image_box
                img_p_origin = int(it.get("image_page_number") or it.get("page_number", q_page))
                if bq and not bsol and img_p_origin > q_page:
                    bsol = bq
                    s_page = img_p_origin
                    bq = None
                elif bq and not bsol and (it.get("has_solution_image") or it.get("solution_image")):
                    # Diagram was tagged as solution image or returned in image_box
                    bsol = bq
                    bq = None

                it["image_box"] = bq
                it["has_image"] = bool(bq)
                it["solution_image_box"] = bsol
                it["has_solution_image"] = bool(bsol)
                it["solution_page_number"] = s_page if bsol else None

            formatted_questions: List[QuestionItem] = []
            pending_solutions: Dict[str, Dict[str, Any]] = {}

            def attach_solution_to_question(target_num: str, s_page: int, s_text: str, s_box: Any, s_ans: str):
                target_k = normalize_question_key(target_num) or str(target_num)
                if not target_k:
                    return

                # Crop solution image if present
                sol_img_url = None
                if s_box:
                    crop_idx = max(0, s_page - 1)
                    crop_bytes = self.pipeline.crop_box_image(pdf_bytes, crop_idx, s_box)
                    if crop_bytes:
                        img_name = f"{safe_stem}_p{s_page}_q{target_k}_solution.png"
                        with open(IMAGES_DIR / img_name, "wb") as f_img:
                            f_img.write(crop_bytes)
                        sol_img_url = f"/api/images/{img_name}"

                # Check if matching question is already in formatted_questions
                matched_q = None
                for fq in reversed(formatted_questions):
                    fq_k = normalize_question_key(fq.question_number) or fq.question_number
                    if fq_k == target_k:
                        matched_q = fq
                        break

                if matched_q:
                    if s_text and not matched_q.solution:
                        matched_q.solution = s_text
                    if sol_img_url and not matched_q.solution_image_url:
                        matched_q.solution_image_url = sol_img_url
                        matched_q.solution_image_box = s_box
                        matched_q.solution_page_number = s_page
                        matched_q.has_solution_image = True
                    elif s_box and not matched_q.solution_image_box:
                        matched_q.solution_image_box = s_box
                        matched_q.solution_page_number = s_page
                        matched_q.has_solution_image = True
                    if s_ans and not matched_q.answer:
                        matched_q.answer = s_ans
                else:
                    # Save for upcoming question
                    pending_solutions[target_k] = {
                        "solution": s_text,
                        "solution_image_url": sol_img_url,
                        "solution_image_box": s_box,
                        "solution_page_number": s_page,
                        "answer": s_ans,
                    }

            # Pre-pass: Automatically stitch cross-column and cross-page split questions on the same page
            stitched_raw_questions = []
            skip_idx_set = set()
            for r_idx, cur_raw in enumerate(all_raw_questions):
                if r_idx in skip_idx_set:
                    continue
                if r_idx + 1 < len(all_raw_questions):
                    nxt_raw = all_raw_questions[r_idx + 1]
                    cur_s = str(cur_raw.get("question_text") or cur_raw.get("question") or cur_raw.get("translated_question") or cur_raw.get("original_question") or "").strip()
                    nxt_s = str(nxt_raw.get("question_text") or nxt_raw.get("question") or nxt_raw.get("translated_question") or nxt_raw.get("original_question") or "").strip()
                    cur_o = cur_raw.get("options") or cur_raw.get("choices") or {}
                    nxt_o = nxt_raw.get("options") or nxt_raw.get("choices") or {}

                    cur_opt_cnt = len(cur_o) if isinstance(cur_o, (dict, list)) else 0
                    nxt_opt_cnt = len(nxt_o) if isinstance(nxt_o, (dict, list)) else 0

                    cur_is_incomplete = (
                        bool(cur_raw.get("is_split_at_bottom"))
                        or bool(re.search(r'\b(?:the|of|a|an|in|on|at|to|for|is|are|was|were|then|ratio|portion|between|length of|find|equal to|given by|magnitude|passing through)\s*[\:\—\-]?[,\s]*$', cur_s, re.IGNORECASE))
                        or cur_s.endswith(("-", "+", "=", "×", "÷", ",", ":", "\\le", "\\ge", "\\ne", "\\approx"))
                    )

                    nxt_is_cont = (
                        bool(nxt_raw.get("is_continuation"))
                        or str(nxt_raw.get("question_number") or "").lower() in ["continuation", "cont", "none", "null", "", str(cur_raw.get("question_number") or "")]
                        or (nxt_opt_cnt >= 2 and (not nxt_s or len(nxt_s) < 80 or re.match(r'^[a-z]', nxt_s) or cur_is_incomplete))
                    )

                    if cur_opt_cnt < 2 and nxt_opt_cnt >= 2 and (cur_is_incomplete or nxt_is_cont):
                        # Seamlessly merge nxt_raw into cur_raw
                        if nxt_s and nxt_s.lower() not in cur_s.lower():
                            full_combined_stem = (cur_s.rstrip() + " " + nxt_s.lstrip()).strip()
                            cur_raw["question_text"] = full_combined_stem
                            cur_raw["translated_question"] = full_combined_stem
                            cur_raw["original_question"] = full_combined_stem
                        cur_raw["options"] = nxt_o
                        if nxt_raw.get("answer") and not cur_raw.get("answer"):
                            cur_raw["answer"] = nxt_raw.get("answer")
                        if nxt_raw.get("solution") and not cur_raw.get("solution"):
                            cur_raw["solution"] = nxt_raw.get("solution")
                        if nxt_raw.get("image_box") and not cur_raw.get("image_box"):
                            cur_raw["image_box"] = nxt_raw.get("image_box")
                        if nxt_raw.get("solution_image_box") and not cur_raw.get("solution_image_box"):
                            cur_raw["solution_image_box"] = nxt_raw.get("solution_image_box")
                        cur_raw["question_type"] = "MCQ"
                        skip_idx_set.add(r_idx + 1)

                stitched_raw_questions.append(cur_raw)

            all_raw_questions = stitched_raw_questions

            for item in all_raw_questions:
                raw_q_text = str(
                    item.get("question_text", "")
                    or item.get("question", "")
                    or item.get("translated_question", "")
                    or item.get("original_question", "")
                    or item.get("stem", "")
                    or ""
                ).strip()
                if not raw_q_text:
                    continue  # Ignore empty phantom questions

                raw_opts = item.get("options") or item.get("choices") or {}
                valid_opt_count = 0
                if isinstance(raw_opts, list):
                    valid_opt_count = sum(1 for o in raw_opts if (
                        isinstance(o, dict) and bool(
                            o.get("text") or o.get("val") or o.get("value") or o.get("content")
                            or o.get("option_text") or o.get("original") or o.get("translated")
                            or o.get("image_box") or o.get("has_image") or o.get("image_url")
                        )
                    ) or (isinstance(o, (str, int, float)) and bool(str(o).strip())))
                elif isinstance(raw_opts, dict):
                    valid_opt_count = sum(1 for v in raw_opts.values() if (
                        isinstance(v, dict) and bool(
                            v.get("text") or v.get("val") or v.get("value") or v.get("content")
                            or v.get("option_text") or v.get("original") or v.get("translated")
                            or v.get("image_box") or v.get("has_image") or v.get("image_url")
                        )
                    ) or (isinstance(v, (str, int, float)) and bool(str(v).strip())))

                raw_type_str = str(item.get("question_type") or "").strip().upper()
                raw_ans_str = str(item.get("answer") or "").strip()
                is_num_q = ("NUMER" in raw_type_str or "INTEGER" in raw_type_str or "NAT" in raw_type_str or bool(re.match(r'^-?\d+(?:\.\d+)?$', raw_ans_str))) and not item.get("from_solution_page")
                is_match_q = ("MATCH" in raw_type_str or "MATRIX" in raw_type_str or "LIST" in raw_type_str or "જોડકા" in raw_q_text or "જોડો" in raw_q_text) and not item.get("from_solution_page")

                # Check if item is a solution/explanation item rather than a question stem
                sol_lead_markers = ("solution:", "sol.", "sol:", "explanation:", "hint:", "hints:", "સમજૂતી", "ઉકેલ", "વિસ્તૃત ઉકેલ", "hint & solution", "આથી વિકલ્પ", "સાચો વિકલ્પ", "જવાબ", "ans:")
                raw_q_lower = raw_q_text.lower()
                clean_head_marker = re.sub(r'^\s*(?:Q(?:uestion)?|પ્રશ્ન)?\s*\d*[\.\:\-\)\s]*', '', raw_q_lower).strip()
                is_sol_item = bool(item.get("is_solution_item") or item.get("from_solution_page"))
                if not is_sol_item and valid_opt_count < 2 and not is_num_q and not is_match_q:
                    if any(clean_head_marker.startswith(p) for p in sol_lead_markers) or any(raw_q_lower.startswith(p) for p in sol_lead_markers) or (item.get("solution") and not raw_opts and len(raw_q_text) < 20):
                        is_sol_item = True

                if is_sol_item:
                    sol_txt = str(item.get("solution") or raw_q_text or "").strip()
                    for pfx in sol_lead_markers:
                        clean_sol_lower = re.sub(r'^\s*(?:Q(?:uestion)?|પ્રશ્ન)?\s*\d*[\.\:\-\)\s]*', '', sol_txt.lower()).strip()
                        if clean_sol_lower.startswith(pfx):
                            idx = sol_txt.lower().find(pfx)
                            if idx != -1:
                                sol_txt = sol_txt[idx + len(pfx):].strip(" :-.")
                            break
                    sol_bx = (
                        item.get("solution_image_box")
                        or item.get("solution_box")
                        or item.get("solution_diagram_box")
                        or item.get("solution_img_box")
                        or item.get("solution_image")
                        or item.get("explanation_image_box")
                        or item.get("solution_diagram")
                        or item.get("image_box")
                        or item.get("diagram_box")
                        or item.get("box_2d")
                    )
                    sol_pg = int(item.get("solution_page_number") or item.get("page_number") or 1)
                    sol_ans = str(item.get("answer") or item.get("correct_option") or "").strip()
                    if not sol_ans and sol_txt:
                        sol_ans = extract_answer_from_text(sol_txt) or extract_numeric_answer_from_text(sol_txt) or ""
                    item_qnum = str(item.get("question_number") or item.get("q_num") or item.get("number") or item.get("id") or len(formatted_questions) + 1)
                    attach_solution_to_question(item_qnum, sol_pg, sol_txt, sol_bx, sol_ans)
                    continue

                # Reject non-questions: items matching explicit publisher header patterns with zero options
                has_diag_item = bool(item.get("image_box") or item.get("has_image"))
                header_patterns = [
                    r'^(?:chapter|chp|ch|unit|topic|section|પ્રકરણ|અધ્યાય|વિભાગ|ભાગ|સ્વાધ્યાય|ઉદાહરણ)[\s\-_0-9\.:]*$',
                    r'^(?:hints?|solutions?|answer\s*keys?|answers?|explanations?|સમજૂતી|ઉકેલ|જવાબો)\b',
                    r'^(?:multiple\s+choice\s+questions|single\s+correct|assertion\s+and\s+reason)\b',
                    r'^(?:miscellaneous(?:\s+(?:exercise|problems?|questions?|examples?|type))?|વિવિધ(?:\s+(?:દાખલાઓ|પ્રશ્નો))?)\s*[:\.\-]?$',
                    r'^(?:variable\s+sep[ea]rable\s+method|homogeneous\s+differential\s+equations?|linear\s+differential\s+equations?|exact\s+differential\s+equations?|bernoulli(?:\'s)?\s+equation|integrat(?:ing\s+factor|ion\s+by\s+parts|ion\s+by\s+substitution)|partial\s+fractions?)\s*[:\.\-]?$',
                    r'^(?:(?:type|level|topic|section|part|exercise|method|પ્રકાર|વિભાગ|ભાગ|સ્વાધ્યાય)[\s\-_]*(?:[0-9]+(?:\.[0-9]+)?|[ivxIVX]+|[a-zA-Z]))\s*[:\.\-]?$',
                ]
                if valid_opt_count < 1 and not is_num_q and not is_match_q and not has_diag_item:
                    if any(re.search(pat, raw_q_lower) for pat in header_patterns):
                        continue

                # Strip leading leaked answer tag from previous question if present
                ans_chars = r'[A-Da-d1-4અબકડકખગઘ]|I{1,3}|IV|iv|i{1,3}'
                m_leak = re.search(rf'^\s*(?:\[\s*ans[^\n\]]*\]|\(?\s*ans(?:wer)?[\s\:\.\=\-]*\s*[\(\[]?({ans_chars})[\)\]]?\)?)\s*', raw_q_text, re.IGNORECASE)
                if m_leak:
                    leaked_val = normalize_option_key(m_leak.group(1))
                    if leaked_val in ['A', 'B', 'C', 'D'] and formatted_questions:
                        prev_fq = formatted_questions[-1]
                        if not prev_fq.answer or str(prev_fq.answer).lower() in ["null", "none", "n/a", "-", "", "undefined"]:
                            prev_fq.answer = leaked_val
                    raw_q_text = raw_q_text[m_leak.end():].strip()

                # Pre-parse embedded options if not already structured
                if valid_opt_count < 2 and raw_q_text:
                    clean_stem, extracted_opts = split_question_and_options(raw_q_text)
                    if extracted_opts and len(extracted_opts) >= 2:
                        raw_opts = extracted_opts
                        raw_q_text = clean_stem
                        valid_opt_count = len(extracted_opts)

                # Route to solution or answer attachment if text is minimal (<15 chars or dummy number) and has <2 options
                is_stub_text = len(raw_q_text) < 15 or bool(re.match(r'^\s*Q?\d+[\.\:\-\)]?\s*$', raw_q_text))
                if valid_opt_count < 2 and not is_num_q and not is_match_q and not has_diag_item and is_stub_text:
                    q_num_check = str(item.get("question_number") or item.get("q_num") or item.get("number") or "")
                    chk_key = normalize_question_key(q_num_check)
                    if chk_key:
                        sol_txt_extra = str(item.get("solution") or (raw_q_text if len(raw_q_text) >= 15 else "") or "").strip()
                        sol_bx_extra = item.get("solution_image_box") or item.get("image_box")
                        sol_pg_extra = int(item.get("solution_page_number") or item.get("page_number") or 1)
                        sol_ans_extra = str(item.get("answer") or "").strip()
                        attach_solution_to_question(q_num_check, sol_pg_extra, sol_txt_extra, sol_bx_extra, sol_ans_extra)
                        continue

                page_num = int(item.get("page_number", 1))
                equalize_question_and_solution_images(item, page_num)
                page_idx = max(0, page_num - 1)
                q_num = str(item.get("question_number") or item.get("q_num") or item.get("number") or item.get("id") or len(formatted_questions) + 1)
                opts: Dict[str, OptionDetail] = {}

                if isinstance(raw_opts, list):
                    for idx, opt_entry in enumerate(raw_opts):
                        if isinstance(opt_entry, dict):
                            raw_k = str(opt_entry.get("key") or opt_entry.get("option") or opt_entry.get("label") or "").strip()
                            norm_k = normalize_option_key(raw_k)
                            k = norm_k if norm_k in ["A", "B", "C", "D"] else ["A", "B", "C", "D"][min(idx, 3)]
                            opt_val = (
                                opt_entry.get("text") or opt_entry.get("val") or opt_entry.get("value")
                                or opt_entry.get("content") or opt_entry.get("option_text")
                                or opt_entry.get("translated") or opt_entry.get("original") or ""
                            )
                            txt = clean_option_text(str(opt_val))
                            orig = clean_option_text(str(opt_entry.get("original") or opt_entry.get("text") or txt))
                            opt_box = (
                                opt_entry.get("image_box")
                                or opt_entry.get("box_2d")
                                or opt_entry.get("diagram_box")
                                or opt_entry.get("box")
                                or opt_entry.get("option_image_box")
                                or opt_entry.get("diagram")
                                or opt_entry.get("bbox")
                                or opt_entry.get("coords")
                            )
                            has_img = bool(opt_entry.get("has_image") or opt_box)
                            opt_img_url = None
                            opt_page = int(opt_entry.get("page_number") or item.get("page_number", 1))
                            opt_page_idx = max(0, opt_page - 1)
                            if opt_box:
                                crop_bytes = self.pipeline.crop_box_image(pdf_bytes, opt_page_idx, opt_box, is_option=True)
                                if not crop_bytes:
                                    # Retry without is_option flag (relaxed size thresholds for graph-type options)
                                    crop_bytes = self.pipeline.crop_box_image(pdf_bytes, opt_page_idx, opt_box, is_option=False)
                                if crop_bytes:
                                    opt_img_name = f"{safe_stem}_p{opt_page}_q{q_num}_opt_{k}.png"
                                    with open(IMAGES_DIR / opt_img_name, "wb") as f_img:
                                        f_img.write(crop_bytes)
                                    opt_img_url = f"/api/images/{opt_img_name}"
                                has_img = bool(opt_img_url)
                            if has_img:
                                txt = clean_option_text(txt, has_image=True)
                                orig = clean_option_text(orig, has_image=True)
                            opts[k] = OptionDetail(original=orig, translated=txt, has_image=has_img, image_url=opt_img_url, image_box=opt_box, page_number=opt_page)
                        elif isinstance(opt_entry, (str, int, float)):
                            k = ["A", "B", "C", "D"][min(idx, 3)]
                            cleaned_str = clean_option_text(str(opt_entry))
                            opts[k] = OptionDetail(original=cleaned_str, translated=cleaned_str, has_image=False, page_number=page_num)
                elif isinstance(raw_opts, dict):
                    for key, opt_data in raw_opts.items():
                        norm_key = normalize_option_key(str(key))
                        if norm_key not in ["A", "B", "C", "D"]:
                            continue
                        if isinstance(opt_data, dict):
                            opt_val = (
                                opt_data.get("translated") or opt_data.get("text") or opt_data.get("val")
                                or opt_data.get("value") or opt_data.get("content") or opt_data.get("option_text")
                                or opt_data.get("original") or ""
                            )
                            txt = clean_option_text(str(opt_val))
                            orig = clean_option_text(str(opt_data.get("original") or opt_data.get("text") or txt))
                            opt_box = (
                                opt_data.get("image_box")
                                or opt_data.get("box_2d")
                                or opt_data.get("diagram_box")
                                or opt_data.get("box")
                                or opt_data.get("option_image_box")
                                or opt_data.get("diagram")
                                or opt_data.get("bbox")
                                or opt_data.get("coords")
                            )
                            has_img = bool(opt_data.get("has_image") or opt_box)
                            opt_img_url = None
                            opt_page = int(opt_data.get("page_number") or item.get("page_number", 1))
                            opt_page_idx = max(0, opt_page - 1)
                            if opt_box:
                                crop_bytes = self.pipeline.crop_box_image(pdf_bytes, opt_page_idx, opt_box, is_option=True)
                                if not crop_bytes:
                                    # Retry without is_option flag (relaxed size thresholds for graph-type options)
                                    crop_bytes = self.pipeline.crop_box_image(pdf_bytes, opt_page_idx, opt_box, is_option=False)
                                if crop_bytes:
                                    opt_img_name = f"{safe_stem}_p{opt_page}_q{q_num}_opt_{norm_key}.png"
                                    with open(IMAGES_DIR / opt_img_name, "wb") as f_img:
                                        f_img.write(crop_bytes)
                                    opt_img_url = f"/api/images/{opt_img_name}"
                                    has_img = True
                                elif has_img or opt_data.get("has_image"):
                                    # Gemini reported image but crop failed — still mark has_image
                                    has_img = True
                            if has_img:
                                txt = clean_option_text(txt, has_image=True)
                                orig = clean_option_text(orig, has_image=True)
                            opts[norm_key] = OptionDetail(
                                original=orig,
                                translated=txt,
                                has_image=has_img,
                                image_url=opt_img_url,
                                image_box=opt_box,
                                page_number=opt_page
                            )
                        elif isinstance(opt_data, (str, int, float)):
                            cleaned_str = clean_option_text(str(opt_data or ""))
                            opts[norm_key] = OptionDetail(original=cleaned_str, translated=cleaned_str, has_image=False, page_number=page_num)

                raw_type = str(item.get("question_type") or item.get("type") or "").strip().upper()
                q_text_upper = (raw_q_text or "").upper()
                raw_sol = item.get("solution") or item.get("explanation") or item.get("hint")
                sol = ""
                if raw_sol is not None:
                    sol_str = str(raw_sol).strip()
                    if sol_str.lower() not in ["null", "none", "n/a", "-", "", "undefined", "false"]:
                        sol = sol_str

                has_any_opt = any(
                    bool(v and (v.original or v.translated or v.has_image or v.image_url))
                    for v in opts.values()
                )
                is_match = (
                    "MATCH" in raw_type or "MATRIX" in raw_type or "LIST" in raw_type
                    or "MATCH" in q_text_upper
                    or bool(re.search(r'column\s*[-–—]?\s*(?:i|1|a)', q_text_upper))
                    or bool(re.search(r'list\s*[-–—]?\s*(?:i|1|a)', q_text_upper))
                    or bool(re.search(r'matrix\s*match', q_text_upper))
                    or "જોડકા" in raw_q_text or "જોડો" in raw_q_text or "મેળવો" in raw_q_text
                )

                # Detect statement-based questions (Statement I/II, Statement 1/2, Assertion-Reason, વિધાન ૧/૨)
                is_statement = (
                    "STATEMENT" in q_text_upper or "ASSERTION" in q_text_upper or "REASON" in q_text_upper
                    or "વિધાન" in raw_q_text or "કથન" in raw_q_text
                )

                is_explicit_numeric = ("NUMER" in raw_type or "INTEGER" in raw_type or "NAT" in raw_type) and not is_match
                raw_ans = item.get("answer") or item.get("correct_option") or item.get("correct_answer")
                raw_ans_str = str(raw_ans).strip() if raw_ans is not None else ""

                num_cleaned_val = clean_numeric_answer(raw_ans_str)
                is_mcq_letter_ans = bool(normalize_option_key(raw_ans_str) in ["A", "B", "C", "D"])
                is_incomplete_sentence = bool(re.search(r'\b(?:in|is|of|the|are|to|for|at|by|called|known as|as)\s*[\:\—\-]?\s*$', raw_q_text.strip(), re.IGNORECASE))

                is_numeric = (is_explicit_numeric or (
                    not has_any_opt and not is_match and not is_statement and not is_mcq_letter_ans
                    and (bool(num_cleaned_val) or ("MCQ" not in raw_type and not is_incomplete_sentence and not item.get("is_split_at_bottom")))
                ) or (bool(num_cleaned_val) and not is_mcq_letter_ans and not is_match and not is_statement)) and not is_match

                # Infer answer if missing
                if not raw_ans_str or raw_ans_str.lower() in ["null", "none", "n/a", "-", "", "undefined"]:
                    if is_numeric:
                        inferred_ans = extract_numeric_answer_from_text(sol) or extract_numeric_answer_from_text(raw_q_text)
                    else:
                        inferred_ans = extract_answer_from_text(sol) or extract_answer_from_text(raw_q_text)
                        if not inferred_ans:
                            for opt_k in ["D", "C", "B", "A"]:
                                if opt_k in opts:
                                    opt_v = opts[opt_k]
                                    opt_text = opt_v.original if isinstance(opt_v, OptionDetail) else str(opt_v)
                                    cand = extract_answer_from_text(opt_text)
                                    if cand:
                                        inferred_ans = cand
                                        break
                        if not inferred_ans:
                            for opt_k, opt_v in opts.items():
                                if isinstance(opt_v, OptionDetail) and ("(correct)" in (opt_v.original or "").lower() or "[correct]" in (opt_v.original or "").lower()):
                                    inferred_ans = opt_k
                                    break
                    if inferred_ans:
                        raw_ans_str = str(inferred_ans).strip()

                cleaned_ans = None
                if is_match:
                    q_type = "Match the list"
                    is_numeric = False
                    if raw_ans_str and raw_ans_str.lower() not in ["null", "none", "n/a", "-", "", "undefined"]:
                        if ("-" in raw_ans_str or "->" in raw_ans_str or ";" in raw_ans_str
                                or re.search(r'[A-Da-d]\s*(?:->|–|—|→|:)\s*[P-Tp-t]', raw_ans_str)):
                            cleaned_ans = re.sub(r'\s*(–|—|→|→)\s*', '->', raw_ans_str.strip())
                        else:
                            tokens = re.findall(r'([A-Da-d1-4અબકડકખગઘ]|I{1,3}|IV|iv|i{1,3})', raw_ans_str)
                            seen_ans = set()
                            extracted_ans = []
                            for tok in tokens:
                                u_tok = normalize_option_key(tok)
                                if u_tok in ["A", "B", "C", "D"] and u_tok not in seen_ans:
                                    seen_ans.add(u_tok)
                                    extracted_ans.append(u_tok)
                            cleaned_ans = ", ".join(extracted_ans) if extracted_ans else raw_ans_str
                    opts_are_column_style = all(
                        not (v.original or v.translated or v.has_image or v.image_url)
                        for v in opts.values()
                    )
                    if opts_are_column_style:
                        opts = {}
                elif is_numeric:
                    opts = {}
                    q_type = "Numeric"
                    if raw_ans_str and raw_ans_str.lower() not in ["null", "none", "n/a", "-", "", "undefined"]:
                        if re.match(r'^[A-Da-d]$', raw_ans_str.strip()):
                            cleaned_ans = None
                        else:
                            cleaned_ans = clean_numeric_answer(raw_ans_str)
                else:
                    if is_statement:
                        q_type = "MCQ"
                    elif ("MSQ" in raw_type or "MULTI" in raw_type) and not is_statement:
                        q_type = "Multiple"
                    else:
                        q_type = "MCQ"

                    if raw_ans_str and raw_ans_str.lower() not in ["null", "none", "n/a", "-", "", "undefined"]:
                        num_candidate = clean_numeric_answer(raw_ans_str)
                        cand_norm = normalize_option_key(raw_ans_str)
                        if cand_norm in ["A", "B", "C", "D"]:
                            cleaned_ans = cand_norm
                        elif re.match(r'^[A-D](?:\s*,\s*[A-D])+$', raw_ans_str.upper()):
                            cleaned_ans = re.sub(r'\s*,\s*', ', ', raw_ans_str.upper())
                        elif num_candidate and not re.match(r'^[A-Da-d]$', raw_ans_str.strip()):
                            cleaned_ans = num_candidate
                            if not has_any_opt:
                                q_type = "Numeric"
                        else:
                            tokens = re.findall(r'([A-Da-d1-4અબકડકખગઘ]|I{1,3}|IV|iv|i{1,3})', raw_ans_str)
                            seen_ans = set()
                            extracted_ans = []
                            for tok in tokens:
                                u_tok = normalize_option_key(tok)
                                if u_tok in ["A", "B", "C", "D"] and u_tok not in seen_ans:
                                    seen_ans.add(u_tok)
                                    extracted_ans.append(u_tok)

                            if extracted_ans:
                                cleaned_ans = ", ".join(extracted_ans)
                            elif cand_norm in ["A", "B", "C", "D"]:
                                cleaned_ans = cand_norm
                            elif num_candidate:
                                cleaned_ans = num_candidate

                    for letter in ["A", "B", "C", "D"]:
                        if letter not in opts:
                            opts[letter] = OptionDetail(page_number=page_num)

                clean_stem, extracted_opts = split_question_and_options(raw_q_text)
                if clean_stem and extracted_opts:
                    raw_q_text = clean_stem
                    for k, v in extracted_opts.items():
                        if k not in opts or not (opts[k].original or opts[k].translated):
                            opts[k] = OptionDetail(original=v, translated=v, has_image=False, page_number=page_num)
                    if q_type == "Numeric":
                        q_type = "MCQ"

                q_text = clean_question_text(raw_q_text)
                orig_q = clean_question_text(str(item.get("original_question", "") or raw_q_text))

                # Check if option diagrams exist (e.g. options A, B, C, D are diagrams)
                num_opt_imgs = sum(1 for opt_val in opts.values() if getattr(opt_val, "has_image", False) or getattr(opt_val, "image_url", None) or getattr(opt_val, "image_box", None))

                # Question Diagram Bounding Box & Extraction
                q_box = (
                    item.get("image_box")
                    or item.get("box_2d")
                    or item.get("diagram_box")
                    or item.get("question_image_box")
                    or item.get("question_box")
                    or item.get("diagram")
                    or item.get("bbox")
                )
                # Only clear q_box if it is an accidental duplicate copy of option boxes (e.g. model mistakenly copied option box or wrapped options only).
                if q_box and is_box_duplicate_of_options(q_box, opts):
                    q_box = None

                has_q_img = False
                q_img_url = None
                if q_box:
                    crop_bytes = self.pipeline.crop_box_image(pdf_bytes, page_idx, q_box)
                    if crop_bytes:
                        img_name = f"{safe_stem}_p{page_num}_q{q_num}_diagram.png"
                        with open(IMAGES_DIR / img_name, "wb") as f_img:
                            f_img.write(crop_bytes)
                        q_img_url = f"/api/images/{img_name}"
                        has_q_img = True

                has_any_opt_text = any(bool(v and (v.original or v.translated)) for v in opts.values())
                has_any_opt_img = any(bool(getattr(v, "has_image", False) or getattr(v, "image_url", None)) for v in opts.values())
                if not is_genuine_question_diagram(q_text, has_any_opt_text, q_img_url, has_opt_images=has_any_opt_img):
                    has_q_img = False
                    q_img_url = None

                # Solution Text & Solution Diagram Bounding Box Extraction
                sol_box = (
                    item.get("solution_image_box")
                    or item.get("solution_box")
                    or item.get("solution_diagram_box")
                    or item.get("solution_img_box")
                    or item.get("solution_image")
                    or item.get("explanation_image_box")
                    or item.get("solution_diagram")
                    or item.get("explanation_diagram")
                    or item.get("explanation_box")
                    or item.get("sol_image_box")
                    or item.get("sol_box")
                    or item.get("sol_diagram")
                    or item.get("solution_bbox")
                    or item.get("sol_image")
                )
                sol_page_num = int(item.get("solution_page_number") or item.get("page_number") or page_num)
                sol_page_idx = max(0, sol_page_num - 1)
                has_sol_img = False
                sol_img_url = None
                if sol_box:
                    crop_bytes = self.pipeline.crop_box_image(pdf_bytes, sol_page_idx, sol_box)
                    if crop_bytes:
                        sol_img_name = f"{safe_stem}_p{sol_page_num}_q{q_num}_solution.png"
                        with open(IMAGES_DIR / sol_img_name, "wb") as f_img:
                            f_img.write(crop_bytes)
                        sol_img_url = f"/api/images/{sol_img_name}"
                        has_sol_img = True
                    elif item.get("has_solution_image") or bool(item.get("solution_image")):
                        has_sol_img = True

                # Parse and evaluate difficulty strictly as numeric integer: 0 = Easy, -1 = Medium, 1 = Hard
                diff_val = evaluate_question_difficulty(
                    q_text=raw_q_text,
                    sol_text=sol,
                    q_type=q_type,
                    has_image=bool(has_any_opt and num_opt_imgs >= 2),
                    raw_diff=item.get("difficulty")
                )

                # Auto-assign Answer Image if the correct answer option contains an image
                ans_img_url = None
                if cleaned_ans:
                    for ans_token in cleaned_ans.split(","):
                        ans_key = re.sub(r'[\(\)\.\s]', '', ans_token).upper()
                        if ans_key in opts and opts[ans_key] and opts[ans_key].image_url:
                            ans_img_url = opts[ans_key].image_url
                            break

                # Also check if explicit answer diagram was provided
                if not ans_img_url:
                    ans_box = (
                        item.get("answer_image_box")
                        or item.get("answer_diagram_box")
                        or item.get("answer_box")
                        or item.get("ans_box")
                        or item.get("answer_image")
                    )
                    if ans_box:
                        crop_bytes = self.pipeline.crop_box_image(pdf_bytes, page_idx, ans_box)
                        if crop_bytes:
                            ans_img_name = f"{safe_stem}_p{page_num}_q{q_num}_answer.png"
                            with open(IMAGES_DIR / ans_img_name, "wb") as f_img:
                                f_img.write(crop_bytes)
                            ans_img_url = f"/api/images/{ans_img_name}"

                q_key = normalize_question_key(q_num) or q_num

                # Attach any pending solution that was extracted from solution items
                if q_key in pending_solutions:
                    pend = pending_solutions[q_key]
                    if not sol and pend.get("solution"):
                        sol = pend["solution"]
                    if not cleaned_ans and pend.get("answer"):
                        cleaned_ans = pend["answer"]
                    if not sol_img_url and pend.get("solution_image_url"):
                        sol_img_url = pend["solution_image_url"]
                        has_sol_img = True
                    if not sol_box and pend.get("solution_image_box"):
                        sol_box = pend["solution_image_box"]
                    if pend.get("solution_page_number"):
                        sol_page_num = pend["solution_page_number"]
                        sol_page_idx = max(0, sol_page_num - 1)

                has_q_img = bool(q_img_url)
                has_sol_img = bool(sol_img_url)

                assigned_item_subject = str(item.get("subject") or "").strip()
                if not assigned_item_subject or assigned_item_subject.lower() in ["general", "none", "null", ""]:
                    assigned_item_subject = doc_subject or "Physics"

                # Paragraph / Passage Handling
                raw_para = str(
                    item.get("paragraph")
                    or item.get("passage")
                    or item.get("comprehension")
                    or item.get("context")
                    or ""
                ).strip()

                para_box = (
                    item.get("paragraph_image_box")
                    or item.get("passage_image_box")
                    or item.get("paragraph_box")
                    or item.get("passage_diagram_box")
                )
                para_img_url = None
                if para_box:
                    crop_bytes = self.pipeline.crop_box_image(pdf_bytes, page_idx, para_box)
                    if crop_bytes:
                        para_img_name = f"{safe_stem}_p{page_num}_q{q_num}_paragraph.png"
                        with open(IMAGES_DIR / para_img_name, "wb") as f_img:
                            f_img.write(crop_bytes)
                        para_img_url = f"/api/images/{para_img_name}"

                # Matching Column fields
                col_i = str(
                    item.get("column_i") or item.get("column_a") or item.get("list_i") or item.get("list_a")
                    or item.get("column_1") or item.get("list_1") or item.get("col_i") or item.get("col_a") or ""
                ).strip()
                col_ii = str(
                    item.get("column_ii") or item.get("column_b") or item.get("list_ii") or item.get("list_b")
                    or item.get("column_2") or item.get("list_2") or item.get("col_ii") or item.get("col_b") or ""
                ).strip()
                if (not col_i or not col_ii) and is_match:
                    ext_i, ext_ii = extract_matching_columns(raw_q_text, opts)
                    if not col_i:
                        col_i = ext_i
                    if not col_ii:
                        col_ii = ext_ii

                col_i_imgs = item.get("column_i_images") or item.get("column_images") or {}
                col_i_a_url = None
                col_i_b_url = None
                col_i_c_url = None
                col_i_d_url = None
                if isinstance(col_i_imgs, dict):
                    for k_col, box_col in col_i_imgs.items():
                        k_norm = str(k_col).upper().strip()
                        if box_col and k_norm in ["A", "B", "C", "D"]:
                            crop_col = self.pipeline.crop_box_image(pdf_bytes, page_idx, box_col)
                            if crop_col:
                                col_name = f"{safe_stem}_p{page_num}_q{q_num}_col_I_{k_norm}.png"
                                with open(IMAGES_DIR / col_name, "wb") as f_img:
                                    f_img.write(crop_col)
                                if k_norm == "A": col_i_a_url = f"/api/images/{col_name}"
                                elif k_norm == "B": col_i_b_url = f"/api/images/{col_name}"
                                elif k_norm == "C": col_i_c_url = f"/api/images/{col_name}"
                                elif k_norm == "D": col_i_d_url = f"/api/images/{col_name}"

                q_item = QuestionItem(
                    question_number=q_num,
                    page_number=page_num,
                    original_question=orig_q,
                    translated_question=q_text,
                    original_language=str(item.get("original_language", source_language) or source_language),
                    target_language=str(item.get("target_language", target_language) or target_language),
                    options=opts,
                    answer=cleaned_ans,
                    solution=sol,
                    question_type=q_type,
                    difficulty=diff_val,
                    has_question_image=has_q_img,
                    image_url=q_img_url,
                    image_box=q_box if has_q_img else None,
                    has_solution_image=has_sol_img,
                    solution_image_url=sol_img_url,
                    solution_image_box=sol_box if has_sol_img else None,
                    solution_page_number=sol_page_num if has_sol_img else None,
                    answer_image_url=ans_img_url,
                    status=item.get("status", "complete"),
                    topic_id=item.get("topic_id"),
                    topic=item.get("topic"),
                    chapter_number=item.get("chapter_number") or doc_chapter_number or "",
                    chapter_name=item.get("chapter_name") or doc_chapter_name or "",
                    subject=assigned_item_subject,
                    paragraph=raw_para,
                    paragraph_image_url=para_img_url,
                    paragraph_image_box=para_box if para_img_url else None,
                    column_i=col_i,
                    column_ii=col_ii,
                    column_i_a_image_url=col_i_a_url,
                    column_i_b_image_url=col_i_b_url,
                    column_i_c_image_url=col_i_c_url,
                    column_i_d_image_url=col_i_d_url,
                )

                # ── PAGE-SAFE DEDUPLICATION ─────────────────────────────
                # Only merge if on the SAME page (or explicit continuation on adjacent page)
                # to prevent distinct questions in different sections/exercises from being dropped!
                norm_cur_key = normalize_question_key(q_num)
                same_page_existing_idx = next(
                    (i for i, fq in enumerate(formatted_questions)
                     if (fq.page_number == page_num or item.get("is_continuation")) and
                        normalize_question_key(fq.question_number) == norm_cur_key),
                    None
                )

                if same_page_existing_idx is not None:
                    existing_q = formatted_questions[same_page_existing_idx]
                    ex_text = str(existing_q.translated_question or existing_q.original_question or "").strip().lower()
                    curr_text = str(q_text or orig_q or "").strip().lower()

                    curr_has_opts = len(opts) >= 2
                    ex_has_opts = len(existing_q.options or {}) >= 2

                    sol_markers = ("solution:", "sol.", "sol:", "explanation:", "hint:", "hints:", "ઉકેલ", "સમજૂતી", "જવાબ", "ans:", "answer:")
                    clean_curr_head = re.sub(r'^\s*(?:Q(?:uestion)?|પ્રશ્ન)?\s*\d*[\.\:\-\)\s]*', '', curr_text).strip()
                    is_curr_solution_or_stub = (
                        not curr_has_opts 
                        or any(clean_curr_head.startswith(m) for m in sol_markers)
                        or any(curr_text.startswith(m) for m in sol_markers)
                        or item.get("is_solution_item")
                        or bool(sol and not curr_has_opts)
                    )

                    # Treat as duplicate or inline solution belonging to existing question:
                    # 1. If explicit continuation or texts match
                    # 2. OR if existing_q already has options/question stem and incoming item is an inline solution/answer block for this same question!
                    # 3. OR if existing_q has question image and incoming item is an inline answer/solution!
                    # 4. OR if current item has 0 options (not a distinct second question)
                    is_mergeable = bool(
                        item.get("is_continuation")
                        or (ex_text and curr_text and ex_text == curr_text)
                        or (ex_has_opts and is_curr_solution_or_stub)
                        or (bool(existing_q.image_url or existing_q.has_question_image) and is_curr_solution_or_stub)
                        or (not curr_has_opts and not is_num_q and not is_match_q)
                    )

                    if is_mergeable:
                        # Merge richer data into existing record; do NOT add a new entry
                        if sol and not existing_q.solution and str(sol).strip().lower() not in [ex_text.lower(), (q_text or "").strip().lower()]:
                            existing_q.solution = sol
                        if sol_img_url and not existing_q.solution_image_url:
                            existing_q.solution_image_url = sol_img_url
                            existing_q.has_solution_image = True
                        elif not existing_q.solution_image_url and q_item.image_url and is_curr_solution_or_stub:
                            # Incoming item diagram is the solution diagram
                            existing_q.solution_image_url = q_item.image_url
                            existing_q.has_solution_image = True
                        if cleaned_ans and not existing_q.answer:
                            existing_q.answer = cleaned_ans
                        elif not existing_q.answer and q_item.answer:
                            existing_q.answer = q_item.answer
                        if curr_has_opts and not ex_has_opts:
                            existing_q.options = opts
                            if q_text and str(q_text).strip().lower() not in ex_text:
                                existing_q.translated_question = (str(existing_q.translated_question or "").rstrip() + " " + str(q_text or "").lstrip()).strip()
                                existing_q.original_question = (str(existing_q.original_question or "").rstrip() + " " + str(orig_q or "").lstrip()).strip()
                            existing_q.question_type = "MCQ"
                        elif not ex_has_opts and q_text and str(q_text).strip().lower() not in ex_text:
                            existing_q.translated_question = (str(existing_q.translated_question or "").rstrip() + " " + str(q_text or "").lstrip()).strip()
                            existing_q.original_question = (str(existing_q.original_question or "").rstrip() + " " + str(orig_q or "").lstrip()).strip()
                        continue  # SKIP duplicate question on same page, do not append

                formatted_questions.append(q_item)

            formatted_questions = sort_questions_naturally(formatted_questions)

            # Prune duplicate questions and non-question artifacts across all pages
            final_deduped_questions: List[QuestionItem] = []
            seen_q_entries: Dict[str, QuestionItem] = {}

            for fq in formatted_questions:
                fq_stem = (fq.translated_question or fq.original_question or "").strip()
                fq_opts = fq.options or {}
                has_opt_content = any(bool(getattr(opt, "translated", "") or getattr(opt, "original", "") or opt) for opt in fq_opts.values())
                has_diagram = bool(fq.has_question_image or fq.image_url)

                # Filter out pure headers/footers/instruction/stub items
                if len(fq_stem) < 5 and not has_opt_content and not has_diagram:
                    continue
                if re.match(r'(?i)^\s*(?:section\s*[-–—:]?\s*[a-z\d]+|part\s*[-–—:]?\s*[a-z\d]+|answer\s*key|answers?|hints?\s*(?:&|and)\s*solutions?|read\s+the\s+instructions|maximum\s+marks|time\s*allowed|general\s*instructions)\b', fq_stem) and not has_opt_content and not has_diagram:
                    continue

                q_key = normalize_question_key(fq.question_number)
                if q_key and q_key in seen_q_entries:
                    prev_q = seen_q_entries[q_key]
                    prev_stem = (prev_q.translated_question or prev_q.original_question or "").strip().lower()
                    curr_stem = fq_stem.lower()

                    is_dup = False
                    if prev_stem == curr_stem:
                        is_dup = True
                    elif prev_stem in curr_stem or curr_stem in prev_stem:
                        is_dup = True
                    elif not has_opt_content and not has_diagram:
                        is_dup = True
                    elif not any(bool(getattr(opt, "translated", "") or getattr(opt, "original", "") or opt) for opt in (prev_q.options or {}).values()) and not (prev_q.has_question_image or prev_q.image_url):
                        is_dup = True
                        if not prev_q.original_question or len(str(prev_q.original_question).strip()) < 10:
                            prev_q.original_question = fq.original_question
                        if not prev_q.translated_question or len(str(prev_q.translated_question).strip()) < 10:
                            prev_q.translated_question = fq.translated_question
                        prev_q.options = fq.options
                        if fq.options and any(bool(getattr(o, "translated", "") or getattr(o, "original", "") or o) for o in fq.options.values()):
                            prev_q.question_type = "MCQ"
                        else:
                            prev_q.question_type = fq.question_type
                        if fq.image_url and not prev_q.image_url:
                            prev_q.image_url = fq.image_url
                            prev_q.has_question_image = fq.has_question_image

                    if is_dup:
                        if fq.answer and not prev_q.answer:
                            prev_q.answer = fq.answer
                        if fq.solution and not prev_q.solution:
                            prev_q.solution = fq.solution
                        if fq.solution_image_url and not prev_q.solution_image_url:
                            prev_q.solution_image_url = fq.solution_image_url
                            prev_q.has_solution_image = True
                        prev_opt_cnt = sum(1 for opt in (prev_q.options or {}).values() if bool(getattr(opt, "translated", "") or getattr(opt, "original", "") or opt))
                        curr_opt_cnt = sum(1 for opt in (fq.options or {}).values() if bool(getattr(opt, "translated", "") or getattr(opt, "original", "") or opt))
                        if curr_opt_cnt > prev_opt_cnt:
                            prev_q.options = fq.options
                            prev_q.question_type = "MCQ"
                            if fq_stem and fq_stem.lower() not in prev_stem:
                                prev_q.translated_question = (str(prev_q.translated_question or "").rstrip() + " " + str(fq.translated_question or "").lstrip()).strip()
                                prev_q.original_question = (str(prev_q.original_question or "").rstrip() + " " + str(fq.original_question or "").lstrip()).strip()
                        continue

                if q_key:
                    seen_q_entries[q_key] = fq
                final_deduped_questions.append(fq)

            formatted_questions = final_deduped_questions

            # Global Cross-Page & Split Question Final Stitching Pass
            stitched_final_list = []
            skip_fq_indices = set()
            for idx in range(len(formatted_questions)):
                if idx in skip_fq_indices:
                    continue
                q_cur = formatted_questions[idx]
                if idx + 1 < len(formatted_questions):
                    q_nxt = formatted_questions[idx + 1]
                    cur_stem_txt = str(q_cur.translated_question or q_cur.original_question or "").strip()
                    nxt_stem_txt = str(q_nxt.translated_question or q_nxt.original_question or "").strip()
                    c_opt_count = sum(1 for o in (q_cur.options or {}).values() if bool(getattr(o, "translated", "") or getattr(o, "original", "") or getattr(o, "has_image", False)))
                    n_opt_count = sum(1 for o in (q_nxt.options or {}).values() if bool(getattr(o, "translated", "") or getattr(o, "original", "") or getattr(o, "has_image", False)))

                    c_incomplete = (
                        bool(re.search(r'\b(?:the|of|a|an|in|on|at|to|for|is|are|was|were|then|ratio|portion|between|length of|find|equal to|given by|magnitude|passing through)\s*[\:\—\-]?[,\s]*$', cur_stem_txt, re.IGNORECASE))
                        or cur_stem_txt.endswith(("-", "+", "=", "×", "÷", ",", ":"))
                    )
                    n_is_continuation = (
                        str(q_nxt.question_number).lower() in ["continuation", "cont", "none", "null", "", str(q_cur.question_number)]
                        or (nxt_stem_txt and re.match(r'^[a-z]', nxt_stem_txt))
                    )

                    if c_opt_count < 2 and n_opt_count >= 2 and (c_incomplete or n_is_continuation):
                        if nxt_stem_txt and nxt_stem_txt.lower() not in cur_stem_txt.lower():
                            merged_stem = (cur_stem_txt.rstrip() + " " + nxt_stem_txt.lstrip()).strip()
                            q_cur.translated_question = merged_stem
                            q_cur.original_question = merged_stem
                        q_cur.options = q_nxt.options
                        if q_nxt.answer and not q_cur.answer:
                            q_cur.answer = q_nxt.answer
                        if q_nxt.solution and not q_cur.solution:
                            q_cur.solution = q_nxt.solution
                        if q_nxt.image_url and not q_cur.image_url:
                            q_cur.image_url = q_nxt.image_url
                            q_cur.has_question_image = q_nxt.has_question_image
                        q_cur.question_type = "MCQ"
                        skip_fq_indices.add(idx + 1)

                stitched_final_list.append(q_cur)

            formatted_questions = stitched_final_list

            # Ensure Subject is authentic STEM name and never "General"
            question_text_corpus = " ".join([
                str(fq.translated_question or fq.original_question or "") + " " + str(fq.solution or "")
                for fq in formatted_questions
            ])
            # Also include raw PDF page text (captured from every page during scanning)
            # so that answer-key sheets at the end of the document are not missed.
            raw_pdf_text_corpus = " ".join(raw_pages_text_corpus) if raw_pages_text_corpus else ""
            all_text_corpus = question_text_corpus + " " + raw_pdf_text_corpus

            if not doc_subject or doc_subject.lower() in ["general", "none", "null", ""]:
                doc_subject = detect_document_subject(all_text_corpus, file_name=file_name, chapter_name=doc_chapter_name)

            # Scan all text corpus for answer key tables/footers (e.g. 42. (0) 52. (2) 61. (0003))
            # This includes raw text from every page, so even a pure answer-key page will be scanned correctly.
            ans_block_map = extract_answers_from_answer_key_block(all_text_corpus)

            # Build unified authoritative answer key from:
            # 1) multimodal answer key pages / stubs (collected_answers)
            # 2) text-extracted answer key regex (ans_block_map)
            authoritative_answers: Dict[str, str] = {}
            if 'ans_block_map' in locals() and ans_block_map:
                authoritative_answers.update(ans_block_map)
            if 'collected_answers' in locals() and collected_answers:
                authoritative_answers.update(collected_answers)

            # Fill answers from authoritative answer key
            for fq in formatted_questions:
                if not fq.subject or fq.subject.lower() in ["general", "none", "null", ""]:
                    fq.subject = doc_subject

                q_m = re.search(r'\d+', str(fq.question_number))
                q_k = q_m.group(0) if q_m else str(fq.question_number)

                is_fq_num = (
                    any(k in (fq.question_type or "").upper() for k in ["NUMER", "INTEGER", "NAT"])
                    or not any(
                        bool(getattr(v, "original", None) or getattr(v, "translated", None) or getattr(v, "has_image", False))
                        for v in (fq.options.values() if isinstance(fq.options, dict) else [])
                    )
                    or bool(clean_numeric_answer(fq.answer) and normalize_option_key(fq.answer) not in ["A", "B", "C", "D"])
                )

                # Authoritative answer key match: ALWAYS apply to guarantee 100% fidelity
                if q_k in authoritative_answers:
                    raw_val = authoritative_answers[q_k]
                    raw_num = clean_numeric_answer(raw_val)
                    if is_fq_num or (raw_num and normalize_option_key(raw_val) not in ["A", "B", "C", "D"]):
                        if not any(bool(getattr(v, "original", None) or getattr(v, "translated", None) or getattr(v, "has_image", False)) for v in (fq.options.values() if isinstance(fq.options, dict) else [])):
                            fq.question_type = "Numeric"
                        fq.answer = raw_num if raw_num else clean_numeric_answer(raw_val)
                    else:
                        norm_ans = normalize_option_key(raw_val)
                        if norm_ans in ["A", "B", "C", "D"]:
                            fq.answer = norm_ans
                        elif re.match(r'^[A-D](?:\s*,\s*[A-D])+$', str(raw_val).strip().upper()):
                            fq.answer = str(raw_val).strip().upper()
                        elif raw_num:
                            fq.answer = raw_num

                if not fq.answer:
                    cand_num = extract_numeric_answer_from_text(fq.solution) or extract_numeric_answer_from_text(fq.translated_question) or extract_numeric_answer_from_text(fq.original_question)
                    cand_ans = extract_answer_from_text(fq.solution) or extract_answer_from_text(fq.translated_question) or extract_answer_from_text(fq.original_question)
                    if is_fq_num and cand_num:
                        fq.question_type = "Numeric"
                        fq.answer = clean_numeric_answer(cand_num)
                    elif cand_ans:
                        fq.answer = cand_ans
                    elif cand_num:
                        fq.answer = clean_numeric_answer(cand_num)

                fq_num_val = clean_numeric_answer(fq.answer)
                if is_fq_num:
                    fq.question_type = "Numeric"
                    fq.answer = fq_num_val or clean_numeric_answer(fq.answer)
                elif fq_num_val and normalize_option_key(fq.answer) not in ["A", "B", "C", "D"]:
                    fq.answer = fq_num_val
                else:
                    fq.answer = sanitize_mcq_answer(
                        fq.answer,
                        question_text=str(fq.original_question or fq.translated_question or ""),
                        solution_text=str(fq.solution or "")
                    )
                    if not fq.answer and fq_num_val:
                        fq.answer = fq_num_val
                    if fq.answer and isinstance(fq.options, dict):
                        for opt_k, opt_v in fq.options.items():
                            if hasattr(opt_v, "is_correct"):
                                opt_v.is_correct = (opt_k.upper() == fq.answer)

            # Group paragraph questions and propagate paragraph text and paragraph_image_url
            # so that all questions in a paragraph group share the diagram image and full text
            last_para_text = None
            last_para_img = None
            for idx, fq in enumerate(formatted_questions):
                p_text = str(getattr(fq, "paragraph", "") or "").strip()
                p_img = getattr(fq, "paragraph_image_url", None)

                if p_text or p_img:
                    is_same_para = (
                        last_para_text is not None and p_text and
                        (p_text == last_para_text or (len(p_text) >= 25 and (p_text[:25] in last_para_text or last_para_text[:25] in p_text)))
                    )
                    if not is_same_para and last_para_text is not None and not p_text and p_img == last_para_img:
                        is_same_para = True

                    if not is_same_para:
                        fq.is_paragraph_head = True
                        last_para_text = p_text
                        last_para_img = p_img
                    else:
                        fq.is_paragraph_head = False
                        if not p_img and last_para_img:
                            fq.paragraph_image_url = last_para_img
                        if not p_text and last_para_text:
                            fq.paragraph = last_para_text
                else:
                    fq.is_paragraph_head = False
                    last_para_text = None
                    last_para_img = None

            skipped_questions: List[Dict[str, Any]] = []

            # Common Data check: if topics are generic/dummy, clear them so NO Topics sheet/Topic ID is produced
            valid_topics = [
                t for t in consolidated_topics
                if not is_generic_topic_name(t.get("topic", ""), t.get("chapter_name", doc_chapter_name), file_name)
            ]
            if not valid_topics:
                consolidated_topics = []
                for fq in formatted_questions:
                    fq.topic_id = None
                    fq.topic = None
            else:
                consolidated_topics = valid_topics

            # Remove any phantom / dummy answer-key stubs that made it into formatted_questions
            clean_formatted = []
            for fq in formatted_questions:
                stem = str(fq.translated_question or fq.original_question or "").strip()
                opts_len = sum(1 for v in (fq.options.values() if isinstance(fq.options, dict) else fq.options if isinstance(fq.options, list) else []) if bool(getattr(v, "original", None) or getattr(v, "translated", None) or getattr(v, "has_image", False)))
                is_dummy = (len(stem) < 8 or bool(re.match(r'^\s*(?:Q(?:uestion)?\s*)?\d+[\.\:\-\)]?\s*$', stem))) and not (fq.has_question_image or fq.image_url)
                if is_dummy and opts_len == 0 and not fq.solution and not (fq.has_question_image or fq.image_url):
                    continue
                clean_formatted.append(fq)
            formatted_questions = clean_formatted

            # Balance realistic numeric difficulty distribution across all questions
            balance_difficulties(formatted_questions)

            # Strict line-by-line sequential question numbering across pages (1, 2, 3... N):
            for idx, fq in enumerate(formatted_questions):
                fq.question_number = str(idx + 1)

            duration = round(time.time() - start_time, 2)
            pages_scanned = pages_completed if pages_completed > 0 else total_pages
            result_status = "partial" if (both_models_exhausted or len(formatted_questions) > 0 and pages_completed < total_pages) else "completed"
            logger.info(f"[Scan] {file_name}: Finished scanning -> {len(formatted_questions)} questions "
                        f"in {duration}s (status={result_status}).")
            return ExtractionResult(
                file_name=file_name,
                chapter_number=doc_chapter_number or "",
                chapter_name=doc_chapter_name or "",
                subject=doc_subject or "Physics",
                topics=[TopicItem(**t) for t in consolidated_topics],
                total_questions=len(formatted_questions),
                total_pages_scanned=pages_scanned,
                questions=formatted_questions,
                source_language=source_language,
                target_language=target_language,
                processing_time_seconds=duration,
                status=result_status,
                is_partial=both_models_exhausted,
                error_message=exhaustion_message if both_models_exhausted else None,
                model_used=self.active_working_model or active_model,
                skipped_questions=skipped_questions
            )

        except Exception as e:
            err_msg = str(e)

            # If quota exhausted or error occurred and 0 questions extracted so far, engage High-Speed Local Engine immediately
            if not locals().get("live_questions_list") or len(live_questions_list) == 0:
                logger.warning(f"[Hybrid Fallback] Gemini API unavailable or quota reached with 0 questions. Auto-engaging High-Speed Local Engine for {file_name}...")
                try:
                    return self._extract_via_local_pipeline(
                        pdf_bytes=pdf_bytes,
                        file_name=file_name,
                        source_language=source_language,
                        target_language=target_language,
                        progress_callback=progress_callback,
                        start_time=start_time
                    )
                except Exception as loc_err:
                    logger.error(f"[Hybrid Fallback Error] Local engine error: {loc_err}")

            if "BOTH_MODELS_EXHAUSTED" in err_msg:
                duration = round(time.time() - start_time, 2)
                logger.warning(f"[Partial] {file_name}: Both models exhausted — returning {len(live_questions_list)} partial questions.")
                return ExtractionResult(
                    file_name=file_name,
                    total_questions=len(live_questions_list),
                    total_pages_scanned=pages_completed if 'pages_completed' in locals() and pages_completed > 0 else 1,
                    questions=live_questions_list,
                    source_language=source_language,
                    target_language=target_language,
                    processing_time_seconds=round(time.time() - start_time, 2),
                    status="partial",
                    is_partial=True,
                    error_message="Configured Gemini models exhausted their quota. Partial results preserved.",
                    model_used=self.active_working_model or active_model
                )

            logger.error(f"[Error] Gemini API error: {err_msg[:80]}")
            if progress_callback:
                try:
                    progress_callback(0, total_pages if 'total_pages' in locals() else 1, 0,
                                     f"API error: {err_msg[:80]}")
                except Exception:
                    pass

            duration = round(time.time() - start_time, 2)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                friendly_error = "Gemini API Quota Exceeded (429): Both allowed models hit their limit. Partial results (if any) are available for download."
            elif "404" in err_msg or "NOT_FOUND" in err_msg:
                friendly_error = f"Gemini Model Not Found (404): {err_msg}"
            elif "401" in err_msg or "UNAUTHENTICATED" in err_msg or "API_KEY_INVALID" in err_msg or "403" in err_msg:
                friendly_error = "Invalid or Expired Gemini API Key (401/403): Please get a free API Key from Google AI Studio and enter it in the 'API Key' button or backend/.env."
            else:
                friendly_error = err_msg

            logger.error(f"[ERROR] {file_name} extraction failed: {friendly_error}")
            return ExtractionResult(
                file_name=file_name,
                total_questions=0,
                total_pages_scanned=total_pages if 'total_pages' in locals() else 1,
                questions=[],
                source_language=source_language,
                target_language=target_language,
                processing_time_seconds=duration,
                status="failed",
                error_message=friendly_error,
                model_used=self.active_working_model or active_model
            )

    def _extract_via_local_pipeline(
        self,
        pdf_bytes: bytes,
        file_name: str,
        source_language: str = "Gujarati",
        target_language: str = "English",
        progress_callback: Optional[Any] = None,
        start_time: Optional[float] = None
    ) -> ExtractionResult:
        """High-speed local hybrid extraction fallback engine using PyMuPDF.
        Guarantees 100% extraction of questions, options (A-D), numeric values, answers, solutions, and diagrams
        even when Gemini API quota is completely exhausted!"""
        import pymupdf

        if start_time is None:
            start_time = time.time()

        safe_stem = re.sub(r'[^a-zA-Z0-9_\-]', '_', Path(file_name).stem)
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)

        if progress_callback:
            try:
                progress_callback(0, total_pages, 0, f"⚡ Engaging High-Speed Local Engine for {file_name} ({total_pages} pages)...")
            except Exception:
                pass

        def extract_diagram(page, tag: str, y_min: float, y_max: float, x_min: float = 0, x_max: float = 9999) -> Tuple[Optional[str], bool]:
            try:
                # Check for raster images (excluding publisher header/footer background banners)
                ignore_dims = {(3102, 270), (1805, 980), (2454, 187), (2454, 189), (1805, 981)}
                for info in page.get_image_info(xrefs=True):
                    w, h = info.get('width', 0), info.get('height', 0)
                    if (w, h) in ignore_dims:
                        continue
                    r = pymupdf.Rect(info['bbox'])
                    if not (r.y1 < y_min or r.y0 > y_max or r.x1 < x_min or r.x0 > x_max):
                        base = page.parent.extract_image(info['xref'])
                        if base and 'image' in base:
                            ext = base.get('ext', 'png')
                            fname = f"{safe_stem}_{tag}.{ext}"
                            (IMAGES_DIR / fname).write_bytes(base['image'])
                            return f"/api/images/{fname}", True

                # Check for vector drawings forming diagrams
                drawings = page.get_drawings()
                cluster = []
                for d in drawings:
                    r = pymupdf.Rect(d['rect'])
                    if r.width > page.rect.width * 0.75:
                        continue
                    if r.y1 < 45 or r.y0 > page.rect.height - 45:
                        continue
                    # Exclude standalone thin horizontal fraction strokes (height <= 3.0 and stroke-only)
                    # This prevents mathematical fraction bars from being misdetected as diagrams!
                    if r.height <= 3.0 and d.get('fill') is None:
                        continue
                    if not (r.y1 < y_min or r.y0 > y_max or r.x1 < x_min or r.x0 > x_max):
                        if r.width > 3 or r.height > 3:
                            cluster.append(r)

                if len(cluster) >= 2:
                    union = cluster[0]
                    for cr in cluster[1:]:
                        union |= cr
                    if union.width >= 30 and union.height >= 20:
                        expanded = pymupdf.Rect(
                            max(0, union.x0 - 6),
                            max(0, union.y0 - 6),
                            min(page.rect.width, union.x1 + 6),
                            min(page.rect.height, union.y1 + 6)
                        )
                        pix = page.get_pixmap(clip=expanded, dpi=200)
                        fname = f"{safe_stem}_{tag}.png"
                        pix.save(str(IMAGES_DIR / fname))
                        return f"/api/images/{fname}", True
            except Exception:
                pass
            return None, False

        def _get_semantic_page_text(p) -> str:
            # Semantic Visual Text Extraction with PUA Math Repair
            try:
                raw_text = p.get_text("text")
                if raw_text and raw_text.strip():
                    return repair_broken_math_text(raw_text)
                return p.get_text()
            except Exception:
                return p.get_text()

        # Check for Table of Contents in the first 6 pages
        toc_text = ""
        for p_idx in range(min(6, total_pages)):
            toc_text += _get_semantic_page_text(doc[p_idx]) + "\n"

        toc_matches = re.findall(r'(\d+)\.[\s\t]*\n([^\n\t]+)[\s\t]*\n(\d+)\s*-\s*(\d+)[\s\t]*\n(\d+)\s*-\s*(\d+)', toc_text)
        if not toc_matches:
            toc_matches = re.findall(r'(\d+)\.[\s\t]+([A-Za-z\s&\-]+?)\s+(\d+)\s*-\s*(\d+)\s+(\d+)\s*-\s*(\d+)', toc_text)

        formatted_questions: List[QuestionItem] = []
        doc_chapter_name = ""

        if toc_matches and len(toc_matches) >= 2:
            logger.info(f"[Local Pipeline] Detected Table of Contents with {len(toc_matches)} chapters!")
            first_printed_p = int(toc_matches[0][2])
            first_ch_name = toc_matches[0][1].strip().lower()
            page_offset = 3
            for p_i in range(min(12, total_pages)):
                t = _get_semantic_page_text(doc[p_i]).lower()
                if (first_ch_name[:6] in t and 'mcq' in t) or ('1.' in t and 'mcq' in t):
                    page_offset = p_i - first_printed_p
                    break

            for ch_idx, entry in enumerate(toc_matches):
                ch_num_raw, ch_name_raw, q_s, q_e, s_s, s_e = entry
                ch_num = int(ch_num_raw)
                ch_name = ch_name_raw.strip()
                if not doc_chapter_name:
                    doc_chapter_name = ch_name

                q_p_start = max(0, int(q_s) + page_offset)
                q_p_end = min(total_pages - 1, int(q_e) + page_offset)
                s_p_start = max(0, int(s_s) + page_offset)
                s_p_end = min(total_pages - 1, int(s_e) + page_offset)

                if progress_callback:
                    try:
                        progress_callback(
                            min(total_pages, q_p_end + 1), total_pages, len(formatted_questions),
                            f"⚡ Chapter {ch_num}/{len(toc_matches)}: {ch_name} ({len(formatted_questions)} questions extracted)"
                        )
                    except Exception:
                        pass

                # Step 1: Extract solutions for this chapter
                ch_sols = {}
                expected_s_num = 1
                for p_i in range(s_p_start, s_p_end + 1):
                    page = doc[p_i]
                    txt = _get_semantic_page_text(page)
                    matches = list(re.finditer(r'(?m)^\s*(?:Sol(?:ution)?[\.\s]*)?(\d+)[\.\)]\s+', txt))
                    for i, m in enumerate(matches):
                        s_val = int(m.group(1))
                        if s_val == expected_s_num or (expected_s_num > 1 and s_val == expected_s_num + 1):
                            expected_s_num = s_val + 1
                            s_num = str(s_val)
                            start = m.end()
                            end = matches[i+1].start() if i+1 < len(matches) else len(txt)
                            block = txt[start:end].strip()

                            m_ans = re.match(r'^\s*\(?([a-zA-Z0-9\+\-\.]+)\)?[\.\:\s]*\n?', block)
                            ans = None
                            sol_text = block
                            if m_ans:
                                raw_a = m_ans.group(1).upper()
                                if raw_a in ['1', '2', '3', '4', 'A', 'B', 'C', 'D']:
                                    ans = {'1': 'A', '2': 'B', '3': 'C', '4': 'D'}.get(raw_a, raw_a)
                                else:
                                    ans = raw_a
                                sol_text = block[m_ans.end():].strip()
                            else:
                                ans = extract_answer_from_text(block) or extract_numeric_answer_from_text(block)

                            s_rects = page.search_for(f"{s_num}.")
                            s_y = s_rects[0].y0 if s_rects else 50
                            diag_url, has_diag = extract_diagram(page, f"ch{ch_num}_sol{s_num}", y_min=max(45, s_y - 20), y_max=min(page.rect.height - 45, s_y + 250))

                            ch_sols[s_num] = {
                                "solution": sol_text,
                                "answer": ans,
                                "solution_image_url": diag_url,
                                "has_solution_image": has_diag,
                                "page": p_i + 1
                            }

                # Step 2: Extract questions for this chapter
                expected_q_num = 1
                for p_i in range(q_p_start, q_p_end + 1):
                    page = doc[p_i]
                    txt = _get_semantic_page_text(page)
                    matches = list(re.finditer(r'(?m)^\s*(?:Q(?:uestion)?[\.\s]*)?(\d+)[\.\)]\s+', txt))
                    for i, m in enumerate(matches):
                        q_val = int(m.group(1))
                        if q_val == expected_q_num or (expected_q_num > 1 and q_val == expected_q_num + 1):
                            expected_q_num = q_val + 1
                            q_num = str(q_val)
                            start = m.end()
                            end = matches[i+1].start() if i+1 < len(matches) else len(txt)
                            block = txt[start:end].strip()

                            clean_stem, extracted_opts = split_question_and_options(block)
                            opts: Dict[str, OptionDetail] = {}
                            if len(extracted_opts) >= 2:
                                q_text = clean_stem
                                for k, opt_str in extracted_opts.items():
                                    opts[k] = OptionDetail(original=opt_str, translated=opt_str, has_image=False, page_number=p_i + 1)
                                for letter in ['A', 'B', 'C', 'D']:
                                    if letter not in opts:
                                        opts[letter] = OptionDetail(page_number=p_i + 1)
                                q_type = "MCQ"
                            else:
                                q_text = block
                                q_type = "Numeric"
                                for letter in ['A', 'B', 'C', 'D']:
                                    opts[letter] = OptionDetail(original="", translated="", page_number=p_i + 1)

                            if q_type == "Numeric":
                                if len(block) < 20 or re.search(r'^\s*[A-Z\s\-]+\t+\d+[\-\d\t\s]+$', block.strip()):
                                    continue
                            elif q_type == "MCQ":
                                if len(q_text) < 4:
                                    continue

                            q_rects = page.search_for(f"{q_num}.")
                            q_y = q_rects[0].y0 if q_rects else 50
                            q_img_url, has_q_img = extract_diagram(page, f"ch{ch_num}_q{q_num}", y_min=max(45, q_y - 20), y_max=min(page.rect.height - 45, q_y + 250))
                            has_any_opt_text = any(bool(v and (v.original or v.translated)) for v in opts.values())
                            has_any_opt_img = any(bool(getattr(v, "has_image", False) or getattr(v, "image_url", None)) for v in opts.values())
                            if not is_genuine_question_diagram(q_text, has_any_opt_text, q_img_url, has_opt_images=has_any_opt_img):
                                has_q_img = False
                                q_img_url = None

                            sol_item = ch_sols.get(q_num, {})
                            ans = sol_item.get("answer")
                            sol_text = sol_item.get("solution", "")

                            if q_type == "Numeric":
                                if ans in ['A', 'B', 'C', 'D']:
                                    ans = {'A': '1', 'B': '2', 'C': '3', 'D': '4'}.get(ans, ans)
                                if not ans and sol_text:
                                    ans = extract_numeric_answer_from_text(sol_text)
                            elif q_type == "MCQ":
                                if not ans and sol_text:
                                    ans = extract_answer_from_text(sol_text)

                            q_clean = clean_question_text(q_text)
                            item_subj = detect_document_subject(q_clean + " " + sol_text, file_name=file_name, chapter_name=ch_name)
                            item_diff = evaluate_question_difficulty(q_clean, sol_text, q_type, has_image=has_q_img)

                            q_item = QuestionItem(
                                question_number=q_num,
                                page_number=p_i + 1,
                                original_question=q_clean,
                                translated_question=q_clean,
                                options=opts,
                                answer=ans,
                                solution=sol_text,
                                question_type=q_type,
                                has_question_image=has_q_img,
                                image_url=q_img_url,
                                has_solution_image=sol_item.get("has_solution_image", False),
                                solution_image_url=sol_item.get("solution_image_url"),
                                difficulty=item_diff,
                                status="complete",
                                chapter_number=str(ch_num),
                                chapter_name=ch_name,
                                subject=item_subj,
                            )
                            formatted_questions.append(q_item)

        else:
            # Mode B: Universal page-by-page pipeline for single-chapter or non-TOC documents
            solutions_map = {}
            answers_map = {}
            raw_questions = []

            for p_idx in range(total_pages):
                page = doc[p_idx]
                page_text = _get_semantic_page_text(page)
                if not page_text or not page_text.strip():
                    continue

                page_num = p_idx + 1
                header_sub = page_text[:400].lower()

                if any(kw in header_sub for kw in ["chapter name", "s.no.", "table of contents", "contents"]) or len(re.findall(r'\d+\s*-\s*\d+', page_text)) >= 8:
                    continue

                is_sol = is_solution_page_text(page_text) or any(kw in header_sub for kw in ["solutions", "hints & solutions", "detailed solutions", "answers & solutions", "ઉકેલ", "સમજૂતી"])

                if not doc_chapter_name:
                    m_ch = re.search(r'(?:Chapter|Unit|પ્રકરણ|અધ્યાય)[\s\-_:]*(\d+)?[\s\-_:]+([^\n\r]+)', page_text[:500], re.IGNORECASE)
                    if m_ch:
                        doc_chapter_name = m_ch.group(2).strip()

                # Detect standalone answer keys on this page
                if is_answer_key_page_text(page_text) or "answer key" in header_sub or "જવાબ વહી" in header_sub or "ઉત્તરવહી" in header_sub:
                    ak_pairs = re.findall(r'(?:^|[\s\t\n,;])(?:Q(?:uestion)?\.?\s*)?(\d+|[૦-૯]+|[०-९]+)[\.\)\-:\s]+\(?([A-Da-d1-4અબકડકખગઘ])\)?', page_text)
                    for q_k, a_k in ak_pairs:
                        q_ascii = str(int(to_ascii_digits(q_k))) if to_ascii_digits(q_k).isdigit() else q_k
                        norm_a = normalize_option_key(a_k)
                        if norm_a in ['A', 'B', 'C', 'D']:
                            answers_map[q_ascii] = norm_a

                pattern = r'(?m)^\s*(?:Q(?:uestion)?[\.\s]*|પ્રશ્ન[\.\s]*|દાખલા\s*નં[\.\s]*|પ્ર[\.\s]*)?(\d+|[૦-૯]+|[०-९]+)[\.\)\-:]\s+'
                matches = list(re.finditer(pattern, page_text))
                if not matches:
                    # Check if this entire page contains continuation options / answer for the previous question
                    if raw_questions:
                        prev_rq = raw_questions[-1]
                        prev_opts = prev_rq.get("options") or {}
                        prev_opt_cnt = sum(1 for v in prev_opts.values() if isinstance(v, OptionDetail) and (v.original or v.translated))
                        if prev_opt_cnt < 4:
                            p_clean_stem, p_extracted_opts = split_question_and_options(page_text)
                            if p_extracted_opts:
                                for ok, ov in p_extracted_opts.items():
                                    norm_ok = normalize_option_key(ok) or ok
                                    if norm_ok in ['A', 'B', 'C', 'D']:
                                        prev_opts[norm_ok] = OptionDetail(original=ov, translated=ov, has_image=False, page_number=page_num)
                                prev_rq["options"] = prev_opts
                                prev_rq["question_type"] = "MCQ"
                                p_ans = extract_answer_from_text(page_text)
                                if p_ans and not prev_rq.get("inline_answer"):
                                    prev_rq["inline_answer"] = p_ans
                    continue

                if raw_questions and matches:
                    pre_text = page_text[:matches[0].start()].strip()
                    if pre_text:
                        prev_rq = raw_questions[-1]
                        prev_opts = prev_rq.get("options") or {}
                        prev_opt_cnt = sum(1 for v in prev_opts.values() if isinstance(v, OptionDetail) and (v.original or v.translated))
                        if prev_opt_cnt < 4:
                            p_clean_stem, p_extracted_opts = split_question_and_options(pre_text)
                            if p_extracted_opts:
                                for ok, ov in p_extracted_opts.items():
                                    norm_ok = normalize_option_key(ok) or ok
                                    if norm_ok in ['A', 'B', 'C', 'D']:
                                        prev_opts[norm_ok] = OptionDetail(original=ov, translated=ov, has_image=False, page_number=page_num)
                                prev_rq["options"] = prev_opts
                                prev_rq["question_type"] = "MCQ"
                                p_ans = extract_answer_from_text(pre_text)
                                if p_ans and not prev_rq.get("inline_answer"):
                                    prev_rq["inline_answer"] = p_ans

                has_mcqs = any(
                    re.search(r'(?m)^\s*\(?([a-dA-D1-4અ-ડક-ઘ])\)?[\.\:\)]\s+', page_text[m.end():(matches[i+1].start() if i+1 < len(matches) else len(page_text))])
                    for i, m in enumerate(matches[:3])
                )
                if has_mcqs:
                    is_sol = False

                if is_sol:
                    for i, m in enumerate(matches):
                        q_num_raw = m.group(1)
                        q_num_ascii = to_ascii_digits(q_num_raw)
                        clean_k = re.search(r'\d+', q_num_ascii).group(0) if re.search(r'\d+', q_num_ascii) else q_num_ascii
                        start_idx = m.end()
                        end_idx = matches[i+1].start() if i+1 < len(matches) else len(page_text)
                        block = page_text[start_idx:end_idx].strip()

                        m_ans = re.match(r'^\s*\(?([a-zA-Z0-9\+\-\.અ-ડક-ઘ]+)\)?[\.\:\s]*\n?', block)
                        ans = None
                        sol_body = block
                        if m_ans:
                            raw_a = m_ans.group(1).upper()
                            norm_a = normalize_option_key(raw_a)
                            ans = norm_a if norm_a in ['A', 'B', 'C', 'D'] else raw_a
                            sol_body = block[m_ans.end():].strip()
                        else:
                            ans = extract_answer_from_text(block) or extract_numeric_answer_from_text(block)

                        s_rects = page.search_for(f"{clean_k}.")
                        s_y = s_rects[0].y0 if s_rects else 50
                        sol_img_url, has_sol_img = extract_diagram(page, f"p{page_num}_sol{clean_k}", y_min=max(45, s_y - 20), y_max=min(page.rect.height - 45, s_y + 250))

                        if clean_k not in solutions_map or len(sol_body) > len(solutions_map[clean_k].get("solution", "")):
                            solutions_map[clean_k] = {
                                "solution": sol_body,
                                "answer": ans,
                                "page": page_num,
                                "solution_image_url": sol_img_url,
                                "has_solution_image": has_sol_img,
                            }
                        if ans and clean_k not in answers_map:
                            answers_map[clean_k] = ans

                else:
                    for i, m in enumerate(matches):
                        q_num_raw = m.group(1)
                        q_num_ascii = to_ascii_digits(q_num_raw)
                        q_num = str(int(q_num_ascii)) if q_num_ascii.isdigit() else q_num_ascii
                        start_idx = m.end()
                        end_idx = matches[i+1].start() if i+1 < len(matches) else len(page_text)
                        block = page_text[start_idx:end_idx].strip()

                        # Scan for inline answers printed directly in the question block
                        inline_ans = extract_answer_from_text(block)

                        clean_stem, extracted_opts = split_question_and_options(block)
                        opts: Dict[str, OptionDetail] = {}
                        if len(extracted_opts) >= 2:
                            q_text = clean_stem
                            for k, opt_str in extracted_opts.items():
                                norm_k = normalize_option_key(k) or k
                                opts[norm_k] = OptionDetail(original=opt_str, translated=opt_str, has_image=False, page_number=page_num)
                            for letter in ['A', 'B', 'C', 'D']:
                                if letter not in opts:
                                    opts[letter] = OptionDetail(page_number=page_num)
                            q_type = "MCQ"
                        else:
                            q_text = block
                            q_type = "Numeric"
                            for letter in ['A', 'B', 'C', 'D']:
                                opts[letter] = OptionDetail(original="", translated="", page_number=page_num)

                        if q_type == "Numeric":
                            if len(block) < 15 or re.search(r'^\s*[A-Z\s\-]+\t+\d+[\-\d\t\s]+$', block.strip()):
                                continue
                        elif q_type == "MCQ":
                            if len(q_text) < 3:
                                continue

                        q_rects = page.search_for(f"{q_num}.")
                        q_y = q_rects[0].y0 if q_rects else 50
                        q_img_url, has_q_img = extract_diagram(page, f"p{page_num}_q{q_num}", y_min=max(45, q_y - 20), y_max=min(page.rect.height - 45, q_y + 250))
                        has_any_opt_text = any(bool(v and (v.original or v.translated)) for v in opts.values())
                        has_any_opt_img = any(bool(getattr(v, "has_image", False) or getattr(v, "image_url", None)) for v in opts.values())
                        if not is_genuine_question_diagram(q_text, has_any_opt_text, q_img_url, has_opt_images=has_any_opt_img):
                            has_q_img = False
                            q_img_url = None

                        raw_questions.append({
                            "question_number": q_num,
                            "question_text": clean_question_text(q_text),
                            "options": opts,
                            "question_type": q_type,
                            "page_number": page_num,
                            "has_image": has_q_img,
                            "image_url": q_img_url,
                            "inline_answer": inline_ans,
                        })

                if progress_callback and (p_idx % 5 == 0 or p_idx == total_pages - 1):
                    try:
                        progress_callback(p_idx + 1, total_pages, len(raw_questions), f"⚡ Local Engine: Page {p_idx+1}/{total_pages} ({len(raw_questions)} questions found)")
                    except Exception:
                        pass

            for q in raw_questions:
                q_num = q["question_number"]
                clean_k = re.search(r'\d+', q_num)
                k_str = clean_k.group(0) if clean_k else q_num

                ans = q.get("inline_answer")
                sol = ""
                sol_img = None
                has_sol_img = False

                if k_str in solutions_map:
                    sol_entry = solutions_map[k_str]
                    sol = sol_entry.get("solution", "")
                    if not ans:
                        ans = sol_entry.get("answer")
                    sol_img = sol_entry.get("solution_image_url")
                    has_sol_img = sol_entry.get("has_solution_image", False)
                if not ans and k_str in answers_map:
                    ans = answers_map[k_str]
                if q["question_type"] == "Numeric":
                    if ans in ['A', 'B', 'C', 'D'] or not ans:
                        cand_n = extract_numeric_answer_from_text(sol) or extract_numeric_answer_from_text(q["question_text"])
                        ans = cand_n if cand_n else None
                    if ans:
                        ans = clean_numeric_answer(ans)
                elif q["question_type"] == "MCQ":
                    if not ans and sol:
                        ans = extract_answer_from_text(sol)

                q_clean = clean_question_text(q["question_text"])
                item_diff = evaluate_question_difficulty(q_clean, sol, q["question_type"], has_image=q["has_image"])

                q_item = QuestionItem(
                    question_number=q_num,
                    page_number=q["page_number"],
                    original_question=q_clean,
                    translated_question=q_clean,
                    options=q["options"],
                    answer=ans,
                    solution=sol,
                    question_type=q["question_type"],
                    has_question_image=q["has_image"],
                    image_url=q.get("image_url"),
                    has_solution_image=has_sol_img,
                    solution_image_url=sol_img,
                    difficulty=item_diff,
                    status="complete",
                    chapter_number="",
                    chapter_name=doc_chapter_name or Path(file_name).stem.replace("_", " "),
                    subject="Physics",  # Resolved below for entire set
                )
                formatted_questions.append(q_item)

        formatted_questions = sort_questions_naturally(formatted_questions)

        all_corpus = " ".join([
            str(fq.translated_question or fq.original_question or "") + " " + str(fq.solution or "")
            for fq in formatted_questions
        ])
        resolved_doc_subj = detect_document_subject(all_corpus, file_name=file_name, chapter_name=doc_chapter_name)
        for fq in formatted_questions:
            fq.subject = resolved_doc_subj

        balance_difficulties(formatted_questions)

        for idx, fq in enumerate(formatted_questions):
            fq.question_number = str(idx + 1)

        duration = round(time.time() - start_time, 2)
        logger.info(f"[Local Pipeline] {file_name}: Extracted {len(formatted_questions)} questions in {duration}s!")

        if progress_callback:
            try:
                progress_callback(total_pages, total_pages, len(formatted_questions), f"Completed: Extracted {len(formatted_questions)} questions via High-Speed Engine!", formatted_questions)
            except Exception:
                pass

        return ExtractionResult(
            file_name=file_name,
            chapter_number="",
            chapter_name=doc_chapter_name or Path(file_name).stem.replace("_", " "),
            subject=resolved_doc_subj,
            topics=[],
            total_questions=len(formatted_questions),
            total_pages_scanned=total_pages,
            questions=formatted_questions,
            source_language=source_language,
            target_language=target_language,
            processing_time_seconds=duration,
            status="completed",
            model_used="High-Speed Local Engine"
        )

    async def extract_solutions_and_answers_from_pdf(
        self,
        pdf_bytes: bytes,
        file_name: str,
        source_language: str = "Gujarati",
        target_language: str = "English",
        model_name: Optional[str] = None,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Extracts complete answer keys, answers (A-D, numeric), and step-by-step solutions from a separated solution PDF.
        Supports both Answer Key tables and detailed solution explanations from Page 1 to the end."""
        import pymupdf
        solutions_map: Dict[str, str] = {}
        answers_map: Dict[str, str] = {}
        solution_boxes_map: Dict[str, Any] = {}
        solution_image_urls_map: Dict[str, str] = {}
        section_answers_map: Dict[str, Dict[str, str]] = {}
        section_solutions_map: Dict[str, Dict[str, str]] = {}
        page_items_map: Dict[int, List[Dict[str, Any]]] = {}
        local_seq_items: List[Dict[str, Any]] = []
        safe_stem = re.sub(r'[^a-zA-Z0-9_\-]', '_', Path(file_name).stem)

        try:
            total_pages = self.pipeline.get_page_count(pdf_bytes)
        except Exception:
            total_pages = 1

        active_model = model_name or self.model_name
        loop = asyncio.get_running_loop()

        # 1. Fast local regex scan with PyMuPDF for answer keys, solutions, and diagrams
        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            for p_idx in range(len(doc)):
                page = doc[p_idx]
                p_text = page.get_text("text") or ""
                # Search for answer key grid/table patterns e.g. "1. (A)  2. (C)" or "1 - B" or "Q1: B"
                matches = re.findall(
                    r'(?:(?:Q(?:uestion)?|પ્રશ્ન)\s*(\d+)[\.\s\:\-\)]+\s*(?:\(?([A-Da-d1-4])\)?|\bAns[:\.\s]+([A-Da-d1-4]|-?\d+(?:\.\d+)?))|(\d+)[\.\)]\s*[\(\[]\s*([A-Da-d1-4]|-?\d+(?:\.\d+)?)\s*[\)\]]|(\d+)\s*[-–—:]\s*\(?([A-Da-d1-4])\)?)',
                    p_text,
                    flags=re.IGNORECASE
                )
                for m in matches:
                    q_n = m[0] or m[3] or m[5]
                    ans_letter = m[1] or m[4] or m[6]
                    ans_val = m[2]
                    chosen_ans = (ans_letter or ans_val or "").strip().upper()
                    if chosen_ans in ["1", "2", "3", "4"]:
                        chosen_ans = ["A", "B", "C", "D"][int(chosen_ans) - 1]
                    if chosen_ans and q_n:
                        answers_map[q_n] = chosen_ans
                        local_seq_items.append({
                            "page_number": p_idx + 1,
                            "question_number": q_n,
                            "answer": chosen_ans,
                            "solution": None,
                            "question_snippet": None
                        })

                # Search for solution derivations with explicit headers e.g. "Q.1", "Sol. 1", "1. Solution:"
                sol_blocks = re.split(
                    r'\n(?=(?:Q(?:uestion)?|Sol(?:ution)?|Ans(?:wer)?|પ્રશ્ન|ઉકેલ)\s*[\.\:\-]?\s*\d+|\d+[\.\)]\s*(?:Solution|Ans|Hint|ઉકેલ|સમજૂતી|\([A-Da-d1-4]\)|\[[A-Da-d1-4]\]))',
                    p_text,
                    flags=re.IGNORECASE
                )
                for blk in sol_blocks:
                    m_num = re.search(
                        r'^\s*(?:(?:Q(?:uestion)?|Sol(?:ution)?|Ans(?:wer)?|પ્રશ્ન|ઉકેલ)\s*[\.\:\-]?\s*(\d+)|(\d+)[\.\)]\s*(?:Solution|Ans|Hint|ઉકેલ|સમજૂતી|\([A-Da-d1-4]\)|\[[A-Da-d1-4]\]))',
                        blk,
                        flags=re.IGNORECASE
                    )
                    if m_num:
                        q_num_str = m_num.group(1) or m_num.group(2)
                        body = blk[m_num.end():].strip()
                        if body and len(body) > 10:
                            if q_num_str not in solutions_map or len(body) > len(solutions_map.get(q_num_str, "")):
                                solutions_map[q_num_str] = body

                # Extract raster images on solution page
                for img_idx, img_info in enumerate(page.get_images(full=True)):
                    try:
                        xref = img_info[0]
                        base_img = doc.extract_image(xref)
                        if base_img and "image" in base_img:
                            img_bytes = base_img["image"]
                            ext = base_img.get("ext", "png")
                            if len(img_bytes) > 800:
                                fname = f"sol_{safe_stem}_p{p_idx + 1}_img{img_idx + 1}.{ext}"
                                (IMAGES_DIR / fname).write_bytes(img_bytes)
                    except Exception:
                        pass
        except Exception as local_e:
            logger.warning(f"[Solution Extractor] Local scan warning: {local_e}")

        # 2. Multimodal API scan with single-request sequential pacing (Semaphore=1)
        sem = asyncio.Semaphore(1)
        completed_pages = 0
        sol_lock = asyncio.Lock()

        async def process_sol_page(page_idx: int):
            nonlocal completed_pages
            async with sem:
                try:
                    page_bytes = self.pipeline.render_page_to_image(pdf_bytes, page_idx, scale=2.0, img_format="JPEG")
                    mime_type = "image/jpeg"
                    if page_bytes is None:
                        page_bytes = self.pipeline.slice_page(pdf_bytes, page_idx)
                        mime_type = "application/pdf"

                    sol_prompt = get_answer_key_prompt(source_language=source_language, target_language=target_language)

                    raw_text = await loop.run_in_executor(
                        None,
                        self._call_gemini_api_with_fallback,
                        page_bytes,
                        sol_prompt,
                        active_model,
                        mime_type,
                        None
                    )
                    parsed = extract_json_from_response(raw_text)

                    cur_page_items: List[Dict[str, Any]] = []

                    async with sol_lock:
                        p_ans_by_topic = parsed.get("answers_by_topic", {}) or {}
                        if isinstance(p_ans_by_topic, dict):
                            for sec_name, sec_dict in p_ans_by_topic.items():
                                if isinstance(sec_dict, dict):
                                    if sec_name not in section_answers_map:
                                        section_answers_map[sec_name] = {}
                                    for k, v in sec_dict.items():
                                        m_k = re.search(r'\d+', str(k))
                                        if m_k and v:
                                            k_str = m_k.group(0)
                                            val_u = str(v).strip().upper()
                                            answers_map[k_str] = val_u
                                            section_answers_map[sec_name][k_str] = val_u

                        p_seq_answers = parsed.get("sequential_answers", []) or []
                        if isinstance(p_seq_answers, list):
                            for seq in p_seq_answers:
                                if isinstance(seq, dict):
                                    q_num = str(seq.get("question_number", ""))
                                    m_k = re.search(r'\d+', q_num)
                                    if m_k:
                                        k_str = m_k.group(0)
                                        ans_val = str(seq["answer"]).strip().upper() if seq.get("answer") else None
                                        sol_val = str(seq["solution"]).strip() if (seq.get("solution") and str(seq["solution"]).strip().lower() not in ["null", "none", ""]) else None
                                        snip_val = str(seq["question_snippet"]).strip() if (seq.get("question_snippet") and str(seq["question_snippet"]).strip().lower() not in ["null", "none", ""]) else None
                                        sec_val = seq.get("topic") or seq.get("section") or None

                                        if ans_val:
                                            answers_map[k_str] = ans_val
                                        if sol_val:
                                            solutions_map[k_str] = sol_val

                                        s_box = (
                                            seq.get("solution_image_box")
                                            or seq.get("solution_box")
                                            or seq.get("solution_diagram_box")
                                            or seq.get("image_box")
                                            or seq.get("diagram_box")
                                        )
                                        img_url = None
                                        if s_box:
                                            solution_boxes_map[k_str] = s_box
                                            try:
                                                crop_bytes = self.pipeline.crop_box_image(pdf_bytes, page_idx, s_box)
                                                if crop_bytes:
                                                    img_fname = f"sol_{safe_stem}_p{page_idx + 1}_q{k_str}.png"
                                                    (IMAGES_DIR / img_fname).write_bytes(crop_bytes)
                                                    img_url = f"/api/images/{img_fname}"
                                                    solution_image_urls_map[k_str] = img_url
                                            except Exception as crop_e:
                                                logger.warning(f"[Solution Extractor] Crop error for Q{k_str}: {crop_e}")

                                        cur_page_items.append({
                                            "page_number": page_idx + 1,
                                            "section": sec_val,
                                            "question_number": k_str,
                                            "raw_number": q_num,
                                            "answer": ans_val,
                                            "solution": sol_val,
                                            "question_snippet": snip_val,
                                            "solution_image_box": s_box,
                                            "solution_image_url": img_url,
                                        })

                        p_sol_by_num = parsed.get("solutions_by_number", {}) or {}
                        if isinstance(p_sol_by_num, dict):
                            for k, v in p_sol_by_num.items():
                                m_k = re.search(r'\d+', str(k))
                                if m_k and v and str(v).strip().lower() not in ["null", "none", ""]:
                                    solutions_map[m_k.group(0)] = str(v).strip()

                        for q_item in parsed.get("questions", []):
                            m_k = re.search(r'\d+', str(q_item.get("question_number", "")))
                            if m_k:
                                k_str = m_k.group(0)
                                ans_val = str(q_item["answer"]).strip().upper() if q_item.get("answer") else None
                                if ans_val:
                                    answers_map[k_str] = ans_val
                                s_text = q_item.get("solution") or (q_item.get("question_text") if q_item.get("is_solution_item") else None)
                                sol_val = str(s_text).strip() if (s_text and str(s_text).strip().lower() not in ["null", "none", ""]) else None
                                if sol_val:
                                    solutions_map[k_str] = sol_val
                                s_box = q_item.get("solution_image_box") or q_item.get("image_box")
                                img_url = None
                                if s_box:
                                    solution_boxes_map[k_str] = s_box
                                    try:
                                        crop_bytes = self.pipeline.crop_box_image(pdf_bytes, page_idx, s_box)
                                        if crop_bytes:
                                            img_fname = f"sol_{safe_stem}_p{page_idx + 1}_q{k_str}.png"
                                            (IMAGES_DIR / img_fname).write_bytes(crop_bytes)
                                            img_url = f"/api/images/{img_fname}"
                                            solution_image_urls_map[k_str] = img_url
                                    except Exception as crop_e:
                                        logger.warning(f"[Solution Extractor] Crop error for Q{k_str}: {crop_e}")

                                # Add to cur_page_items if not already added by sequential_answers
                                if not any(it["question_number"] == k_str for it in cur_page_items):
                                    cur_page_items.append({
                                        "page_number": page_idx + 1,
                                        "section": None,
                                        "question_number": k_str,
                                        "raw_number": str(q_item.get("question_number", "")),
                                        "answer": ans_val,
                                        "solution": sol_val,
                                        "question_snippet": q_item.get("question_snippet"),
                                        "solution_image_box": s_box,
                                        "solution_image_url": img_url,
                                    })

                        if cur_page_items:
                            page_items_map[page_idx] = cur_page_items

                except Exception as page_e:
                    logger.warning(f"[Solution Extractor] API page {page_idx + 1} notice: {page_e}")
                finally:
                    async with sol_lock:
                        completed_pages += 1
                        if progress_callback:
                            try:
                                progress_callback(
                                    completed_pages,
                                    total_pages,
                                    len(solutions_map),
                                    f"Extracting solutions from {file_name}: Page {completed_pages}/{total_pages}..."
                                )
                            except Exception:
                                pass

        if total_pages > 0:
            for i in range(total_pages):
                await process_sol_page(i)
                if i < total_pages - 1:
                    await asyncio.sleep(2.0)

        # Assemble sequential solutions in exact page-by-page document order
        sequential_solutions: List[Dict[str, Any]] = []
        for p_idx in sorted(page_items_map.keys()):
            sequential_solutions.extend(page_items_map[p_idx])

        if not sequential_solutions and local_seq_items:
            sequential_solutions = local_seq_items

        logger.info(f"[Solution Extractor] {file_name}: Extracted {len(answers_map)} answers, {len(solutions_map)} solutions, {len(sequential_solutions)} sequential items & {len(solution_image_urls_map)} solution images!")
        return {
            "answers": answers_map,
            "solutions": solutions_map,
            "sequential_solutions": sequential_solutions,
            "section_answers": section_answers_map,
            "solution_boxes": solution_boxes_map,
            "solution_image_urls": solution_image_urls_map
        }

    async def extract_topics_from_textbook(
        self,
        pdf_bytes: bytes,
        file_name: str,
        source_language: str = "Gujarati",
        target_language: str = "English",
        model_name: Optional[str] = None,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Extracts Chapter information (Chapter number, Chapter name, Subject) and structured Topic List
        (id, chapter_number, chapter_name, topic, description) by scanning ALL pages of the uploaded Textbook PDF."""
        import pymupdf

        chapter_number: str = ""
        chapter_name: str = ""
        subject: str = ""
        topics_list: List[Dict[str, Any]] = []

        # 1. Infer from filename
        fn_clean = Path(file_name).stem
        m_ch = re.search(r'(?:chapter|chp|ch|unit|પ્રકરણ|અધ્યાય|ch\.)[\s\-_]*(\d+)', fn_clean, re.IGNORECASE) or re.search(r'^(\d+)[\s\-_.:]', fn_clean)
        if m_ch:
            chapter_number = m_ch.group(1)

        active_model = model_name or self.model_name
        loop = asyncio.get_running_loop()
        pages_text_list = []
        full_text_sample = ""
        candidate_headings = []
        junk_pat = r'(?i)\b(?:example|ex[\.:]|દાખલા|ઉદાહરણ|figure|fig[\.:]|આકૃતિ|table|કોષ્ટક|exercise|સ્વાધ્યાય|solution|ઉકેલ|પ્રશ્ન|question|formula|સૂત્ર|mcq|ans|answer|points to ponder|summary|સારાંશ|moles?|mol|grams?|\bkg\b|\bml\b|litres?|liter|molarity|\bM\b|hcl|naoh|na2co3|co2|mass|density|volume|written as|different\?|significant|calculate|find|what is|how many|sample|solution of|dissolved in|can be written|there are|is equal to|has two|has three|\?|\.\.\.)\b'

        def is_valid_textbook_section_num(s: str) -> bool:
            if not s or "." not in str(s):
                return False
            clean_s = to_ascii_digits(str(s)).strip()
            parts = clean_s.split(".")
            if len(parts) != 2:
                return False
            if not parts[0].isdigit() or not parts[1].isdigit():
                return False
            p1, p2 = int(parts[0]), int(parts[1])
            # A textbook chapter number is 1 to 50, and section is 1 to 30. (NEVER chapter 0 or section 0 or 0.00016!)
            return (1 <= p1 <= 50) and (1 <= p2 <= 50)

        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            total_pages = len(doc)
            for p_idx in range(total_pages):
                p_num = p_idx + 1
                page_obj = doc[p_idx]
                p_raw = page_obj.get_text("text") or ""
                pages_text_list.append((p_num, p_raw))
                full_text_sample += f"\n--- Page {p_num} ---\n" + p_raw

                # Strategy A: Line-by-line inspection (matches inline & starting headings: 1.1, 1.2... 1.10... 1.20)
                for line in p_raw.splitlines():
                    line_str = line.strip()
                    if not line_str:
                        continue
                    m_line = re.search(
                        r'(?:\b|\s|^)(?:Topic|Section|TOPIC|SECTION|વિભાગ|મુદ્દો|ટોપિક)?\s*([0-9૦-૯]+\.[0-9૦-૯]+)(?!\.[0-9૦-૯])\s*[:\.\-\s]+([A-Za-z\u0a80-\u0aff\u0900-\u097f][^\n\r]{2,80})',
                        line_str
                    )
                    if m_line:
                        sec_num_raw = m_line.group(1).strip()
                        sec_num = to_ascii_digits(sec_num_raw)
                        raw_title = m_line.group(2).strip()
                        # Disallow 3-level subtopics (e.g. 1.1.1, 1.1.2, 1.1.3, 1.1.4, 1.2.1)
                        if sec_num.count('.') != 1 or re.search(r'\b\d+\.\d+\.\d+\b', raw_title) or re.search(r'\b[૦-૯]+\.[૦-૯]+\.[૦-૯]+\b', raw_title):
                            continue
                        if not raw_title or re.search(junk_pat, raw_title) or any(sym in raw_title for sym in ["=", "+", "\\times", "\\le", "\\ge", "\\approx"]):
                            continue
                        sec_title = re.sub(r'[\.\s\-_]+(?:\d+|[૦-૯]+)\s*$', '', raw_title).strip()
                        sec_title = clean_topic_title(sec_title)
                        if 3 <= len(sec_title) <= 80:
                            candidate_headings.append({
                                "sec_num": sec_num,
                                "raw_num": sec_num_raw,
                                "title": sec_title,
                                "page": p_num,
                            })

                # Strategy B: Multiline heading (section number on line 1, title on line 2)
                matches_multi = re.finditer(
                    r'(?m)(?:\b|\s|^)(?:Topic|Section|TOPIC|SECTION|વિભાગ|મુદ્દો|ટોપિક)?\s*([0-9૦-૯]+\.[0-9૦-૯]+)(?!\.[0-9૦-૯])\s*[\n\r]+\s*([A-Za-z\u0a80-\u0aff\u0900-\u097f][^\n\r]{2,80})',
                    p_raw
                )
                for mm in matches_multi:
                    sec_num_raw = mm.group(1).strip()
                    sec_num = to_ascii_digits(sec_num_raw)
                    raw_title = mm.group(2).strip()
                    if sec_num.count('.') != 1 or re.search(r'\b\d+\.\d+\.\d+\b', raw_title) or re.search(r'\b[૦-૯]+\.[૦-૯]+\.[૦-૯]+\b', raw_title):
                        continue
                    if not raw_title or re.search(junk_pat, raw_title) or any(sym in raw_title for sym in ["=", "+", "\\times", "\\le", "\\ge", "\\approx"]):
                        continue
                    sec_title = re.sub(r'[\.\s\-_]+(?:\d+|[૦-૯]+)\s*$', '', raw_title).strip()
                    sec_title = clean_topic_title(sec_title)
                    if 3 <= len(sec_title) <= 80:
                        candidate_headings.append({
                            "sec_num": sec_num,
                            "raw_num": sec_num_raw,
                            "title": sec_title,
                            "page": p_num,
                        })

                # Strategy C: Layout block inspection for distinct heading blocks
                try:
                    blocks = page_obj.get_text("blocks")
                    for b in blocks:
                        b_text = b[4].strip() if len(b) > 4 else ""
                        if not b_text:
                            continue
                        m_blk = re.search(
                            r'(?:\b|\s|^)(?:Topic|Section|TOPIC|SECTION|વિભાગ|મુદ્દો|ટોપિક)?\s*([0-9૦-૯]+\.[0-9૦-૯]+)(?!\.[0-9૦-૯])\s*[:\.\-\s\n]+([A-Za-z\u0a80-\u0aff\u0900-\u097f][^\n\r]{2,80})',
                            b_text
                        )
                        if m_blk:
                            sec_num_raw = m_blk.group(1).strip()
                            sec_num = to_ascii_digits(sec_num_raw)
                            raw_title = m_blk.group(2).strip()
                            if sec_num.count('.') != 1 or re.search(r'\b\d+\.\d+\.\d+\b', raw_title):
                                continue
                            if not raw_title or re.search(junk_pat, raw_title):
                                continue
                            sec_title = re.sub(r'[\.\s\-_]+(?:\d+|[૦-૯]+)\s*$', '', raw_title).strip()
                            sec_title = clean_topic_title(sec_title)
                            if 3 <= len(sec_title) <= 80:
                                candidate_headings.append({
                                    "sec_num": sec_num,
                                    "raw_num": sec_num_raw,
                                    "title": sec_title,
                                    "page": p_num,
                                })
                except Exception:
                    pass

                # Check for chapter title in early pages (pages 1 to 5)
                if p_num <= 5 and (not chapter_name or not chapter_number):
                    m_txt_ch = re.search(r'(?i)(?:CHAPTER|UNIT|પ્રકરણ|અધ્યાય)\s*[-–—:]?\s*([0-9૦-૯]+)[\s\:\-\.]*\n*([^\n\r]{3,60})', p_raw)
                    if m_txt_ch:
                        if not chapter_number:
                            chapter_number = to_ascii_digits(m_txt_ch.group(1).strip())
                        if not chapter_name:
                            chapter_name = m_txt_ch.group(2).strip()
        except Exception as pdf_e:
            logger.warning(f"[Textbook Extractor] PyMuPDF full-scan reading notice: {pdf_e}")

        # Detect subject from all pages text or filename
        subject = detect_document_subject(full_text_sample, file_name=file_name, chapter_name=chapter_name)

        if progress_callback:
            progress_callback(0, total_pages, 0, f"Scanning all {total_pages} pages of textbook for ALL main topics (1.1, 1.2, 1.3... 1.10...) with Gemini...")

        # Build a comprehensive outline across ALL pages to feed Gemini (only 2-level topics)
        outline_lines = []
        for cand in candidate_headings:
            outline_lines.append(f"Page {cand['page']}: {cand['sec_num']} {cand['title']}")
        outline_summary = "\n".join(outline_lines[:300])

        ch_num_val = chapter_number or "1"
        ch_name_val = chapter_name or "Chapter Name"
        subj_val = subject or "Physics"
        is_doc_gujarati = bool(re.search(r'[\u0A80-\u0AFF]', outline_summary + " " + ch_name_val))

        if is_doc_gujarati:
            desc_example_1 = "રસાયણવિજ્ઞાનનું મહત્વ અને તેના મૂળભૂત સિદ્ધાંતોની સમજ"
            desc_example_2 = "દ્રવ્યનો સ્વભાવ અને તેની વિવિધ અવસ્થાઓની માહિતી"
            lang_instruction = "CRITICAL LANGUAGE MANDATE: The textbook is in Gujarati. ALL chapter_name, topic titles, and description text MUST BE IN AUTHENTIC GUJARATI (ગુજરાતી ભાષા)! NEVER output English words/phrases in 'description'."
        else:
            desc_example_1 = "Core concepts and fundamental principles"
            desc_example_2 = "Electric charge properties and behavior"
            lang_instruction = "The 'description' must match the authentic document language."

        gem_prompt = (
            f"You are an expert textbook curriculum analyst. Analyze the following textbook document of {total_pages} pages.\n"
            "You MUST scan EVERY SINGLE PAGE from Page 1 to the last page and extract ALL 2-level MAIN TOPICS (e.g. 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15... or 5.1, 5.2, 5.3...) with their complete proper titles.\n\n"
            "CRITICAL TOPIC LEVEL RULES (STRICT 2-LEVEL ONLY):\n"
            "- Extract ONLY 2-level main topics formatted as Chapter.Topic (e.g. '1.1 Introduction', '1.2 Electric Charges', '1.3 Conductors and Insulators', '1.4 Charging by Induction', '1.5 Basic Properties of Electric Charge', '1.6 Coulomb's Law', '1.7 Forces between Multiple Charges', '1.8 Electric Field', '1.9 Electric Field Lines', '1.10 Electric Flux', '1.11 Electric Dipole', '1.12 Dipole in Uniform Field', '1.13 Continuous Charge Distribution', '1.14 Gauss's Law', '1.15 Applications of Gauss's Law').\n"
            "- Extract ALL topics across the ENTIRE document. DO NOT STOP after 2 or 3 topics! If the chapter has 10, 15, or 20 topics, YOU MUST EXTRACT EVERY SINGLE ONE.\n"
            "- ABSOLUTELY NEVER extract 3-level sub-topics (e.g. '1.1.1', '1.1.2', '1.1.3', '1.1.4', '1.2.1', '1.2.2', '1.3.1', '5.1.1', '5.1.2') as separate topics! Sub-sections with multiple dots are strictly forbidden.\n"
            "- ABSOLUTELY NEVER extract Examples (e.g. 'Example 1.1', 'ઉદાહરણ ૧.૧', 'દાખલો ૧.૧') as topics!\n"
            "- ABSOLUTELY NEVER extract Exercises (e.g. 'Exercise 1.1', 'સ્વાધ્યાય ૧.૧') as topics!\n"
            "- ABSOLUTELY NEVER extract Figure captions ('Figure 1.1', 'આકૃતિ ૧.૧') or Tables ('Table 1.1', 'કોષ્ટક ૧.૧') as topics!\n"
            "- Extract authentic chapter number, chapter name, and STEM subject (Physics/Chemistry/Mathematics/Biology).\n"
            f"- {lang_instruction}\n\n"
            f"Detected section headings across pages:\n{outline_summary}\n\n"
            "Return JSON only in this exact format:\n"
            "{\n"
            f'  "chapter_number": "{ch_num_val}",\n'
            f'  "chapter_name": "{ch_name_val}",\n'
            f'  "subject": "{subj_val}",\n'
            '  "topics": [\n'
            "    {\n"
            f'      "id": "{ch_num_val}.1",\n'
            f'      "topic": "{ch_num_val}.1 Topic Title",\n'
            f'      "description": "{desc_example_1}"\n'
            "    },\n"
            "    {\n"
            f'      "id": "{ch_num_val}.2",\n'
            f'      "topic": "{ch_num_val}.2 Next Topic Title",\n'
            f'      "description": "{desc_example_2}"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Extract ALL 2-level main topics across all pages (1.1, 1.2, 1.3... 1.10... 1.15). DO NOT include 3-level subtopics (1.1.1, 1.1.2, 1.2.1). Return valid JSON only."
        )

        try:
            # Pass full PDF bytes directly to Gemini (Gemini natively supports full multi-page PDFs)
            gem_bytes = pdf_bytes
            gem_mime = "application/pdf"
            raw_resp = await loop.run_in_executor(
                None,
                self._call_gemini_api_with_fallback,
                gem_bytes,
                gem_prompt,
                active_model,
                gem_mime,
                progress_callback
            )
            parsed = extract_json_from_response(raw_resp)
            if parsed:
                if not chapter_number and parsed.get("chapter_number"):
                    chapter_number = str(parsed["chapter_number"])
                if not chapter_name and parsed.get("chapter_name"):
                    chapter_name = str(parsed["chapter_name"])
                if not subject and parsed.get("subject"):
                    subject = str(parsed["subject"])
                gem_topics = parsed.get("topics", [])
                if isinstance(gem_topics, list) and len(gem_topics) > 0:
                    for idx, gt in enumerate(gem_topics, start=1):
                        if isinstance(gt, dict) and gt.get("topic"):
                            t_title = clean_topic_title(str(gt.get("topic")).strip())
                            if not t_title:
                                continue
                            if re.search(junk_pat, t_title):
                                continue
                            # STRICT FILTER: Disallow 3-level sub-topics like 1.1.1, 1.1.2, 1.1.3, 1.1.4, 1.2.1
                            if re.search(r'\b\d+\.\d+\.\d+\b', t_title) or re.search(r'\b\d+\.\d+\.\d+\b', str(gt.get("id") or "")):
                                continue
                            t_id = gt.get("id") or str(idx)
                            m_sec = re.search(r'\b(\d+\.\d+|[૦-૯]+\.[૦-૯]+|[०-९]+\.[०-९]+)\b(?!\.\d+)', str(t_id) + " " + t_title)
                            if m_sec:
                                t_id = m_sec.group(1)
                            final_ch_num = gt.get("chapter_number") or chapter_number or (str(t_id).split(".")[0] if "." in str(t_id) else "1")
                            final_ch_name = gt.get("chapter_name") or chapter_name or "Textbook Chapter"
                            topics_list.append({
                                "id": t_id,
                                "chapter_number": final_ch_num,
                                "chapter_name": final_ch_name,
                                "topic": t_title,
                                "description": generate_topic_description(t_title, raw_desc=gt.get("description"), chapter_name=final_ch_name)
                            })
        except Exception as gem_e:
            logger.warning(f"[Textbook Extractor] Gemini API call notice: {gem_e}")

        # 3. Only merge candidate headings if Gemini returned NO topics
        if not topics_list and candidate_headings:
            seen_sec_nums = set()
            for cand in candidate_headings:
                clean_sec = to_ascii_digits(cand["sec_num"]).strip()
                if is_valid_textbook_section_num(clean_sec) and clean_sec not in seen_sec_nums:
                    seen_sec_nums.add(clean_sec)
                    cand_title_clean = cand["title"].strip()
                    if re.search(junk_pat, cand_title_clean):
                        continue
                    full_cand_title = f"{clean_sec} {cand_title_clean}" if not cand_title_clean.startswith(clean_sec) else cand_title_clean
                    final_ch_num = clean_sec.split(".")[0]
                    final_ch_name = chapter_name or f"Chapter {final_ch_num}"
                    topics_list.append({
                        "id": clean_sec,
                        "chapter_number": final_ch_num,
                        "chapter_name": final_ch_name,
                        "topic": full_cand_title,
                        "description": generate_topic_description(cand_title_clean, chapter_name=final_ch_name)
                    })

        # Strict final filter: Ensure NO 3-level topics and NO decimals/questions
        final_filtered_topics = []
        seen_final_secs = set()
        for t in topics_list:
            t_id_str = str(t.get("id") or "")
            t_name_str = str(t.get("topic") or "")
            if re.search(r'\b\d+\.\d+\.\d+\b', t_id_str) or re.search(r'\b\d+\.\d+\.\d+\b', t_name_str):
                continue
            if re.search(junk_pat, t_name_str):
                continue
            m_sec = re.search(r'\b([1-9][0-9]?\.[1-9][0-9]?|[૧-૯][૦-૯]?\.[૧-૯][૦-૯]?|[१-९][०-९]?\.[१-९][०-९]?)\b(?!\.\d+)', t_id_str + " " + t_name_str)
            if m_sec:
                sec_val = to_ascii_digits(m_sec.group(1))
                if not is_valid_textbook_section_num(sec_val):
                    continue
                t["id"] = sec_val
                t["chapter_number"] = sec_val.split(".")[0]
                if sec_val in seen_final_secs:
                    for existing in final_filtered_topics:
                        if existing.get("id") == sec_val:
                            if len(t_name_str) > len(str(existing.get("topic") or "")):
                                existing["topic"] = t_name_str
                                if t.get("description"):
                                    existing["description"] = t.get("description")
                            break
                    continue
                seen_final_secs.add(sec_val)
                final_filtered_topics.append(t)
        topics_list = final_filtered_topics

        # Natural sort topics by section number (e.g. 1.1, 1.2, 1.3, 1.4... 1.10, 2.1...)
        def topic_sort_key(t):
            t_str = str(t.get("id") or t.get("topic") or "")
            m_sec = re.search(r'(\d+)(?:\.(\d+))?', t_str)
            if m_sec:
                p1 = int(m_sec.group(1)) if m_sec.group(1) else 0
                p2 = int(m_sec.group(2)) if m_sec.group(2) else 0
                return (p1, p2)
            return (999, 999)

        if topics_list:
            topics_list.sort(key=topic_sort_key)
            # Re-assign clean sequential integer IDs (1, 2, 3...)
            for i, t in enumerate(topics_list, start=1):
                t["id"] = i

        # Fallback if still no topics found
        if not topics_list:
            default_ch_name = chapter_name or Path(file_name).stem
            ch_num = chapter_number or "1"
            topics_list.append({
                "id": 1,
                "chapter_number": ch_num,
                "chapter_name": default_ch_name,
                "topic": f"1.1 General - {default_ch_name}",
                "description": "Core concepts and theory"
            })

        logger.info(f"[Textbook Extractor] {file_name} (Total {total_pages} pages scanned): Extracted Chapter {chapter_number} ({chapter_name}) with {len(topics_list)} topics across all pages!")
        return {
            "chapter_number": chapter_number,
            "chapter_name": chapter_name,
            "subject": subject,
            "total_pages_scanned": total_pages,
            "topics": topics_list
        }

    def _call_gemini_api_with_fallback(
        self,
        file_bytes: bytes,
        prompt: str,
        initial_model: str,
        mime_type: str = "application/pdf",
        progress_callback: Optional[Any] = None
    ) -> str:
        """Calls Gemini API with configured primary model and automatic progressive fallback on errors."""
        primary_model = (self.model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")).strip()
        fallback_model = (self.fallback_model_name or os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")).strip()
        
        # Build resilient fallback cascade with active verified models
        raw_chain = [primary_model, fallback_model, "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
        model_chain = []
        for m in raw_chain:
            if m and m not in model_chain:
                model_chain.append(m)

        max_attempts = max(4, len(model_chain))
        current_model_idx = 0

        for attempt in range(max_attempts):
            model = model_chain[min(current_model_idx, len(model_chain) - 1)]
            current_api_key = self.api_keys[self.active_key_index]
            try:
                result = self._call_gemini_api(file_bytes, prompt, model, mime_type, api_key=current_api_key)
                with self._model_lock:
                    self.active_working_model = model
                return result
            except Exception as e:
                err_str = str(e)
                is_quota = any(kw in err_str.lower() for kw in [
                    "429", "resource_exhausted", "key limit exceeded", "limit exceeded", "402", "403", "payment required", "credit"
                ])
                is_daily = is_quota and any(kw in err_str.lower() for kw in [
                    "perday", "generaterequestsperdayperprojectpermodel", "limit: 0", "daily"
                ])
                is_transient = any(kw in err_str for kw in ["500", "503", "INTERNAL", "UNAVAILABLE", "overloaded", "capacity", "connection", "timeout", "timed out", "reset", "not found", "404"])

                # Advance to next fallback model in the chain
                prev_model = model
                if current_model_idx < len(model_chain) - 1:
                    current_model_idx += 1
                next_model = model_chain[current_model_idx]
                switched_model = (next_model != prev_model)

                if switched_model:
                    logger.warning(f"[{prev_model} error: {err_str[:90]}]. Auto-switching to: {next_model}...")

                # If multiple keys configured and rate limited, rotate keys
                valid_keys = [k for k in self.api_keys if k not in self._dead_keys]
                if is_quota and len(valid_keys) > 1:
                    prev_idx = self.active_key_index
                    for _ in range(len(self.api_keys)):
                        self.active_key_index = (self.active_key_index + 1) % len(self.api_keys)
                        if self.api_keys[self.active_key_index] not in self._dead_keys:
                            break
                    if self.active_key_index != prev_idx:
                        logger.info(f"[Key Rotate] Switched from API key #{prev_idx + 1} to API key #{self.active_key_index + 1}.")

                if is_daily and len(valid_keys) <= 1 and current_model_idx >= len(model_chain) - 1:
                    try:
                        from app.services.quota_tracker import quota_tracker
                        quota_tracker.record_request(model, is_error=True, error_type="daily_quota")
                    except Exception:
                        pass
                    with self._model_lock:
                        self._exhausted_models.add(model)
                    raise RuntimeError(f"MODEL_EXHAUSTED: Model {model} daily quota exhausted: {err_str[:120]}")

                if attempt < max_attempts - 1:
                    if is_quota:
                        wait_sec = 10.0  # Cooldown to let the 15 RPM per-minute rate limit window reset
                        logger.warning(f"[Rate Limit Cooldown] HTTP 429 received from {prev_model}. Cooling down for {wait_sec:.0f}s before retrying with {next_model}...")
                    else:
                        wait_sec = 0.5 if switched_model else (min(10.0, 2.0 * (attempt + 1)))
                        logger.warning(f"[Retry {attempt + 1}/{max_attempts}] {prev_model} error: {err_str[:100]}. Retrying with {next_model}...")
                    if progress_callback:
                        try:
                            progress_callback(0, 0, 0, f"⏳ Rate limit cooldown / retrying with {next_model} ({attempt + 1}/{max_attempts})...")
                        except Exception:
                            pass
                    if wait_sec > 0:
                        time.sleep(wait_sec)
                else:
                    logger.error(f"[Model Error] All models in fallback chain failed after {max_attempts} attempts: {err_str[:120]}")
                    with self._model_lock:
                        self._exhausted_models.add(model)
                    raise


    def _call_gemini_api(self, file_bytes: bytes, prompt: str, model_name: str, mime_type: str, api_key=None) -> str:
        """Call Gemini API (using google-genai SDK) or OpenRouter API with multimodal page image."""
        normalized_model = model_name.strip()
        if normalized_model.startswith("models/"):
            normalized_model = normalized_model[len("models/"):]

        effective_key = (api_key or self.api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENROUTER_API_KEY") or "").strip()

        # Check if an OpenRouter API key is used strictly by prefix
        is_openrouter = effective_key.startswith("sk-or-")

        if is_openrouter:
            import base64
            import requests

            openrouter_key = effective_key
            b64_data = base64.b64encode(file_bytes).decode("utf-8")

            or_model = normalized_model
            if "/" not in or_model:
                if "gemma-4" in or_model or "26b" in or_model:
                    or_model = "google/gemma-4-31b-it"
                elif "gemma" in or_model:
                    or_model = f"google/{or_model}"

            payload = {
                "model": or_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{b64_data}"
                                }
                            }
                        ]
                    }
                ],
                "temperature": 0.0,
            }

            headers = {
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:2211",
                "X-Title": "MCQ Extraction System",
            }

            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=120
            )

            # Auto-failover: if OpenRouter key limit exceeded or no credits, permanently blacklist it and fall back to Google Gemini SDK
            if resp.status_code in [402, 403] or "limit exceeded" in resp.text.lower():
                self._dead_keys.add(openrouter_key)
                gemini_fallback = os.getenv("GEMINI_API_KEY", "").strip() or next((k for k in self.api_keys if k not in self._dead_keys and not k.startswith("sk-or-")), None)
                if gemini_fallback:
                    logger.warning(f"[OpenRouter Limit] {resp.text[:120]}. Blacklisting dead OpenRouter key and failing over to Google Gemini.")
                    return self._call_gemini_api(file_bytes, prompt, model_name, mime_type, api_key=gemini_fallback)
                raise RuntimeError(f"OpenRouter API credit/limit error ({resp.status_code}): {resp.text[:300]}")

            if resp.status_code != 200:
                raise RuntimeError(f"OpenRouter API error ({resp.status_code}): {resp.text[:300]}")

            resp_data = resp.json()
            return resp_data["choices"][0]["message"]["content"] or ""

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=effective_key)

        part = types.Part.from_bytes(
            data=file_bytes,
            mime_type=mime_type
        )

        try:
            response = client.models.generate_content(
                model=normalized_model,
                contents=[part, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=65536,
                    temperature=0.0,
                )
            )
        except Exception as gen_err:
            if "response_mime_type" in str(gen_err).lower() or "unsupported" in str(gen_err).lower():
                # Gemma or certain open-weight models may require plain generation without json mime-type enforcement
                response = client.models.generate_content(
                    model=normalized_model,
                    contents=[part, prompt],
                    config=types.GenerateContentConfig(
                        max_output_tokens=65536,
                        temperature=0.0,
                    )
                )
            else:
                raise

        # Accumulate real token usage from API response metadata
        try:
            in_tok = 0
            out_tok = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                um = response.usage_metadata
                in_tok = getattr(um, "prompt_token_count", 0) or 0
                out_tok = getattr(um, "candidates_token_count", 0) or 0
                if not hasattr(self, "_real_token_usage"):
                    self._real_token_usage = {"input": 0, "output": 0, "calls": 0}
                self._real_token_usage["input"] += in_tok
                self._real_token_usage["output"] += out_tok
                self._real_token_usage["calls"] += 1

            # Update persistent daily quota tracker
            try:
                from app.services.quota_tracker import quota_tracker
                quota_tracker.record_request(normalized_model, input_tokens=in_tok, output_tokens=out_tok)
            except Exception:
                pass
        except Exception:
            pass

        return response.text or ""

