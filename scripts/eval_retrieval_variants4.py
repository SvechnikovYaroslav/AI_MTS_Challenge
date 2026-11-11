"""RAG Research 4: проверка кандидата (стемминг + TOP_K) на полном наборе.

Вход: demo_questions.csv (18) + data/diag/mts_49_qa_retrieval_inputs.csv (49)
+ P0-пробы + E-пробы по SIM-терминам. Итого 18+49+6+5=78 запросов.

Варианты (один фактор за раз, как в Research 3):
  A: baseline tokenizer, k5      — как в проде
  B: baseline tokenizer, k8
  C: stem tokenizer, k5
  D: stem tokenizer, k8          — кандидат Research 3
  E: stem + нормализация составных/разговорных терминов, k8

Production retrieval.py НЕ меняется — собственный BM25 в скрипте.
Выход: data/diag/variants4_metrics.json + stdout-таблицы.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import kb_loader  # noqa: E402
from eval_retrieval_variants import (  # noqa: E402
    BM25, GOLD, P0_PROBES, tok_base, tok_stem,
)

DATA_DIR = ROOT / "data" / "diag"
QA_CSV = DATA_DIR / "mts_49_qa_retrieval_inputs.csv"

# ------------------------------------------------- E: нормализация терминов ---
# ТОЛЬКО целевые семейства, без универсальных замен:
#  - «сим-карта» во всех формах и разговорное «симка/симки» → «симкарта»
#    (в БЗ термин «сим-карта/сим-карты»; стеммер режет дефис на «сим»+«картами»,
#    а «симки»→«симк» — без склейки они не встречаются);
#  - «SIM-карты»/«SIM другого оператора» — то же семейство;
#  - «оператор связи» уже покрывается стеммером, отдельно не нужно.
# Ничего не сливаем вне семейства «сим(‑)карт*».

_RE_SIMHYPH = re.compile(r"(?i)\b(?:сим|sim)[-\s]?карт\w*")
_RE_SIMCOLLOQ = re.compile(r"(?i)\bсимк[а-яё]*")
_RE_SIMLATIN = re.compile(r"(?i)\bsim\b(?!\s*[-\s]?карт)")


def tok_stem_e(text: str) -> list[str]:
    t = _RE_SIMHYPH.sub(" симкарта ", text)
    t = _RE_SIMCOLLOQ.sub(" симкарта ", t)
    t = _RE_SIMLATIN.sub(" симкарта ", t)
    return tok_stem(t)


# ------------------------------------------- E-пробы по SIM-формулировкам ---
E_PROBES = {
    "e_sim_kol": "В счётчиках стоят симки другого оператора — это проблема?",
    "e_sim_upper": "SIM-карты другого оператора подойдут для вашей платформы?",
    "e_sim_hyphen": "Если в ПУ стоят сим-картами чужого оператора, что делать?",
    "e_sim_phrase": "SIM другого оператора — поддерживается?",
    "e_sim_svyaz": "Нужен ли оператор связи для удалённого съёма показаний?",
}
E_GOLD = {"files": ["22-askue.md"], "chunks": ["20-products/22-askue.md#c015"]}

# Загрузить QA-кандидатов как file-level gold (это подсказки, не факт-уровень).
def load_qa() -> list[dict]:
    rows = []
    with QA_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            files = [x.strip() for x in r["candidate_source_files"].split(";") if x.strip()]
            rows.append({"id": r["id"].strip(), "question": r["question"].strip(),
                         "group": "qa49", "files": files, "chunks": []})
    return rows


def load_questions() -> list[dict]:
    rows = []
    with (ROOT / "demo_questions.csv").open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            g = GOLD[r["id"].strip()]
            grp = "ctl" if r["id"].strip() in {str(i) for i in range(12, 19)} else "exp"
            rows.append({"id": r["id"].strip(), "question": r["question"].strip(),
                         "group": grp, "files": g["files"], "chunks": g["chunks"]})
    for pid, q in P0_PROBES.items():
        g = GOLD[pid]
        rows.append({"id": pid, "question": q, "group": "exp",
                     "files": g["files"], "chunks": g["chunks"]})
    for eid, q in E_PROBES.items():
        rows.append({"id": eid, "question": q, "group": "exp",
                     "files": E_GOLD["files"], "chunks": E_GOLD["chunks"]})
    rows.extend(load_qa())
    return rows


GROUPS = {"exp": lambda i: i["group"] == "exp", "ctl": lambda i: i["group"] == "ctl",
          "demo18": lambda i: i["group"] in ("exp", "ctl") and not i["id"].startswith(("p0_", "e_")),
          "p0": lambda i: i["id"].startswith("p0_"),
          "e_probes": lambda i: i["id"].startswith("e_"),
          "qa49": lambda i: i["group"] == "qa49"}


def file_rank(hits, files):
    for i, h in enumerate(hits):
        if h["file"].split("/")[-1] in files:
            return i + 1
    return None


def chunk_rank(hits, chunks):
    for i, h in enumerate(hits):
        if h["id"] in chunks:
            return i + 1
    return None


def run(name, index, top_k, questions, keep=10):
    per_q, t0 = [], time.perf_counter()
    for it in questions:
        hits = index.rank(it["question"], top_k)
        fr = file_rank(hits, it["files"])
        cr = chunk_rank(hits, it["chunks"]) if it["chunks"] else None
        per_q.append({
            "id": it["id"], "group": it["group"], "file_rank": fr, "chunk_rank": cr,
            "uniq_docs": len({h["file"] for h in hits}),
            "text_chars": sum(len(h.get("text", "")) for h in hits),
            "hits": [{"id": h["id"], "file": h["file"], "section": h.get("section"),
                      "score": round(h["score"], 3)} for h in hits],
        })
    ms = (time.perf_counter() - t0) / len(questions) * 1000

    def metrics(rows):
        n = len(rows)
        fh = {k: round(sum(1 for r in rows if (r["file_rank"] or 99) <= k) / n, 3)
              for k in (1, 3, 5, 8, 10)}
        lab = [r for r in rows if r["chunk_rank"] is not None or r.get("has_chunks")]
        return fh

    # passage-метрики только по вопросам с размеченными чанками
    labeled_ids = {it["id"] for it in questions if it["chunks"]}
    lab = [r for r in per_q if r["id"] in labeled_ids]
    pr = {k: round(sum(1 for r in lab if (r["chunk_rank"] or 99) <= k) / len(lab), 3)
          for k in (3, 5, 8, 10)} if lab else {}
    mrr = round(sum(1 / r["chunk_rank"] for r in lab if r["chunk_rank"]) / len(lab), 3) if lab else None
    p0 = [r for r in per_q if r["id"].startswith("p0_")]
    epr = [r for r in per_q if r["id"].startswith("e_")]
    return {
        "name": name, "top_k": top_k, "ms": round(ms, 2),
        "all": metrics(per_q), "passage": pr, "mrr": mrr, "labeled_n": len(lab),
        "p0_miss8": sum(1 for r in p0 if (r["chunk_rank"] or 99) > 8),
        "p0_miss10": sum(1 for r in p0 if (r["chunk_rank"] or 99) > 10),
        "e_sim_solved": sum(1 for r in epr if r["chunk_rank"] and r["chunk_rank"] <= 8),
        "e_sim_n": len(epr),
        "uniq_docs_avg": round(sum(r["uniq_docs"] for r in per_q) / len(per_q), 2),
        "text_chars_avg": round(sum(r["text_chars"] for r in per_q) / len(per_q)),
        "per_q": per_q,
    }


def group_metrics(result, questions, name):
    """Метрики file-hit по группам для готового result."""
    out = {}
    ids = {it["id"]: it["group"] for it in questions}
    for gname, pred in GROUPS.items():
        rows = [r for r in result["per_q"] if pred({"id": r["id"], "group": ids.get(r["id"], "?")})]
        if not rows:
            continue
        n = len(rows)
        out[gname] = {
            "n": n,
            "fH@1": round(sum(1 for r in rows if (r["file_rank"] or 99) <= 1) / n, 3),
            "fH@3": round(sum(1 for r in rows if (r["file_rank"] or 99) <= 3) / n, 3),
            "fH@5": round(sum(1 for r in rows if (r["file_rank"] or 99) <= 5) / n, 3),
            "fH@8": round(sum(1 for r in rows if (r["file_rank"] or 99) <= 8) / n, 3),
            "fH@10": round(sum(1 for r in rows if (r["file_rank"] or 99) <= 10) / n, 3),
        }
    return out


def regressions(base_res, var_res, questions):
    """Вопросы, где file_rank ухудшился (стал None или больше) vs baseline."""
    bq = {r["id"]: r for r in base_res["per_q"]}
    out = []
    for r in var_res["per_q"]:
        b = bq[r["id"]]
        br, vr = b["file_rank"], r["file_rank"]
        if br is not None and (vr is None or vr > br):
            out.append({"id": r["id"], "base_rank": br, "var_rank": vr})
    return out


def main():
    corpus = kb_loader.load_corpus()
    # добавляем text в хиты для подсчёта объёма — BM25.rank возвращает без text;
    # обернём: после rank маппим id->text
    text_by_id = {c["id"]: c.get("text", "") for c in corpus}

    class Idx(BM25):
        def rank(self, q, k):
            res = super().rank(q, k)
            for h in res:
                h["text"] = text_by_id.get(h["id"], "")
            return res

    questions = load_questions()
    print(f"questions: {len(questions)} "
          f"(demo18={sum(1 for q in questions if q['group'] in ('exp','ctl') and not q['id'].startswith(('p0_','e_')))}, "
          f"p0={sum(1 for q in questions if q['id'].startswith('p0_'))}, "
          f"e={sum(1 for q in questions if q['id'].startswith('e_'))}, qa49={sum(1 for q in questions if q['group']=='qa49')})")

    idx_base = Idx(corpus, tok_base)
    idx_stem = Idx(corpus, tok_stem)
    idx_e = Idx(corpus, tok_stem_e)
    ident = lambda q: q  # noqa: E731

    variants = [
        run("A_base_k5", idx_base, 5, questions),
        run("B_base_k8", idx_base, 8, questions),
        run("C_stem_k5", idx_stem, 5, questions),
        run("D_stem_k8", idx_stem, 8, questions),
        run("E_stemE_k8", idx_e, 8, questions),
        run("E_stemE_k10", idx_e, 10, questions),
    ]

    # --- сводная таблица ---
    print(f"\n{'var':12s} {'fH@1':>5s} {'fH@3':>5s} {'fH@5':>5s} {'fH@8':>5s} {'fH@10':>5s} "
          f"{'pR@5':>5s} {'pR@10':>5s} {'MRR':>5s} {'P0m8':>4s} {'Esim':>4s} {'docs':>5s} {'kch':>6s} {'ms':>6s}")
    for v in variants:
        a = v["all"]
        print(f"{v['name']:12s} {a[1]:>5} {a[3]:>5} {a[5]:>5} {a[8]:>5} {a[10]:>5} "
              f"{v['passage'].get(5,'-'):>5} {v['passage'].get(10,'-'):>5} {v['mrr'] or '-':>5} "
              f"{v['p0_miss8']:>4d} {v['e_sim_solved']}/{v['e_sim_n']:<3d} "
              f"{v['uniq_docs_avg']:>5} {v['text_chars_avg']:>6} {v['ms']:>6}")

    # --- по группам ---
    print("\n=== file-hit по группам (fH@5 / fH@8) ===")
    for v in variants:
        gm = group_metrics(v, questions, v["name"])
        print(f"{v['name']:12s} " + "  ".join(
            f"{g}: {m['fH@5']}/{m['fH@8']} (n={m['n']})" for g, m in gm.items()))

    # --- регрессии vs A_base_k5 ---
    print("\n=== регрессии file_rank vs A_base_k5 ===")
    base = variants[0]
    for v in variants[1:]:
        reg = regressions(base, v, questions)
        print(f"{v['name']:12s} {len(reg)} регрессий: " +
              ", ".join(f"{r['id']}({r['base_rank']}->{r['var_rank']})" for r in reg[:12]))

    # --- passage-регрессии (chunk_rank потерян) ---
    print("\n=== passage-регрессии vs A_base_k5 ===")
    bq = {r["id"]: r for r in base["per_q"] if r["chunk_rank"]}
    for v in variants[1:]:
        lost = [r["id"] for r in v["per_q"]
                if r["id"] in bq and bq[r["id"]]["chunk_rank"]
                and (r["chunk_rank"] is None or r["chunk_rank"] > bq[r["id"]]["chunk_rank"])]
        print(f"{v['name']:12s} {lost}")

    # --- E-пробы детально ---
    print("\n=== E-пробы (SIM-формулировки): chunk_rank по вариантам ===")
    hdr = "probe".ljust(14) + "".join(v["name"].rjust(11) for v in variants)
    print(hdr)
    e_ids = [q["id"] for q in questions if q["id"].startswith("e_")]
    for eid in e_ids:
        row = eid.ljust(14)
        for v in variants:
            r = next(x for x in v["per_q"] if x["id"] == eid)
            row += str(r["chunk_rank"]).rjust(11)
        print(row)

    # --- top-10 промахи passage для D и E ---
    for v in variants:
        miss = [r["id"] for r in v["per_q"]
                if r["id"] in {it["id"] for it in questions if it["chunks"]}
                and (r["chunk_rank"] is None or r["chunk_rank"] > 10)]
        print(f"\n{v['name']}: размеченные вопросы без gold-чанка в top-10: {miss}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "variants4_metrics.json"
    slim = [{k: val for k, val in v.items() if k != "per_q"} |
            {"groups": group_metrics(v, questions, v["name"]),
             "regressions": regressions(base, v, questions) if v is not base else [],
             "per_q": [{"id": r["id"], "group": r["group"], "file_rank": r["file_rank"],
                        "chunk_rank": r["chunk_rank"], "uniq_docs": r["uniq_docs"],
                        "text_chars": r["text_chars"]} for r in v["per_q"]]}
            for v in variants]
    out.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
