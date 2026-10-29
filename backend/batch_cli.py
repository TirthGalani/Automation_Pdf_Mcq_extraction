"""Command-Line Interface for Batch MCQ PDF Extraction and Translation.

Usage:
    python batch_cli.py --input-dir ./pdfs --source Gujarati --target English --output-dir ./output
    python batch_cli.py --file sample.pdf --source Hindi --target English
"""

import os
import sys
import json
import argparse
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.extractor import GeminiExtractor
from app.utils import export_to_csv_bytes, export_to_excel_bytes

load_dotenv()


async def process_pdf_file(
    extractor: GeminiExtractor,
    pdf_path: Path,
    source_lang: str,
    target_lang: str,
    output_dir: Path,
    model_name: str
):
    print(f"\n[+] Processing: {pdf_path.name} ({source_lang} -> {target_lang})")
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    result = await extractor.extract_from_pdf(
        pdf_bytes=pdf_bytes,
        file_name=pdf_path.name,
        source_language=source_lang,
        target_language=target_lang,
        model_name=model_name
    )

    if result.status == "completed":
        print(f"    ✓ Extracted {result.total_questions} questions in {result.processing_time_seconds}s")
        
        # Save JSON output
        out_json_path = output_dir / f"{pdf_path.stem}_mcq.json"
        data = {"questions": [q.model_dump() for q in result.questions]}
        with open(out_json_path, "w", encoding="utf-8") as out_f:
            json.dump(data, out_f, indent=2, ensure_ascii=False)
        print(f"    ✓ Saved JSON: {out_json_path}")
        return result
    else:
        print(f"    ✗ Failed: {result.error_message}")
        return None


async def main():
    parser = argparse.ArgumentParser(description="Batch MCQ PDF Extractor & Translator via Gemini API")
    parser.add_argument("--file", type=str, help="Path to single PDF file")
    parser.add_argument("--input-dir", type=str, help="Directory containing PDF files")
    parser.add_argument("--source", type=str, default="Gujarati", help="Source Language (e.g., Gujarati, Hindi, English)")
    parser.add_argument("--target", type=str, default="English", help="Target Language (e.g., English, Hindi, Gujarati)")
    parser.add_argument("--model", type=str, default="gemini-3.6-flash", help="Gemini Model (e.g. gemini-3.6-flash, gemini-3.1-pro-preview)")
    parser.add_argument("--output-dir", type=str, default="./output", help="Directory to save extracted results")
    parser.add_argument("--api-key", type=str, default=None, help="Gemini API Key (optional if in .env)")

    args = parser.parse_args()

    api_key = args.api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY is not set. Set it in .env or pass with --api-key.")
        sys.exit(1)

    extractor = GeminiExtractor(api_key=api_key, model_name=args.model)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = []
    if args.file:
        pdf_files.append(Path(args.file))
    elif args.input_dir:
        pdf_files.extend(list(Path(args.input_dir).glob("*.pdf")))
    else:
        print("Please provide --file <path> or --input-dir <path>")
        sys.exit(1)

    if not pdf_files:
        print("No PDF files found to process.")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF file(s). Starting extraction using {args.model}...")

    all_results = []
    for pdf_path in pdf_files:
        res = await process_pdf_file(
            extractor=extractor,
            pdf_path=pdf_path,
            source_lang=args.source,
            target_lang=args.target,
            output_dir=output_dir,
            model_name=args.model
        )
        if res:
            all_results.append(res)

    # Export merged CSV and Excel if multiple files
    if all_results:
        csv_path = output_dir / "all_mcqs_merged.csv"
        with open(csv_path, "wb") as f:
            f.write(export_to_csv_bytes(all_results))
        print(f"\n[✓] Merged CSV exported: {csv_path}")

        excel_path = output_dir / "all_mcqs_merged.xlsx"
        with open(excel_path, "wb") as f:
            f.write(export_to_excel_bytes(all_results))
        print(f"[✓] Merged Excel exported: {excel_path}")

    print("\n[✓] All batch jobs completed!")


if __name__ == "__main__":
    asyncio.run(main())
