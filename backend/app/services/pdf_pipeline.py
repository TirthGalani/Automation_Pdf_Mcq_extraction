"""Specialized PDF Processing & Rendering Pipeline.

Coordinates:
- pypdfium2: High-quality PDF page rendering to images (300 DPI / 3.0x scale).
- Pillow (PIL): Precise bounding box diagram cropping.
- pypdf: PDF page slicing and page count fallback.
"""

import io
from typing import Dict, Any, Optional
from PIL import Image
from app.logger import get_logger

logger = get_logger("pdf_pipeline")

# 1. High-Quality Rendering via pypdfium2
try:
    import pypdfium2 as pdfium
    HAS_PYPDFIUM = True
except ImportError:
    HAS_PYPDFIUM = False

# 2. Pure Python PDF Processing via pypdf
try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def trim_option_label_from_crop(pil_img: Image.Image) -> Image.Image:
    """
    If an option crop contains a leading option label like '(a)', '(b)', '(c)', '(d)'
    separated by white space from the chemical structure/diagram, automatically trim away the option label.
    """
    if not HAS_NUMPY:
        return pil_img
    try:
        arr = np.array(pil_img.convert('L'))
        h, w = arr.shape
        if w < 90:
            return pil_img
        dark = (arr < 220)
        col_counts = dark.sum(axis=0)

        # Search for an isolated label in the first 35% of the image width
        max_search_x = int(w * 0.35)
        in_comp = False
        comp_start = -1
        comp_end = -1
        gap_start = -1
        gap_len = 0

        for x in range(max_search_x):
            is_dark = (col_counts[x] > 0)
            if is_dark:
                if not in_comp:
                    in_comp = True
                    if comp_start == -1:
                        comp_start = x
                if gap_start != -1:
                    # Check if gap is significant and preceding component is small (like a label '(a)')
                    if gap_len >= 8 and (comp_end - comp_start) < 60:
                        trimmed = pil_img.crop((x, 0, w, h))
                        if trimmed.size[0] >= 15 and trimmed.size[1] >= 15:
                            return trimmed
                        return pil_img
                    gap_start = -1
                    gap_len = 0
            else:
                if in_comp:
                    in_comp = False
                    comp_end = x
                    gap_start = x
                if gap_start != -1:
                    gap_len += 1
    except Exception:
        pass
    return pil_img


def autocrop_tight_diagram(pil_img: Image.Image, padding: int = 8, is_option: bool = False) -> Image.Image:
    """
    Trims excessive blank white margins from a cropped diagram,
    keeping a tight, cut-to-cut padding around all visual diagram content with zero bleed into adjacent figures.
    """
    if not HAS_NUMPY:
        return pil_img
    try:
        arr = np.array(pil_img.convert('L'))
        h, w = arr.shape
        if h < 20 or w < 20:
            return pil_img

        # Identify dark/ink pixels (threshold < 240 considers lines, drawings, text)
        dark_mask = (arr < 240)
        if not np.any(dark_mask):
            return pil_img

        y_indices, x_indices = np.where(dark_mask)
        min_y, max_y = int(y_indices.min()), int(y_indices.max())
        min_x, max_x = int(x_indices.min()), int(x_indices.max())

        content_w = max_x - min_x
        content_h = max_y - min_y

        # If dark content is trivial noise, return original
        if content_w < 8 or content_h < 8:
            return pil_img

        # Safe framing margin: guarantees peripheral labels (P, V, T, A, B, C), arrowheads, and curves have breathing room
        pad = 8 if is_option else max(16, min(28, padding))
        pad_top = pad
        pad_bottom = pad + 4
        pad_left = pad
        pad_right = pad + 4

        crop_left = max(0, min_x - pad_left)
        crop_top = max(0, min_y - pad_top)
        crop_right = min(w, max_x + pad_right + 1)
        crop_bottom = min(h, max_y + pad_bottom + 1)

        trimmed = pil_img.crop((crop_left, crop_top, crop_right, crop_bottom))
        if trimmed.size[0] >= 12 and trimmed.size[1] >= 12:
            return trimmed
        return pil_img
    except Exception:
        return pil_img


