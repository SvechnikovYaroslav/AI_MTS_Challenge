"""Qwen Generation Audit: сравнение retrieval-контекстов baseline vs V2.

Baseline = конфигурация тега mts-score-0.4533: токенизация без
стемминга/SIM-нормализации, TOP_K=5 (воспроизводится через
eval_retrieval_variants.BM25 + tok_base).
Candidate = develop: production retrieval.retrieve(), TOP_K=8.

Для каждого из 78 вопросов сохраняет в data/diag/gen_contexts_audit.json:
- top-k фрагменты обеих версий (file/section/score/сниппет);
- наличие gold-чанков в каждом контексте;
- оценку размера user-prompt (символы).

Тексты БЗ — только в data/diag (gitignored). В stdout — только ID и числа.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import kb_loader  # noqa: E402
import prompts  # noqa: E402
import retrieval  # noqa: E402
from eval_retrieval_variants import BM25, GOLD, P0_PROBES, tok_base  # noqa: E402
from eval_retrieval_variants4 import E_PROBES, E_GOLD, load_qa  # noqa: E402

DATA_DIR = ROOT / "data" / "diag"


def questions() -> list[dict]:
    rows = []
    with (ROOT / "demo_questions.csv").open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            i = r["id"].strip()
            g = GOLD[i]
            rows.append({"id": i, "question": r["question"].strip(),
                         "group": "demo", "files": g["files"], "chunks": g["chunks"]})
    for pid, q in {**P0_PROBES, **E_PROBES}.items():
        g = GOLD.get(pid) or E_GOLD
        rows.append({"id": pid, "question": q, "group": "probe",
                     "files": g["files"], "chunks": g["chunks"]})
    rows.extend(load_qa())
    return rows


def to_hit(h: dict, text_by_id: dict) -> dict:
    return {"id": h["id"], "file": h["file"], "section": h.get("section"),
            "score": round(h["score"], 3),
            "content": text_by_id.get(h["id"], "")[:400]}


def main():
    corpus = kb_loader.load_corpus()
    text_by_id = {c["id"]: c.get("text", "") for c in corpus}
    retrieval.build_index(corpus)
    base_idx = BM25(corpus, tok_base)
    qs = questions()

    out_rows = []
    for it in qs:
        # baseline: k=5, без V2-нормализации
        b_hits_raw = base_idx.rank(it["question"], 5)
        b_hits = [to_hit(h, text_by_id) for h in b_hits_raw]
        # V2: production retrieval, TOP_K=8
        v_hits_raw = retrieval.retrieve(it["question"])
        v_hits = [{"id": h["id"], "file": h["file"], "section": h["section"],
                   "score": h["score"], "content": h["content"][:400]}
                  for h in v_hits_raw]

        b_prompt = prompts.build_user_prompt(it["question"], b_hits)
        v_prompt = prompts.build_user_prompt(it["question"], v_hits)
        b_gold = [g for g in it["chunks"] if any(h["id"] == g for h in b_hits)]
        v_gold = [g for g in it["chunks"] if any(h["id"] == g for h in v_hits)]

        out_rows.append({
            "id": it["id"], "group": it["group"],
            "baseline": {"k": len(b_hits), "hits": b_hits,
                         "prompt_chars": len(b_prompt),
                         "gold_in_context": len(b_gold), "gold_total": len(it["chunks"])},
            "v2": {"k": len(v_hits), "hits": v_hits,
                   "prompt_chars": len(v_prompt),
                   "gold_in_context": len(v_gold), "gold_total": len(it["chunks"])},
        })

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "gen_contexts_audit.json"
    out.write_text(json.dumps(out_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    # stdout: только ID/числа
    print(f"{'id':14s} {'grp':5s} {'base_k':>6s} {'v2_k':>4s} {'b_pch':>6s} {'v_pch':>6s} {'b_gold':>6s} {'v_gold':>6s}")
    for r in out_rows:
        b, v = r["baseline"], r["v2"]
        print(f"{r['id']:14s} {r['group']:5s} {b['k']:>6d} {v['k']:>4d} "
              f"{b['prompt_chars']:>6d} {v['prompt_chars']:>6d} "
              f"{b['gold_in_context']}/{b['gold_total']:<4d} {v['gold_in_context']}/{v['gold_total']:<4d}")
    n = len(out_rows)
    b_avg = sum(r["baseline"]["prompt_chars"] for r in out_rows) / n
    v_avg = sum(r["v2"]["prompt_chars"] for r in out_rows) / n
    b_gold_q = sum(1 for r in out_rows if r["baseline"]["gold_in_context"])
    v_gold_q = sum(1 for r in out_rows if r["v2"]["gold_in_context"])
    print(f"\navg prompt chars: baseline={b_avg:.0f} v2={v_avg:.0f} (+{v_avg-b_avg:.0f})")
    print(f"questions with >=1 gold chunk in context: baseline={b_gold_q}/{n} v2={v_gold_q}/{n}")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
