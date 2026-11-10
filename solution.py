"""Конкурсный entry point МТС: questions.csv -> submission.csv.

Платформа проверки переносит корневые .py-файлы и requirements.txt,
задаёт DATA_DIR (questions.csv + knowledge-base.zip) и ожидает
submission.csv в рабочем каталоге с колонками `id,answer`.

Каждый вопрос обрабатывается независимо по id. Реальная RAG-логика —
в ai_engine.py и соседних модулях (зона ML-участника).
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

# Корень проекта = каталог этого файла; модули AI Core лежат рядом.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_engine  # noqa: E402
import kb_loader  # noqa: E402


def questions_csv_path() -> Path:
    return kb_loader.get_data_dir() / "questions.csv"


def submission_csv_path() -> Path:
    return Path(os.environ.get("SUBMISSION_PATH", "submission.csv"))


def read_questions(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "id" not in reader.fieldnames:
            raise ValueError(f"questions.csv: ожидается колонка 'id', найдено {reader.fieldnames}")
        question_col = "question" if "question" in reader.fieldnames else reader.fieldnames[-1]
        return [{"id": row["id"], "question": row.get(question_col, "")} for row in reader]


def main() -> int:
    qpath = questions_csv_path()
    if not qpath.exists():
        print(f"ERROR: questions.csv not found in DATA_DIR={kb_loader.get_data_dir()}", file=sys.stderr)
        return 2

    questions = read_questions(qpath)
    print(f"Loaded {len(questions)} questions from {qpath}")

    # Прогрев AI Core (загрузка корпуса и т.п.) — на усмотрение ML.
    try:
        kb_loader.load_corpus()
    except NotImplementedError:
        pass  # допустимо: corpus может грузиться лениво внутри answer_question
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: corpus preload failed: {exc}", file=sys.stderr)

    out_path = submission_csv_path()
    answered = 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "answer"])
        writer.writeheader()
        for item in questions:
            try:
                result = ai_engine.answer_question(item["question"])
                answer = str(result.get("answer", "")).strip()
            except Exception as exc:  # noqa: BLE001 — не роняем весь прогон
                print(f"ERROR id={item['id']}: {exc}", file=sys.stderr)
                answer = ""
            writer.writerow({"id": item["id"], "answer": answer})
            answered += 1
            print(f"[{answered}/{len(questions)}] id={item['id']}")

    print(f"Wrote {answered} answers to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
