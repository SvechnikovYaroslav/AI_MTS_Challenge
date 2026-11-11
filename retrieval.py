"""Слой поиска по базе знаний МТС (RAG retrieval).

Baseline: BM25 (Okapi) по чанкам из kb_loader. Без эмбеддингов и
реранкера — осознанно: сначала оцениваем простейший baseline.
BM25 не даёт семантического понимания: синонимы и перефразировки
могут не находиться, это известное ограничение первого этапа.

Индекс строится один раз на процесс и кэшируется.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any

import kb_loader

_TOKEN_RE = re.compile(r"[0-9a-zа-яё]+")

# BM25 параметры (стандартные Okapi).
K1 = 1.5
B = 0.75


def _env_top_k() -> int:
    try:
        return max(1, min(30, int(os.environ.get("TOP_K", "") or 5)))
    except ValueError:
        return 5


def tokenize(text: str) -> list[str]:
    """Нормализация: lower, ё->е, слова из букв/цифр (ru+en)."""
    return _TOKEN_RE.findall(text.lower().replace("ё", "е"))


class BM25Index:
    """Минимальный BM25Okapi поверх списка чанков."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks
        self.tokenized = [tokenize(_doc_text(c)) for c in chunks]
        self.doc_len = [len(t) for t in self.tokenized]
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0.0
        # df: сколько документов содержат термин.
        df: dict[str, int] = {}
        for toks in self.tokenized:
            for term in set(toks):
                df[term] = df.get(term, 0) + 1
        n = len(self.tokenized)
        # IDF по формуле BM25+: log((N - df + 0.5) / (df + 0.5) + 1).
        self.idf = {
            term: math.log((n - d + 0.5) / (d + 0.5) + 1.0) for term, d in df.items()
        }
        # tf на документ.
        self.tf: list[dict[str, int]] = []
        for toks in self.tokenized:
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            self.tf.append(tf)

    def score(self, query_tokens: list[str]) -> list[float]:
        scores = [0.0] * len(self.chunks)
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if not idf:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(term, 0)
                if not f:
                    continue
                denom = f + K1 * (1 - B + B * self.doc_len[i] / (self.avgdl or 1.0))
                scores[i] += idf * (f * (K1 + 1)) / denom
        return scores


def _doc_text(chunk: dict[str, Any]) -> str:
    # Ищем и по имени файла/разделу — названия продуктов критичны.
    return f"{chunk.get('file', '')} {chunk.get('section', '')} {chunk.get('text', '')}"


_INDEX: BM25Index | None = None


def _get_index() -> BM25Index:
    global _INDEX
    if _INDEX is None:
        _INDEX = BM25Index(kb_loader.load_corpus())
    return _INDEX


def build_index(chunks: list[dict[str, Any]]) -> BM25Index:
    """Построить и закэшировать индекс из готовых чанков (для тестов)."""
    global _INDEX
    _INDEX = BM25Index(chunks)
    return _INDEX


def reset_index() -> None:
    global _INDEX
    _INDEX = None


def retrieve(query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    """Найти top-k релевантных чанков для запроса.

    Returns:
        [{"id", "file", "section", "score", "content"}, ...] по убыванию score.
        Пустой список — нет чанков с положительным score (нет данных).
    """
    k = top_k if top_k is not None else _env_top_k()
    index = _get_index()
    if not index.chunks:
        return []

    tokens = tokenize(query)
    if not tokens:
        return []

    scores = index.score(tokens)
    ranked = sorted(
        range(len(index.chunks)),
        key=lambda i: scores[i],
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for i in ranked[:k]:
        if scores[i] <= 0:
            break
        c = index.chunks[i]
        out.append(
            {
                "id": c.get("id", f"chunk-{i}"),
                "file": c.get("file", ""),
                "section": c.get("section", ""),
                "score": round(scores[i], 4),
                "content": c.get("text", ""),
            }
        )
    return out
