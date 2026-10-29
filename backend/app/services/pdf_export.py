"""
PDF Export Service — Generates a beautifully formatted exam-style PDF from extracted MCQ data.

Features:
  - Proper question format: Question → Options (A/B/C/D) → Answer → Solution
  - LaTeX / KaTeX math expressions rendered as inline images via matplotlib.mathtext
  - Tightly-cropped diagram images (question image, option images, solution image)
  - No question cut across pages — each question block paginate safely
  - Unicode-friendly (supports Gujarati, Hindi, English)
  - Correct 1-to-1 solution ↔ question matching
"""

import io
import re
from pathlib import Path
from typing import List, Optional, Any, Tuple

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
    KeepTogether, HRFlowable
)

from app.models import ExtractionResult, QuestionItem, OptionDetail
from app.utils import sort_questions_naturally, format_solution_text

# ── Constants ─────────────────────────────────────────────────────────────────
IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "extracted_images"

PAGE_W, PAGE_H = A4
MARGIN_LEFT  = 18 * mm
MARGIN_RIGHT = 18 * mm
MARGIN_TOP   = 18 * mm
MARGIN_BOTTOM = 20 * mm
CONTENT_W = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT

# Colour palette
C_PRIMARY    = colors.HexColor("#1e293b")   # dark navy
C_ACCENT     = colors.HexColor("#3b82f6")   # blue
C_GREEN      = colors.HexColor("#16a34a")   # correct answer green
C_ORANGE     = colors.HexColor("#f59e0b")   # solution header
C_LIGHT_BG   = colors.HexColor("#f8fafc")   # very light grey background
C_BORDER     = colors.HexColor("#e2e8f0")   # border grey
C_MUTED      = colors.HexColor("#64748b")   # muted text
C_WHITE      = colors.white
C_SOLUTION   = colors.HexColor("#fffbeb")   # warm yellow for solution
C_SOL_BORDER = colors.HexColor("#f59e0b")

DIFF_LABELS = {0: "Easy", -1: "Medium", 1: "Hard"}
DIFF_COLORS = {
    0:  colors.HexColor("#16a34a"),
    -1: colors.HexColor("#d97706"),
    1:  colors.HexColor("#dc2626"),
}

# ── Matplotlib LaTeX renderer (lazy import, graceful fallback) ─────────────────
_MPL_AVAILABLE = False
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _MPL_AVAILABLE = True
except Exception:
    pass


def _latex_to_png_bytes(latex_expr: str, font_size: float = 11) -> Optional[bytes]:
    """Renders a LaTeX math expression to a small PNG image using matplotlib."""
    if not _MPL_AVAILABLE:
        return None
    try:
        # Strip surrounding $ delimiters
        expr = latex_expr.strip()
        if expr.startswith("$$") and expr.endswith("$$"):
            expr = expr[2:-2].strip()
        elif expr.startswith("$") and expr.endswith("$"):
            expr = expr[1:-1].strip()
        if not expr:
            return None

        fig = plt.figure(figsize=(0.01, 0.01))
        fig.patch.set_visible(False)
        text = fig.text(0, 0, f"${expr}$", fontsize=font_size,
                        color="black", ha="left", va="bottom")
        fig.canvas.draw()
        # Get tight bounding box
        bbox = text.get_window_extent(renderer=fig.canvas.get_renderer())
        # Add small padding
        pad = 2
        w_in = max((bbox.width + pad * 2) / fig.dpi, 0.2)
        h_in = max((bbox.height + pad * 2) / fig.dpi, 0.15)
        plt.close(fig)

        fig2 = plt.figure(figsize=(w_in, h_in))
        fig2.patch.set_visible(False)
        ax = fig2.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        ax.text(0.0, 0.0, f"${expr}$", fontsize=font_size,
                color="black", ha="left", va="bottom",
                transform=ax.transAxes)
        buf = io.BytesIO()
        fig2.savefig(buf, format="png", dpi=150,
                     bbox_inches="tight", transparent=True)
        plt.close(fig2)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        return None


