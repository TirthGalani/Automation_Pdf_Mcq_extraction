import os
import re
import sys
import uuid
import time
import json
import logging
import traceback
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union, Callable

import pandas as pd
from PIL import Image as PILImage
from dotenv import load_dotenv

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as OpenpyxlImage

from app.logger import get_logger
from app.utils import (
    clean_solution_text,
    format_solution_text,
    extract_answer_from_text,
    extract_json_from_response,
    repair_broken_math_text,
)

load_dotenv()
logger = get_logger("solution_generator")

IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "extracted_images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


# =====================================================================
# 1. COLUMN NORMALIZATION HELPERS
# =====================================================================

COLUMN_SYNONYMS = {
    "question": [
        "question", "question_text", "question text", "question statement", "stem", "stem_text",
        "original_question", "original question", "translated_question", "translated question",
        "q_text", "qtext", "problem", "problem_text", "item_text", "description"
    ],
    "option_a": [
        "option a", "option_a", "optiona", "choice a", "choice_a", "choicea", "a", "opt_a", "opta",
        "vikalp a", "(a)", "a.", "option 1", "opt 1", "choice 1"
    ],
    "option_b": [
        "option b", "option_b", "optionb", "choice b", "choice_b", "choiceb", "b", "opt_b", "optb",
        "vikalp b", "(b)", "b.", "option 2", "opt 2", "choice 2"
    ],
    "option_c": [
        "option c", "option_c", "option_c", "optionc", "choice c", "choice_c", "choicec", "c", "opt_c", "optc",
        "vikalp c", "(c)", "c.", "option 3", "opt 3", "choice 3"
    ],
    "option_d": [
        "option d", "option_d", "optiond", "choice d", "choice_d", "choiced", "d", "opt_d", "optd",
        "vikalp d", "(d)", "d.", "option 4", "opt 4", "choice 4"
    ],
    "answer": [
        "answer", "correct_answer", "correct answer", "ans", "key", "answer_key", "answer key",
        "correct option", "correct_option", "right_answer", "right answer", "jawab", "uttar"
    ],
    "solution": [
        "solution", "detailed_solution", "detailed solution", "explanation", "hints", "hints_and_solutions",
        "hints & solutions", "sol", "solution_text", "solution text", "samajuti", "ukel"
    ],
    "solution_image": [
        "solution image", "solution_image", "solution_image_url", "solution image url", "solution_diagram",
        "solution diagram", "sol_image", "sol_img", "solution_img", "explanation_image", "diagram", "figure"
    ],
    "id": [
        "id", "qno", "q_no", "q num", "q_num", "question number", "question_number", "question no",
        "sno", "s_no", "sr_no", "sr no", "#"
    ],
    "subject": [
        "subject", "sub", "domain", "discipline"
    ],
    "chapter": [
        "chapter", "chapter_name", "chapter name", "chapter_number", "chapter no", "prakaran"
    ],
    "topic": [
        "topic", "topic_name", "topic name", "topic_id", "section"
    ]
}


def normalize_df_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """
    Analyzes DataFrame columns and maps them to standardized keys.
    Returns the dataframe and a mapping dictionary: {standard_key: original_col_name}.
    """
    col_mapping: Dict[str, str] = {}
    lower_col_map = {str(c).strip().lower(): c for c in df.columns}

    for std_key, synonyms in COLUMN_SYNONYMS.items():
        for syn in synonyms:
            if syn in lower_col_map:
                col_mapping[std_key] = lower_col_map[syn]
                break

    return df, col_mapping


# =====================================================================
# 2. GEMINI API CALLER & FALLBACK
# =====================================================================

def get_gemini_api_key(provided_key: Optional[str] = None) -> str:
    """Fetches the active Gemini API key from parameters or environment."""
    load_dotenv(override=True)
    if provided_key and len(provided_key.strip()) > 5:
        return provided_key.strip()
    
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key and len(key) > 5:
        return key

    for idx in range(1, 10):
        k = os.getenv(f"GEMINI_API_KEY_{idx}", "").strip()
        if k and len(k) > 5:
            return k

    raw_keys = os.getenv("GEMINI_API_KEYS", "").strip()
    if raw_keys:
        for k in re.split(r'[\r\n,;]+', raw_keys):
            k_clean = k.strip()
            if k_clean and len(k_clean) > 5:
                return k_clean

    or_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if or_key and len(or_key) > 5:
        return or_key

    raise ValueError("No Gemini API key found. Please set GEMINI_API_KEY in .env or provide it.")


