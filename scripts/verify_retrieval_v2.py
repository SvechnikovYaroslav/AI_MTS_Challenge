"""Проверка Retrieval V2 на production retrieval.py (self-contained).

Прогоняет 78 запросов (18 demo + 6 P0 + 5 E-проб + 49 QA) через
РЕАЛЬНЫЙ retrieval.retrieve() и считает file/passage-метрики.
Gold-разметка продублирована из scripts/eval_retrieval_variants*.py
(feature/rag-evaluation) — только id/имена файлов, без текстов БЗ.

Ожидаемые метрики (Research 4, вариант E_stemE_k8):
fH@8=.962, pR@8=.75, MRR=.683, P0miss@8=0, EXP fH@5=1.0, QA49 fH@8=.959.

Выход: data/diag/retrieval_v2_verify.json + stdout.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import kb_loader  # noqa: E402
import retrieval  # noqa: E402

DATA_DIR = ROOT / "data" / "diag"
QA_CSV = DATA_DIR / "mts_49_qa_retrieval_inputs.csv"

GOLD = {
    "1": {"files": ["23-solar.md"], "chunks": ["20-products/23-solar.md#c008"]},
    "2": {"files": ["23-solar.md"], "chunks": []},
    "3": {"files": ["23-solar.md"], "chunks": ["20-products/23-solar.md#c003"]},
    "4": {"files": ["23-solar.md"], "chunks": []},
    "5": {"files": ["22-askue.md"], "chunks": ["20-products/22-askue.md#c015"]},
    "6": {"files": ["22-askue.md", "25-meter-reading.md"], "chunks": []},
    "7": {"files": ["22-askue.md"], "chunks": []},
    "8": {"files": ["25-meter-reading.md"], "chunks": []},
    "9": {"files": ["25-meter-reading.md"], "chunks": []},
    "10": {"files": ["14-tariffs.md", "11-price-categories.md", "26-general.md"], "chunks": []},
    "11": {"files": ["21-orem.md", "17-faq.md"], "chunks": ["20-products/21-orem.md#c017"]},
    "12": {"files": ["10-market.md", "03-calculation-and-requests.md"], "chunks": []},
    "13": {"files": ["21-orem.md", "26-general.md"], "chunks": ["20-products/21-orem.md#c017"]},
    "14": {"files": ["23-solar.md"], "chunks": []},
    "15": {"files": ["22-askue.md", "25-meter-reading.md"], "chunks": []},
    "16": {"files": ["24-losses.md"], "chunks": []},
    "17": {"files": ["11-price-categories.md", "14-tariffs.md"], "chunks": []},
    "18": {"files": ["22-askue.md", "03-calculation-and-requests.md"], "chunks": []},
    "p0_magadan": {"files": ["02-product-scope-and-limits.md", "10-market.md", "26-general.md"],
                   "chunks": ["00-reference/02-product-scope-and-limits.md#c001",
                              "10-energy/10-market.md#c003", "20-products/26-general.md#c004"]},
    "p0_units750": {"files": ["01-numbers-and-indicators.md", "02-product-scope-and-limits.md", "21-orem.md"],
                    "chunks": ["00-reference/01-numbers-and-indicators.md#c000",
                               "00-reference/02-product-scope-and-limits.md#c001",
                               "20-products/21-orem.md#c003", "20-products/21-orem.md#c024"]},
    "p0_market750": {"files": ["12-power-thresholds.md", "02-product-scope-and-limits.md", "10-market.md"],
                     "chunks": ["10-energy/12-power-thresholds.md#c004",
                                "00-reference/02-product-scope-and-limits.md#c001",
                                "10-energy/10-market.md#c002"]},
    "p0_ses_expand": {"files": ["23-solar.md"], "chunks": ["20-products/23-solar.md#c003"]},
    "p0_sim": {"files": ["22-askue.md"], "chunks": ["20-products/22-askue.md#c015"]},
    "p0_unprofitable": {"files": ["21-orem.md", "26-general.md"], "chunks": ["20-products/21-orem.md#c017"]},
}
P0_PROBES = {
    "p0_magadan": "Мы на Камчатке, в Магадане. Можем выйти на оптовый рынок электроэнергии?",
    "p0_units750": "У нас присоединённая мощность 750 кВт. Это больше 750 000 кВт·ч?",
    "p0_market750": "Объект с присоединённой мощностью 750 кВт — доступен выход на оптовый рынок?",
    "p0_ses_expand": "Поставили солнечную станцию на 60 кВт, через год захотим расширить — так можно?",
    "p0_sim": "В счётчиках стоят симки другого оператора. Для вашей платформы их надо менять?",
    "p0_unprofitable": "Если расчёт покажет, что проект нам невыгоден, вы так и скажете?",
}
E_PROBES = {
    "e_sim_kol": "В счётчиках стоят симки другого оператора — это проблема?",
    "e_sim_upper": "SIM-карты другого оператора подойдут для вашей платформы?",
    "e_sim_hyphen": "Если в ПУ стоят сим-картами чужого оператора, что делать?",
    "e_sim_phrase": "SIM другого оператора — поддерживается?",
    "e_sim_svyaz": "Нужен ли оператор связи для удалённого съёма показаний?",
}
E_GOLD = {"files": ["22-askue.md"], "chunks": ["20-products/22-askue.md#c015"]}

# Альтернативные корректные источники (вручную проверено по корпусу):
#  - demo 12: чанк 21-orem#c007 описывает проверку учёта для оптового рынка;
#  - KB-QA-003: пороги выхода на опт дублируются в 02-product-scope и
#    01-numbers-and-indicators (раздел «Выход на оптовый рынок»).
ALT_FILES = {
    "12": ["21-orem.md"],
    "KB-QA-003": ["02-product-scope-and-limits.md", "01-numbers-and-indicators.md"],
}


def load_qa() -> list[dict]:
    rows = []
    with QA_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            files = [x.strip() for x in r["candidate_source_files"].split(";") if x.strip()]
            files += [f for f in ALT_FILES.get(r["id"].strip(), []) if f not in files]
            rows.append({"id": r["id"].strip(), "question": r["question"].strip(),
                         "group": "qa49", "files": files, "chunks": []})
    return rows


def questions() -> list[dict]:
    rows = []
    with (ROOT / "demo_questions.csv").open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            i = r["id"].strip()
            g = GOLD[i]
            files = g["files"] + [f for f in ALT_FILES.get(i, []) if f not in g["files"]]
            rows.append({"id": i, "question": r["question"].strip(),
                         "group": "ctl" if i in {str(n) for n in range(12, 19)} else "exp",
                         "files": files, "chunks": g["chunks"]})
    for pid, q in {**P0_PROBES, **E_PROBES}.items():
        g = GOLD.get(pid) or E_GOLD
        rows.append({"id": pid, "question": q, "group": "exp",
                     "files": g["files"], "chunks": g["chunks"]})
    rows.extend(load_qa())
    return rows


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


def main():
    corpus = kb_loader.load_corpus()
    retrieval.build_index(corpus)
    qs = questions()
    per_q = []
    for it in qs:
        hits = retrieval.retrieve(it["question"])  # TOP_K=8 по умолчанию
        per_q.append({
            "id": it["id"], "group": it["group"],
            "file_rank": file_rank(hits, it["files"]),
            "chunk_rank": chunk_rank(hits, it["chunks"]) if it["chunks"] else None,
            "n_hits": len(hits),
            "uniq_docs": len({h["file"] for h in hits}),
            "text_chars": sum(len(h["content"]) for h in hits),
        })

    labeled = {q["id"] for q in qs if q["chunks"]}
    lab = [r for r in per_q if r["id"] in labeled]
    p0 = [r for r in per_q if r["id"].startswith("p0_")]
    epr = [r for r in per_q if r["id"].startswith("e_")]

    def fh(rows, k):
        return round(sum(1 for r in rows if (r["file_rank"] or 99) <= k) / len(rows), 3)

    res = {
        "n_questions": len(qs),
        "file_hit": {k: fh(per_q, k) for k in (1, 3, 5, 8)},
        "passage_recall": {k: round(sum(1 for r in lab if (r["chunk_rank"] or 99) <= k) / len(lab), 3)
                           for k in (5, 8)},
        "mrr": round(sum(1 / r["chunk_rank"] for r in lab if r["chunk_rank"]) / len(lab), 3),
        "labeled_n": len(lab),
        "p0_miss8": sum(1 for r in p0 if (r["chunk_rank"] or 99) > 8),
        "e_sim_solved": f"{sum(1 for r in epr if r['chunk_rank'] and r['chunk_rank'] <= 8)}/{len(epr)}",
        "avg_uniq_docs": round(sum(r["uniq_docs"] for r in per_q) / len(per_q), 2),
        "avg_text_chars": round(sum(r["text_chars"] for r in per_q) / len(per_q)),
        "groups": {},
        "watch": {},
        "per_q": per_q,
    }
    for gname, pred in {
        "exp": lambda r: r["group"] == "exp",
        "ctl": lambda r: r["group"] == "ctl",
        "demo18": lambda r: r["group"] in ("exp", "ctl") and not r["id"].startswith(("p0_", "e_")),
        "qa49": lambda r: r["group"] == "qa49",
    }.items():
        rows = [r for r in per_q if pred(r)]
        res["groups"][gname] = {"n": len(rows), "fH@5": fh(rows, 5), "fH@8": fh(rows, 8)}
    for wid in ("12", "11", "KB-QA-003", "KB-QA-046"):
        res["watch"][wid] = next(r for r in per_q if r["id"] == wid)

    print(json.dumps({k: v for k, v in res.items() if k != "per_q"},
                     ensure_ascii=False, indent=2))
    miss = [r["id"] for r in per_q if r["id"] in labeled and (r["chunk_rank"] or 99) > 8]
    print("labeled misses @8:", miss)
    out = DATA_DIR / "retrieval_v2_verify.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out)


if __name__ == "__main__":
    main()