def _split_latex_text(text: str) -> List[Tuple[str, bool]]:
    """
    Splits text into alternating (segment, is_latex) chunks.
    is_latex=True means the segment is a LaTeX math expression.
    """
    # Match $$...$$ first (display math), then $...$
    pattern = re.compile(r'(\$\$[^\$]+\$\$|\$[^\$\n]+?\$)')
    parts = []
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            parts.append((text[last:m.start()], False))
        parts.append((m.group(0), True))
        last = m.end()
    if last < len(text):
        parts.append((text[last:], False))
    return parts if parts else [(text, False)]


# ── Style helpers ──────────────────────────────────────────────────────────────
def _build_styles():
    """Creates all Paragraph styles used in the PDF."""
    base = getSampleStyleSheet()

    def ps(name, **kwargs):
        d = dict(
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=C_PRIMARY,
            spaceAfter=2,
            spaceBefore=0,
        )
        d.update(kwargs)
        return ParagraphStyle(name=name, **d)

    styles = {
        "doc_title":    ps("doc_title",   fontSize=16, fontName="Helvetica-Bold",
                           textColor=C_PRIMARY, spaceAfter=4, alignment=TA_LEFT),
        "doc_subtitle": ps("doc_subtitle", fontSize=10, textColor=C_MUTED,
                           spaceAfter=8),
        "q_number":     ps("q_number",    fontSize=11, fontName="Helvetica-Bold",
                           textColor=C_ACCENT, spaceAfter=2),
        "q_text":       ps("q_text",      fontSize=10, leading=15,
                           textColor=C_PRIMARY, spaceAfter=4, alignment=TA_JUSTIFY),
        "opt_key":      ps("opt_key",     fontSize=10, fontName="Helvetica-Bold",
                           textColor=C_ACCENT),
        "opt_text":     ps("opt_text",    fontSize=10, leading=14,
                           textColor=C_PRIMARY),
        "answer_label": ps("answer_label", fontSize=9, fontName="Helvetica-Bold",
                           textColor=C_WHITE),
        "answer_val":   ps("answer_val",  fontSize=9, fontName="Helvetica-Bold",
                           textColor=C_GREEN),
        "sol_header":   ps("sol_header",  fontSize=9, fontName="Helvetica-Bold",
                           textColor=C_ORANGE, spaceAfter=3),
        "sol_text":     ps("sol_text",    fontSize=9, leading=13,
                           textColor=C_PRIMARY, alignment=TA_JUSTIFY),
        "page_footer":  ps("page_footer", fontSize=8, textColor=C_MUTED,
                           alignment=TA_CENTER),
        "chapter_tag":  ps("chapter_tag", fontSize=8, textColor=C_MUTED),
    }
    return styles


# ── Image helpers ──────────────────────────────────────────────────────────────
def _load_image_from_url(img_url: Optional[str], max_width: float, max_height: float = 120 * mm) -> Optional[Image]:
    """Loads a cropped PNG image from the extracted_images directory and scales it."""
    if not img_url:
        return None
    img_filename = img_url.split("/")[-1]
    img_path = IMAGES_DIR / img_filename
    if not img_path.exists() or img_path.stat().st_size == 0:
        return None
    try:
        with PILImage.open(img_path) as pil_img:
            orig_w, orig_h = pil_img.size
            if orig_w < 4 or orig_h < 4:
                return None
            # Scale to fit within max_width × max_height while maintaining aspect
            scale = min(max_width / orig_w, max_height / orig_h, 1.0)
            new_w = max(8, orig_w * scale)
            new_h = max(8, orig_h * scale)
        return Image(str(img_path), width=new_w, height=new_h)
    except Exception:
        return None


