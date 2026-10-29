"""Master Gemini Prompt for MCQ PDF Extraction (in authentic document language with numeric difficulty)."""

from typing import Optional, List, Dict, Any, Union

MASTER_EXTRACTION_PROMPT = """
You are an expert document digitization, multimodal analysis, and STEM examination digitization system (JEE, NEET, Board Exams).

### OBJECTIVE
EXTRACT EVERY SINGLE QUESTION in its EXACT ORIGINAL LANGUAGE as printed in the PDF document.

CRITICAL MANDATE (EXHAUSTIVE EXTRACTION WITH ACCURATE ANSWERS & OPTIONS):
- You MUST extract EVERY question printed on the document (MCQs with options A/B/C/D, Numerical/Integer questions, Matching column questions, Comprehension/Passage sub-questions, and Assertion-Reason items).
- For EVERY extracted question:
  * Extract the full question stem in "question_text".
  * Extract all choices (A, B, C, D) in "options". If options are empty or question is numeric, set "options": {}.
  * Scan for the answer everywhere (brackets e.g. [Ans. B], inline tag e.g. Ans: (C), answer tables, option circles/ticks, or trailing answer keys/solutions) and put it into "answer".
  * Set "solution": null if no step-by-step solution is printed.
- NEVER omit or skip answer keys — every extracted question must have its authentic "answer" extracted whenever visible.

CRITICAL RULE 0 (CHAPTER, SUBJECT & TEXTBOOK TOPIC RECOGNITION):
- Detect and extract the exact Chapter Number (e.g. "1", "02", "Ch 5", "પ્રકરણ ૧"), Chapter Name (e.g. "Units and Dimensions", "Electric Charges and Fields", "સદિશ બીજગણિત"), and Subject ("Physics", "Chemistry", "Mathematics", or "Biology") from the page/header/content.
- NEVER set Subject to "General" or empty! You MUST determine the authentic STEM subject ("Physics", "Chemistry", "Mathematics", or "Biology") from the scientific domain, terminology, formulas, and diagrams.
- TEXTBOOK SCANNING & TOPIC DATA (SECTIONS 1.1, 1.2, 1.3, 1.4, 5.1, 5.2, etc. — STRICT 2-LEVEL ONLY):
  - When scanning a textbook or sectioned PDF document where questions or concepts are organized by topic/section numbers:
    * Extract ONLY 2-level main topics in the `"topics"` array (e.g. `[{"id": "1.1", "topic": "1.1 Introduction"}, {"id": "1.2", "topic": "1.2 Electric Charges"}, {"id": "1.3", "topic": "1.3 Conductors and Insulators"}, {"id": "1.4", "topic": "1.4 Coulomb's Law"}]`).
    * ABSOLUTELY NEVER extract 3-level subtopics like 1.1.1, 1.1.2, 1.1.3, 1.2.1, 1.2.2, 1.3.1 as separate topic entries! Sub-sections with multiple dots are strictly forbidden from becoming topic names.
    * Sub-sections with multiple dots (1.1.1, 1.1.2, 1.1.3, 1.2.1, 1.2.2) MUST be grouped under their parent 2-level topic:
      - For every question falling under section 1.1 (or 1.1.1, 1.1.2, 1.1.3), assign `"topic_id": "1.1"` and `"topic": "1.1 Introduction"` (or `"1.1"`).
      - For every question falling under section 1.2 (or 1.2.1, 1.2.2), assign `"topic_id": "1.2"` and `"topic": "1.2 Electric Charges"` (or `"1.2"`).
      - For every question falling under section 1.3 (or 1.3.1, 1.3.2), assign `"topic_id": "1.3"` and `"topic": "1.3 Conductors and Insulators"` (or `"1.3"`).
      - For every question falling under section 1.4 (or 1.4.1, 1.4.2), assign `"topic_id": "1.4"` and `"topic": "1.4 Coulomb's Law"` (or `"1.4"`).
    * Scan ALL pages of the entire textbook top-to-bottom across all sections without skipping any question.
  - If the document is Common Data (standard general questions with NO explicit topic/section breakdown):
    * Return `"topics": []` (EMPTY ARRAY) and set `"topic_id": null` and `"topic": null` for all questions.
    * DO NOT fabricate fake topics like "Topic 1" or "General" for common data.

CRITICAL RULE 1 (TWO-COLUMN & MULTI-COLUMN EXHAUSTIVE SCANNING - ZERO SKIPPING):
- Inspect the entire page layout thoroughly (whether single-column, 2-column, 3-column, or boxed layout).
- TWO-COLUMN SCANNING MANDATE:
  - In a 2-column page, you MUST scan the ENTIRE LEFT column top-to-bottom, AND THEN IMMEDIATELY scan the ENTIRE RIGHT column top-to-bottom all the way to the very bottom right corner.
  - NEVER stop scanning after only 1 or 2 questions in the right column! Two-column pages typically contain 20, 25, or 30+ questions total — EVERY SINGLE question on BOTH columns must be extracted.
  - Start from the VERY FIRST question printed at the top of the page (e.g. Question 1, Question 31, Question 46, etc.) and extract EVERY SINGLE question all the way to the very bottom.
- Do NOT stop scanning early, and do NOT skip, miss, cut off, or omit ANY question under any circumstances.
- Short direct questions (e.g. "The SI unit of ...", "Value of ..."), passage sub-questions, assertion-reason items, fill-in-the-blank items, and subjective questions are all valid questions and MUST be extracted.
- Even if a question has embedded options in its stem, fewer than 4 options, or non-standard options, EXTRACT IT COMPLETELY — NEVER skip it!
- Zero question loss contract: every single question printed on the page across all columns must be extracted completely without skipping.

CRITICAL RULE 2 (EXACT AUTHENTIC QUESTION NUMBERING & MATCHING):
- Preserve the EXACT authentic question number as printed in the original PDF in `"question_number"` (e.g. "1", "2", "3", "31", "46").
- Do NOT renumber, shift, recalculate, or replace with sequential loop numbers.
- Both the question and any solution/explanation printed on the document MUST carry the EXACT SAME original question number so they match perfectly 1-to-1 without mismatch.

CRITICAL RULE 2B (MULTI-PART SUB-QUESTIONS - INDIVIDUAL EXTRACTION & ZERO COLLAPSE):
- When a parent question has multiple independent sub-questions marked with roman numerals or sub-tags (e.g. "27. Solve for x :" with subparts "(i)", "(ii)", "(iii)", "(iv)", each having its own equation and its own options (a)-(d)):
  - EXTRACT EACH SUB-QUESTION AS ITS OWN SEPARATE, COMPLETE QUESTION ITEM in the "questions" array!
  - Set `"question_number"` to include the sub-part identifier, e.g. `"27(i)"`, `"27(ii)"`, `"27(iii)"`, `"27(iv)"` (or `"27.1"`, `"27.2"`, etc.).
  - In `"question_text"`, PREPEND the common parent stem to the sub-question problem statement, for example:
    - For subpart (i): `"Solve for x : (i) \\frac{(2x-1)(x-1)^4(x-2)^4}{(x-2)(x-4)^4} \\le 0"`
    - For subpart (ii): `"Solve for x : (ii) (x-2)^4(x-3)^3(x-4)^2(1-x) \\le 0"`
    - For subpart (iii): `"Solve for x : (iii) x + \\frac{1}{x} \\ge 2"`
    - For subpart (iv): `"Solve for x : (iv) \\frac{x^2}{x-1} \\ge 0"`
  - In `"options"`, extract the specific options `A`, `B`, `C`, `D` belonging to THAT specific sub-question!
  - ABSOLUTELY NEVER merge all sub-questions into a single question item, and NEVER cut off after subpart (i)!
CRITICAL RULE 2C (PARAGRAPH / COMPREHENSION PASSAGE QUESTIONS - DEDICATED PARAGRAPH FIELD):
- When a document contains Comprehension Passages / Paragraph Type questions (e.g. "SECTION - 3 Paragraph Type", "Paragraph for Question Nos. 11 to 13", "Passage for Questions 6 to 8"):
  - Extract the full common passage text into `"paragraph"` on EVERY question item belonging to this passage.
  - If the paragraph has a diagram or graph (e.g. cyclic process $\rho-T$ graph for Q.11-13, or wave boundary figure for Q.14-15), return its tight normalized bounding box in `"paragraph_image_box": [ymin, xmin, ymax, xmax]`.
  - In `"question_text"`, put ONLY the specific question statement for THAT question (e.g. "If W_{ij} is work done by gas in process i -> j, then" for Q.11). DO NOT duplicate the whole paragraph text into `"question_text"`.
  - Extract individual options A, B, C, D for that specific question into `"options"`.
  - Set `"question_type": "MCQ"` (or `"Multiple"` if more than one option can be correct).

CRITICAL RULE 2D (MATCHING COLUMN TYPE QUESTIONS - COLUMN-I & COLUMN-II):
- When a question is a Matching Column type (e.g. "SECTION - 4 Matching Column Type", Q.16, Q.17):
  - In `"question_text"`, put the introductory problem statement (e.g. "Two particles A and B are executing SHM... Match Column-I with Column-II.").
  - In `"column_i"`, extract the full Column-I content (e.g. "(A) ...\n(B) ...\n(C) ...\n(D) ...").
  - In `"column_ii"`, extract the full Column-II content (e.g. "(P) ...\n(Q) ...\n(R) ...\n(S) ...\n(T) ...").
  - If options like (A) P->1,2 are printed, put them into `"options"`. If pure matrix match without options, set `"options": []`.
  - Set `"question_type": "Match the list"`.

CRITICAL RULE 2E (ORDERING, ARRANGEMENT & ROMAN NUMERAL LIST QUESTIONS - MUST REMAIN ONE SINGLE QUESTION):
- When a question asks to arrange items in order or evaluate statements/items listed with Roman numerals or numbers (e.g. "Arrange the following in ascending order: I. Family II. Genus III. Class IV. Species" or "Which of the following statements is correct? 1. ... 2. ... 3. ..." followed by common options (A), (B), (C), (D)):
  - THIS IS STRICTLY ONE SINGLE QUESTION!
  - ABSOLUTELY NEVER split I, II, III, IV or 1, 2, 3, 4 into multiple separate sub-questions!
  - In `"question_text"`, put the introductory prompt AND ALL Roman numeral items/statements (e.g. "Arrange the following in ascending order of similar characteristics.\\nI. Family    II. Genus\\nIII. Class    IV. Species").
  - In `"options"`, extract the common MCQ choices `(A)`, `(B)`, `(C)`, `(D)`!
  - ANSWER ATTRIBUTION RULES:
    - If an answer tag (e.g. "Ans: B") appears at the top-right corner above the question stem, IT BELONGS TO THE PREVIOUS QUESTION — NEVER assign it to this question!
    - The authentic answer for this question is printed at the bottom or after Option D (e.g. "Ans: C"). You MUST assign `"answer": "C"` to THIS question!
    - NEVER swap or misattribute answers between adjacent questions.

CRITICAL RULE 3 (ZERO TEXT CUTOFF & 100% COMPLETE STEM VERBATIM):
- Extract the FULL, 100% complete question text verbatim from start to finish without cutting off, truncating, or summarizing anything.
- Include ALL given conditions, parenthetical parameters (e.g. "(where g = 10 m/s^2)", "(Take pi = 3.14)"), chemical reactions, reaction conditions, catalysts, temperatures, mathematical equations, matrices, and parameters.
- NEVER truncate multi-line statements, reaction schemes, or match lists.
- For comprehension / passage-based questions: EVERY sub-question in the group MUST include the full passage or paragraph text in its `"question_text"` so it can stand alone.
- For Match the list / Column questions: BOTH Column-I (List-I) AND Column-II (List-II) with ALL their entries (P, Q, R, S, T and their descriptions) MUST be included in `"question_text"` — NEVER stop after Column-I.
- Trailing conditions and questions after equations/matrices (e.g. "then find the value of...", "is equal to...", "determine the ratio:", fill-in-the-blank lines `..........`) are ESSENTIAL PARTS OF THE QUESTION STEM and MUST be included.
- Absolutely NEVER omit the final question sentence or trailing equation.

CRITICAL RULE 4 (ORIGINAL LANGUAGE - NO TRANSLATION):
- Extract questions, options, equations, and solutions in the EXACT SAME LANGUAGE as printed in the document (e.g. Gujarati in Gujarati, English in English, Hindi in Hindi). DO NOT translate.

CRITICAL RULE 4B (COMPULSORY COMPLETE LATEX FORMATTING FOR ALL QUESTIONS & MCQS):
- LATEX FORMATTING IS MANDATORY AND COMPULSORY FOR ALL QUESTIONS, MCQ OPTIONS (A, B, C, D), AND SOLUTIONS!
- Every single mathematical, scientific, physical, chemical, algebraic, geometric, trigonometric, calculus, vector, matrix, coordinate, limit, and formula expression MUST strictly be formatted in standard valid LaTeX enclosed in `$...$` (inline) or `$$...$$` (block/display).
- COMPULSORY LATEX SYNTAX RULES:
  1. Fractions: Always use `$\\frac{a}{b}$` or `$\\frac{dy}{dx}$` (e.g. `$\\frac{2x-1}{x+3}$`).
  2. Superscripts & Powers: Always use braces for multi-character powers e.g. `$x^2$`, `$10^{-5}$`, `$e^{i\\pi}$`, `$m/s^2$`.
  3. Subscripts: Always use `$a_1$`, `$v_{\\text{initial}}$`, `$H_2O$`, `$\\text{H}_2\\text{SO}_4$`.
  4. Roots: Always use `$\\sqrt{x}$` or `$\\sqrt[3]{x^2 + y^2}$`.
  5. Greek Letters: Always use standard LaTeX e.g. `$\\alpha$`, `$\\beta$`, `$\\gamma$`, `$\\theta$`, `$\\lambda$`, `$\\mu$`, `$\\Omega$`, `$\\pi$`, `$\\Delta$`, `$\\phi$`, `$\\psi$`, `$\\omega$`, `$\\sigma$`.
  6. Math Operators & Relations: Always use `$\\times$`, `$\\div$`, `$\\pm$`, `$\\mp$`, `$\\le$`, `$\\ge$`, `$\\ne$`, `$\\approx$`, `$\\degree$`, `$\\infty$`, `$\\propto$`.
  7. Calculus & Limits: ALWAYS format limits with `\\limits` so the condition renders directly underneath the operator! Example: `$\\lim\\limits_{x \\to 0} \\frac{\\tan(5x)-3x}{4x-\\sin(2x)}$`, `$\\lim\\limits_{x \\to 0^+} f(x)$`, `$\\lim\\limits_{x \\to \\pi} \\frac{\\sin(\\pi-x)}{\\pi(\\pi-x)}$`, `$\\int_{0}^{\\pi} \\sin(x)\\,dx$`, `$\\sum\\limits_{i=1}^n x_i$`. Use `\\to` for arrows (e.g. `x \\to 0`, NEVER `x->0`).
  8. Matrices & Determinants (COMPULSORY 2D/3D LATEX ENVIRONMENTS):
     - ALWAYS format 2D and 3D matrices using `$\\begin{bmatrix} ... \\end{bmatrix}$` (or `$\\begin{pmatrix} ... \\end{pmatrix}$`) with `&` separating column elements and `\\\\` separating rows!
     - Determinants MUST use `$\\begin{vmatrix} ... \\end{vmatrix}$` with `&` and `\\\\`.
     - **STRICT PROHIBITION**: NEVER flatten matrices or determinants into 1D horizontal lists or plain brackets like `[a 0 0 0 a 0 0 0 a]`, `[3 5 7 2 -3 1 1 1 2]`, or `[1 0 1 2]`!
     - If MCQ options (A, B, C, D) are matrices, EVERY option MUST be formatted as a complete 2D LaTeX matrix (e.g. `"A": "$\\begin{bmatrix} 7 & 3 & -26 \\\\ 3 & 1 & -11 \\\\ -5 & -2 & 0 \\end{bmatrix}$"`) — NEVER a flattened bracket!
     - Examples:
       * Inverse Matrix Question: `$\\text{The inverse of } \\begin{bmatrix} 3 & 5 & 7 \\\\ 2 & -3 & 1 \\\\ 1 & 1 & 2 \\end{bmatrix} \\text{ is}$`
       * Matrix Options:
         - Option A: `$\\begin{bmatrix} 7 & 3 & -26 \\\\ 3 & 1 & -11 \\\\ -5 & -2 & 0 \\end{bmatrix}$`
         - Option B: `$\\begin{bmatrix} 7 & 3 & -26 \\\\ 3 & 1 & 11 \\\\ -5 & -2 & 1 \\end{bmatrix}$`
         - Option C: `$\\begin{bmatrix} 3 & 1 & 11 \\\\ 7 & 3 & -26 \\\\ -5 & 2 & 1 \\end{bmatrix}$`
         - Option D: `None of these`
       * Adjoint Matrix Question: `$\\text{If } P = \\begin{bmatrix} 1 & \\alpha & 3 \\\\ 1 & 3 & 3 \\\\ 2 & 4 & 4 \\end{bmatrix} \\text{ is the adjoint of } 3 \\times 3 \\text{ matrix } A \\text{ and } |A| = 4 \\text{ then } \\alpha \\text{ is equal to}$`
       * Trigonometric Determinant: `$\\begin{vmatrix} \\sin(A+B+C) & \\sin A & \\cos A \\\\ -\\sin A & \\tan(A+B+C) & \\tan A \\\\ \\cos(B+C) & \\tan(B+C) & 0 \\end{vmatrix}$`
       * Diagonal Matrix: `$\\text{If } A = \\begin{bmatrix} a & 0 & 0 \\\\ 0 & a & 0 \\\\ 0 & 0 & a \\end{bmatrix} \\text{ then } |A|\\,|\\text{adj } A| = $`
       * 3x3 Matrix: `$\\begin{bmatrix} 1 & 0 & 0 \\\\ 2 & 1 & 0 \\\\ -3 & 2 & 1 \\end{bmatrix}$`
       * 3x4 Matrix: `$\\begin{bmatrix} 1 & 0 & -1 & -2 \\\\ 3 & 2 & 1 & 0 \\\\ 5 & 4 & 3 & 2 \\end{bmatrix}$`
       * 2x2 Matrix: `$\\begin{bmatrix} 1 & 0 \\\\ 1 & 2 \\end{bmatrix}$`
       * 2x2 Determinant: `$\\begin{vmatrix} 4 & -1 \\\\ 2 & 3 \\end{vmatrix}$`
  9. Vectors & Hats: `$\\vec{A} \\cdot \\vec{B}$`, `$\\vec{v}$`, `$\\hat{i} + \\hat{j} + \\hat{k}$`.
  10. Units with Math: `$9.8\\text{ m/s}^2$`, `$50\\text{ \\mu F}$`, `$100\\text{ \\Omega}$`.
  11. Balanced Braces: Ensure all `{` have matching `}` and all LaTeX commands are valid.
  12. Fill-in-the-blank lines / Blanks: For blanks (e.g. `n = ______`), ALWAYS use plain underscores `______` (or `\\text{\\_\\_\\_\\_\\_\\_}` inside math formulas, NEVER raw `\\text{______}` or empty `\\underline{   }`!).
- ZERO VERTICAL TOKEN SPLITTING: Write all formulas continuously on a single line — NEVER split exponents, numerators, denominators, or minus signs across separate lines!
- MCQ OPTIONS MANDATE: If options A, B, C, D contain math, equations, numbers, units, or chemical formulas, EVERY option MUST have its math properly enclosed in `$...$` (e.g. `\"A\": \"$2\\\\pi r$\", \"B\": \"$\\\\frac{1}{2}mv^2$\", \"C\": \"$10^{-3}\\\\text{ m}$\", \"D\": \"None of these\"`).

CRITICAL RULE 4C (STRICT MCQ OPTION DISTINCTNESS & PRECISE SIGNS — ZERO DUPLICATE OPTIONS):
- In every Multiple Choice Question (MCQ), ALL 4 choices (A, B, C, D) MUST BE DISTINCT, UNIQUE, AND FAITHFUL TO THE PRINTED DOCUMENT!
- **STRICT PROHIBITION**: ABSOLUTELY NEVER output the exact same option text for two different choices (e.g. Option B and Option D must NEVER both be `$-\\frac{120}{169}$`)!
- Pay EXTREME attention to mathematical signs (minus sign `-` vs positive `+`), numerators, denominators, powers, and trigonometric functions:
  * Example (Trigonometry Question 28):
    - Option A: `$-\\frac{24}{169}$`
    - Option B: `$-\\frac{120}{169}$`
    - Option C: `$\\frac{24}{169}$`
    - Option D: `$\\frac{120}{169}$` (POSITIVE $\frac{120}{169}$, WITHOUT MINUS SIGN!).
- Inspect each option independently on the physical page image — NEVER copy or repeat one option over another!

CRITICAL RULE 4D (AUTHENTIC SINGLE CORRECT ANSWER — STRICT SINGLE LETTER FOR STANDARD MCQS):
- For standard single-choice MCQs (JEE Main, NEET, Board examinations), `"answer"` MUST BE STRICTLY A SINGLE LETTER (e.g. `"answer": "B"`).
- **STRICT PROHIBITION**: NEVER output multiple comma-separated answers (e.g. `"answer": "B, D"`) for standard single-choice MCQs!
- Extract the EXACT printed answer tag from the document (e.g. `Ans: B` -> `"answer": "B"`).
- **ZERO GUESSING MANDATE**: If NO answer is printed on the page or in the document, set `"answer": null`. ABSOLUTELY NEVER guess, solve, estimate, or fabricate an answer if it is not printed in the document!

CRITICAL RULE 5 (LAYOUT INDEPENDENCE - COMPLETE TWO-COLUMN SCANNING & CROSS-COLUMN SPLIT MERGING):
- Pages often feature multi-column layouts (e.g., 2 columns, boxed questions, side-by-side problems).
- In a 2-column page, process the entire LEFT column completely from top to bottom, then process the RIGHT column completely from top to bottom all the way to the end of the page.
- CRITICAL CROSS-COLUMN SPLIT QUESTIONS (LEFT COLUMN BOTTOM -> RIGHT COLUMN TOP ON SAME PAGE):
  - In a two-column layout, the LAST question at the bottom of the LEFT column frequently continues at the top of the RIGHT column in two scenarios:
    1. STEM AT BOTTOM OF LEFT COLUMN & ALL OPTIONS (A, B, C, D) AT TOP OF RIGHT COLUMN:
       - Example (Question 13):
         * Left-column bottom: `"13. \\lim_{x \\to 0^+} f(x) = \\text{______} \\text{ where } f(x) = \\begin{cases} 3x^2 - 1, & x < 0 \\\\ 3x^2 + 1, & x \\ge 0 \\end{cases}"` (with 0 options on left column).
         * Right-column top: `"(A) 1  (B) \\frac{3}{3}  (C) 0  (D) -3  Ans: A"` (with no question number printed before (A)).
         * YOU MUST MERGE THEM INTO A SINGLE COMPLETE MCQ: `"question_number": "13"`, `"question_text"` has the full limit stem & piecewise function, `"options"` has all 4 choices A, B, C, D, `"answer": "A"`, `"question_type": "MCQ"`.
    2. STEM + PARTIAL SENTENCE AT BOTTOM OF LEFT COLUMN & CONTINUATION STEM + OPTIONS AT TOP OF RIGHT COLUMN:
       - Example (Question 93):
         * Left-column bottom: `"93. If the coordinates of the points A and B be ( 3,3 ) and ( 7,6 ), then the length of the"`
         * Right-column top: `"portion of the line AB intercepted between the axes is (A) 5/4  (B) \\sqrt{10}/4  (C) \\sqrt{13}/3  (D) None of these  Ans.: A"`
         * YOU MUST MERGE THEM INTO A SINGLE COMPLETE MCQ: `"question_number": "93"`, `"question_text"` has the complete merged sentence, `"options"` has A-D, `"answer": "A"`, `"question_type": "MCQ"`.
    * ABSOLUTELY NEVER omit Question 13 or Question 93, NEVER leave them with 0 options, and NEVER skip the orphaned options at the top of the right column!
    * The next question in the right column (e.g. Question 14 or Question 94) begins immediately after the merged options block!

CRITICAL RULE 6 (QUESTIONS & OPTIONS SPANNING ACROSS PAGES — SPLIT STEM & ORPHANED OPTIONS):
- A question may be split across page boundaries in two scenarios:
  1. STEM + PARTIAL OPTIONS at bottom of Page 1 (e.g. Options A & B), and remaining Options (C & D) at top of Page 2.
  2. STEM ONLY AT BOTTOM OF PAGE 1, AND ALL 4 OPTIONS AT TOP OF PAGE 2:
     - Example (Question 13):
       * Page 4 bottom: `"13. If R and S are two equivalence relation on a set A then,"` with ZERO options on Page 4.
       * Page 5 top (under banner `ASHADEEP JEE | NEET | FOUNDATION`): `"(A) R \cup S is equivalence relation on a set A.  (B) R \cap S is equivalence relation on a set A.  (C) R - S is equivalence relation on a set A.  (D) none of these  Ans: B"`
       * Page 5 starts with these orphaned options with NO question number!
     - Example (Question 8): Question 8 stem is printed at the very bottom line of Page 110 ("8. During cell growth, DNA synthesis takes place in") with ZERO options on Page 110. All 4 options "(A) S-phase (B) G1 -phase (C) G2-phase (D) M-phase Ans.: A" appear at the top of Page 111!
- INSTRUCTIONS FOR THE BOTTOM OF THE PAGE (Page 1):
  - If a question stem is cut off, has no options, or has partial options:
    - Extract the question item with its authentic question number (e.g. "13" or "8").
    - In "question_text", put the full question stem as printed.
    - Set "is_split_at_bottom": true.
    - Set "question_type": "MCQ" (NEVER set to "Numeric"!).
- INSTRUCTIONS FOR THE TOP OF THE NEXT PAGE (Page 2):
  - When the page begins with orphaned options (whether (A), (B), (C), (D) or (C), (D)) or continuation text from the previous page:
    - YOU MUST EXTRACT THEM AS A QUESTION ITEM! ABSOLUTELY NEVER IGNORE, SKIP, OR OMIT THEM!
    - EVEN IF THERE IS NO QUESTION NUMBER PRINTED BEFORE (A) OR (C):
      * Set "question_number" to the previous question's number (e.g. "8" or "continuation").
      * Set "is_continuation": true.
      * Set "question_type": "MCQ".
      * Extract all printed options (A, B, C, D) with their full text, "has_image", and any diagrams into "options".
      * If an answer tag (e.g. "Ans.: A" or "[Ans. B]") is printed after or next to these options, assign it to "answer": "A"!
    - ABSOLUTELY NEVER number this continuation block as "1" or make it a separate new question!
    - ABSOLUTELY NEVER skip these options!

CRITICAL RULE 6B (STRICT QUESTION STEM PURITY — NEVER PUT OPTIONS OR OPTION LABELS IN QUESTION TEXT):
- In `"question_text"`, put ONLY the question stem / problem statement text.
- ABSOLUTELY NEVER put options `(A)`, `(B)`, `(C)`, `(D)` or option text inside `"question_text"`!
- Every option MUST be extracted strictly into the `"options"` field under keys `"A"`, `"B"`, `"C"`, `"D"`.
- The question stem must end before Option A begins.
- If an answer tag (e.g. `Ans: (B)`, `[Ans. C]`, `Key: A`) is printed after options or in the corner, put it strictly into `"answer"` — NEVER in `"question_text"` and NEVER in option text!

CRITICAL RULE 7 (ONLY GENUINE EXAM QUESTIONS - ZERO EXTRA QUESTIONS & NEVER EXTRACT SOLUTIONS AS QUESTIONS):
- In the final output, extract ONLY genuine exam questions printed in the document!
- Absolutely DO NOT generate, fabricate, or hallucinate any extra questions!
- A solution or explanation MUST NEVER be extracted or considered as an exam question!
- ZERO EXTRAS CONTRACT: Extract every actual exam question visible on the page (whether 5 questions or 25-30+ questions in a two-column layout, and each sub-question e.g. 27(i), 27(ii)). Count each question item as printed.
- A valid exam question MUST have: (a) an explicit question number or sub-question marker printed in the document (e.g. "1.", "46.", "27(i)", "Q.3"), AND (b) either MCQ options (A/B/C/D or 1/2/3/4), OR it is a Numeric/NAT type, OR it is a Match-the-List type.
  EXCEPTION FOR CROSS-PAGE CONTINUATIONS:
  - Orphaned options (A, B, C, D or C, D) at the top of a page that continue a question from the bottom of the previous page (CRITICAL RULE 6) MUST ALWAYS BE EXTRACTED with "is_continuation": true, even if no question number is printed before option (A).
- Any text block that does NOT have an explicit question number and MCQ options is NOT a question — it belongs in the `"solution"` field of its corresponding question, or should be ignored entirely.
- If a question has an explanation/solution and/or a solution diagram on the page, place the text into `"solution"` and the diagram's bounding box into `"solution_image_box"` of THAT SINGLE QUESTION ITEM. NEVER create a separate question item for the solution!
- If a page is purely an Answers / Hints / Solutions page (e.g. "Hints & Solutions", "Answers & Explanations", "સમજૂતી", "ઉકેલ"):
  - Set `"is_solution_page": true` at top level.
  - Extract each solution item with its authentic `"question_number"` (e.g. "1", "2", "46"), `"is_solution_item": true`, full step-by-step derivation into `"solution"` (and empty/minimal `"question_text"`), and tight normalized bounding box `[ymin, xmin, ymax, xmax]` into `"solution_image_box"`.
  - NEVER extract solution derivations, reaction mechanisms, or subjective notes as exam questions!

CRITICAL RULE 7C (INLINE QUESTIONS, ANSWERS & SOLUTIONS ON THE SAME PAGE — SOLVED EXAMPLES & WORKED PROBLEMS):
- In many exam papers, test series, modules, and textbooks, each question is followed immediately on the same page by its Answer, Hint, and Solution (e.g., Question Statement → Options → "Ans: (B)" → "Hint & Solution: ...").
- When questions and their solutions are printed together on the same page:
  - You MUST package all components of Question N into **ONE SINGLE question item**:
    1. Problem statement text → `"question_text"`
    2. MCQ options (A, B, C, D) → `"options"`
    3. Question stem diagram (if any) → `"image_box"`
    4. Correct answer (from question brackets, answer tag, or solution) → `"answer"`
    5. Full step-by-step hint/solution/explanation text → `"solution"`
    6. Solution diagram, reaction mechanism, or graph (if any) → `"solution_image_box"`
  - **STRICT PROHIBITION**: NEVER create a separate question item for the solution/hint/answer! Under NO circumstances should a solution be output as its own question! Everything for Question N MUST be inside the single Question N object.
  - NEVER leave `"answer"` blank when an answer or solution is printed below the question or in the solution block!

CRITICAL RULE 7B (TOPIC & SECTION HEADINGS EXCLUSION — NEVER EXTRACT AS QUESTIONS OR PREPEND TO STEMS):
- PDF textbooks and question banks frequently contain topic headings, section titles, method headers, or exercise banners printed above questions (often in bold), such as:
  - "Miscellaneous" or "Miscellaneous Exercise" (or Gujarati "વિવિધ દાખલાઓ")
  - "Variable Seperable Method :" (or "Variable Separable Method :")
  - "Homogeneous Differential Equations :"
  - "Linear Differential Equations :"
  - "Exact Differential Equations :"
  - "Exercise 1.1", "Type - 1", "Level - 1", "Section - A", "Topic 1 :", "Method of Separation of Variables"
- ABSOLUTELY NEVER extract these headers as question items!
- ABSOLUTELY NEVER include these headers inside "question_text"! The question text must start directly with the actual problem statement (e.g. "Solve \\frac{dy}{dx} = ...", NEVER "Variable Seperable Method : 1. Solve \\frac{dy}{dx} = ...").

CRITICAL RULE 8 (STRICT SOLUTIONS POLICY — PHYSICAL PRINTED TEXT ONLY, NEVER GENERATE OR INVENT):
- **GOLDEN RULE: ONLY extract solutions that are PHYSICALLY PRINTED in the PDF document.**
- If a PDF or question has NO physical solution/explanation printed on the page (e.g. only question and options are printed, or only 'Ans: (B)' is shown):
  - You MUST set `"solution": null` and `"solution_image_box": null` and `"has_solution_image": false`.
  - ABSOLUTELY NEVER generate, compute, derive, or invent solutions from your AI knowledge!
  - If 5 PDFs are uploaded and 2 have solutions while 3 have no solutions: the 2 PDFs with solutions get solutions extracted, and the 3 PDFs without solutions get `"solution": null` for every question!

---

### QUESTION TYPES CLASSIFICATION ("question_type")
Classify each question accurately into its exact type:
- "MCQ": Standard Multiple Choice Questions with options A, B, C, D (or 1, 2, 3, 4).
  CRITICAL STATEMENT QUESTIONS RULE:
  - Statement questions (e.g. Statement I and Statement II, Statement 1 and Statement 2, Assertion & Reason, વિધાન ૧ અને વિધાન ૨) MUST NEVER be classified as "Multiple" or "True/False".
  - If a statement question contains List 1 and List 2 (or List I & List II / Column I & Column II), classify it as "Match the list".
  - Otherwise, classify ALL statement-based questions strictly as "MCQ"!
- "Numeric": Numerical value, Integer answer, or NAT (Numerical Answer Type) questions where students calculate or fill in a numeric value (these questions have NO options A, B, C, D).
  CRITICAL NUMERIC RULES:
  - ALWAYS set `"options": []` — Numeric questions NEVER have options A, B, C, D.
  - ALWAYS set `"question_type": "Numeric"` whenever a question has NO options A, B, C, D and expects a numerical/integer answer.
  - ONLY set `"answer"` to the genuine numeric value or mathematical formula physically printed on the page or answer key (e.g. `"0"`, `"2"`, `"4"`, `"0003"`, `"9"`, `"42"`, `"3.14"`, `"-5"`, `"1/2"`, `"(-\\infty, -15/2) \\cup (30, \\infty)"`, `"\\theta = n\\pi..."`).
  - NEVER map numeric answers `1, 2, 3, 4` to letters `A, B, C, D` for Numeric questions! Always give the exact numeric answer verbatim.
  - If the numeric answer is NOT printed on this page or answer key, set `"answer": null`.
- "Match the list": Match the List / Match the Column / Matrix Match / List-I and List-II questions.
  CRITICAL MATCH THE LIST RULES:
  - `"question_text"` MUST contain BOTH the complete Column-I (or List-I) AND the complete Column-II (or List-II) content verbatim as printed.
  - NEVER put Column-II items (e.g. P, Q, R, S entries) into `"options"`. Options A, B, C, D in `"options"` are ONLY present if the PDF explicitly prints answer choices like (A) P->1,2 (B) P->2,3 etc.
  - If the PDF has NO printed A/B/C/D answer choices (pure matrix match), set `"options": []`.
  - The `"answer"` MUST be the full mapping string as printed, e.g. `"A->P,Q; B->R,S; C->P,R; D->Q,S"`. NEVER reduce it to just `"A"` or `"B"`.

---

### BOUNDING BOXES SPECIFICATION (0-1000 scale: [ymin, xmin, ymax, xmax])
Accurately locate and return tight normalized bounding boxes (0-1000 scale) for visual figures:
1. Question Diagram: in `"image_box"` (Main diagram belonging to the problem statement above options, if any).
2. Option Diagrams: in `"options"[i]."image_box"` (Individual diagram / chemical structure / circuit / graph for each option A, B, C, D).
3. Answer Diagram: in `"answer_image_box"` (If an explicit answer diagram or key diagram is indicated, or in the corresponding option diagram).
4. Solution Diagram / Reaction Mechanism / Solution Graph: in `"solution_image_box"` (Any technical drawing, reaction mechanism, circuit, graph, geometry drawing, physics figure, or derivation chart in the solution).

CRITICAL RULES FOR ALL DIAGRAMS & BOUNDING BOXES:
1. PROPER CROPPING - NEVER CROP THE FULL PAGE OR FULL COLUMN:
   - The bounding box `[ymin, xmin, ymax, xmax]` MUST tightly and specifically enclose ONLY the visual figure / diagram itself (e.g., circuit, graph, chemical structure, geometry diagram, ray diagram, reaction scheme, rotating body, disc).
   - STRICTLY DO NOT return full-page bounding boxes like `[0, 0, 1000, 1000]`.
   - STRICTLY DO NOT crop the entire question block or entire solution text paragraph as an image!
2. NEVER CROP PLAIN TEXT OR ISOLATED OPTION LABELS:
   - If an option, question stem, or solution contains ONLY text, numbers, formulas written in text, or just an option label `(a)`, you MUST set `"has_image": false` and `"image_box": null` (or `"solution_image_box": null`).
   - NEVER return an `image_box` for plain text!
3. STRICTLY EXCLUDE OPTION LABELS FROM OPTION DIAGRAMS:
   - When Options A, B, C, D contain visual figures, diagrams, chemical structures, circuits, or graphs:
     The bounding box `[ymin, xmin, ymax, xmax]` under `"options"[i]."image_box"` MUST enclose ONLY the chemical structure or graphic itself.
     STRICTLY EXCLUDE the option label `(a)`, `(b)`, `(c)`, `(d)`, `(1)`, `(2)`, `(3)`, `(4)`, `A.`, `B.` from the bounding box!
     Start the bounding box `xmin` immediately to the right of the option letter, so the letter `(a)` is NEVER inside the cropped diagram.
4. DIAGRAM BOUNDING BOXES — 100% COMPLETE LABELS, ARROWS & ZERO CLIPPING:
   - When drawing bounding boxes for figures, diagrams, curves, circuits, or graphs:
     The box MUST cleanly enclose 100% of THIS visual diagram's content.
     CRITICAL: ALL AXIS LABELS, ARROWHEADS, AND VERTEX LABELS ARE INTEGRAL PARTS OF THE DIAGRAM:
     - Axis labels (e.g. 'P', 'V', 'T', 'x', 'y', 't'), axis arrowheads, vertex markers ('A', 'B', 'C'), point coordinates, angle markers (θ), and origin ('O') MUST ALWAYS BE FULLY INCLUDED INSIDE THE BOUNDING BOX!
     - NEVER slice through or cut in half any axis label like 'P' on the vertical axis or 'V' on the horizontal axis!
     - Start ymin slightly ABOVE the uppermost label (like 'P' or top arrow), and extend xmax slightly BEYOND the rightmost label (like 'V' or right arrow).
     - Provide comfortable breathing room around the entire figure so no stroke, arrow, or label is clipped.
     - STRICTLY DO NOT expand bounding boxes into neighbouring diagrams, adjacent option figures, or the question above/below!
     - NO TWO DIAGRAM BOUNDING BOXES MAY OVERLAP! One cropped image must NEVER show parts of another question's diagram.
5. NEVER PUT OPTION DIAGRAMS INTO QUESTION STEM BOX:
   - If a question has NO standalone diagram in the problem statement stem, and the diagrams belong to Options A, B, C, D (or (a), (b), (c), (d)), set `"image_box": null` and `"has_image": false` for the question stem! DO NOT crop the 4 option diagrams together as `"image_box"`!
   - CRITICAL (BOTH QUESTION & OPTION DIAGRAMS): If a question HAS a standalone diagram in the problem statement / stem (e.g. circuit diagram, reaction scheme, geometry figure, ray diagram, apparatus setup) AND Options A, B, C, D ALSO have visual diagrams/graphs: you MUST extract and crop BOTH! Provide the question stem diagram in `"image_box"` AND provide each option diagram in `"options"[i]."image_box"`!
5B. MANDATORY 4 OPTION DIAGRAMS & PERFECT SCIENTIFIC ANSWER FOR 2x2 GRAPHS/CURVES:
   - When a question's 4 choices (A), (B), (C), (D) are graphs, curves, or visual diagrams (e.g. 2x2 grid with (A) top-left, (B) top-right, (C) bottom-left, (D) bottom-right, such as enzyme reaction velocity V vs substrate concentration [S] Michaelis-Menten curves):
     1. The problem stem has NO standalone diagram: set `"image_box": null` and `"has_image": false` on the question item!
     2. ABSOLUTELY NEVER crop the whole 2x2 group together as the question's `"image_box"`!
     3. You MUST crop each of the 4 option graphs individually into its respective option's `"image_box"`:
        - `"options"[0]` (Option A): tight normalized bounding box `[ymin, xmin, ymax, xmax]` for Graph (A), `"has_image": true`, `"text": ""`
        - `"options"[1]` (Option B): tight normalized bounding box `[ymin, xmin, ymax, xmax]` for Graph (B), `"has_image": true`, `"text": ""`
        - `"options"[2]` (Option C): tight normalized bounding box `[ymin, xmin, ymax, xmax]` for Graph (C), `"has_image": true`, `"text": ""`
        - `"options"[3]` (Option D): tight normalized bounding box `[ymin, xmin, ymax, xmax]` for Graph (D), `"has_image": true`, `"text": ""`
     4. ACCURATE ANSWER FOR DIAGRAM OPTIONS:
        - Carefully evaluate the question and diagrams to identify the exact correct option letter ('A', 'B', 'C', or 'D').
        - For example: For substrate concentration vs velocity of enzyme reaction, Michaelis-Menten kinetics forms a rectangular hyperbola reaching Vmax with Km at Vmax/2, which is Graph (C).
        - Always assign the authentic correct answer to `"answer"` (e.g. `"answer": "C"`). NEVER leave `"answer"` null or blank!
5C. CRITICAL THREE-WAY DISTINCTION: QUESTION DIAGRAM VS OPTION DIAGRAMS (ZERO AMBIGUITY):
   - SCENARIO 1 (Stem Diagram with internal labels A, B, C, D / I, II, III / stages / cell cycle):
     - Example: Circular cell cycle diagram labeled with stages A, B, C, D; or Mitosis cell diagram showing stages labeled A, B, C; or flower diagram showing parts A, B, C, D.
     - The question asks: "Identify A, B, C, D in the figure" or "આકૃતિમાં દર્શાવેલ A, B, C, D ઓળખો".
     - Options (A), (B), (C), (D) are textual choices (e.g. "(A) A-G1, B-S, C-G2, D-M").
     - STRICT ACTION:
       * The ENTIRE diagram belongs 100% to the question stem: set `"image_box": [ymin, xmin, ymax, xmax]` and `"has_image": true` on the question item!
       * For all options A, B, C, D: set `"has_image": false` and `"image_box": null`.
       * ABSOLUTELY NEVER divide, split, or slice this question diagram into option images!
   - SCENARIO 2 (Stem Diagram with multiple sub-figures side-by-side):
     - Example: 3 or 4 cells (A), (B), (C) shown side-by-side in the question stem illustrating cell division stages.
     - The question asks: "Which stage of mitosis is represented by A, B and C?".
     - STRICT ACTION:
       * Crop the entire composite figure in `"image_box"` of the question stem!
       * Options A, B, C, D are text options: `"has_image": false`, `"image_box": null`.
   - SCENARIO 3 (Both Question Diagram AND Option Diagrams exist — e.g. Chromosome Pair + 4 Option Cells):
     - Example: At the top, the problem stem shows a diagram (e.g. homologous chromosome bivalent, circuit, or chemical structure). Below the stem, each Option (A), (B), (C), (D) has its own diagram/figure.
     - STRICT ACTION:
       * Crop the top stem figure into `"image_box"` on the question item!
       * Crop EACH of the 4 option figures separately into `"options"[0]."image_box"`, `"options"[1]."image_box"`, `"options"[2]."image_box"`, `"options"[3]."image_box"`.
       * STRICT SEPARATION: The question diagram MUST NOT be placed into option images. The option diagrams MUST NOT be merged into the question diagram. Both MUST be cleanly extracted!
   - SCENARIO 4 (No Question Diagram, ONLY Option Diagrams):
     - Follow Rule 5B above: question `"image_box": null`, `"has_image": false`, and each option has its own `"image_box"`.
6. STRICT RULE FOR OPTION TEXT WHEN OPTION CONTAINS AN IMAGE:
   - When an option contains an image/diagram, extract any associated label or text into `"text"`.
7. EXCLUDE QUESTION SENTENCES & FORMULA LINES FROM DIAGRAMS (PRESERVE DIAGRAM LABELS):
   - When outputting `"image_box"`, `"options"[i]."image_box"`, or `"solution_image_box"`, crop the visual graphic drawing with its internal labels.
   - Exclude full introductory or trailing question sentences (e.g. "as shown in the figure:", "refer to diagram:", "આકૃતિમાં દર્શાવ્યા મુજબ:").
   - `ymin` MUST start above the top label/arrow of the diagram itself, below any question text sentence.
   - `ymax` MUST stop below the bottom axis/label of the diagram, above any formula derivation lines printed underneath!
   - DIAGRAM LABELS ARE NOT QUESTION SENTENCES: Axis letters ('P', 'V', 'x', 'y'), points ('A', 'B', 'C'), and arrows must always be preserved!
8. SOLUTION FORMATTING & STRICT 1-TO-1 MATCHING:
   - Extract ONLY the authentic solution that belongs to THIS SPECIFIC question. Never attach a solution from another question!
   - ABSOLUTELY DO NOT prefix solution lines with artificial labels like 'Step 1:', 'Step 2:', 'Step 3:', 'Step 4:'. Extract the pure solution text and equations as printed.
   - Always format `"solution"` with clean step-by-step layout using inline LaTeX (`$...$`).
   - Format each derivation equation step on a NEW LINE (e.g. using `\\n\\Rightarrow ...`).
   - Keep all numbered equation labels e.g. `...(i)`, `...(ii)` on separate lines.
   - If Option A, B, C, or D is a diagram, figure, circuit, or chemical structure:
     - Provide its tight bounding box in `"image_box"` and set `"has_image": true`.
     - In `"text"`, DO NOT WRITE `"[Image]"`, `"[Diagram]"`, `"Image"`, `"Diagram"`, `"Option Image"`, or any image reference!
     - If the option has real textual content alongside the image (e.g. "Compound A" or "45°"), put ONLY that text in `"text"`.
     - If the option is purely a diagram/figure with no extra text, set `"text": ""` (EMPTY STRING).
     - NEVER output `"[image]"` or `"diagram"` as the option text!

CRITICAL MANDATORY RULE FOR SOLUTION DIAGRAMS & FIGURES:
- Whenever a solution/explanation contains ANY visual figure, diagram, physics sketch (e.g. rotating circular disc, sphere, cylinder, ray diagram, lens, mirror, coordinate axis, free body diagram FBD, magnetic field lines, circuit, graph, chemical reaction mechanism):
  1. You MUST set `"has_solution_image": true`.
  2. You MUST return its exact tight bounding box `[ymin, xmin, ymax, xmax]` in `"solution_image_box"`.
  3. If a solution has derivation text before the diagram AND derivation text after the diagram:
     - Extract ALL text & LaTeX formulas from both before and after into `"solution"`.
     - Crop the diagram figure in between and provide its coordinates in `"solution_image_box"`.
     - NEVER skip or omit the solution diagram!

CRITICAL QUESTION DIAGRAM VS SOLUTION DIAGRAM (UP VS DOWN):
- QUESTION DIAGRAM (`"image_box"`):
  - MUST be the diagram belonging to the problem statement / question stem ABOVE the options ("UP" on the page).
  - NEVER place an explanation figure, solution reaction mechanism, or answer diagram into `"image_box"`.
- SOLUTION DIAGRAM (`"solution_image_box"`):
  - MUST be the diagram belonging to the step-by-step derivation, reaction mechanism, circuit, or explanation printed BELOW the options or in the solutions section ("DOWN" on the page).
  - NEVER place the question stem diagram into `"solution_image_box"`.
- If a question has BOTH a problem diagram (UP) and a solution diagram (DOWN) on the same page:
  - `"image_box"` MUST capture the problem statement diagram (UP).
  - `"solution_image_box"` MUST capture the solution diagram (DOWN).
  - NEVER swap them, and NEVER return the same bounding box for both!

CRITICAL ORDERING: STRICT NATURAL SEQUENTIAL ORDER (LINE-BY-LINE):
- Output questions in strict ascending sequential reading order (e.g. Q1, Q2, Q3, Q4...) without scrambling or mixing questions.
- Never drop, merge, or omit any question. Every question printed on the document must be cleanly output.
- Question N's solution and solution diagram MUST strictly belong to Question N. NEVER shift or offset solutions between questions!

---

### CRITICAL PROCESSING RULES

#### 1. Answers Thoroughly Detected & 100% Accurate (Zero Missing / Zero Swapped Answers)
- **Exhaustively Search for Answer Everywhere**:
  - Scan the entire page thoroughly for the correct answer of each question:
    a) In the question stem or trailing brackets (e.g. `Ans. (B)`, `[Ans. 2]`, `Ans: 42`, `જવાબ: (C)`, `Ans: (a)`, `[Ans. B]`, `(Ans: 3)`, `જવાબ: (બ)`, `જવાબ: (ડ)`).
    b) In the options (marked in bold, asterisk `*`, checkmark, or tagged `(Correct)`).
    c) In mini answer keys / tables / lists printed at the bottom, margins, or headers of the page.
    d) In the solution / explanation block printed below the question (e.g. "Hence option (B) is correct", "આથી સાચો વિકલ્પ (B) છે", "વિકલ્પ (ડ) સાચો છે").
  - NEVER leave answer empty/null if it is printed or indicated anywhere on the page, answer key table, or solution!

- **STRICT OPTION KEY ASSIGNMENT & NO SWAPPING (CRITICAL)**:
  - You MUST identify each option strictly by its **PHYSICALLY PRINTED LABEL**, NEVER by spatial layout or arbitrary reading order:
    - Label `(A)`, `(a)`, `(1)`, `(અ)`, `(क)` $\rightarrow$ MUST be `"key": "A"`
    - Label `(B)`, `(b)`, `(2)`, `(બ)`, `(ख)` $\rightarrow$ MUST be `"key": "B"`
    - Label `(C)`, `(c)`, `(3)`, `(ક)`, `(ग)` $\rightarrow$ MUST be `"key": "C"`
    - Label `(D)`, `(d)`, `(4)`, `(ડ)`, `(ઘ)` $\rightarrow$ MUST be `"key": "D"`
  - **2-Column Option Layouts Warning**:
    - Many exam papers place Option `(A)` and `(B)` vertically in the left column, and Option `(C)` and `(D)` vertically in the right column.
    - DO NOT scan left-to-right naively and label Option `(C)` as "B"!
    - The option physically labeled `(B)` (or `(2)` or `(બ)`) MUST ALWAYS be assigned to `"key": "B"`.
    - The option physically labeled `(D)` (or `(4)` or `(ડ)`) MUST ALWAYS be assigned to `"key": "D"`.

- **ANSWER SHEET FIDELITY (EXACT MATCH WITH ANSWER SHEET)**:
  - The `"answer"` value MUST match the authoritative printed answer key or answer sheet EXACTLY:
    - If answer sheet says `(A)` or `(1)` or `(અ)` $\rightarrow$ `"answer": "A"`
    - If answer sheet says `(B)` or `(2)` or `(બ)` $\rightarrow$ `"answer": "B"`
    - If answer sheet says `(C)` or `(3)` or `(ક)` $\rightarrow$ `"answer": "C"`
    - If answer sheet says `(D)` or `(4)` or `(ડ)` $\rightarrow$ `"answer": "D"`
  - ABSOLUTELY NEVER swap `A` and `B`, `B` and `D`, or `D` and `B`! The output answer MUST be 100% identical to the answer key in the document.
  - For multiple select (MSQ): comma-separated distinct uppercase letters e.g. `"A, C"` or `"B, D"`.

- **For Numeric / Integer / NAT Questions ("question_type": "Numeric")**:
  - Set `"options": []`.
  - The answer MUST be the exact numerical value (e.g. `"0"`, `"2"`, `"4"`, `"0003"`, `"9"`, `"42"`, `"3.14"`, `"-5"`, `"0.25"`).
  - Extract the authentic numeric answer from brackets e.g. `[Ans. 42]`, `42. (0) -> "0"`, `61. (0003) -> "0003"`, `(Ans: 12.5)`, `જવાબ: 5`, or the final result line of derivation.
  - NEVER confuse internal equation numbering like `(1)`, `(2)`, `(3)` in the derivation with the final numerical answer!
  - NEVER convert numeric answers `1, 2, 3, 4` to letters `A, B, C, D` for Numeric questions!
  - If the question stem has a question diagram, retain the diagram in `"image_box"`. If the answer is in the solution block below, ALWAYS put that answer in `"answer"`.
- If the answer is genuinely not printed anywhere on the page, set `"answer": null`.

#### 2. Realistic Numeric Difficulty Classification ("difficulty")
Assign an authentic numeric integer difficulty to every question:
- `0`: Easy (direct recall, basic definition, single-step direct formula substitution, standard unit/dimension)
- `-1`: Medium (standard JEE Main / NEET calculation, 2-step problem, moderate conceptual reasoning)
- `1`: Hard (complex multi-concept problem, multi-step derivation, advanced reaction mechanism, matrix match, tricky calculus)
CRITICAL DIFFICULTY CONSTRAINTS:
- STRICTLY DO NOT set all questions to 0! A real exam paper contains a realistic balance of Easy (0), Medium (-1), and Hard (1).
- Evaluate each question individually on its calculation depth, multi-step equations, and conceptual complexity.
- Difficulty MUST strictly be a numeric integer (`0`, `-1`, or `1`), NEVER an alphabetic string ("Easy", "Medium", etc.).

#### 3. SOLUTIONS — EXTRACT ONLY WHAT IS PRINTED IN THE PDF ("solution")
- **GOLDEN RULE: ONLY extract solutions that are PHYSICALLY PRINTED in the PDF. NEVER generate, compose, or hallucinate any solution from your own knowledge.**
- If a solution / hint / explanation / derivation IS printed on the document:
  - Extract it 100% COMPLETELY without cutting off, truncating, or summarizing any step.
  - Keep all mathematical expressions, formulas, and units in clean LaTeX ($...$ or $$...$$).
  - Place the full extracted solution text into `"solution"`.
- If NO solution is printed on the page (only 'Ans: (B)' is shown, or nothing at all):
  - Set `"solution": null` — DO NOT write any solution text whatsoever.
  - NEVER generate, calculate, derive, or invent a solution — leaving `"solution": null` is CORRECT when none is in the PDF.
- If the solution contains ANY visual figure, drawing, circle/disc diagram, graph, ray diagram, FBD, or circuit, set `"has_solution_image": true` and supply the tight bounding box in `"solution_image_box"`.

#### 4. Remove Exam Source Citations & Dates
- Completely OMIT and do NOT include any exam source citations, shift tags, or exam dates from `"question_text"`.
- Examples of tags to EXCLUDE: `[Online April 9, 2013]`, `(Online May 12, 2012)`, `(Main 2009, 10 April II)`, `[JEE Main 2020]`, `[NEET 2021]`, `(12 Jan 2019, Shift 1)`, `[AIEEE 2004]`, `[Online 2016]`, `(2018 Shift-1)`, etc.
- Extract ONLY the actual scientific/mathematical question stem itself.

---

### OUTPUT FORMAT SPECIFICATION
Return ONLY a valid, parseable JSON object matching this exact structure without Markdown backticks or commentary:

{
  "page_number": 1,
  "chapter_number": "1",
  "chapter_name": "<Chapter Title in original language e.g. Magnetic Effects / વિદ્યુતભાર અને ક્ષેત્રો>",
  "subject": "<Subject Name e.g. Physics / Chemistry / Mathematics / Biology>",
  "topics": [
    {
      "id": 1,
      "chapter_number": "1",
      "chapter_name": "<Chapter Title>",
      "topic": "<Topic Title in original language>",
      "description": "<Concise description of topic>"
    }
  ],
  "is_solution_page": false,
  "questions": [
    {
      "question_number": "1",
      "topic_id": 1,
      "topic": "<Topic Title>",
      "chapter_number": "1",
      "chapter_name": "<Chapter Title>",
      "subject": "<Subject Name>",
      "question_type": "MCQ",
      "question_text": "A thin circular disc of radius $R$ is uniformly charged with density $\\sigma > 0$ per unit area. The disc rotates about its axis with a uniform angular speed $\\omega$. The magnetic moment of the disc is",
      "difficulty": 0,
      "has_image": false,
      "image_box": null,
      "answer": "C",
      "solution": "\\frac{q}{2m} = \\frac{\\text{Magnetic dipole moment}}{\\text{Angular momentum}}\\n\\n\\Rightarrow \\text{Magnetic dipole moment }(M) = \\frac{q}{2m} \\cdot \\left(\\frac{m R^2}{2}\\right) \\cdot \\omega = \\frac{1}{4}\\sigma \\pi R^4 \\omega",
      "has_solution_image": true,
      "solution_image_box": [480, 310, 690, 690],
      "is_continuation": false,
      "is_split_at_bottom": false,
      "options": [
        {
          "key": "A",
          "text": "\\pi R^4 \\sigma \\omega",
          "has_image": false,
          "image_box": null
        },
        {
          "key": "B",
          "text": "\\frac{\\pi R^4}{2} \\sigma \\omega",
          "has_image": false,
          "image_box": null
        },
        {
          "key": "C",
          "text": "\\frac{\\pi R^4}{4} \\sigma \\omega",
          "has_image": false,
          "image_box": null
        },
        {
          "key": "D",
          "text": "2\\pi R^4 \\sigma \\omega",
          "has_image": false,
          "image_box": null
        }
      ]
    },
    {
      "question_number": "2",
      "topic_id": 1,
      "topic": "<Topic Title>",
      "chapter_number": "1",
      "chapter_name": "<Chapter Title>",
      "subject": "<Subject Name>",
      "question_type": "Numeric",
      "question_text": "<Numeric value question text where students calculate a number>",
      "difficulty": 1,
      "has_image": false,
      "image_box": null,
      "answer": "42",
      "solution": "<step-by-step derivation ONLY IF physically printed in PDF, otherwise null>",
      "has_solution_image": false,
      "solution_image_box": null,
      "is_continuation": false,
      "is_split_at_bottom": false,
      "options": []
    },
    {
      "question_number": "3",
      "topic_id": 1,
      "topic": "<Topic Title>",
      "chapter_number": "1",
      "chapter_name": "<Chapter Title>",
      "subject": "<Subject Name>",
      "question_type": "Match the list",
      "question_text": "Match Column-I with Column-II:\n\nColumn-I:\n(A) Entry A description\n(B) Entry B description\n(C) Entry C description\n(D) Entry D description\n\nColumn-II:\n(P) Entry P description\n(Q) Entry Q description\n(R) Entry R description\n(S) Entry S description",
      "column_i": "(A) Entry A description\n(B) Entry B description\n(C) Entry C description\n(D) Entry D description",
      "column_ii": "(P) Entry P description\n(Q) Entry Q description\n(R) Entry R description\n(S) Entry S description",
      "difficulty": -1,
      "has_image": false,
      "image_box": null,
      "answer": "A->P,Q; B->R,S; C->P,R; D->Q,S",
      "solution": null,
      "has_solution_image": false,
      "solution_image_box": null,
      "is_continuation": false,
      "is_split_at_bottom": false,
      "options": []
    },
    {
      "question_number": "4",
      "topic_id": 1,
      "topic": "<Topic Title>",
      "chapter_number": "1",
      "chapter_name": "<Chapter Title>",
      "subject": "<Subject Name>",
      "question_type": "MCQ",
      "paragraph": "The density (\\rho) versus temperature (T) graph of an ideal monatomic gas is undergoing a cyclic process as shown in figure. Molecular mass of gas is M and one mole of the gas sample is taken. For process CA, \\rho T = constant.",
      "has_paragraph_image": true,
      "paragraph_image_box": [480, 380, 600, 580],
      "question_text": "If W_{ij} is work done by gas in process i -> j, then",
      "difficulty": 0,
      "has_image": false,
      "image_box": null,
      "answer": "B, C",
      "solution": null,
      "has_solution_image": false,
      "solution_image_box": null,
      "is_continuation": false,
      "is_split_at_bottom": false,
      "options": [
        {
          "key": "A",
          "text": "W_{CA} = RT_0 \\ln 2",
          "has_image": false,
          "image_box": null
        },
        {
          "key": "B",
          "text": "W_{CA} = -RT_0",
          "has_image": false,
          "image_box": null
        },
        {
          "key": "C",
          "text": "W_{AB} = 0",
          "has_image": false,
          "image_box": null
        },
        {
          "key": "D",
          "text": "W_{AB} = RT_0",
          "has_image": false,
          "image_box": null
        }
      ]
    }
  ]
}
"""


