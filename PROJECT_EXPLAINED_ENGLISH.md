# 📘 MCQ PDF Extraction & Translation System — Complete Logic & Architecture Guide (In Simple English)

This guide explains the entire project in clear, simple English: **the complete logic**, **which AI model does what**, **how the outputs are generated**, and a **file-by-file & folder-by-folder breakdown**.

---

## 📑 Table of Contents
1. [The Big Picture: Simple Step-by-Step Workflow](#1-the-big-picture-simple-step-by-step-workflow)
2. [Which Model Does What? (AI Logic & Auto-Fallback)](#2-which-model-does-what-ai-logic--auto-fallback)
   - [Gemini Flash vs Gemini Pro](#gemini-flash-vs-gemini-pro)
   - [Auto-Fallback Logic (What happens when quota runs out?)](#auto-fallback-logic)
   - [Prompt Intelligence Logic (What commands are given to AI?)](#prompt-intelligence-logic)
3. [How the Output is Generated? (Output Pipelines)](#3-how-the-output-is-generated)
   - [Excel Output (.xlsx) with Real Images in Cells](#excel-output-logic)
   - [PDF Output with Rendered LaTeX Math Formulas](#pdf-output-logic)
   - [CSV and JSON Export Logic](#csv-and-json-export-logic)
4. [Folder-by-Folder and File-by-File Logic](#4-folder-by-folder-and-file-by-file-logic)
   - [Root Startup Scripts (`start_app.bat`)](#root-startup-scripts)
   - [Backend Root Files (`.env`, `token_calculator.py`, `requirements.txt`, etc.)](#backend-root-files)
   - [Backend App Module (`models.py`, `prompt_template.py`, `extractor.py`, `utils.py`, `main.py`)](#backend-app-module)
   - [Backend Services (`pdf_pipeline.py`, `pdf_export.py`)](#backend-services)
   - [Frontend Client (`index.html`, `styles.css`, `config.js`, `app.js`, `ui.js`)](#frontend-client)

---

# 1. The Big Picture: Simple Step-by-Step Workflow

When you have entrance exam PDFs (JEE, NEET, Board papers), they contain:
- Complex **Two-Column layouts**.
- **LaTeX Math & Physics formulas** like $\frac{-b \pm \sqrt{D}}{2a}$ or $\Omega$.
- **Diagrams & Scientific Circuits** in question stems or options (A, B, C, D).
- Different languages (English, Gujarati, Hindi).
- Answers or solutions printed at the back or in a separate PDF.

### Here is how the system processes everything step-by-step:

```
[ Step 1: User uploads PDF(s) in Browser ]
                     │
                     ▼
[ Step 2: Token Calculator (token_calculator.py) ]
  • Counts total pages.
  • Fetches live USD-to-INR rate via online API.
  • Calculates total multimodal tokens and shows estimated cost (₹) to the user.
                     │
                     ▼
[ Step 3: High-Resolution Rendering (pdf_pipeline.py) ]
  • Uses 'pypdfium2' to convert each PDF page into a 300 DPI crystal-clear image.
                     │
                     ▼
[ Step 4: Gemini Multimodal Vision AI (extractor.py + prompt_template.py) ]
  • Gemini inspects the 300 DPI page image.
  • Reads Left Column top-to-bottom, then Right Column top-to-bottom.
  • Extracts:
      - Question stem (with math formulas in LaTeX $..$)
      - Options A, B, C, D
      - Correct Answer & Solution
      - Normalized bounding boxes [ymin, xmin, ymax, xmax] for all diagrams.
                     │
                     ▼
[ Step 5: Diagram Cropping & Margin Cleaning (pdf_pipeline.py) ]
  • Crops exact diagram regions from the original 300 DPI page.
  • Uses NumPy thresholding to trim excessive blank margins (autocrop).
  • Strips accidental option letters (e.g. '(a)') from diagram crops.
  • Saves crisp PNG images in 'extracted_images/' folder.
                     │
                     ▼
[ Step 6: JSON Repair & Data Sanitization (utils.py) ]
  • Fixes unescaped LaTeX backslashes (\frac, \alpha) so JSON never crashes.
  • Automatically repairs truncated JSON if token limits cut the response mid-way.
  • Extracts embedded options if they were printed inside the question stem.
                     │
                     ▼
[ Step 7: Separate Solution PDF Matching (extractor.py) ]
  • If a separate Solution PDF was uploaded, it extracts solutions and answers.
  • Matches Q.1 Solution -> Q.1 Question, Q.2 -> Q.2 by authentic question number.
                     │
                     ▼
[ Step 8: Multi-Format Exporter (utils.py & pdf_export.py) ]
  • Excel (.xlsx): 21 standard columns, with PHYSICAL IMAGES EMBEDDED DIRECTLY IN CELLS.
  • PDF: Printable exam-style PDF with LaTeX math rendered via Matplotlib.
  • CSV: UTF-8 with BOM for Excel compatibility.
  • JSON: Master API schema.
  • ZIP: All cropped diagram images packaged together.
```

---

# 2. Which Model Does What? (AI Logic & Auto-Fallback)

### Gemini Flash vs Gemini Pro

| Feature | Primary Model (`gemini-3.5-flash` / `3.6-flash`) | Fallback Model (`gemini-3.1-pro-preview` / `2.5-pro`) |
| :--- | :--- | :--- |
| **Role** | Default workhorse for all normal extractions. | Automatic safety net when Flash runs out of quota. |
| **Speed** | Super fast (few seconds per page). | Moderate speed, deeper reasoning. |
| **Cost** | Extremely cheap (~$0.075 per 1M tokens). | Higher cost (~$1.25 per 1M tokens). |
| **Task** | Analyzes page image, extracts 2-column text, math, options, and diagram boxes. | Handles deep science reasoning or continues jobs seamlessly when Flash quota is exhausted. |

---

### Auto-Fallback Logic (What happens when quota runs out?)
If you extract a 40-page PDF and Google's API returns `HTTP 429: Resource Exhausted` (Quota limit hit):
1. `extractor.py` catches the error in a specialized `try-except` block.
2. **The program DOES NOT crash** and never loses existing progress!
3. It posts an immediate warning: `⚠️ Flash quota exhausted — switched to gemini-3.1-pro-preview`.
4. The job automatically switches to Pro model from that exact page and continues.
5. If both models run out of quota, it marks the job as `Partial` and preserves all questions scanned so far so you can download them immediately.

---

### Prompt Intelligence Logic (`prompt_template.py`)
Gemini is guided by **8 strict examination digitization rules**:
* **Rule 0 (Subject Detection)**: Automatically identifies `Physics`, `Chemistry`, `Mathematics`, or `Biology`. Never marks "General".
* **Rule 1 (Two-Column Scanning)**: Explicitly commands the AI: *"Scan entire LEFT column top-to-bottom, then scan entire RIGHT column top-to-bottom"*. Prevents missing or jumbled questions.
* **Rule 2 (Authentic Question Numbering)**: If the page prints Question `46`, AI outputs `46`, NOT sequential loop numbers `1`. This enables 100% accurate 1-to-1 matching with back-of-the-book solutions.
* **Rule 2B (Sub-Questions)**: If Q.27 has sub-parts `(i)`, `(ii)`, `(iii)`, it extracts each as a separate question item so nothing is collapsed.
* **Rule 2C & 2D (Paragraphs & Matching Tables)**: Dedicated extraction fields for JEE Advanced Comprehension Passages and Column-I / Column-II matching matrices.
* **Rule 3 & 4 (Zero Cutoff & Original Script)**: Never truncates long questions or reaction conditions. Leaves Gujarati in Gujarati, Hindi in Hindi, and equations in clean LaTeX `$..$`.
* **Rule 6 (Cross-Page Questions)**: If question starts at bottom of Page 1 and options are on Page 2, flags them with `is_split_at_bottom` and `is_continuation` to stitch them seamlessly.
* **Rule 7 (Genuine Questions Contract)**: Forbids AI from inventing fake questions or treating solution explanations as new questions.

---

# 3. How the Output is Generated?

### Excel Output Logic (`utils.py -> export_to_excel_bytes`)
Unlike basic tools that only export plain text:
1. It uses `openpyxl` to build an Excel workbook.
2. Headers are styled with **Dark Slate Navy (`#1E293B`)** and white bold text.
3. **Physical Image Embedding**: When a question or option has a diagram, it downloads the cropped PNG from `extracted_images/` and **inserts the actual graphic image directly inside the Excel cell** (`ws.add_image`).
4. Any row containing an image automatically expands to **height 75pt** so the image is clearly visible without manual row dragging.
5. **Multi-Sheet Architecture for JEE Advanced**:
   - **Sheet 1 (`Questions`)**: Standard MCQs, Multi-Correct MCQs, Numerical & Integer questions (19 standard columns).
   - **Sheet 2 (`Paragraph Type`)**: Comprehension passages with 21 columns (`ID | Paragraph | Question | Type | Option A-D | Answer | Marks | Difficulty | Subject | Paragraph Image | Question Image | Option Images | Solution | Solution Image`). Group headers show passage text & diagram on the first question of each passage set.
   - **Sheet 3 (`Match The Column`)**: Matrix matching questions with 21 columns (`ID | Question | Column-I | Column-II | Type | Option A-D | Answer | Marks | Difficulty | Subject | Question Image | Answer Image | Column-I Images | Solution | Solution Image`).
6. **Standard Exams (Non-Advance)**: Clean single-sheet (`Questions`) or dual-sheet (`Questions` + `Topics` when topics are provided).

### PDF Output Logic (`pdf_export.py`)
1. **LaTeX Math Rendering**: Equations enclosed in `$..$` (e.g. $\lim_{x\to 0} \frac{\sin x}{x}$) are rendered into high-resolution PNG images via `matplotlib.mathtext`.
2. **ReportLab Flowables**: Formats question cards, green answer badges, cropped diagram figures, and warm-yellow highlighted solution boxes.
3. **KeepTogether Pagination**: Prevents a question stem from breaking across page breaks, keeping the question card intact.

### CSV & JSON Logic
- **CSV**: Uses UTF-8 encoding with Byte Order Mark (`utf-8-sig`) so Gujarati, Hindi, and mathematical symbols open in Microsoft Excel without garbled text (`????`).
- **JSON**: Outputs the master schema matching database ingestion specs.

---

# 4. Folder-by-Folder and File-by-File Logic

---

## 📁 Root Directory

### 1. `start_app.bat`
* **Purpose**: Single-click launcher for Windows.
* **Logic**:
  - Automatically runs `python -m pip install -r backend/requirements.txt` to verify all packages are installed.
  - Launches the web browser to `http://localhost:8009`.
  - Executes the FastAPI backend server using `uvicorn`:
    `python -m uvicorn app.main:app --host localhost --port 8009 --reload --reload-dir app`.

---

## 📁 `backend/` Directory

### 2. `backend/.env` and `.env.example`
* **Purpose**: Secrets and system configuration.
* **Logic**:
  - `GEMINI_API_KEY`: Your Google AI Studio API key.
  - `GEMINI_MODEL`: Primary model name (`gemini-3.5-flash`).
  - `GEMINI_FALLBACK_MODEL`: Backup model name (`gemini-3.1-pro-preview`).
  - `PORT`: Web server port (`8009`).

### 3. `backend/.jobs_cache.json`
* **Purpose**: Job state database across server restarts.
* **Logic**: Keeps records of the last 20 batch extraction jobs. If server restarts or connection drops, progress is safely preserved and incomplete jobs are flagged gracefully.

### 4. `backend/requirements.txt`
* **Purpose**: Python package dependencies.
* **Logic**:
  - `fastapi`, `uvicorn`: High-performance asynchronous API server.
  - `google-genai`, `google-generativeai`: Official Google Gemini SDKs.
  - `pypdfium2`, `pdfplumber`, `pypdf`: PDF page splitting and 300 DPI rendering.
  - `pillow`: Image processing, cropping, and diagram resizing.
  - `pandas`, `openpyxl`: Excel table construction and in-cell image embedding.
  - `reportlab`, `matplotlib`: PDF generation with LaTeX math typesetting.

### 5. `backend/token_calculator.py`
* **Purpose**: Pre-extraction token and cost estimation.
* **Logic**:
  - `get_pdf_page_count()`: Inspects page count without loading entire PDF.
  - `fetch_usd_to_inr()`: Connects to live currency exchange APIs to get the real-time USD-to-INR rate (e.g. ₹84.50).
  - Calculates: `Input Tokens = Master Prompt Tokens + (Pages * ~1000 Vision Image Tiles) + Text Tokens`.
  - Displays exact cost in both USD ($) and Indian Rupees (₹) before you spend any money or quota.

### 6. `backend/batch_cli.py`
* **Purpose**: Command-Line Interface for headless automation.
* **Logic**: Allows running extractions directly from Command Prompt (CMD) on a single file or entire folder of PDFs without opening the web browser:
  `python batch_cli.py --input-dir ./pdfs --source Gujarati --target English`

### 7. `backend/test_extraction_improvements.py`
* **Purpose**: Automated regression test suite.
* **Logic**: Tests edge cases like LaTeX backslash escaping, 2-column question sorting, option letter cleaning, and brace-balancing algorithms to ensure updates never break existing features.

### 8. `backend/extracted_images/`
* **Purpose**: PNG image cache.
* **Logic**: All diagrams cropped from PDF question stems, option choices, and solutions are stored here and served through `/api/images/{filename}`.

---

## 📁 `backend/app/` Module

### 9. `backend/app/models.py`
* **Purpose**: Pydantic data models and schemas.
* **Logic**:
  - `OptionDetail`: Represents option text, image presence, image URL, and bounding box `[ymin, xmin, ymax, xmax]`.
  - `QuestionItem`: Holds complete question data (stem, options, answer, solution, difficulty, diagrams, comprehension paragraphs, matching tables).
  - `ExtractionResult`: Holds all questions for a single PDF, processing time, status, and chapter/topic metadata.
  - `BatchJobProgress`: Tracks real-time job progress (scanned pages, percentage, current file, active model, fallback status, warning notices).

### 10. `backend/app/prompt_template.py`
* **Purpose**: Gemini prompt instructions.
* **Logic**: Formulates the master system prompt enforcing two-column reading order, verbatim LaTeX formulas, authentic numbering, sub-part extraction, and diagram bounding box output.

### 11. `backend/app/extractor.py`
* **Purpose**: Core multimodal extraction engine (`GeminiExtractor`).
* **Logic**:
  - Renders each PDF page to a 300 DPI image via `pypdfium2`.
  - Submits the image to Gemini multimodal vision API.
  - Receives response, parses JSON, and finds diagram coordinates.
  - Calls `pdf_pipeline` to crop diagrams and save PNGs into `extracted_images/`.
  - Handles rate limits: automatically switches to `gemini-3.1-pro-preview` when Flash quota exhausts.
  - `extract_solutions_and_answers_from_pdf()`: Extracts separate solution PDFs and matches solutions 1-to-1 with questions.

### 12. `backend/app/utils.py`
* **Purpose**: Data sanitation, JSON repair, and Excel/CSV generator.
* **Logic**:
  - `repair_json_escapes()`: Repairs LaTeX backslash collisions (e.g. `\frac`, `\alpha`, `\Omega`) that invalidate standard JSON.
  - `extract_json_from_response()`: Truncated JSON recovery engine; if AI token limits cut a response mid-way, it auto-balances unclosed braces `]}` to save complete questions.
  - `split_question_and_options()`: Detects embedded options inside question text and splits them into distinct fields.
  - `clean_question_text()`: Cleans out exam citation tags like `[JEE Main 2019, 12 April]`.
  - `export_to_excel_bytes()`: Generates styled `.xlsx` workbook and embeds real diagram images directly inside cells.
  - `export_to_csv_bytes()`: Generates UTF-8 BOM CSV.

### 13. `backend/app/main.py`
* **Purpose**: FastAPI application and REST endpoints.
* **Logic**:
  - `POST /api/count-tokens`: Returns multimodal tokens, page count, and estimated cost.
  - `POST /api/batch-extract`: Starts asynchronous background job and immediately returns `job_id`.
  - `_run_batch_job()`: Background worker looping through uploaded PDFs, triggering extraction, updating live progress, and matching solutions.
  - `GET /api/jobs/{job_id}`: Polling endpoint queried by frontend every 1.2s to stream live progress.
  - `GET /api/export/{job_id}/[excel|pdf|csv|json|images]`: File export endpoints.
  - `GET /api/images/{name}`: Serves diagram PNGs to the browser.
  - Mounts `frontend/` as static website at root `/`.

---

## 📁 `backend/app/services/` Module

### 14. `backend/app/services/pdf_pipeline.py`
* **Purpose**: High-precision PDF rendering and diagram auto-cropping.
* **Logic**:
  - `crop_image_from_page()`: Maps 0–1000 normalized coordinates to exact pixel locations at 300 DPI and extracts the cropped region.
  - `autocrop_tight_diagram()`: Uses pixel thresholding to remove empty white margins around diagrams.
  - `trim_option_label_from_crop()`: Detects and removes option letters (`(a)`, `(b)`) accidentally captured in the diagram crop.

### 15. `backend/app/services/pdf_export.py`
* **Purpose**: Exam-style PDF generator.
* **Logic**:
  - `_latex_to_png_bytes()`: Renders math formulas into crisp PNGs via Matplotlib.
  - `export_results_to_pdf()`: Assembles questions, diagrams, green answer indicators, and yellow solution boxes into a print-ready A4 PDF document.

---

## 📁 `frontend/` Client

### 16. `frontend/index.html`
* **Purpose**: User Interface Dashboard.
* **Logic**:
  - Left sidebar: API key configuration, model selector, language selectors.
  - Main area: Drag-and-Drop upload area for Question PDFs and optional Solution PDF.
  - Modal: Pre-run Token & Cost estimation modal with USD and INR prices.
  - Live progress section: Percentage bar, current file/page indicators, active model badge.
  - Results viewer: Question cards with rendered math, diagram tabs, and export buttons.

### 17. `frontend/css/styles.css`
* **Purpose**: UI Styling & Themes.
* **Logic**: Modern slate dark theme (`#0f172a`), glassmorphism cards, micro-animations, and responsive layout.

### 18. `frontend/js/config.js`
* **Purpose**: Configuration.
* **Logic**: Sets `API_BASE_URL: "http://localhost:8009"`. All frontend API calls (endpoints `/api/extract`, `/api/download`, `/api/logs`, etc.) use this constant.

### 19. `frontend/js/app.js`
* **Purpose**: Client application state manager.
* **Logic**:
  - Intercepts file uploads and calls `POST /api/count-tokens` to open the cost estimation modal.
  - Submits extraction job to `POST /api/batch-extract`.
  - Sets up polling interval (`setInterval` every 1200ms) to query `GET /api/jobs/{job_id}`.
  - Updates progress bars in real-time and renders questions as each page completes.

### 20. `frontend/js/ui.js`
* **Purpose**: DOM rendering & interactions.
* **Logic**:
  - Renders question cards dynamically.
  - Invokes **KaTeX** to render LaTeX equations in questions, options, and solutions.
  - Implements **Diagram Lightbox Modal** so clicking any diagram zooms in for inspection.
  - Handles export button clicks (Excel, PDF, CSV, JSON, ZIP).