def strip_surrounding_text_from_crop(pil_img: Image.Image, min_gap_px: int = 16) -> Image.Image:
    """
    Detects and strips ONLY full-width extraneous question sentence lines accidentally captured in crop.
    STRICTLY PROTECTS localized diagram features: axis labels (P, V, T, x, y), vertex labels (A, B, C),
    arrowheads, and legends are NEVER stripped or sliced.
    """
    if not HAS_NUMPY or pil_img is None:
        return pil_img
    try:
        arr = np.array(pil_img.convert('L'))
        h, w = arr.shape
        if h < 60 or w < 40:
            return pil_img

        dark = (arr < 225)
        row_counts = dark.sum(axis=1)

        # Find continuous ink bands and blank gaps
        bands = []
        in_band = False
        b_start = 0

        for y in range(h):
            has_ink = (row_counts[y] > 2)
            if has_ink and not in_band:
                in_band = True
                b_start = y
            elif not has_ink and in_band:
                in_band = False
                bands.append((b_start, y))
        if in_band:
            bands.append((b_start, h))

        if len(bands) < 2:
            return pil_img

        # Helper to check if a band is an extraneous text line vs an internal diagram feature
        def is_extraneous_text_sentence(b_y1: int, b_y2: int) -> bool:
            band_h = b_y2 - b_y1
            # Real printed text line height at 300 DPI is typically 12-65px
            if band_h < 10 or band_h > 70:
                return False
            band_dark = dark[b_y1:b_y2, :]
            ink_cols = np.where(band_dark.any(axis=0))[0]
            if len(ink_cols) == 0:
                return False
            band_w = ink_cols[-1] - ink_cols[0]
            if band_w < 20:
                return False
            total_ink = band_dark.sum()
            # Dense text ink
            if total_ink < 30:
                return False
            return True

        # 1. Check top band (e.g. trailing sentence of question above: "as shown in the figure:")
        top_start, top_end = bands[0]
        next_start, _ = bands[1]
        gap_top = next_start - top_end

        total_rest_h = bands[-1][1] - next_start
        # Strip top band if separated by a blank gap (>= 6px) AND is an extraneous text line
        if gap_top >= max(4, min_gap_px) and total_rest_h >= 40 and is_extraneous_text_sentence(top_start, top_end):
            cropped = pil_img.crop((0, next_start, w, h))
            return strip_surrounding_text_from_crop(cropped, min_gap_px=min_gap_px)

        # 2. Check bottom band (e.g. leading option text or answer tag below)
        bot_start, bot_end = bands[-1]
        _, prev_end = bands[-2]
        gap_bot = bot_start - prev_end

        total_prev_h = prev_end - bands[0][0]
        # Strip bottom band if separated by a blank gap (>= 6px) AND is an extraneous text line
        if gap_bot >= max(4, min_gap_px) and total_prev_h >= 40 and is_extraneous_text_sentence(bot_start, bot_end):
            cropped = pil_img.crop((0, 0, w, prev_end))
            return strip_surrounding_text_from_crop(cropped, min_gap_px=min_gap_px)

        return pil_img
    except Exception:
        return pil_img


