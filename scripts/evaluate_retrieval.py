"""Диагностика retrieval baseline на локальной базе МТС (research only).

Запускает РЕАЛЬНЫЕ kb_loader.py и retrieval.py (без изменений) на
knowledge-base.zip и сохраняет top-k фрагментов для каждого вопроса
в data/diag/ — для ручной разметки релевантности.

Это НЕ часть конкурсного сабмита: скрипт лежит в scripts/ и не
входит в submission.zip. Ничего не оптимизирует и не меняет
поведение ai_engine/retrieval/kb_loader.

Usage:
    python scripts/evaluate_retrieval.py [--questions demo_questions.csv]
        [--top-k 10] [--out data/diag]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import kb_loader  # noqa: E402
import retrieval  # noqa: E402


def read_questions(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        qcol = "question" if "question" in (reader.fieldnames or []) else (reader.fieldnames or ["question"])[-1]
        return [
            {"id": (row.get("id") or "").strip(), "question": (row.get(qcol) or "").strip()}
            for row in reader
        ]


def snippet(text: str, width: int = 220) -> str:
    flat = " ".join(text.split())
    return flat[:width] + ("…" if len(flat) > width else "")


def corpus_stats(corpus: list[dict]) -> dict:
    lengths = [len(c["text"]) for c in corpus]
    per_file = Counter(c["file"] for c in corpus)
    per_section = Counter(c.get("section") or "<none>" for c in corpus)
    return {
        "chunks": len(corpus),
        "docs": len(per_file),
        "chunk_len": {
            "min": min(lengths) if lengths else 0,
            "max": max(lengths) if lengths else 0,
            "avg": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        },
        "chunks_per_file": dict(per_file.most_common()),
        "top_sections": dict(per_section.most_common(15)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(ROOT / "demo_questions.csv"))
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--out", default=str(ROOT / "data" / "diag"))
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    corpus = kb_loader.load_corpus()
    stats = corpus_stats(corpus)
    retrieval.build_index(corpus)
    print(f"corpus: {stats['chunks']} chunks / {stats['docs']} docs")

    questions = read_questions(Path(args.questions))
    print(f"questions: {len(questions)}")

    results = []
    for item in questions:
        q = item["question"]
        hits = retrieval.retrieve(q, top_k=args.top_k)
        entry = {
            "id": item["id"],
            "question": q,
            "query_used": q,  # session_context=None — как в solution.py
            "n_hits": len(hits),
            "distinct_files_top10": len({h["file"] for h in hits}),
            "hits": [
                {
                    "rank": i + 1,
                    "chunk_id": h["id"],
                    "file": h["file"],
                    "section": h["section"],
                    "score": h["score"],
                    "snippet": snippet(h["content"]),
                }
                for i, h in enumerate(hits)
            ],
        }
        results.append(entry)
        top = hits[0]["file"] if hits else "-"
        print(f"  id={item['id']}: hits={len(hits)} top={top} score={hits[0]['score'] if hits else 0}")

    payload = {
        "meta": {
            "questions_file": args.questions,
            "top_k": args.top_k,
            "corpus_stats": stats,
            "note": "session_context=None; query = raw question text",
        },
        "results": results,
    }
    out_json = out_dir / "retrieval_top10.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Шаблон таблицы для ручной разметки (без текстов — только метаданные).
    lines = [
        "# Retrieval evaluation — manual labeling template",
        "",
        "| id | question(short) | required_fact | expected_file#chunk | bm25_rank | in_top3 | in_top5 | notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        q_short = " ".join(r["question"].split())[:80]
        lines.append(f"| {r['id']} | {q_short} |  |  |  |  |  |  |")
    (out_dir / "label_template.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    (out_dir / "corpus_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"saved: {out_json}")
    print(f"saved: {out_dir / 'label_template.md'}")
    print(f"saved: {out_dir / 'corpus_stats.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