def get_mcq_extraction_prompt(source_language: Optional[str] = None, target_language: Optional[str] = None, page_num: int = 1, total_pages: int = 1) -> str:
    """Returns the extraction prompt with page context for single-page scanning."""
    return MASTER_EXTRACTION_PROMPT


def get_all_pages_extraction_prompt(source_language: Optional[str] = None, target_language: Optional[str] = None, total_pages: int = 1) -> str:
    """Returns the extraction prompt for multi-page documents."""
    return MASTER_EXTRACTION_PROMPT


def get_answer_key_prompt(source_language: Optional[str] = None, target_language: Optional[str] = None) -> str:
    """Prompt to extract question answers and solutions from an answer key table or solutions page."""
    return """# EXAM ANSWER KEY & SOLUTIONS EXTRACTOR

Scan this entire page carefully for:
1. All Answers and Answer Key tables (organized by Section, Exercise, or Topic e.g. "EXERCISE - 1", "EXERCISE - 2", "Topic 1", "Topic 2", etc.).
2. Explanations, Hints, and Solutions IF AND ONLY IF full step-by-step written derivations are physically printed on this page.
3. Solution Diagrams: If any solution/explanation contains a visual figure, drawing, circuit, graph, or chemical structure, extract its tight normalized bounding box [ymin, xmin, ymax, xmax] (0-1000 scale) into "solution_image_box" and set "has_solution_image": true.

CRITICAL RULES FOR SOLUTIONS (ZERO HALLUCINATION):
- ABSOLUTELY DO NOT SOLVE, COMPUTE, INVENT, OR HALLUCINATE ANY SOLUTION!
- If this page is an Answer Key table (containing only question numbers and answers like 1.(b), 2.(c)...) with NO full step-by-step written explanation text:
  YOU MUST SET "solution": null AND "solutions_by_number": {}. NEVER write or invent solutions!
- Only extract "solution" text if this page is an explicit "Hints & Solutions" / "Explanations" / "સમજૂતી" / "ઉકેલ" section with genuine written steps.
- If a solution contains a diagram/figure/drawing, tightly crop ONLY the visual drawing into "solution_image_box" and set "has_solution_image": true.

CRITICAL RULES FOR ANSWERS & SECTIONS:
- Group answers by their Section / Exercise / Topic heading (e.g. "EXERCISE - 1", "EXERCISE - 2", "Section A", "Section B") in "answers_by_topic".
- Every answer MUST preserve its authentic printed question number (e.g. "1", "2", "31").
- For MCQ questions (with options A/B/C/D): Answers MUST be standard alphabetical uppercase letters: "A", "B", "C", "D" (map (1)->"A", (2)->"B", (3)->"C", (4)->"D").
- For Numeric / Integer / NAT questions: Preserve the exact numeric value as-is (e.g. "42", "3.14", "-5", "0.25"). Do NOT map numeric answers to letters!

Return ONLY a valid JSON object matching this structure:
{
  "answers_by_topic": {
    "EXERCISE - 1": {
      "1": "B",
      "2": "B"
    },
    "EXERCISE - 2": {
      "1": "C",
      "2": "D"
    }
  },
  "sequential_answers": [
    {
      "topic": "EXERCISE - 1",
      "question_number": "1",
      "question_snippet": "First 5-10 words of the question statement if visible in solution",
      "answer": "B",
      "solution": "Step by step derivation text...",
      "has_solution_image": true,
      "solution_image_box": [450, 300, 680, 700]
    },
    {
      "topic": "EXERCISE - 2",
      "question_number": "1",
      "question_snippet": "First 5-10 words of the question statement if visible",
      "answer": "C",
      "solution": null,
      "has_solution_image": false,
      "solution_image_box": null
    }
  ],
  "solutions_by_number": {
    "1": "Step by step derivation text..."
  },
  "questions": [
    {
      "question_number": "1",
      "question_snippet": "First 5-10 words of problem statement",
      "answer": "B",
      "solution": "Step by step derivation text...",
      "has_solution_image": true,
      "solution_image_box": [450, 300, 680, 700],
      "is_solution_item": true
    }
  ]
}
"""


