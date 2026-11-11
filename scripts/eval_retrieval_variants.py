"""RAG Research 3: сравнительные эксперименты retrieval БЕЗ изменения baseline.

Production retrieval.py/kb_loader.py не меняются: скрипт строит
СОБСТВЕННЫЙ BM25-индекс поверх чанков kb_loader.load_corpus() и
прогоняет варианты токенизации/запроса/дедупликации.

Вход: demo_questions.csv (18 вопросов) + P0-пробы (Магадан, 750 кВт,
кВт·ч, расширение СЭС, SIM, невыгодность, диалоги).
Файл mts_49_qa_retrieval_inputs.csv на момент запуска ОТСУТСТВУЕТ —
49 дополнительных проверок не выполнялись.

Выход: data/diag/variants_metrics.json + таблица в stdout.
В Git — только этот код и обезличенные агрегаты.
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

import kb_loader  # noqa: E402

DATA_DIR = ROOT / "data" / "diag"

# ---------------------------------------------------------------- gold ---
# Только id/имена файлов/чанков — без текстов БЗ. Многоуровневая разметка:
# gold_files — документ(ы), содержащие ответ; gold_chunks — конкретные
# фрагменты с обязательным фактом (где подтверждено вручную).
GOLD: dict[str, dict] = {
    # --- demo_questions.csv ids 1-18 ---
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
    # --- P0-пробы (разметка вручную по корпусу) ---
    "p0_magadan": {
        "files": ["02-product-scope-and-limits.md", "10-market.md", "26-general.md"],
        "chunks": [
            "00-reference/02-product-scope-and-limits.md#c001",
            "10-energy/10-market.md#c003",
            "20-products/26-general.md#c004",
        ],
    },
    "p0_units750": {
        "files": ["01-numbers-and-indicators.md", "02-product-scope-and-limits.md", "21-orem.md"],
        "chunks": [
            "00-reference/01-numbers-and-indicators.md#c000",
            "00-reference/02-product-scope-and-limits.md#c001",
            "20-products/21-orem.md#c003",
            "20-products/21-orem.md#c024",
        ],
    },
    "p0_market750": {
        "files": ["12-power-thresholds.md", "02-product-scope-and-limits.md", "10-market.md"],
        "chunks": [
            "10-energy/12-power-thresholds.md#c004",
            "00-reference/02-product-scope-and-limits.md#c001",
            "10-energy/10-market.md#c002",
        ],
    },
    "p0_ses_expand": {
        "files": ["23-solar.md"],
        "chunks": ["20-products/23-solar.md#c003"],
    },
    "p0_sim": {
        "files": ["22-askue.md"],
        "chunks": ["20-products/22-askue.md#c015"],
    },
    "p0_unprofitable": {
        "files": ["21-orem.md", "26-general.md"],
        "chunks": ["20-products/21-orem.md#c017"],
    },
}

P0_PROBES = {
    "p0_magadan": "Мы на Камчатке, в Магадане. Можем выйти на оптовый рынок электроэнергии?",
    "p0_units750": "У нас присоединённая мощность 750 кВт. Это больше 750 000 кВт·ч?",
    "p0_market750": "Объект с присоединённой мощностью 750 кВт — доступен выход на оптовый рынок?",
    "p0_ses_expand": "Поставили солнечную станцию на 60 кВт, через год захотим расширить — так можно?",
    "p0_sim": "В счётчиках стоят симки другого оператора. Для вашей платформы их надо менять?",
    "p0_unprofitable": "Если расчёт покажет, что проект нам невыгоден, вы так и скажете?",
}

# Сплит: экспериментальная часть — ids 1-11 + все P0; контрольная — 12-18.
EXPERIMENTAL_IDS = {str(i) for i in range(1, 12)} | set(P0_PROBES)
CONTROL_IDS = {str(i) for i in range(12, 19)}


# ------------------------------------------------------------- variants ---

TOKEN_RE = re.compile(r"[0-9a-zа-яё]+")

CYR = re.compile(r"^[а-яё]+$")
# Простейший стеммер: срезание частотных русских флексий (префиксный матчинг
# сохраняет основу). Только для кириллических слов >=5 букв.
SUFFIXES = sorted(
    [
        "иями", "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими",
        "иях", "ях", "ов", "ев", "ей", "ий", "ый", "ой", "ая", "яя",
        "ое", "ее", "ые", "ие", "ам", "ям", "ах", "ом", "ем", "ую",
        "юю", "ью", "а", "я", "о", "е", "ы", "и", "у", "ю", "ь", "й", "х",
    ],
    key=len, reverse=True,
)


def stem(word: str) -> str:
    if len(word) < 5 or not CYR.match(word):
        return word
    for suf in SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


def tok_base(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower().replace("ё", "е"))


def tok_stem(text: str) -> list[str]:
    return [stem(t) for t in tok_base(text)]


class BM25:
    """Копия логики retrieval.BM25Index с инъецируемым токенизатором."""

    K1, B = 1.5, 0.75

    def __init__(self, chunks, tokenize):
        self.chunks = chunks
        self.tokenize = tokenize
        self.toks = [tokenize(_doc_text(c)) for c in chunks]
        self.dl = [len(t) for t in self.toks]
        self.avgdl = sum(self.dl) / len(self.dl) if self.dl else 0.0
        df: Counter = Counter()
        for t in self.toks:
            df.update(set(t))
        n = len(self.toks)
        import math

        self.idf = {t: math.log((n - d + 0.5) / (d + 0.5) + 1.0) for t, d in df.items()}
        self.tf = []
        for t in self.toks:
            c: Counter = Counter(t)
            self.tf.append(dict(c))

    def rank(self, query: str, top_k: int) -> list[dict]:
        qt = self.tokenize(query)
        scores = [0.0] * len(self.chunks)
        for term in set(qt):
            idf = self.idf.get(term)
            if not idf:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(term, 0)
                if f:
                    denom = f + self.K1 * (1 - self.B + self.B * self.dl[i] / (self.avgdl or 1.0))
                    scores[i] += idf * (f * (self.K1 + 1)) / denom
        order = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in order[:top_k]:
            if scores[i] <= 0:
                break
            c = self.chunks[i]
            out.append({"id": c.get("id"), "file": c.get("file"), "section": c.get("section"), "score": scores[i]})
        return out


def _doc_text(c):
    return f"{c.get('file','')} {c.get('section','')} {c.get('text','')}"


def dialogue_last_user(question: str) -> str:
    """Вариант C: для вопросов с историей — последняя реплика клиента
    + числовые параметры из всего текста (кВт, счётчиков и т.п.)."""
    if "Пользователь:" not in question and "пользователь:" not in question.lower():
        return question
    # последняя реплика пользователя
    parts = re.split(r"(?i)пользователь:", question)
    last = parts[-1]
    last = re.split(r"(?i)ассистент:", last)[0].strip()
    # числовые/единичные параметры из всего диалога
    params = re.findall(r"\d+[\d\s]*(?:квт|мвт|квт·ч|счётчик\w*|объект\w*|магазин\w*|цех\w*|арендатор\w*)", question, re.I)
    extra = " ".join(p.strip() for p in params)
    return (last + " " + extra).strip() or question


def diversify(ranked: list[dict], max_per_file: int = 3, max_per_section: int = 2) -> list[dict]:
    """Вариант D: мягкое разнообразие — cap на файл и на (file,section)."""
    fc: Counter = Counter()
    sc: Counter = Counter()
    out = []
    for h in ranked:
        f, s = h["file"], h.get("section") or ""
        if fc[f] >= max_per_file or sc[(f, s)] >= max_per_section:
            continue
        fc[f] += 1
        sc[(f, s)] += 1
        out.append(h)
    return out


# ------------------------------------------------------------ evaluation ---

def read_questions() -> list[dict]:
    rows = []
    with (ROOT / "demo_questions.csv").open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append({"id": row["id"].strip(), "question": row["question"].strip()})
    for pid, q in P0_PROBES.items():
        rows.append({"id": pid, "question": q})
    return rows


def file_hit(hits, gold_files):
    names = {h["file"].split("/")[-1] for h in hits}
    return any(g in names for g in gold_files)


def best_gold_rank(hits, gold_chunks):
    for i, h in enumerate(hits):
        if h["id"] in gold_chunks:
            return i + 1
    return None


def best_gold_file_rank(hits, gold_files):
    for i, h in enumerate(hits):
        if h["file"].split("/")[-1] in gold_files:
            return i + 1
    return None


def dup_count(hits):
    """Повторы: сколько хитов разделяют (file, section) с предыдущими."""
    seen = Counter()
    dups = 0
    for h in hits:
        key = (h["file"], h.get("section") or "")
        if seen[key]:
            dups += 1
        seen[key] += 1
    return dups


def run_variant(name, index, query_fn, top_k, diversify_flag=False):
    questions = read_questions()
    per_q = []
    t0 = time.perf_counter()
    for item in questions:
        q = query_fn(item["question"])
        hits = index.rank(q, top_k * 3)  # запас для диверсификации
        if diversify_flag:
            hits = diversify(hits)[:top_k]
        else:
            hits = hits[:top_k]
        gold = GOLD[item["id"]]
        fr = best_gold_file_rank(hits, gold["files"])
        cr = best_gold_rank(hits, gold["chunks"]) if gold["chunks"] else None
        per_q.append({
            "id": item["id"], "hits": hits,
            "file_rank": fr, "chunk_rank": cr,
            "dup": dup_count(hits),
        })
    elapsed = (time.perf_counter() - t0) / len(questions) * 1000

    def hits_at(k, field):
        subset = [r for r in per_q if r[field] is not None or field == "file_rank"]
        return round(sum(1 for r in per_q if (r[field] or 10**9) <= k) / len(per_q), 3)

    # file-hit считаем по всем вопросам; passage — только размеченные
    labeled = [r for r in per_q if GOLD[r["id"]]["chunks"]]
    file_hits = {k: hits_at(k, "file_rank") for k in (1, 3, 5, 10)}
    pass_hits = {
        k: round(sum(1 for r in labeled if (r["chunk_rank"] or 10**9) <= k) / len(labeled), 3)
        for k in (3, 5, 8, 10)
    } if labeled else {}
    mrr = round(
        sum(1 / r["chunk_rank"] for r in labeled if r["chunk_rank"]) / len(labeled), 3
    ) if labeled else None
    p0 = [r for r in per_q if r["id"].startswith("p0_")]
    p0_miss5 = sum(1 for r in p0 if (r["chunk_rank"] or 10**9) > 5 or r["chunk_rank"] is None)
    return {
        "name": name, "top_k": top_k,
        "file_hit": file_hits, "passage_recall": pass_hits, "mrr": mrr,
        "labeled_n": len(labeled),
        "p0_critical_miss_top5": p0_miss5, "p0_n": len(p0),
        "avg_dup_per_q": round(sum(r["dup"] for r in per_q) / len(per_q), 2),
        "avg_ms": round(elapsed, 1),
        "per_q": [{"id": r["id"], "file_rank": r["file_rank"], "chunk_rank": r["chunk_rank"],
                   "dup": r["dup"], "top3": [(h["file"].split("/")[-1], round(h["score"], 2)) for h in r["hits"][:3]]}
                  for r in per_q],
    }


def main():
    corpus = kb_loader.load_corpus()
    print(f"corpus: {len(corpus)} chunks")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    idx_base = BM25(corpus, tok_base)
    idx_stem = BM25(corpus, tok_stem)

    ident = lambda q: q  # noqa: E731

    variants = [
        # A: TOP_K sweep на baseline
        run_variant("A_base_k5", idx_base, ident, 5),
        run_variant("A_base_k8", idx_base, ident, 8),
        run_variant("A_base_k10", idx_base, ident, 10),
        # B: стемминг (top_k=5 как baseline)
        run_variant("B_stem_k5", idx_stem, ident, 5),
        run_variant("B_stem_k8", idx_stem, ident, 8),
        # C: dialog-aware (baseline index)
        run_variant("C_dialog_k5", idx_base, dialogue_last_user, 5),
        run_variant("C_dialog_k8", idx_base, dialogue_last_user, 8),
        # D: diversity (baseline, top_k=8 -> cap -> 5/8)
        run_variant("D_div_k5", idx_base, ident, 5, diversify_flag=True),
        run_variant("D_div_k8", idx_base, ident, 8, diversify_flag=True),
        # Комбинации лучших факторов (проверка совместимости)
        run_variant("AB_stem_dialog_k8", idx_stem, dialogue_last_user, 8),
        run_variant("ABD_stem_dialog_div_k8", idx_stem, dialogue_last_user, 8, diversify_flag=True),
        run_variant("ABD_stem_dialog_div_k10", idx_stem, dialogue_last_user, 10, diversify_flag=True),
    ]

    # --- отчёт ---
    print(f"\n{'variant':28s} {'fH@1':>5s} {'fH@3':>5s} {'fH@5':>5s} {'fH@10':>5s} "
          f"{'pR@5':>5s} {'pR@10':>5s} {'MRR':>5s} {'P0miss':>6s} {'dup':>5s} {'ms':>6s}")
    for v in variants:
        pr5 = v["passage_recall"].get(5, "-")
        pr10 = v["passage_recall"].get(10, "-")
        print(f"{v['name']:28s} {v['file_hit'][1]:>5} {v['file_hit'][3]:>5} {v['file_hit'][5]:>5} "
              f"{v['file_hit'][10]:>5} {str(pr5):>5s} {str(pr10):>5s} {str(v['mrr']):>5s} "
              f"{v['p0_critical_miss_top5']:>6d} {v['avg_dup_per_q']:>5} {v['avg_ms']:>6}")

    out = DATA_DIR / "variants_metrics.json"
    out.write_text(json.dumps(variants, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved {out}")

    # Детализация по экспериментальной/контрольной части для baseline vs combo
    for v in variants:
        if v["name"] in ("A_base_k5", "ABD_stem_dialog_div_k8"):
            exp = [r for r in v["per_q"] if r["id"] in EXPERIMENTAL_IDS]
            ctl = [r for r in v["per_q"] if r["id"] in CONTROL_IDS]
            def fh(rows, k):
                return round(sum(1 for r in rows if (r["file_rank"] or 99) <= k) / len(rows), 3)
            print(f"{v['name']}: EXP fileH@5={fh(exp,5)} n={len(exp)} | "
                  f"CTL fileH@5={fh(ctl,5)} n={len(ctl)}")


if __name__ == "__main__":
    main()