def _make_latex_image_flowable(latex_expr: str, font_size: float = 11,
                                max_width: float = CONTENT_W) -> Optional[Image]:
    """Renders a LaTeX expression to an inline Image flowable."""
    png_bytes = _latex_to_png_bytes(latex_expr, font_size=font_size)
    if not png_bytes:
        return None
    try:
        buf = io.BytesIO(png_bytes)
        with PILImage.open(buf) as pil_img:
            w, h = pil_img.size
            if w < 4 or h < 4:
                return None
            # 150 DPI render → convert px to points (1 point = 1/72 inch, 150dpi)
            scale_factor = 72.0 / 150.0
            disp_w = w * scale_factor
            disp_h = h * scale_factor
            if disp_w > max_width:
                ratio = max_width / disp_w
                disp_w = max_width
                disp_h *= ratio
        buf2 = io.BytesIO(png_bytes)
        return Image(buf2, width=disp_w, height=disp_h)
    except Exception:
        return None


# ── Rich text paragraph builder (handles inline LaTeX) ────────────────────────
def _text_to_paragraph(text: str, style, max_img_width: float = CONTENT_W) -> List[Any]:
    """
    Converts a text string that may contain LaTeX $...$ into a list of flowables.
    Pure text → single Paragraph.
    Text with LaTeX → alternating Paragraphs and Image flowables.
    """
    if not text:
        return []

    # Escape ampersands for ReportLab XML parser
    safe_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Check if there's any LaTeX
    has_latex = bool(re.search(r'\$[^\$\n]+?\$|\$\$[^\$]+\$\$', text))

    if not has_latex or not _MPL_AVAILABLE:
        # Simple paragraph — still escape properly
        try:
            return [Paragraph(safe_text, style)]
        except Exception:
            # Fallback to plain ASCII if XML parse fails
            plain = re.sub(r'[^\x20-\x7e\u0900-\u097f\u0a80-\u0aff]', '?', text)
            return [Paragraph(plain.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)]

    # Split into text / LaTeX segments
    segments = _split_latex_text(text)
    flowables = []
    buffer_text = ""

    for seg_text, is_latex in segments:
        if is_latex:
            # Flush accumulated plain text first
            if buffer_text.strip():
                safe_buf = buffer_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                try:
                    flowables.append(Paragraph(safe_buf, style))
                except Exception:
                    pass
                buffer_text = ""
            # Render LaTeX
            latex_img = _make_latex_image_flowable(seg_text, font_size=style.fontSize,
                                                    max_width=max_img_width)
            if latex_img:
                flowables.append(latex_img)
            else:
                # Fallback: show raw LaTeX text
                raw_safe = seg_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                try:
                    flowables.append(Paragraph(f'<font color="#7c3aed">{raw_safe}</font>', style))
                except Exception:
                    pass
        else:
            buffer_text += seg_text

    # Flush remaining text
    if buffer_text.strip():
        safe_buf = buffer_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        try:
            flowables.append(Paragraph(safe_buf, style))
        except Exception:
            pass

    return flowables if flowables else [Paragraph(safe_text, style)]


