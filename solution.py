"""Конкурсный entry point МТС: questions.csv -> submission.csv.

Платформа проверки переносит корневые .py-файлы и requirements.txt,
задаёт DATA_DIR (questions.csv + knowledge-base.zip) и ожидает
submission.csv в рабочем каталоге с колонками `id,answer`.

Каждый ID обрабатывается независимо: session_context всегда None,
история между тестами не переносится (история внутри текста вопроса
передаётся модели как есть — это часть входных данных).

Инициализация: корпус и BM25-индекс строятся ОДИН раз до запуска
потоков — параллельные retrieve() не перечитывают базу.

Устойчивость к сбоям:
- ошибка одного вопроса (сеть, таймаут, пустой ответ LLM) не отменяет
  остальные: в его строку пишется непустой честный fallback;
- submission.csv формируется всегда при наличии вопросов — строго
  колонки id,answer, по строке на каждый входной ID;
- exit code: 0 — все ответы успешны; 1 — все запросы к модели
  неуспешны (submission всё равно записан); 2 — нет questions.csv;
  3 — база знаний недоступна. Частичные сбои -> exit 0, но failures
  и типы ошибок печатаются в stderr.
- API-ключи в логи не выводятся никогда.
"""

from __future__ import annotations

import csv
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_engine  # noqa: E402
import kb_loader  # noqa: E402
import retrieval  # noqa: E402

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


def _answer_one(question: str) -> tuple[str, str | None]:
    """Один независимый вопрос -> (текст ответа, тип ошибки|None)."""
    try:
        result = ai_engine.answer_question(question, session_context=None)
        answer = str(result.get("answer", "")).strip()
    except Exception as exc:  # noqa: BLE001 — изолируем сбой одного вопроса
        print(f"ERROR question failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return ERROR_ANSWER, type(exc).__name__
    if not answer:
        return ERROR_ANSWER, "EmptyAnswer"
    # Жёсткий лимит регламента — обрезка по границе слова.
    if len(answer) > 10_000:
        answer = answer[: 9_999].rsplit(" ", 1)[0] + "…"
    return answer, None


def main() -> int:
    started = time.perf_counter()
    qpath = questions_csv_path()
    if not qpath.exists():
        print(
            f"ERROR: questions.csv not found in DATA_DIR={kb_loader.get_data_dir()}",
            file=sys.stderr,
        )
        return 2

    questions = read_questions(qpath)
    print(f"Loaded {len(questions)} questions from {qpath}")

    # Однократная инициализация корпуса И индекса: retrieve() в потоках
    # использует уже построенный индекс и не перечитывает ZIP.
    try:
        corpus = kb_loader.load_corpus()
        retrieval.build_index(corpus)
        print(f"Corpus ready: {len(corpus)} chunks, BM25 index built")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: knowledge base unavailable: {exc}", file=sys.stderr)
        return 3

    out_path = submission_csv_path()
    answers: list[str] = [ERROR_ANSWER] * len(questions)
    error_kinds: Counter[str] = Counter()
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
                    answers[i], err = fut.result()
                except Exception as exc:  # noqa: BLE001 — страховка
                    print(f"ERROR id={questions[i]['id']}: {exc}", file=sys.stderr)
                    answers[i], err = ERROR_ANSWER, type(exc).__name__
                if err is not None:
                    failures += 1
                    error_kinds[err] += 1
                done += 1
                if done % 10 == 0 or done == len(questions):
                    print(f"[{done}/{len(questions)}] processed", flush=True)

    # Запись submission.csv: UTF-8, колонки id,answer; csv-модуль корректно
    # экранирует кавычки и переносы строк.
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["id", "answer"])
        for item, answer in zip(questions, answers):
            writer.writerow([item["id"], answer])

    elapsed = time.perf_counter() - started
    total = len(questions)
    ok = total - failures
    print(
        f"STATS total={total} ok={ok} failures={failures} "
        f"error_kinds={dict(error_kinds)} elapsed={elapsed:.1f}s "
        f"workers={workers} -> {out_path}",
        file=sys.stderr,
    )

    if total and failures == total:
        # Модель не ответила ни на один запрос — это не «успешный» сабмит.
        print("ERROR: все запросы к модели завершились ошибкой", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
