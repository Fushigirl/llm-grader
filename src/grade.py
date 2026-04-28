# coding: utf-8
"""
Grade student PDF submissions using a two-phase LLM approach.

Phase 1: LLM extracts the reflection (考察) section from the full PDF text.
Phase 2: LLM scores the extracted reflection against the rubric.

Usage:
  python grade.py                                 # all students, ollama backend
  python grade.py --evaluator "山下航佑"           # only students assigned to this grader
  python grade.py --backend ui --ui-user myuser   # web UI LLM (password prompted)
  python grade.py --backend claude                # Claude API

Output:
  result/<folder-name>[_evaluator]_grades.csv
  result/<folder-name>[_evaluator]_grades.xlsx
"""
import os
import re
import sys
import argparse
import getpass

import pandas as pd

from pdf_extractor import extract_pdf_text
from llm_client import call_llm

DEFAULT_SUBMISSIONS_DIR = "data/submissions"
DEFAULT_RUBRIC_FILE = "data/rubric.txt"
DEFAULT_ASSIGNMENT_FILE = "data/assignment.xlsx"
DEFAULT_OUTPUT_DIR = "result"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
DEFAULT_UI_MODEL = "Qwen3.5 35B-A3B"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
DEFAULT_UI_URL = "https://exp.cmlabvps.net/local-llm/"

MAX_PDF_CHARS = 12000


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def build_extraction_prompt(pdf_text: str) -> str:
    return f"""以下は学生が提出したレポートのテキストです（PDF全文）。

このテキストの中から「学生自身が書いた考察・分析・まとめ」に相当する記述を全て抜き出してください。

抽出ルール:
- コードそのもの（import, plt., def, for 等）は除く
- データの出力結果（数値の表・グラフラベル等）は除く
- 課題説明文・問題文（「〜しなさい」「〜を求めよ」等）は除く
- 学生が自分の言葉で書いた分析・解釈・考えだけを残す
- 複数の考察問題がある場合は「【問N】」のように番号を付けて区別する

出力形式（考察が1問の場合）:
【考察】
（学生の記述をそのまま）

出力形式（考察が複数の場合）:
【問1の考察】
（学生の記述をそのまま）

【問2の考察】
（学生の記述をそのまま）

考察に相当する記述が見当たらない場合は「考察記述なし」とだけ返してください。

---
【レポート全文】
{pdf_text}"""


def build_evaluation_prompt(student_name: str, extracted: str, rubric: str) -> str:
    return f"""以下は学生「{student_name}」の考察記述（フェーズ1で抽出済み）です。
コードや実装手順は含まれていません。この記述のみで採点してください。

【考察記述】
{extracted}

【評価ポイント・模範解答】
{rubric}

評価ポイントの各基準について、学生の考察が満たしているかを以下の形式で返してください。
記号の判定基準:
○: 模範解答の内容に少しでも似た記述・言及があれば○（完全一致不要）
△: 全く関係ない内容だが何か書いている
×: 何も書いていない、または明らかに的外れ

基準1: ○/△/× ― コメント（1文）
基準2: ○/△/× ― コメント（1文）
総評: （2文以内）

注意:
- 返答は上記3行だけにしてください。
- 根拠が抽出テキストに無い内容を補完しないでください。"""


# ---------------------------------------------------------------------------
# Assignment file helpers
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    return re.sub(r"[\s　]+", "", str(s).strip())


def load_assignment(assignment_file: str) -> list:
    """Return [(normalized_name, original_name, evaluator), ...] or []."""
    try:
        df = pd.read_excel(assignment_file)
        return [
            (_normalize(r["提出者　氏名"]),
             str(r["提出者　氏名"]).strip(),
             str(r["採点者"]).strip())
            for _, r in df.iterrows()
        ]
    except Exception:
        return []


def _filter_by_evaluator(folders: list, evaluator: str, assignment: list) -> list:
    norm_eval = _normalize(evaluator)
    assigned_keys = {
        key_norm
        for key_norm, _, eval_name in assignment
        if _normalize(eval_name) == norm_eval
    }
    return [
        f for f in folders
        if any(k in _normalize(f) for k in assigned_keys)
    ]


