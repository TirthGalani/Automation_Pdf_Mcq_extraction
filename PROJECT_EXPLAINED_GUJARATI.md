# 📘 MCQ PDF Extraction & Translation System — સંપૂર્ણ Logic અને વિગતવાર માર્ગદર્શિકા

આ દસ્તાવેજમાં આખા પ્રોજેક્ટનું **સરળ ભાષામાં Logic**, **કયું Model શું કામ કરે છે**, **Output કઈ રીતે બને છે**, અને **દરેક ફાઇલ તથા ફોલ્ડરનું અંદરનું કાર્ય (Line-by-Line / Block-by-Block Logic)** સમજાવેલ છે.

---

## 📑 અનુક્રમણિકા (Index)
1. [સિસ્ટમનો મૂળ આઈડિયા અને સિમ્પલ Flow (Big Picture)](#1-સિસ્ટમનો-મૂળ-આઈડિયા-અને-સિમ્પલ-flow)
2. [કયું Model વપરાય છે અને AI Logic શું છે?](#2-કયું-model-વપરાય-છે-અને-ai-logic-શું-છે)
   - [Gemini Flash vs Gemini Pro](#gemini-flash-vs-gemini-pro)
   - [Auto-Fallback Logic (Quota પતી જાય ત્યારે શું થાય?)](#auto-fallback-logic)
   - [Prompt Logic (AI ને શું આદેશ અપાય છે?)](#prompt-logic)
3. [Output કઈ રીતે તૈયાર થાય છે? (Output Pipeline)](#3-output-કઈ-રીતે-તૈયાર-થાય-છે)
   - [Excel (.xlsx) માં ફોટો સાથે ડેટા કઈ રીતે આવે છે?](#excel-output-logic)
   - [PDF માં ગણિતના સૂત્રો (LaTeX) કઈ રીતે છપાય છે?](#pdf-output-logic)
   - [JSON & CSV Logic](#json--csv-logic)
4. [દરેક Folder અને દરેક File નું વિગતવાર Logic](#4-દરેક-folder-અને-દરેક-file-નું-વિગતવાર-logic)
   - [Root Files (`start_app.bat`)](#root-files)
   - [Backend Root Files (`.env`, `requirements.txt`, `token_calculator.py`, etc.)](#backend-root-files)
   - [Backend App Module (`models.py`, `extractor.py`, `utils.py`, `main.py`, etc.)](#backend-app-module)
   - [Backend Services (`pdf_pipeline.py`, `pdf_export.py`)](#backend-services)
   - [Frontend Module (`index.html`, `styles.css`, `app.js`, `ui.js`, `config.js`)](#frontend-module)

---

# 1. સિસ્ટમનો મૂળ આઈડિયા અને સિમ્પલ Flow

તમારી પાસે **JEE, NEET કે બોર્ડની પરીક્ષાના PDF પેપરો** હોય છે. આ PDF માં:
- પ્રશ્નો **૨ કૉલમમાં (Two-Column)** હોય છે.
- ગણિત અને ફિઝિક્સના **LaTeX સૂત્રો** ($\frac{a}{b}$, $\sqrt{x}$, $\Omega$) હોય છે.
- પ્રશ્નો અને Options (A, B, C, D) માં **આકૃતિઓ (Diagrams / Circuits / Chemistry Structures)** હોય છે.
- અમુક PDF **ગુજરાતી કે હિન્દીમાં** હોય છે.
- જવાબો અને Detailed Solution ક્યાંક પાછળના પેજ પર અથવા અલગ PDF માં હોય છે.

### આ સિસ્ટમ આખું કામ સ્ટેપ-બાય-સ્ટેપ કઈ રીતે કરે છે?
```
[ ૧. વપરાશકર્તા PDF અપલોડ કરે છે ]
                 │
                 ▼
[ ૨. Token Calculator ] ──► અગાઉથી ગણે છે કે કેટલા Tokens વપરાશે અને કેટલા રૂપિયા (INR) નો ખર્ચ થશે.
                 │
                 ▼
[ ૩. pypdfium2 Engine ] ──► PDF ના દરેક પેજને 300 DPI ના હાઈ-ક્વોલિટી ફોટામાં કન્વર્ટ કરે છે.
                 │
                 ▼
[ ૪. Gemini Multimodal AI ] ──► ફોટો + માસ્ટર પ્રોમ્પ્ટ વાંચીને JSON ડેટા આપે છે:
                                 - પ્રશ્ન લખાણ (LaTeX સાથે)
                                 - Options (A, B, C, D)
                                 - સાચો જવાબ & સોલ્યુશન
                                 - આકૃતિના Bounding Box Coordinates [ymin, xmin, ymax, xmax]
                 │
                 ▼
[ ૫. Auto-Cropper & Cleaner ] ──► ઓરિજિનલ પેજમાંથી આકૃતિઓ કાપીને PNG બનાવે છે અને whitespace સાફ કરે છે.
                 │
                 ▼
[ ૬. Solution Matcher ] ──► જો સોલ્યુશનની અલગ PDF આપી હોય, તો Q.1 નો જવાબ Q.1 માં મેચ કરી દે છે.
                 │
                 ▼
[ ૭. Final Exporter ] ──► Excel (ફોટા સાથે), PDF (ગણિતના સૂત્રો સાથે), CSV અને JSON ડાઉનલોડ માટે તૈયાર કરે છે.
```

---

# 2. કયું Model વપરાય છે અને AI Logic શું છે?

### Gemini Flash vs Gemini Pro

1. **`gemini-3.5-flash` / `gemini-3.6-flash` (પ્રાથમિક મોડેલ - Default)**:
   - **શા માટે?**: ખૂબ જ ઝડપી (Fast) છે અને સસ્તું છે.
   - **કાર્ય**: તે PDF પેજનો ફોટો જુએ છે, બંને કૉલમ (ડાબી બાજુ અને જમણી બાજુ) ના પ્રશ્નો વાંચે છે અને ફટાફટ JSON બનાવીને આપે છે.
   - **ટોકન ચાર્જ**: આશરે $0.075 પ્રતિ 1M tokens.

2. **`gemini-3.1-pro-preview` / `gemini-2.5-pro` (ફોલબેક મોડેલ - Fallback)**:
   - **શા માટે?**: જ્યારે Flash મોડેલની લિમિટ આવી જાય (HTTP 429 Quota Exhausted) અથવા બહુ વધારે જટિલ ગણિત-સાયન્સ હોય, ત્યારે આ મોડેલ કામ સંભાળી લે છે.
   - **કાર્ય**: પ્રો મોડેલ હાઈ-રિઝનિંગ પાવર ધરાવે છે જેથી કોઈ ભૂલ ન પડે.

---

### Auto-Fallback Logic (Quota પતી જાય ત્યારે શું થાય?)
જો તમે 50 પેજની મોટી PDF નાખો અને ગૂગલના Flash મોડેલનો Quota પતી જાય:
1. `extractor.py` માં ટ્રાય-કેચ (try-except) રાખેલું છે જે `ResourceExhausted` અથવા `429` એરર પકડે છે.
2. સિસ્ટમ **ક્રેશ થતી નથી** કે અટકતી નથી!
3. તે તરત જ મેસેજ મોકલે છે: `⚠️ Flash quota exhausted — switched to gemini-3.1-pro-preview`.
4. જે પેજ પર પહોંચ્યા હતા ત્યાંથી જ પ્રો મોડેલ આગળનું કામ સંભાળી લે છે.
5. જો બંને મોડેલ પતી જાય, તો અત્યાર સુધી જેટલા પ્રશ્નો કઢાયા તેટલા સાચવીને **Partial Success** તરીકે તમને ડાઉનલોડ કરવા આપી દે છે.

---

### Prompt Logic (`prompt_template.py`)
AI મોડેલને આડેધડ આદેશ નથી આપતા, પણ ૮ કડક નિયમો (Rules) સાથે બાંધવામાં આવ્યું છે:
* **Rule 0 (વિષય ઓળખવો)**: માત્ર `Physics`, `Chemistry`, `Mathematics` કે `Biology` જ વિષય લખવો, "General" ક્યારેય નહીં.
* **Rule 1 (ટૂ-કૉલમ સ્કેનિંગ)**: ડાબી કૉલમ ઉપરથી નીચે સુધી આખી વાંચવી, પછી જ જમણી કૉલમ વાંચવી. વચ્ચેથી પેજ અધૂરું છોડવું નહીં.
* **Rule 2 (ઓરિજિનલ નંબરિંગ)**: જો પેપર પર `46` નંબર છાપ્યો હોય તો JSON માં `46` જ લખવું, `1` નહીં. જેથી સોલ્યુશન સાથે ભૂલ વગર 1-to-1 મેચ થાય.
* **Rule 2B (સબ-પ્રશ્નો)**: જો પ્રશ્ન ૨૭ માં `(i)`, `(ii)`, `(iii)` હોય, તો બધાને અલગ અલગ પ્રશ્ન તરીકે બહાર કાઢવા.
* **Rule 3 & 4 (ઝીરો કટઓફ & મૂળ ભાષા)**: પ્રશ્ન કાપ્યા વગર પૂરો લખવો. ગુજરાતી હોય તો ગુજરાતીમાં જ રાખવું, અંગ્રેજીમાં ભાષાંતર કરીને બગાડવું નહીં. ગણિતના સમીકરણો `$..$` માં જ લખવા.
* **Rule 6 (પેજ વચ્ચે તૂટેલા પ્રશ્નો)**: જો પ્રશ્ન પેજ ૧ ના છેડે શરૂ થાય અને Options પેજ ૨ પર હોય, તો તેને `is_split_at_bottom` અને `is_continuation` થી જોડી દેવા.

---

# 3. Output કઈ રીતે તૈયાર થાય છે?

### Excel Output Logic (`export_to_excel_bytes` in `utils.py`)
સામાન્ય કન્વર્ટર માત્ર ટેક્સ્ટ આપે છે, જ્યારે આ સિસ્ટમ:
1. **OpenPyXL** લાયબ્રેરી વાપરે છે.
2. હેડરને **ડાર્ક નેવી બ્લૂ (`#1E293B`)** કલર અને સફેદ બોલ્ડ અક્ષરો આપે છે.
3. જો પેપરમાં આકૃતિ હોય, તો તે આકૃતિ માત્ર પાથ (URL) તરીકે નહીં, પણ **સેલ (Cell) ની અંદર જ ફોટો એમ્બેડ (Insert Image)** કરી દે છે!
4. જે રો (Row) માં ફોટો હોય તેની હાઇટ આપોઆપ **75pt** થઈ જાય છે જેથી ફોટો ચોખ્ખો દેખાય.
5. **JEE Advanced માટે ૩ Sheets ની વિશેષ વ્યવસ્થા**:
   - **Sheet 1 (`Questions`)**: સામાન્ય MCQ, Multiple Correct અને Numerical/Integer પ્રશ્નો (૧૯ કૉલમ).
   - **Sheet 2 (`Paragraph Type`)**: ફકરા (Comprehension Passage) આધારિત પ્રશ્નો ૨૧ કૉલમમાં (`ID | Paragraph | Question | Type | Option A-D | Answer | Marks | Difficulty | Subject | Paragraph Image | Question Image | Option Images | Solution | Solution Image`). ફકરાના ગ્રુપના પ્રથમ પ્રશ્ન પર જ ફકરાની ટેક્સ્ટ અને આકૃતિ દેખાય છે.
   - **Sheet 3 (`Match The Column`)**: જોડકાં (Matrix Matching) આધારિત પ્રશ્નો ૨૧ કૉલમમાં (`ID | Question | Column-I | Column-II | Type | Option A-D | Answer | Marks | Difficulty | Subject | Question Image | Answer Image | Column-I Images | Solution | Solution Image`).
6. **સામાન્ય પેપર્સ (Non-Advance)**: સ્વચ્છ ૧ Sheet (`Questions`) અથવા Topic વાળા પેપર્સ માટે ૨ Sheets (`Questions` + `Topics`) જ બને છે.

### PDF Output Logic (`pdf_export.py`)
1. **LaTeX Rendering**: ગણિતના સમીકરણો જેવા કે $\int_0^\pi \sin(x)dx$ ને Matplotlib ની મદદથી નાના ક્રિસ્પ PNG ફોટા બનાવી લે છે.
2. **ReportLab Platypus**: પ્રશ્ન, ચારેય ઓપ્શન્સ, સાચો જવાબ (લીલા રંગમાં), અને સોલ્યુશન (યલો હાઈલાઈટ બોક્સમાં) સુંદર રીતે ગોઠવે છે.
3. **KeepTogether Logic**: એવો નિયમ છે કે પ્રશ્ન અને તેના ઓપ્શન્સ ક્યારેય પેજના છેડે અડધા કપાઈને બીજા પેજ પર ન જાય; આખો પ્રશ્ન કાર્ડ સાથે જ રહે.

---

# 4. દરેક Folder અને દરેક File નું વિગતવાર Logic

---

## 📁 Root Files

### 1. `start_app.bat`
* **શું કરે છે?**: વિન્ડોઝમાં સિંગલ-ક્લિક સ્ટાર્ટઅપ.
* **Logic**:
  - `python -m pip install -r backend/requirements.txt`: જરૂરી પેકેજ ચેક કરીને ઇન્સ્ટોલ કરે છે.
  - `start "" http://localhost:8009`: બ્રાઉઝર ખોલે છે.
  - `cd backend` & `uvicorn app.main:app`: FastAPI સર્વર પોર્ટ 8009 પર ચાલુ કરે છે.

---

## 📁 `backend/` Folder

### 2. `backend/.env` અને `.env.example`
* **શું કરે છે?**: સિક્રેટ કી અને કોન્ફિગરેશન.
* **Logic**:
  - `GEMINI_API_KEY`: ગૂગલ AI સ્ટુડિયોની API કી.
  - `GEMINI_MODEL`: પ્રાઇમરી મોડેલ (જેમ કે `gemini-3.6-flash`).
  - `GEMINI_FALLBACK_MODEL`: સેકન્ડરી મોડેલ (જેમ કે `gemini-3.5-pro-preview`).

### 3. `backend/.jobs_cache.json`
* **શું કરે છે?**: જોબ્સનો ઇતિહાસ (Database).
* **Logic**: સર્વર અચાનક રીસ્ટાર્ટ થાય કે લાઈટ જાય, તો પણ અગાઉ થયેલા બેચ પ્રોસેસિંગના ડેટા ગુમ ન થાય તે માટે JSON ફાઈલમાં છેલ્લી 20 જોબ્સનો રેકોર્ડ સચવાય છે.

### 4. `backend/requirements.txt`
* **શું કરે છે?**: તમામ પાયથોન લાઈબ્રેરીઓનું લિસ્ટ:
  - `fastapi`, `uvicorn`: વેબ સર્વર માટે.
  - `google-genai`, `google-generativeai`: ગૂગલ AI મોડેલ સાથે વાત કરવા.
  - `pypdfium2`, `pdfplumber`, `pypdf`: PDF પ્રોસેસિંગ અને 300 DPI ઈમેજ રેન્ડરિંગ માટે.
  - `pillow` (PIL): આકૃતિઓ કાપવા (Crop) માટે.
  - `pandas`, `openpyxl`: Excel ફાઇલ બનાવવા અને ફોટા એમ્બેડ કરવા માટે.
  - `reportlab`, `matplotlib`: LaTeX ગણિત સાથે સુપ્રીમ ક્વોલિટી PDF પેપર બનાવવા.

### 5. `backend/token_calculator.py`
* **શું કરે છે?**: ટોકન ગણતરી અને લાઇવ ખર્ચ અંદાજ.
* **Logic**:
  - `get_pdf_page_count()`: PDF ના પેજ ગણે છે.
  - `fetch_usd_to_inr()`: ઓનલાઇન API થી ડૉલર સામે રૂપિયાનો લાઇવ રેટ લાવે છે (દા.ત. ₹84.50).
  - ગણે છે કે: `Input Tokens = Prompt + (પેજ દીઠ ~1000 Vision Tokens) + ટેક્સ્ટ`.
  - એક્સટ્રેક્શન શરૂ કરતા પહેલાં યુઝરને ચોક્કસ ખર્ચ (₹ માં) બતાવે છે.

### 6. `backend/batch_cli.py`
* **શું કરે છે?**: બ્રાઉઝર વગર કમાન્ડ લાઇન (CMD) માંથી ડાયરેક્ટ PDF એક્સટ્રેક્ટ કરવા માટેનું ટૂલ.
* **Logic**: `--input-dir ./pdfs` આપો એટલે અંદર રહેલી બધી જ PDF એક પછી એક પ્રોસેસ કરીને સીધું JSON સેવ કરી દે.

### 7. `backend/test_extraction_improvements.py`
* **શું કરે છે?**: ઓટોમેટેડ ટેસ્ટિંગ ફાઇલ.
* **Logic**: સિસ્ટમમાં કોઈ ફેરફાર કરીએ તો LaTeX રિપેર, 2-કૉલમ સોર્ટિંગ, ઓપ્શન સાફ-સફાઈ વગેરે યોગ્ય ચાલે છે કે નહીં તેની ખાતરી કરે છે.

### 8. `backend/extracted_images/`
* **શું કરે છે?**: આ ફોલ્ડરમાં PDF માંથી કાપેલી તમામ આકૃતિઓ (PNG ફાઇલો) સેવ થાય છે, જે યુઝરને બ્રાઉઝરમાં દેખાય છે અને Excel માં એડ થાય છે.

---

## 📁 `backend/app/` Module

### 9. `backend/app/models.py`
* **શું કરે છે?**: Pydantic Data Models (ડેટાનું માળખું).
* **Logic**:
  - `OptionDetail`: દરેક ઓપ્શનનું ટેક્સ્ટ અને આકૃતિનું બોક્સ.
  - `QuestionItem`: સવાલ, ઓપ્શન્સ, જવાબ, સોલ્યુશન, ડિફિકલ્ટી, આકૃતિઓ, પેસેજ, મેચિંગ કૉલમ.
  - `ExtractionResult`: એક ફાઈલનું આખું પરિણામ.
  - `BatchJobProgress`: પ્રોસેસિંગના ટકા, હાલનું પેજ, મોડેલનું સ્ટેટસ.

### 10. `backend/app/prompt_template.py`
* **શું કરે છે?**: AI ને અપાતી માસ્ટર ઇન્સ્ટ્રક્શન્સ (પ્રોમ્પ્ટ).
* **Logic**:
  - ગૂગલ જેમિની મોડેલને ચોક્કસ નિયમો આપે છે જેથી તે ડાબી-જમણી કૉલમ વ્યવસ્થિત વાંચે, સાચા JSON ફોર્મેટમાં જ આઉટપુટ આપે, અને સાયન્સના સૂત્રો `$..$` માં લખે.

### 11. `backend/app/extractor.py`
* **શું કરે છે?**: સમગ્ર એક્સટ્રેક્શનનું મગજ (Core Engine).
* **Logic**:
  - `pypdfium2` થી PDF પેજને 300 DPI ઈમેજ બનાવે છે.
  - Gemini API ને આ ઈમેજ મોકલે છે.
  - AI તરફથી આવેલા જવાબમાંથી Bounding Box `[ymin, xmin, ymax, xmax]` પકડે છે.
  - તે બોક્સ મુજબ પેજમાંથી આકૃતિ કટ કરીને `extracted_images/` માં સાચવે છે.
  - જો Flash મોડેલ ફેલ થાય, તો ઓટોમેટિક Pro મોડેલ પર સ્વિચ કરે છે.
  - જો Solution PDF આપી હોય તો `extract_solutions_and_answers_from_pdf()` થી સોલ્યુશન્સ લાવીને પ્રશ્નો સાથે જોડી દે છે.

### 12. `backend/app/utils.py`
* **શું કરે છે?**: ડેટા ક્લીનિંગ અને એક્સપોર્ટ ટૂલ્સ.
* **Logic**:
  - `repair_json_escapes()`: ગૂગલ ઘણીવાર `\frac` કે `\alpha` આપે છે જેનાથી JSON તૂટી જાય છે; આ ફંક્શન તેને રિપેર કરીને `\\frac` બનાવે છે.
  - `extract_json_from_response()`: જો ટોકન લિમિટના કારણે JSON અધૂરું કપાઈ ગયું હોય, તો છેલ્લે બાકી રહેલા કૌંસ `]}` આપમેળે પૂરા કરીને ડેટા બચાવી લે છે.
  - `split_question_and_options()`: જો પ્રશ્નની અંદર જ `(A) (B) (C) (D)` છપાઈ ગયા હોય, તો તેને છૂટા પાડીને ઓપ્શન્સમાં મૂકી દે છે.
  - `clean_question_text()`: બિનજરૂરી એક્ઝામ ટેગ્સ જેવા કે `[JEE Main 2019]` હટાવે છે.
  - `export_to_excel_bytes()`: કમ્પ્લીટ Excel શીટ બનાવે છે અને ફોટા અંદર સેલમાં ચોંટાડે છે.
  - `export_to_csv_bytes()`: UTF-8 BOM સાથે CSV બનાવે છે જેથી ગુજરાતી અક્ષરો એક્સેલમાં બગડે નહીં.

### 13. `backend/app/main.py`
* **શું કરે છે?**: FastAPI સર્વર અને તમામ API Endpoints.
* **Logic**:
  - `/api/health`: સર્વર અને કી ચેક કરે છે.
  - `/api/count-tokens`: ફાઇલોના ટોકન અને કિંમત ગણે છે.
  - `/api/batch-extract`: બેકગ્રાઉન્ડ ટાસ્ક શરૂ કરે છે અને યુઝરને તરત `job_id` આપી દે છે જેથી બ્રાઉઝર હેંગ ન થાય.
  - `/api/jobs/{id}`: દર સેકન્ડે ફ્રન્ટએન્ડને જણાવે છે કે કેટલા ટકા કામ પત્યું.
  - `/api/export/{id}/[excel|csv|json|pdf|images]`: યુઝરને વિવિધ ફોર્મેટમાં ફાઇલ ડાઉનલોડ કરાવે છે.
  - `/api/images/{name}`: કાપેલી આકૃતિઓ બ્રાઉઝરમાં બતાવે છે.

---

## 📁 `backend/app/services/` Module

### 14. `backend/app/services/pdf_pipeline.py`
* **શું કરે છે?**: ઈમેજ પ્રોસેસિંગ અને ક્રોપિંગ એન્જિન.
* **Logic**:
  - `crop_image_from_page()`: નોર્મલાઇઝ્ડ 0-1000 કોઓર્ડિનેટ્સને 300 DPI પિક્સેલમાં કન્વર્ટ કરીને ફોટો ક્રોપ કરે છે.
  - `autocrop_tight_diagram()`: આકૃતિની આસપાસની વધારાની સફેદ જગ્યા કાપીને ટાઈટ ફિટ કરે છે.
  - `trim_option_label_from_crop()`: જો આકૃતિ સાથે ભૂલથી `(A)` કે `(B)` અક્ષર ક્રોપ થઈ ગયો હોય, તો તેને સાફ કરે છે.

### 15. `backend/app/services/pdf_export.py`
* **શું કરે છે?**: પ્રિન્ટ કરી શકાય તેવી સુંદર પરીક્ષા પેપર PDF જનરેટર.
* **Logic**:
  - `_latex_to_png_bytes()`: Matplotlib ની મદદથી ગણિતના સૂત્રોને સુંદર PNG બનાવે છે.
  - ReportLab દ્વારા પ્રોફેશનલ લેઆઉટ બનાવે છે જેમાં પ્રશ્ન, ઓપ્શન્સ, સાચો જવાબ અને યલો સોલ્યુશન બોક્સ છપાય છે.

---

## 📁 `frontend/` Module

### 16. `frontend/index.html`
* **શું કરે છે?**: વેબ એપ્લિકેશનનું મુખ્ય પેજ (UI).
* **Logic**:
  - ડાબી બાજુ સાઇડબાર (API કી, મોડેલ પસંદગી, લેંગ્વેજ).
  - વચ્ચે Drag & Drop અપલોડ બોક્સ (પ્રશ્ન પેપર + સોલ્યુશન પેપર).
  - લાઈવ પ્રોગ્રેસ બાર અને સ્ટેટસ મેસેજ.
  - નીચે પ્રશ્નોના પ્રિવ્યુ કાર્ડ્સ અને એક્સપોર્ટ બટનો (Excel, CSV, PDF, JSON).

### 17. `frontend/css/styles.css`
* **શું કરે છે?**: પ્રીમિયમ ડાર્ક થીમ ડિઝાઇનિંગ.
* **Logic**: સ્લેટ ડાર્ક બેકગ્રાઉન્ડ, ગ્લાસમોર્ફિઝમ કાર્ડ્સ, સ્મૂધ એનિમેશન અને રિસ્પોન્સિવ લેઆઉટ.

### 18. `frontend/js/config.js`
* **શું કરે છે?**: બેકએન્ડ API URL (`http://localhost:8009`) સેટ કરે છે.

### 19. `frontend/js/app.js`
* **શું કરે છે?**: ફ્રન્ટએન્ડનું કંટ્રોલર (Controller).
* **Logic**:
  - જ્યારે યુઝર ફાઇલ ડ્રોપ કરે ત્યારે `POST /api/count-tokens` કોલ કરીને ટોકન મોડલ પોપઅપ બતાવે છે.
  - 'Start Extraction' દબાવતા `POST /api/batch-extract` પર ફાઇલો અપલોડ કરે છે.
  - દર 1.2 સેકન્ડે `GET /api/jobs/{job_id}` થી પોલિંગ કરીને પેજ-બાય-પેજ પ્રોગ્રેસ અપડેટ કરે છે.
  - કામ પૂરું થતાં ડાઉનલોડ બટનો સક્ષમ (Enable) કરે છે.

### 20. `frontend/js/ui.js`
* **શું કરે છે?**: DOM રેન્ડરિંગ અને વિઝ્યુઅલ ફીચર્સ.
* **Logic**:
  - કાઢેલા પ્રશ્નોના કાર્ડ્સ બનાવે છે.
  - **KaTeX / MathJax** દ્વારા ગણિતના સમીકરણો બ્રાઉઝરમાં સાચા મેથ સિમ્બોલ તરીકે રેન્ડર કરે છે.
  - જો યુઝર આકૃતિ પર ક્લિક કરે, તો **Lightbox Modal** ખોલીને આકૃતિ મોટી કરીને બતાવે છે.