def call_gemini_for_solution(
    prompt: str,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
) -> str:
    """Calls Gemini with configured model and returns string response."""
    key = get_gemini_api_key(api_key)
    model = (model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")).strip()
    if model.startswith("models/"):
        model = model[len("models/"):]

    # Check if OpenRouter key
    if key.startswith("sk-or-"):
        import requests
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:2211",
            "X-Title": "Solution Generator",
        }
        or_model = model
        if "/" not in or_model:
            or_model = f"google/{or_model}"
        payload = {
            "model": or_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        resp = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=120)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"] or ""
        else:
            raise RuntimeError(f"OpenRouter API error ({resp.status_code}): {resp.text[:200]}")

    # Google GenAI SDK
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)

    # Resilient model cascade: modern Gemini 3.6/3.5 Flash & Pro with automatic retry
    raw_models = [
        model,
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-2.5-pro",
        "gemini-1.5-pro",
        "gemini-1.5-flash"
    ]
    seen_models = []
    for m in raw_models:
        if m and m not in seen_models:
            seen_models.append(m)

    last_err = None
    for target_model in seen_models:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=target_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        max_output_tokens=8192,
                        temperature=0.1,
                    )
                )
                return response.text or ""
            except Exception as e:
                last_err = e
                err_str = str(e)
                if "503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str:
                    time.sleep(2.0 * (attempt + 1))
                else:
                    break  # Try next model in chain

        logger.warning(f"Error calling {target_model}: {last_err}. Trying next fallback model...")

    raise RuntimeError(f"All Gemini models failed for solution generation: {last_err}")



# =====================================================================
# 3. MATPLOTLIB DIAGRAM EXECUTION ENGINE
# =====================================================================