# ── Option row builder ─────────────────────────────────────────────────────────
def _build_option_flowables(key: str, opt: Optional[OptionDetail], styles: dict,
                             correct_answer: Optional[str]) -> List[Any]:
    """Builds the flowable(s) for a single option (A/B/C/D)."""
    if not opt:
        return []

    opt_text = (opt.translated or opt.original or "").strip()
    opt_img_url = opt.image_url
    has_img = bool(opt_img_url or opt.has_image)

    is_correct = (
        correct_answer and
        key.upper() in [a.strip().upper() for a in (correct_answer or "").split(",")]
    )
    key_color = "#16a34a" if is_correct else "#3b82f6"
    key_html = f'<font color="{key_color}"><b>({key})</b></font>'

    flowables = []

    if has_img and opt_img_url:
        # Option has a diagram image
        opt_img_flowable = _load_image_from_url(opt_img_url, max_width=CONTENT_W * 0.45)
        if opt_img_flowable:
            # Build a mini-table: key | image
            key_para = Paragraph(key_html + ("  ✓" if is_correct else ""), styles["opt_key"])
            tbl = Table(
                [[key_para, opt_img_flowable]],
                colWidths=[14 * mm, CONTENT_W * 0.45],
                hAlign="LEFT"
            )
            tbl.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            flowables.append(tbl)
            return flowables
        # Fallback if image not found
        if not opt_text:
            opt_text = "[Diagram]"

    # Text option (may contain LaTeX)
    if opt_text:
        # Combine key + text into a paragraph with inline key badge
        plain_key = f"({key})" + ("  ✓" if is_correct else "")
        full_text = f'<font color="{key_color}"><b>{plain_key}</b></font>  ' + \
                    opt_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        try:
            flowables.append(Paragraph(full_text, styles["opt_text"]))
        except Exception:
            flowables.append(Paragraph(f"({key})  {opt_text}", styles["opt_text"]))

        # Check for LaTeX inside option text
        if _MPL_AVAILABLE and re.search(r'\$[^\$\n]+?\$|\$\$[^\$]+\$\$', opt_text):
            flowables = []  # Reset and use proper LaTeX rendering
            header_para = Paragraph(f'<font color="{key_color}"><b>({key})</b></font>', styles["opt_key"])
            content_flowables = _text_to_paragraph(opt_text, styles["opt_text"],
                                                    max_img_width=CONTENT_W * 0.8)
            header_table = Table(
                [[header_para, content_flowables[0] if content_flowables else Paragraph("", styles["opt_text"])]],
                colWidths=[14 * mm, CONTENT_W - 14 * mm],
                hAlign="LEFT"
            )
            header_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            flowables.append(header_table)
            for cf in content_flowables[1:]:
                flowables.append(cf)
    return flowables


# ── Answer badge ───────────────────────────────────────────────────────────────
def _build_answer_badge(answer: Optional[str], q_type: str, styles: dict) -> Optional[Table]:
    """Creates a small answer badge: ✓ Answer: B"""
    if not answer:
        return None
    ans_display = answer.strip()
    label_para = Paragraph('<font color="#ffffff"><b>✓ Answer</b></font>', styles["answer_label"])
    val_para = Paragraph(f'<font color="#16a34a"><b>{ans_display}</b></font>', styles["answer_val"])
    tbl = Table([[label_para, val_para]], colWidths=[22 * mm, CONTENT_W - 22 * mm], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), C_GREEN),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#f0fdf4")),
        ("ROUNDEDCORNERS", [4]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbf7d0")),
    ]))
    return tbl