def _assignment_order(folder: str, assignment: list) -> int:
    norm = _normalize(folder)
    for i, (key_norm, _, _) in enumerate(assignment):
        if key_norm and key_norm in norm:
            return i
    return 99999


# ---------------------------------------------------------------------------
# Two-phase LLM grading
# ---------------------------------------------------------------------------

def _parse_eval_result(raw: str) -> dict:
    row: dict = {"詳細（抽出）": "", "詳細（評価）": raw}
    for line in raw.splitlines():
        line = line.strip()
        if re.match(r"基準\s*1", line):
            row["基準1"] = line
        elif re.match(r"基準\s*2", line):
            row["基準2"] = line
        elif line.startswith("総評"):
            row["総評"] = line
    return row


def _run_two_phase(
    student_name: str,
    pdf_text: str,
    rubric: str,
    backend: str,
    model: str,
    ui_url: str,
    ui_user: str,
    ui_pass: str,
) -> tuple:
    extraction_prompt = build_extraction_prompt(pdf_text[:MAX_PDF_CHARS])
    extracted = call_llm(extraction_prompt, backend, model, ui_url, ui_user, ui_pass, max_tokens=2000)

    if "考察記述なし" in extracted or len(extracted.strip()) < 10:
        no_reflection = (
            "基準1: × ― 考察記述が見当たりません。\n"
            "基準2: × ― 考察記述が見当たりません。\n"
            "総評: 提出物に考察相当の記述が確認できませんでした。"
        )
        return extracted, no_reflection

    eval_prompt = build_evaluation_prompt(student_name, extracted, rubric)
    evaluation = call_llm(eval_prompt, backend, model, ui_url, ui_user, ui_pass, max_tokens=900)
    return extracted, evaluation


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Grade student PDF submissions with LLM")
    parser.add_argument(
        "--submissions-dir", default=DEFAULT_SUBMISSIONS_DIR,
        help=f"Student submission folder (default: {DEFAULT_SUBMISSIONS_DIR})",
    )
    parser.add_argument(
        "--rubric-file", default=DEFAULT_RUBRIC_FILE,
        help=f"Rubric text file (default: {DEFAULT_RUBRIC_FILE})",
    )
    parser.add_argument("--rubric", type=str, help="Rubric text inline (overrides --rubric-file)")
    parser.add_argument(
        "--assignment-file", default=DEFAULT_ASSIGNMENT_FILE,
        help=f"Grader assignment Excel file (default: {DEFAULT_ASSIGNMENT_FILE})",
    )
    parser.add_argument(
        "--evaluator", type=str, default="",
        help="Filter to only students assigned to this grader name",
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument("--backend", choices=["ollama", "claude", "ui"], default="ollama")
    parser.add_argument("--model", type=str, help="Override model name")
    parser.add_argument("--ui-url", default=DEFAULT_UI_URL, help="Web UI URL (ui backend only)")
    parser.add_argument(
        "--ui-user", type=str, default="",
        help="UI login username (or set LLM_USER env var; ui backend only)",
    )
    parser.add_argument("--no-excel", action="store_true", help="Skip Excel report generation")
    args = parser.parse_args()

    # Resolve model
    if args.model:
        model = args.model
    elif args.backend == "ollama":
        model = DEFAULT_OLLAMA_MODEL
    elif args.backend == "ui":
        model = DEFAULT_UI_MODEL
    else:
        model = DEFAULT_CLAUDE_MODEL

    # Credentials (UI backend only — password never accepted as a CLI arg)
    ui_user, ui_pass = "", ""
    if args.backend == "ui":
        ui_user = args.ui_user or os.environ.get("LLM_USER", "")
        if not ui_user:
            ui_user = input("UI username: ").strip()
        ui_pass = getpass.getpass("UI password: ")

    # Rubric
    if args.rubric:
        rubric = args.rubric
    elif os.path.isfile(args.rubric_file):
        with open(args.rubric_file, encoding="utf-8") as f:
            rubric = f.read()
    else:
        print(f"Rubric file not found: {args.rubric_file}")
        print("Paste rubric text below. Finish with Ctrl+Z+Enter (Windows) or Ctrl+D (Unix):")
        rubric = sys.stdin.read()
    if not rubric.strip():
        print("No rubric provided. Exiting.")
        sys.exit(1)

    # Submissions directory
    if not os.path.isdir(args.submissions_dir):
        print(f"Submissions directory not found: {args.submissions_dir}")
        sys.exit(1)

    # Assignment file
    assignment = load_assignment(args.assignment_file)
    if not assignment and args.evaluator:
        print(f"Warning: assignment file not found or unreadable: {args.assignment_file}")

    # Collect and optionally filter student folders
    all_folders = sorted(
        f for f in os.listdir(args.submissions_dir)
        if os.path.isdir(os.path.join(args.submissions_dir, f))
    )
    if args.evaluator:
        folders = _filter_by_evaluator(all_folders, args.evaluator, assignment)
        print(f"Evaluator: {args.evaluator!r}  ({len(folders)}/{len(all_folders)} students)")
    else:
        folders = all_folders

    if assignment:
        folders = sorted(folders, key=lambda f: _assignment_order(f, assignment))

    # Output path
    os.makedirs(args.output_dir, exist_ok=True)
    base = os.path.basename(args.submissions_dir.rstrip("/\\"))
    suffix = f"_{args.evaluator}" if args.evaluator else ""
    csv_path = os.path.join(args.output_dir, f"{base}{suffix}_grades.csv")

    print(f"Backend: {args.backend}  Model: {model}")
    print(f"Students: {len(folders)}  Output: {csv_path}")
    print("=" * 60)

    results = []
    for folder in folders:
        folder_path = os.path.join(args.submissions_dir, folder)
        pdfs = [f for f in os.listdir(folder_path) if f.lower().endswith(".pdf")]

        if not pdfs:
            print(f"[skip] {folder} — no PDF found")
            results.append({"学生": folder, "基準1": "", "基準2": "", "総評": "PDFなし"})
            continue

        pdf_path = os.path.join(folder_path, pdfs[0])
        print(f"Processing: {folder}")

        try:
            pdf_text = extract_pdf_text(pdf_path)
            if not pdf_text.strip():
                print("  → text extraction failed (including OCR)")
                results.append({
                    "学生": folder, "基準1": "", "基準2": "",
                    "総評": "テキスト抽出失敗（OCRも不可）",
                })
                continue

            print("  Phase 1: extracting reflection ... ", end="", flush=True)
            extracted, evaluation = _run_two_phase(
                folder, pdf_text, rubric, args.backend, model,
                args.ui_url, ui_user, ui_pass,
            )
            print("done")
            preview = extracted[:100].replace("\n", " ")
            print(f"  [{len(extracted)} chars] {preview}...")
            eval_preview = evaluation[:100].replace("\n", " ")
            print(f"  Phase 2: {eval_preview}")
            print()

            row = {"学生": folder, "抽出考察": extracted}
            row.update(_parse_eval_result(evaluation))
            results.append(row)

        except Exception as e:
            print(f"  Error: {e}")
            results.append({"学生": folder, "基準1": "", "基準2": "", "総評": f"エラー: {e}"})

    df = pd.DataFrame(results)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\nSaved CSV: {csv_path}")

    if not args.no_excel:
        try:
            from excel_report import make_excel
            xlsx_path = csv_path.replace(".csv", ".xlsx")
            make_excel(
                csv_path=csv_path,
                out_path=xlsx_path,
                assignment_file=args.assignment_file,
                rubric_file=args.rubric_file,
            )
        except Exception as e:
            print(f"Excel generation failed: {e}")
            print("Run manually: python excel_report.py <csv_path>")


if __name__ == "__main__":
    main()