def render_matplotlib_diagram(
    matplotlib_code: str,
    output_image_path: Path,
) -> bool:
    """
    Safely executes Python Matplotlib code to generate a high-contrast 300 DPI diagram.
    Returns True if the image was successfully generated.
    """
    if not matplotlib_code or not str(matplotlib_code).strip():
        return False

    code = matplotlib_code.strip()
    # Strip markdown code fences if present
    code = re.sub(r'^```(?:python)?\s*', '', code, flags=re.IGNORECASE)
    code = re.sub(r'\s*```$', '', code)
    # Clean up potentially hanging commands
    code = re.sub(r'\bplt\.show\(\s*\)', '', code)

    output_image_path.parent.mkdir(parents=True, exist_ok=True)
    out_str = str(output_image_path.resolve())

    script_lines = [
        "import os, sys",
        "import numpy as np",
        "import matplotlib",
        "matplotlib.use('Agg')",
        "import matplotlib.pyplot as plt",
        "import matplotlib.patches as patches",
        "from matplotlib.path import Path as MplPath",
        "import matplotlib.ticker as ticker",
        f"OUTPUT_IMAGE_PATH = r'{out_str}'",
        code,
        "# Fallback savefig if not called by generated code",
        "if not os.path.exists(OUTPUT_IMAGE_PATH) or os.path.getsize(OUTPUT_IMAGE_PATH) == 0:",
        "    plt.savefig(OUTPUT_IMAGE_PATH, bbox_inches='tight', dpi=300, facecolor='white')",
        "plt.close('all')",
    ]
    script_content = "\n".join(script_lines)

    import tempfile
    import subprocess
    temp_script_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", delete=False) as tf:
            tf.write(script_content)
            temp_script_path = tf.name

        result = subprocess.run(
            [sys.executable, temp_script_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.warning(f"Matplotlib execution stderr: {result.stderr.strip()[:300]}")
    except Exception as e:
        logger.warning(f"Error rendering matplotlib diagram: {e}")
    finally:
        if temp_script_path and os.path.exists(temp_script_path):
            try:
                os.unlink(temp_script_path)
            except Exception:
                pass

    if output_image_path.exists() and output_image_path.stat().st_size > 0:
        try:
            with PILImage.open(output_image_path) as pil_img:
                pil_img.load()
        except Exception:
            pass
        return True

    return False



# =====================================================================
# 4. SINGLE QUESTION SOLUTION & DIAGRAM GENERATOR
# =====================================================================

def build_solution_prompt(
    question_text: str,
    options: Dict[str, str],
    existing_answer: Optional[str] = None,
    subject: Optional[str] = None,
    chapter: Optional[str] = None,
    generate_image: bool = True,
) -> str:
    """Builds a structured prompt instructing Gemini to solve the question and generate diagram code if needed."""
    opts_str = "\n".join([f"({k}) {v}" for k, v in options.items() if v and str(v).strip()])

    prompt = f"""
You are an expert STEM professor, educator, and examination problem solver (JEE Advanced, NEET, Board Level).

TASK:
Provide an authoritative, clear, and comprehensive step-by-step mathematical/scientific solution for the following question. Determine the exact correct answer key. If a visual diagram or graph makes the solution clearer and complete, provide clean Python Matplotlib code to render it.

QUESTION:
{question_text}

OPTIONS:
{opts_str if opts_str else "None provided (Numeric / Short answer question)"}

KNOWN CONTEXT:
- Provided Answer (if any): {existing_answer or "Unknown - Please derive and deduce"}
- Subject: {subject or "STEM"}
- Chapter: {chapter or "N/A"}

OUTPUT JSON FORMAT REQUIREMENTS:
Return ONLY a valid JSON object with the following exact keys:
{{
  "answer": "A", // Correct option letter (A, B, C, D) or concise numeric answer
  "solution": "Step 1: Formula used: $v = u + at$\\n\\nStep 2: Substituting values:\\n$$v = 0 + (9.8)(2) = 19.6\\\\text{{ m/s}}$$\\n\\nConclusion: Therefore, the correct option is (A).",
  "has_diagram": true, // true if diagram/graph/circuit/geometry/free-body plot is helpful; false otherwise
  "diagram_description": "Free body diagram showing normal force, gravity, and friction components",
  "matplotlib_code": "# Python matplotlib code that plots the diagram\\nimport matplotlib.pyplot as plt\\nimport numpy as np\\n\\nplt.figure(figsize=(5, 3.5), dpi=300)\\n# ... plot lines, labels, arrows, shapes ...\\nplt.title('Diagram Title', fontsize=11)\\nplt.tight_layout()\\nplt.savefig(OUTPUT_IMAGE_PATH, bbox_inches='tight', dpi=300, facecolor='white')"
}}

MATPLOTLIB CODE INSTRUCTIONS (ONLY WHEN has_diagram IS TRUE):
1. Write clean, self-contained Python code using `plt`, `np`, or `patches`.
2. Do NOT call `plt.show()`.
3. Use high-contrast colors (e.g. dark blue '#1f77b4', dark red '#d62728', black '#000000'), white background, legible font size (10-12pt).
4. Use standard LaTeX format inside labels when showing math (e.g. `r'$F_N = mg\\\\cos\\\\theta$'`).
5. Always call `plt.savefig(OUTPUT_IMAGE_PATH, bbox_inches='tight', dpi=300, facecolor='white')` at the end.
6. If no diagram is needed, set `"has_diagram": false`, `"matplotlib_code": null`, and `"diagram_description": null`.

SOLUTION FORMATTING RULES:
- Use clear step-by-step formatting with line breaks (`\\n\\n`).
- Wrap ALL mathematical equations and variables in LaTeX: inline `$x^2$` or display block `$$\\frac{{a}}{{b}}$$`.
- Maintain rigorous scientific accuracy.
"""
    return prompt.strip()


def generate_single_solution_and_diagram(
    question_dict: Dict[str, Any],
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    generate_image: bool = True,
    unique_prefix: str = "sol",
) -> Dict[str, Any]:
    """
    Generates step-by-step solution, answer, and diagram for a single question dictionary.
    Returns dictionary with updated keys:
    {
        "answer": str,
        "solution": str,
        "has_solution_image": bool,
        "solution_image_url": Optional[str],
        "solution_image_path": Optional[str],
        "diagram_description": Optional[str]
    }
    """
    q_text = str(question_dict.get("question") or question_dict.get("question_text") or "").strip()
    if not q_text:
        return {
            "answer": question_dict.get("answer", ""),
            "solution": question_dict.get("solution", ""),
            "has_solution_image": False,
            "solution_image_url": None,
            "solution_image_path": None,
        }

    opts = {
        "A": str(question_dict.get("option_a") or question_dict.get("A") or "").strip(),
        "B": str(question_dict.get("option_b") or question_dict.get("B") or "").strip(),
        "C": str(question_dict.get("option_c") or question_dict.get("C") or "").strip(),
        "D": str(question_dict.get("option_d") or question_dict.get("D") or "").strip(),
    }

    existing_ans = question_dict.get("answer") or question_dict.get("correct_answer") or ""
    subject = question_dict.get("subject", "")
    chapter = question_dict.get("chapter", "")

    prompt = build_solution_prompt(
        question_text=q_text,
        options=opts,
        existing_answer=existing_ans,
        subject=subject,
        chapter=chapter,
        generate_image=generate_image,
    )

    raw_response = call_gemini_for_solution(prompt, api_key=api_key, model_name=model_name)
    parsed = extract_json_from_response(raw_response)

    gen_answer = parsed.get("answer") or existing_ans or ""
    gen_solution = parsed.get("solution") or ""
    formatted_solution = format_solution_text(clean_solution_text(gen_solution))

    has_diag = bool(parsed.get("has_diagram")) and generate_image
    mpl_code = parsed.get("matplotlib_code")
    diag_desc = parsed.get("diagram_description")

    sol_image_url = None
    sol_image_path = None
    has_sol_img = False

    if has_diag and mpl_code:
        q_id = str(question_dict.get("id") or question_dict.get("question_number") or uuid.uuid4().hex[:6])
        q_id_clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', q_id)
        img_filename = f"{unique_prefix}_q{q_id_clean}_{int(time.time())}_{uuid.uuid4().hex[:4]}.png"
        target_path = IMAGES_DIR / img_filename

        success = render_matplotlib_diagram(mpl_code, target_path)
        if success:
            has_sol_img = True
            sol_image_url = f"/api/images/{img_filename}"
            sol_image_path = str(target_path)
            logger.info(f"Generated solution diagram image: {img_filename}")

    return {
        "answer": gen_answer,
        "solution": formatted_solution,
        "has_solution_image": has_sol_img,
        "solution_image_url": sol_image_url,
        "solution_image_path": sol_image_path,
        "diagram_description": diag_desc,
    }


# =====================================================================
# 5. DATAFRAME SOLUTION & DIAGRAM PIPELINE
# =====================================================================

def generate_solutions_for_df(
    df: pd.DataFrame,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    generate_images: bool = True,
    overwrite_existing: bool = False,
    output_excel_path: Optional[Union[str, Path]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> pd.DataFrame:
    """
    Main processing function:
    Accepts a pandas DataFrame with questions, solves each question, renders diagrams,
    and returns an updated DataFrame. If output_excel_path is given, also exports a styled
    Excel workbook with physical diagram images embedded into cells.
    """
    if df.empty:
        return df

    out_df = df.copy()
    _, col_map = normalize_df_columns(out_df)

    q_col = col_map.get("question")
    if not q_col:
        # Fallback: check if the first string column contains questions
        for c in out_df.columns:
            if out_df[c].dtype == object and out_df[c].str.len().mean() > 15:
                q_col = c
                break

    if not q_col:
        raise ValueError("Could not find a valid Question column in the provided DataFrame.")

    opt_a_col = col_map.get("option_a")
    opt_b_col = col_map.get("option_b")
    opt_c_col = col_map.get("option_c")
    opt_d_col = col_map.get("option_d")
    ans_col = col_map.get("answer")
    sol_col = col_map.get("solution")
    img_col = col_map.get("solution_image")
    id_col = col_map.get("id")
    sub_col = col_map.get("subject")
    ch_col = col_map.get("chapter")

    # Ensure target output columns exist in DataFrame
    if not sol_col:
        sol_col = "Solution"
        out_df[sol_col] = ""
    if not ans_col:
        ans_col = "Answer"
        out_df[ans_col] = ""
    if not img_col:
        img_col = "Solution Image"
        out_df[img_col] = ""
    if "Solution Image URL" not in out_df.columns:
        out_df["Solution Image URL"] = ""

    total_rows = len(out_df)
    unique_run_id = f"df_{int(time.time())}"

    for idx, row in out_df.iterrows():
        current_idx = int(idx) if isinstance(idx, int) else 0
        q_text = str(row.get(q_col, "") or "").strip()
        if not q_text or q_text.lower() == "nan":
            continue

        existing_sol = str(row.get(sol_col, "") or "").strip()
        if existing_sol and existing_sol.lower() != "nan" and not overwrite_existing:
            # Skip already solved question if overwrite is False
            continue

        q_id = str(row.get(id_col, current_idx + 1)) if id_col else str(current_idx + 1)
        if progress_callback:
            try:
                progress_callback(current_idx + 1, total_rows, f"Solving Question {current_idx + 1}/{total_rows} (ID: {q_id})...")
            except Exception:
                pass

        opts_dict = {
            "option_a": row.get(opt_a_col, "") if opt_a_col else "",
            "option_b": row.get(opt_b_col, "") if opt_b_col else "",
            "option_c": row.get(opt_c_col, "") if opt_c_col else "",
            "option_d": row.get(opt_d_col, "") if opt_d_col else "",
        }

        q_payload = {
            "id": q_id,
            "question": q_text,
            "answer": row.get(ans_col, "") if ans_col else "",
            "subject": row.get(sub_col, "") if sub_col else "",
            "chapter": row.get(ch_col, "") if ch_col else "",
            **opts_dict
        }

        try:
            res = generate_single_solution_and_diagram(
                question_dict=q_payload,
                api_key=api_key,
                model_name=model_name,
                generate_image=generate_images,
                unique_prefix=unique_run_id,
            )

            out_df.at[idx, sol_col] = res["solution"]
            if not str(row.get(ans_col, "")).strip() or overwrite_existing:
                out_df.at[idx, ans_col] = res["answer"]

            if res["has_solution_image"] and res["solution_image_url"]:
                out_df.at[idx, img_col] = Path(res["solution_image_path"]).name
                out_df.at[idx, "Solution Image URL"] = res["solution_image_url"]

        except Exception as err:
            logger.error(f"Error solving row {current_idx + 1}: {err}")
            if not out_df.at[idx, sol_col]:
                out_df.at[idx, sol_col] = f"Error generating solution: {err}"

    # If Excel export requested, generate styled Excel with embedded images
    if output_excel_path:
        export_df_to_styled_excel(out_df, output_excel_path, sol_col=sol_col, img_col=img_col)

    return out_df


# =====================================================================
# 6. EXCEL EXPORTER WITH CELL-EMBEDDED IMAGES
# =====================================================================

def export_df_to_styled_excel(
    df: pd.DataFrame,
    output_path: Union[str, Path],
    sol_col: str = "Solution",
    img_col: str = "Solution Image",
) -> bytes:
    """
    Exports DataFrame to Excel (.xlsx) with professional formatting and physical images
    embedded directly inside the 'Solution Image' cells.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Solved Questions"
    ws.views.sheetView[0].showGridLines = True

    header_font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
    cell_font = Font(name="Arial", size=9)
    border_thin = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0"),
    )
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # Exclude internal URL columns from visible Excel columns
    visible_cols = [c for c in df.columns if c != "Solution Image URL"]

    # Write Header
    ws.append(visible_cols)
    for col_idx in range(1, len(visible_cols) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center
        cell.border = border_thin
    ws.row_dimensions[1].height = 28

    img_col_letter = None
    if img_col in visible_cols:
        img_col_idx = visible_cols.index(img_col) + 1
        img_col_letter = get_column_letter(img_col_idx)

    # Write Data Rows
    for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
        row_vals = [row.get(c, "") for c in visible_cols]
        ws.append(row_vals)
        has_embedded_img = False

        # Apply Cell Formatting
        for col_idx, c_name in enumerate(visible_cols, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = cell_font
            cell.border = border_thin
            if c_name in ["ID", "Answer", "Type", "Difficulty", "Marks", "Subject", "Chapter"]:
                cell.alignment = align_center
            else:
                cell.alignment = align_left

        # Check and embed image
        img_val = str(row.get(img_col, "") or "").strip()
        img_url_val = str(row.get("Solution Image URL", "") or "").strip()
        img_path = None

        if img_val and (IMAGES_DIR / img_val).exists():
            img_path = IMAGES_DIR / img_val
        elif img_url_val:
            cand_name = img_url_val.split("/")[-1]
            if (IMAGES_DIR / cand_name).exists():
                img_path = IMAGES_DIR / cand_name

        if img_path and img_path.exists() and img_path.stat().st_size > 0 and img_col_letter:
            try:
                with PILImage.open(img_path) as pil_img:
                    w, h = pil_img.size
                    if w > 0 and h > 0:
                        max_w, max_h = 160.0, 95.0
                        scale = min(max_w / w, max_h / h, 1.0)
                        new_w = max(20, int(w * scale))
                        new_h = max(20, int(h * scale))

                        xl_img = OpenpyxlImage(str(img_path))
                        xl_img.width = new_w
                        xl_img.height = new_h
                        ws.add_image(xl_img, f"{img_col_letter}{row_idx}")
                        has_embedded_img = True
            except Exception as img_err:
                logger.warning(f"Error embedding image in Excel: {img_err}")

        # Set row height dynamically
        if has_embedded_img:
            ws.row_dimensions[row_idx].height = 80
        else:
            sol_len = len(str(row.get(sol_col, "") or ""))
            if sol_len > 250:
                ws.row_dimensions[row_idx].height = 65
            elif sol_len > 100:
                ws.row_dimensions[row_idx].height = 45
            else:
                ws.row_dimensions[row_idx].height = 25

    # Auto-fit Column Widths
    for col_idx, col_name in enumerate(visible_cols, start=1):
        letter = get_column_letter(col_idx)
        if col_name == img_col:
            ws.column_dimensions[letter].width = 24
        elif col_name in ["Question", "question", "question_text", "Question Text"]:
            ws.column_dimensions[letter].width = 45
        elif col_name in [sol_col, "Solution", "solution"]:
            ws.column_dimensions[letter].width = 50
        elif col_name in ["Option A", "Option B", "Option C", "Option D", "A", "B", "C", "D"]:
            ws.column_dimensions[letter].width = 22
        elif col_name in ["ID", "Answer", "Marks", "Difficulty"]:
            ws.column_dimensions[letter].width = 12
        else:
            ws.column_dimensions[letter].width = 18

    # Save to file or BytesIO
    out_path = Path(output_path) if output_path else None
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(out_path))
        logger.info(f"Saved solved questions Excel to: {out_path}")

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.getvalue()


# =====================================================================
# 7. CONVENIENCE WRAPPER FOR FILES
# =====================================================================

def generate_solutions_for_file(
    file_path_or_bytes: Union[str, Path, bytes, BytesIO],
    file_name: str = "questions.xlsx",
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    generate_images: bool = True,
    output_excel_path: Optional[Union[str, Path]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[pd.DataFrame, bytes]:
    """
    Loads an Excel or CSV file into a DataFrame, executes solution & diagram generation,
    and returns (DataFrame, excel_bytes).
    """
    if isinstance(file_path_or_bytes, (str, Path)):
        p = Path(file_path_or_bytes)
        if p.suffix.lower() in [".xlsx", ".xls"]:
            df = pd.read_excel(p)
        else:
            df = pd.read_csv(p)
    elif isinstance(file_path_or_bytes, bytes):
        bio = BytesIO(file_path_or_bytes)
        if file_name.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(bio)
        else:
            df = pd.read_csv(bio)
    elif isinstance(file_path_or_bytes, BytesIO):
        if file_name.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(file_path_or_bytes)
        else:
            df = pd.read_csv(file_path_or_bytes)
    else:
        raise ValueError("Unsupported input format for file_path_or_bytes.")

    solved_df = generate_solutions_for_df(
        df=df,
        api_key=api_key,
        model_name=model_name,
        generate_images=generate_images,
        output_excel_path=output_excel_path,
        progress_callback=progress_callback,
    )

    excel_bytes = export_df_to_styled_excel(solved_df, output_excel_path or "")
    return solved_df, excel_bytes