class PDFPipeline:
    """Unified document pipeline for high-DPI page rendering and diagram cropping."""

    def __init__(self):
        self._page_cache: Dict[str, Any] = {}

    # -------------------------------------------------------------------------
    # 1. pypdfium2: Convert PDF pages to high-quality images (300 DPI)
    # -------------------------------------------------------------------------
    def get_pil_page(self, pdf_bytes: bytes, page_idx: int = 0, scale: float = 3.0) -> Optional[Any]:
        """Returns cached PIL image of the rendered page for fast cropping."""
        if not HAS_PYPDFIUM:
            return None
        cache_key = f"{len(pdf_bytes)}_{page_idx}_{scale}"
        if cache_key in self._page_cache:
            return self._page_cache[cache_key]

        try:
            pdf = pdfium.PdfDocument(pdf_bytes)
            if page_idx >= len(pdf):
                return None
            page = pdf[page_idx]
            pil_image = page.render(scale=scale).to_pil()
            # Limit cache size to 20 pages in memory
            if len(self._page_cache) > 20:
                self._page_cache.clear()
            self._page_cache[cache_key] = pil_image
            return pil_image
        except Exception as e:
            logger.error(f"[PDFPipeline] render page error: {e}")
            return None

    def render_page_to_image(self, pdf_bytes: bytes, page_idx: int = 0, scale: float = 2.0, img_format: str = "JPEG") -> Optional[bytes]:
        """Renders a specific PDF page to image bytes using pypdfium2 with high performance."""
        pil_image = self.get_pil_page(pdf_bytes, page_idx, scale=scale)
        if pil_image is not None:
            try:
                img_byte_arr = io.BytesIO()
                if img_format.upper() == "JPEG":
                    if pil_image.mode != "RGB":
                        rgb_img = pil_image.convert("RGB")
                    else:
                        rgb_img = pil_image
                    rgb_img.save(img_byte_arr, format="JPEG", quality=92, optimize=False)
                else:
                    pil_image.save(img_byte_arr, format="PNG", compress_level=1)
                return img_byte_arr.getvalue()
            except Exception as e:
                logger.error(f"[PDFPipeline] pypdfium2 render error: {e}")
        return None

    # -------------------------------------------------------------------------
    # 2. Smart Diagram Cropping
    # -------------------------------------------------------------------------
    def crop_box_image(
        self,
        pdf_bytes: bytes,
        page_idx: int,
        box: Any,
        scale: float = 3.0,
        padding_px: int = 6,
        is_option: bool = False
    ) -> Optional[bytes]:
        """Crops a specific bounding box cleanly from cached page with tight, cut-to-cut margins."""
        if not box:
            return None

        try:
            pil_image = self.get_pil_page(pdf_bytes, page_idx, scale=scale)
            if pil_image is None:
                return None
            w, h = pil_image.size

            ymin, xmin, ymax, xmax = 0.0, 0.0, 0.0, 0.0
            
            # Handle box_2d or raw list/tuple or dict or string with safe float conversions
            import re
            if isinstance(box, dict):
                if "box_2d" in box and isinstance(box["box_2d"], (list, tuple)) and len(box["box_2d"]) >= 4:
                    box_list = box["box_2d"]
                    ymin, xmin, ymax, xmax = float(box_list[0]), float(box_list[1]), float(box_list[2]), float(box_list[3])
                elif "bbox" in box and isinstance(box["bbox"], (list, tuple)) and len(box["bbox"]) >= 4:
                    box_list = box["bbox"]
                    ymin, xmin, ymax, xmax = float(box_list[0]), float(box_list[1]), float(box_list[2]), float(box_list[3])
                elif "coords" in box and isinstance(box["coords"], (list, tuple)) and len(box["coords"]) >= 4:
                    box_list = box["coords"]
                    ymin, xmin, ymax, xmax = float(box_list[0]), float(box_list[1]), float(box_list[2]), float(box_list[3])
                else:
                    ymin = float(box.get("ymin", box.get("top", box.get("y0", 0))))
                    xmin = float(box.get("xmin", box.get("left", box.get("x0", 0))))
                    ymax = float(box.get("ymax", box.get("bottom", box.get("y1", 0))))
                    xmax = float(box.get("xmax", box.get("right", box.get("x1", 0))))
            elif isinstance(box, (list, tuple)) and len(box) >= 4:
                ymin, xmin, ymax, xmax = float(box[0]), float(box[1]), float(box[2]), float(box[3])
            elif isinstance(box, str):
                nums = re.findall(r'[-+]?\d*\.?\d+', box)
                if len(nums) >= 4:
                    ymin, xmin, ymax, xmax = float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3])
                else:
                    return None
            else:
                return None

            # Check validity
            if ymax <= ymin or xmax <= xmin:
                return None

            max_coord = max(ymin, xmin, ymax, xmax)

            # REJECT full-page or oversized boxes (guard against full page screenshot captures)
            if max_coord <= 1.05:
                norm_w = xmax - xmin
                norm_h = ymax - ymin
                if (norm_w > 0.92 and norm_h > 0.92) or (norm_w * norm_h > 0.82):
                    logger.debug(f"[PDFPipeline] Rejecting oversized/full-page box: [{ymin}, {xmin}, {ymax}, {xmax}]")
                    return None
                if is_option and (norm_w > 0.85 or norm_h > 0.55):
                    logger.debug(f"[PDFPipeline] Rejecting oversized option box: [{ymin}, {xmin}, {ymax}, {xmax}]")
                    return None
            elif max_coord <= 1005.0:
                norm_w = (xmax - xmin) / 1000.0
                norm_h = (ymax - ymin) / 1000.0
                if ((xmax - xmin) > 920 and (ymax - ymin) > 920) or (norm_w * norm_h > 0.82):
                    logger.debug(f"[PDFPipeline] Rejecting oversized/full-page box (1000 scale): [{ymin}, {xmin}, {ymax}, {xmax}]")
                    return None
                if is_option and ((xmax - xmin) > 850 or (ymax - ymin) > 550):
                    logger.debug(f"[PDFPipeline] Rejecting oversized option box (1000 scale): [{ymin}, {xmin}, {ymax}, {xmax}]")
                    return None
            
            # Clean tight padding: ensures visual edges and arrowheads are preserved without bleeding into text above/below
            if is_option:
                pad_top = max(2, min(8, padding_px + 2))
                pad_bottom = max(2, min(8, padding_px + 2))
                pad_left = max(2, min(8, padding_px + 2))
                pad_right = max(2, min(8, padding_px + 2))
            else:
                pad_top = max(4, min(12, padding_px + 4))
                pad_bottom = max(4, min(12, padding_px + 4))
                pad_left = max(4, min(12, padding_px + 4))
                pad_right = max(4, min(12, padding_px + 4))

            # Calculate raw unpadded box dimensions
            if max_coord <= 1.05:
                raw_w = (xmax - xmin) * w
                raw_h = (ymax - ymin) * h
                left = int(xmin * w) - pad_left
                top = int(ymin * h) - pad_top
                right = int(xmax * w) + pad_right
                bottom = int(ymax * h) + pad_bottom
            elif max_coord <= 1005.0:
                raw_w = ((xmax - xmin) / 1000.0) * w
                raw_h = ((ymax - ymin) / 1000.0) * h
                left = int((xmin / 1000.0) * w) - pad_left
                top = int((ymin / 1000.0) * h) - pad_top
                right = int((xmax / 1000.0) * w) + pad_right
                bottom = int((ymax / 1000.0) * h) + pad_bottom
            else:
                raw_w = (xmax - xmin)
                raw_h = (ymax - ymin)
                left = int(xmin) - pad_left
                top = int(ymin) - pad_top
                right = int(xmax) + pad_right
                bottom = int(ymax) + pad_bottom

            # Reject only non-existent micro noise
            if raw_w < 10 or raw_h < 10:
                return None

            # Clamping to valid image bounds
            left = max(0, min(w - 1, left))
            top = max(0, min(h - 1, top))
            right = max(left + 10, min(w, right))
            bottom = max(top + 10, min(h, bottom))

            crop_w = right - left
            crop_h = bottom - top

            if crop_w < 12 or crop_h < 12:
                return None

            cropped = pil_image.crop((left, top, right, bottom))

            # Automatically trim any option label on the left if separated by white space
            if is_option:
                cropped = trim_option_label_from_crop(cropped)

            # Strip any extraneous question/solution text lines accidentally included above or below
            cropped = strip_surrounding_text_from_crop(cropped)

            # Clean autocrop tight around diagram strokes with clean padding
            cropped = autocrop_tight_diagram(cropped, padding=6, is_option=is_option)

            out_buf = io.BytesIO()
            cropped.save(out_buf, format="PNG", optimize=True)
            return out_buf.getvalue()
        except Exception as e:
            logger.warning(f"[PDFPipeline] crop_box_image error: {e}")
            return None

    # -------------------------------------------------------------------------
    # 3. Page Slicing (Pure Python via pypdf)
    # -------------------------------------------------------------------------
    def slice_page(self, pdf_bytes: bytes, page_idx: int) -> bytes:
        """Extracts a single page from a multi-page PDF as bytes using pypdf."""
        if not HAS_PYPDF:
            return pdf_bytes

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        if page_idx >= len(reader.pages):
            return pdf_bytes

        writer = pypdf.PdfWriter()
        writer.add_page(reader.pages[page_idx])
        out_stream = io.BytesIO()
        writer.write(out_stream)
        return out_stream.getvalue()

    def extract_page_text(self, pdf_bytes: bytes, page_idx: int) -> str:
        """Extracts plain text from a specific page using pypdf."""
        if HAS_PYPDF:
            try:
                reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
                if page_idx < len(reader.pages):
                    return reader.pages[page_idx].extract_text() or ""
            except Exception:
                pass
        return ""

    def get_page_count(self, pdf_bytes: bytes) -> int:
        """Returns the total number of pages in a PDF document."""
        if HAS_PYPDF:
            try:
                reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
                return len(reader.pages)
            except Exception:
                pass
        if HAS_PYPDFIUM:
            try:
                pdf = pdfium.PdfDocument(pdf_bytes)
                return len(pdf)
            except Exception:
                pass
        return 1


# Global pipeline instance
default_pdf_pipeline = PDFPipeline()
