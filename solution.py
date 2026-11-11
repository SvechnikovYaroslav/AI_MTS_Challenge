"""Конкурсный entry point МТС: questions.csv -> submission.csv.

Платформа проверки переносит корневые .py-файлы и requirements.txt,
задаёт DATA_DIR (questions.csv + knowledge-base.zip) и ожидает
submission.csv в рабочем каталоге с колонками `id,answer`.

Каждый ID обрабатывается независимо: session_context всегда None,
история между тестами не переносится (история внутри текста вопроса
передаётся модели как есть — это часть входных данных).

Поведение при сбоях:
- корпус/индекс инициализируются один раз до обработки вопросов;
- ошибка одного вопроса (сеть, таймаут, пустой ответ LLM) не роняет
  прогон: в submission.csv пишется честное сообщение об ошибке,
  счётчик failures печатается в stderr;
- дублирующиеся id — предупреждение в stderr, обрабатываются все строки
  (выходная строка на каждый входной ID, как требует регламент).
"""

from __future__ import annotations

import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_engine  # noqa: E402
import kb_loader  # noqa: E402

# Честный ответ при инфраструктурном сбое одного вопроса.
# Это НЕ фиктивный «успешный» ответ — в stderr пишется ERROR,
# а текст прямо сообщает о невозможности ответа.
ERROR_ANSWER = (
    "Не удалось сформировать ответ консультанта из-за внутренней ошибки "
    "сервиса. Попробуйте повторить запрос позже или обратитесь к специалисту."
)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name, "") or default)))
    except ValueError:
        return default


def questions_csv_path() -> Path:
    return kb_loader.get_data_dir() / "questions.csv"


def submission_csv_path() -> Path:
    return Path(os.environ.get("SUBMISSION_PATH", "submission.csv"))


def read_questions(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "id" not in reader.fieldnames:
            raise ValueError(
                f"questions.csv: ожидается колонка 'id', найдено {reader.fieldnames}"
            )
        question_col = "question" if "question" in reader.fieldnames else reader.fieldnames[-1]
        rows = [
            {"id": (row["id"] or "").strip(), "question": (row.get(question_col) or "").strip()}
            for row in reader
        ]
    # Дубликаты id — диагностика, но не остановка: регламент требует
    # строку на каждый входной ID.
    seen: set[str] = set()
    dups = [r["id"] for r in rows if r["id"] in seen or seen.add(r["id"])]
    if dups:
        print(f"WARNING: duplicate ids in questions.csv: {sorted(set(dups))}", file=sys.stderr)
    return rows


def _answer_one(question: str) -> str:
    """Один независимый вопрос -> текст ответа (<=10000 символов)."""
    try:
        result = ai_engine.answer_question(question, session_context=None)
        answer = str(result.get("answer", "")).strip()
    except Exception as exc:  # noqa: BLE001 — изолируем сбой одного вопроса
        print(f"ERROR question failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return ERROR_ANSWER
    if not answer:
        return ERROR_ANSWER
    # Жёсткий лимит регламента — обрезка по границе слова.
    if len(answer) > 10_000:
        answer = answer[: 9_999].rsplit(" ", 1)[0] + "…"
    return answer


def main() -> int:
    qpath = questions_csv_path()
    if not qpath.exists():
        print(
            f"ERROR: questions.csv not found in DATA_DIR={kb_loader.get_data_dir()}",
            file=sys.stderr,
        )
        return 2

    questions = read_questions(qpath)
    print(f"Loaded {len(questions)} questions from {qpath}")

    # Однократная инициализация корпуса и поискового индекса.
    # При отсутствии БЗ фиксируем ошибку и выходим: сабмит без базы
    # знаний был бы фиктивным «успехом».
    try:
        corpus = kb_loader.load_corpus()
        print(f"Corpus ready: {len(corpus)} chunks")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: knowledge base unavailable: {exc}", file=sys.stderr)
        return 3

    out_path = submission_csv_path()
    answers: list[str] = [ERROR_ANSWER] * len(questions)
    failures = 0

    workers = _env_int("MAX_WORKERS", 3, 1, 8)
    if not questions:
        print("WARNING: questions.csv is empty — writing header only")
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_answer_one, item["question"]): i
                for i, item in enumerate(questions)
            }
            done = 0
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    answers[i] = fut.result()
                except Exception as exc:  # noqa: BLE001 — страховка
                    print(f"ERROR id={questions[i]['id']}: {exc}", file=sys.stderr)
                    answers[i] = ERROR_ANSWER
                done += 1
                if answers[i] == ERROR_ANSWER:
                    failures += 1
                if done % 10 == 0 or done == len(questions):
                    print(f"[{done}/{len(questions)}] processed", flush=True)

    # Запись submission.csv: UTF-8, колонки id,answer; csv-модуль корректно
    # экранирует кавычки и переносы строк.
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["id", "answer"])
        for item, answer in zip(questions, answers):
            writer.writerow([item["id"], answer])

    print(
        f"Wrote {len(questions)} answers to {out_path} "
        f"(failures={failures}, workers={workers})",
        file=sys.stderr if failures else sys.stdout,
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