# ── Solution block ─────────────────────────────────────────────────────────────
def _build_solution_block(solution_text: str, sol_img_url: Optional[str],
                           styles: dict) -> List[Any]:
    """Builds the solution section flowables."""
    if not solution_text and not sol_img_url:
        return []

    flowables = []
    header = Paragraph('<font color="#f59e0b"><b>💡 Solution</b></font>', styles["sol_header"])

    content_items = []
    if solution_text:
        formatted_sol = format_solution_text(solution_text)
        sol_flowables = _text_to_paragraph(formatted_sol, styles["sol_text"],
                                            max_img_width=CONTENT_W - 12 * mm)
        content_items.extend(sol_flowables)

    if sol_img_url:
        sol_img = _load_image_from_url(sol_img_url, max_width=CONTENT_W - 12 * mm,
                                        max_height=80 * mm)
        if sol_img:
            content_items.append(Spacer(1, 4))
            content_items.append(sol_img)

    if not content_items:
        return []

    # Wrap everything in a styled yellow box
    inner_rows = [[item] for item in [header] + content_items]
    sol_table = Table(inner_rows, colWidths=[CONTENT_W - 6 * mm], hAlign="LEFT")
    sol_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_SOLUTION),
        ("BOX", (0, 0), (-1, -1), 1.0, C_SOL_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    flowables.append(sol_table)
    return flowables


# ── Per-question block ─────────────────────────────────────────────────────────
def _build_question_block(q: QuestionItem, styles: dict, global_idx: int) -> List[Any]:
    """Builds all flowables for a single question (kept together on a page if possible)."""
    block: List[Any] = []

    q_text = (q.translated_question or q.original_question or "").strip()
    if not q_text:
        return []

    # ── Question header row: number + type + difficulty ────────────────────────
    q_num_str = str(q.question_number or global_idx)
    diff_label = DIFF_LABELS.get(q.difficulty, "Medium")
    diff_color = DIFF_COLORS.get(q.difficulty, C_MUTED)
    q_type_display = (q.question_type or "MCQ").strip()

    header_left = Paragraph(
        f'<font color="#3b82f6"><b>Q{q_num_str}.</b></font>'
        f'  <font color="#94a3b8" size="8">{q_type_display}</font>',
        styles["q_number"]
    )
    header_right = Paragraph(
        f'<font color="{diff_color.hexval() if hasattr(diff_color,"hexval") else "#64748b"}" size="8"><b>{diff_label}</b></font>',
        styles["chapter_tag"]
    )

    hdr_table = Table([[header_left, header_right]],
                       colWidths=[CONTENT_W * 0.75, CONTENT_W * 0.25], hAlign="LEFT")
    hdr_table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    block.append(hdr_table)
    block.append(Spacer(1, 3))

    # ── Question text (with LaTeX rendering) ───────────────────────────────────
    q_flowables = _text_to_paragraph(q_text, styles["q_text"])
    block.extend(q_flowables)

    # ── Question image ─────────────────────────────────────────────────────────
    if q.image_url:
        q_img = _load_image_from_url(q.image_url, max_width=CONTENT_W * 0.75,
                                      max_height=70 * mm)
        if q_img:
            block.append(Spacer(1, 4))
            block.append(q_img)
            block.append(Spacer(1, 4))

    # ── Options ────────────────────────────────────────────────────────────────
    opts = q.options or {}
    correct_ans = (q.answer or "").strip()

    # Detect if options have images — layout as 2-column grid if text-only
    opt_items = []
    for key in ["A", "B", "C", "D"]:
        opt = opts.get(key)
        if not opt:
            continue
        opt_flowables = _build_option_flowables(key, opt, styles, correct_ans)
        if opt_flowables:
            opt_items.append((key, opt_flowables))

    has_opt_images = any(
        bool((opts.get(k) and opts[k].image_url) or (opts.get(k) and opts[k].has_image))
        for k in ["A", "B", "C", "D"]
    )

    if opt_items:
        block.append(Spacer(1, 3))
        if has_opt_images:
            # Vertical layout for image options
            for _key, opt_fl in opt_items:
                block.extend(opt_fl)
                block.append(Spacer(1, 2))
        else:
            # 2-column text layout
            row_pairs = []
            for i in range(0, len(opt_items), 2):
                left_fl = opt_items[i][1]
                right_fl = opt_items[i + 1][1] if i + 1 < len(opt_items) else [Paragraph("", styles["opt_text"])]
                left_cell = left_fl[0] if left_fl else Paragraph("", styles["opt_text"])
                right_cell = right_fl[0] if right_fl else Paragraph("", styles["opt_text"])
                row_pairs.append([left_cell, right_cell])

            opt_table = Table(row_pairs, colWidths=[CONTENT_W / 2, CONTENT_W / 2], hAlign="LEFT")
            opt_table.setStyle(TableStyle([
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            block.append(opt_table)

    # ── Answer badge ────────────────────────────────────────────────────────────
    if correct_ans:
        block.append(Spacer(1, 5))
        ans_badge = _build_answer_badge(correct_ans, q.question_type or "MCQ", styles)
        if ans_badge:
            block.append(ans_badge)

    # ── Solution ───────────────────────────────────────────────────────────────
    sol_text = (q.solution or "").strip()
    sol_img_url = q.solution_image_url
    if sol_text or sol_img_url:
        block.append(Spacer(1, 5))
        sol_flowables = _build_solution_block(sol_text, sol_img_url, styles)
        block.extend(sol_flowables)

    # ── Separator ──────────────────────────────────────────────────────────────
    block.append(Spacer(1, 6))
    block.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=C_BORDER))
    block.append(Spacer(1, 6))

    return block


# ── Document-level page decoration ────────────────────────────────────────────
class _PageDecoration:
    """Adds header and footer to each page via SimpleDocTemplate onPage hooks."""

    def __init__(self, doc_title: str, doc_subtitle: str):
        self.doc_title = doc_title
        self.doc_subtitle = doc_subtitle
        self._style = ParagraphStyle(
            "footer_style", fontName="Helvetica", fontSize=8,
            textColor=colors.HexColor("#94a3b8"), alignment=TA_CENTER
        )

    def __call__(self, canvas, doc):
        canvas.saveState()
        w, h = A4

        # Top rule
        canvas.setStrokeColor(C_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_LEFT, h - MARGIN_TOP + 4, w - MARGIN_RIGHT, h - MARGIN_TOP + 4)

        # Header text
        canvas.setFont("Helvetica-Bold", 9)
        canvas.setFillColor(C_PRIMARY)
        canvas.drawString(MARGIN_LEFT, h - MARGIN_TOP + 7, self.doc_title[:80])
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(C_MUTED)
        canvas.drawRightString(w - MARGIN_RIGHT, h - MARGIN_TOP + 7, f"Page {doc.page}")

        # Footer rule
        canvas.setStrokeColor(C_BORDER)
        canvas.line(MARGIN_LEFT, MARGIN_BOTTOM - 4, w - MARGIN_RIGHT, MARGIN_BOTTOM - 4)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(C_MUTED)
        canvas.drawCentredString(w / 2, MARGIN_BOTTOM - 12,
                                  f"MCQ Extract AI  •  {self.doc_subtitle}")
        canvas.restoreState()


# ── Main export function ───────────────────────────────────────────────────────
def export_results_to_pdf(results: List[ExtractionResult]) -> bytes:
    """
    Generates a formatted exam-style PDF from extracted MCQ results.

    Returns the PDF as raw bytes ready to be served as an HTTP response.
    """
    if not results:
        return b""

    # Build document metadata
    all_files = [r.file_name for r in results]
    all_subjects = list({r.subject for r in results if r.subject})
    all_chapters = list({r.chapter_name for r in results if r.chapter_name})

    doc_title = " | ".join(all_subjects) if all_subjects else "MCQ Question Paper"
    if all_chapters:
        doc_title += f"  —  {', '.join(all_chapters[:2])}"

    doc_subtitle = f"{sum(r.total_questions for r in results)} Questions"
    if all_files:
        doc_subtitle += f"  •  {', '.join(Path(f).stem for f in all_files[:2])}"

    # Set up output buffer and document
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP + 10,
        bottomMargin=MARGIN_BOTTOM + 8,
        title=doc_title,
        author="MCQ Extract AI",
    )

    styles = _build_styles()
    page_deco = _PageDecoration(doc_title, doc_subtitle)
    story: List[Any] = []

    # ── Cover block ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(doc_title, styles["doc_title"]))
    story.append(Paragraph(doc_subtitle, styles["doc_subtitle"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1.5, color=C_ACCENT))
    story.append(Spacer(1, 5 * mm))

    # ── Questions ──────────────────────────────────────────────────────────────
    global_idx = 1
    for res in results:
        sorted_qs = sort_questions_naturally(res.questions)
        for q in sorted_qs:
            q_text = (q.translated_question or q.original_question or "").strip()
            if not q_text:
                continue

            q_block = _build_question_block(q, styles, global_idx)
            if q_block:
                # KeepTogether attempts to keep a question on one page;
                # for very long questions it gracefully falls back to splitting.
                try:
                    story.append(KeepTogether(q_block))
                except Exception:
                    story.extend(q_block)
            global_idx += 1

    # Build the PDF
    doc.build(story, onFirstPage=page_deco, onLaterPages=page_deco)
    buf.seek(0)
    return buf.getvalue()


def export_single_result_to_pdf(result: ExtractionResult) -> bytes:
    """Generates a formatted PDF for a single extraction result."""
    return export_results_to_pdf([result])
