"""Эвристическая оценка ответов Groq Eval Lab.

ВАЖНО: это ЧЕРНОВЫЕ эвристики для сортировки и отбора кейсов на ручную
проверку — НЕ экспертная оценка и НЕ официальный score МТС.
Спорные результаты помечаются needs_manual_review.
"""

from __future__ import annotations

import re
from typing import Any

REFUSAL_MARKERS = (
    "не могу", "не могу ответить", "нет данных", "не располагаю",
    "не указан", "не указано", "не найден", "не подтвержд",
    "вне моей компетенции", "не относится к моей", "обратитесь к специалисту",
    "уточните", "уточняющий вопрос",
)

OVERCLAIM_PATTERNS = ("руб", "₽", "гарантирую", "100%", "точно скажу")


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")


def check_fact_coverage(answer: str, required_facts: list[list[str]]) -> dict:
    """Каждая группа — альтернатива: достаточно одной подстроки."""
    a = _norm(answer)
    groups = []
    for i, alts in enumerate(required_facts):
        hit = any(_norm(alt) in a for alt in alts)
        groups.append({"group": i, "hit": hit, "alts": alts})
    return {"groups": groups,
            "covered": sum(1 for g in groups if g["hit"]),
            "total": len(groups)}


def check_forbidden(answer: str, forbidden: list[str]) -> list[str]:
    a = _norm(answer)
    return [f for f in forbidden if _norm(f) in a]


def check_excessive_refusal(answer: str, has_context: bool) -> bool:
    """Отказ при наличии релевантного контекста — подозрителен."""
    if not has_context:
        return False
    a = _norm(answer)
    refusal_hits = sum(1 for m in REFUSAL_MARKERS if m in a)
    # Короткий чистый отказ без фактов
    return refusal_hits >= 2 and len(a.split()) < 40


def check_length(answer: str, soft_words: int = 150, hard_words: int = 300) -> dict:
    n = len(answer.split())
    return {"words": n, "over_soft": n > soft_words, "over_hard": n > hard_words}


def check_last_reply(answer: str, last_user_text: str | None) -> dict:
    """Грубая проверка: ответ содержит ключевые слова последней реплики.

    Не экспертная оценка — только флаг для ручной проверки.
    """
    if not last_user_text:
        return {"applicable": False}
    words = [w for w in re.findall(r"[а-яёa-z0-9]{4,}", _norm(last_user_text))]
    a = _norm(answer)
    hits = sum(1 for w in set(words) if w in a)
    return {"applicable": True, "keyword_hits": hits,
            "needs_review": hits == 0}


def evaluate_answer(case: dict, answer: str, meta: dict) -> dict:
    """Полный набор эвристик для одного ответа."""
    facts = check_fact_coverage(answer, case.get("required_facts", []))
    forbidden_hits = check_forbidden(answer, case.get("forbidden", []))
    refusal = check_excessive_refusal(answer, bool(case.get("context_ids")))
    length = check_length(answer)
    last_reply = check_last_reply(answer, case.get("last_user_text"))
    finish = meta.get("finish_reason")
    return {
        "coverage": facts,
        "missing_facts": facts["total"] - facts["covered"],
        "forbidden_hits": forbidden_hits,
        "excessive_refusal": refusal,
        "length": length,
        "last_reply": last_reply,
        "truncated": finish == "length",
        "empty": not answer.strip(),
        "needs_manual_review": bool(
            facts["total"] - facts["covered"] > 0
            or forbidden_hits or refusal or finish == "length"
            or (last_reply.get("needs_review"))
        ),
        "finish_reason": finish,
        "usage": meta.get("usage") or {},
        "latency_ms": meta.get("latency_ms"),
    }


def aggregate(results: list[dict]) -> dict:
    """Агрегаты по прогону (честные счётчики, без «оценок качества»)."""
    n = len(results)
    if not n:
        return {}
    return {
        "n": n,
        "coverage_full": sum(1 for r in results if r["coverage"]["covered"] == r["coverage"]["total"]),
        "missing_facts_total": sum(r["missing_facts"] for r in results),
        "forbidden_cases": sum(1 for r in results if r["forbidden_hits"]),
        "excessive_refusals": sum(1 for r in results if r["excessive_refusal"]),
        "truncated": sum(1 for r in results if r["truncated"]),
        "empty": sum(1 for r in results if r["empty"]),
        "needs_manual_review": sum(1 for r in results if r["needs_manual_review"]),
        "avg_words": round(sum(r["length"]["words"] for r in results) / n, 1),
        "over_soft": sum(1 for r in results if r["length"]["over_soft"]),
        "total_prompt_tokens": sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in results),
        "total_completion_tokens": sum((r.get("usage") or {}).get("completion_tokens", 0) for r in results),
    }
