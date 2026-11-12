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

# Кueсы отрицания перед запрещённым термином: «не могу предоставить
# прогноз» — не запрещённое утверждение, а честный отказ.
NEGATION_CUES = (
    "не могу", "не могу предоставить", "не располага", "не располаг",
    "не указан", "не указано", "не упомина", "не содерж",
    "отсутству", "нет данных", "не является", "не относится",
    "не позволяет", "не поддержива", "кроме", "без ",
)
NEGATION_WINDOW = 60  # символов перед попаданием forbidden-термина

COVERAGE_VERBS = (
    "покрыва", "хватает", "достаточно", "укладыва", "вписыва",
    "уложит", "потянет", "справится", "вмещает",
)
# Единицы/объекты, которые нельзя молча приравнивать (разные сущности).
COUNTABLE_UNITS = (
    "квартир", "прибор", "точек", "точка", "счетчик", "счётчик",
    "датчик", "станк", "абонент", "потребител", "здани",
)


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
    """Запрещённые утверждения. Отрицания («не могу предоставить
    прогноз») НЕ считаются попаданием — это отказ, а не утверждение."""
    a_raw = answer.lower()
    a = _norm(answer)
    hits = []
    for f in forbidden:
        fn = _norm(f)
        start = 0
        while True:
            idx = a.find(fn, start)
            if idx < 0:
                break
            start = idx + 1
            prefix = a_raw[max(0, idx - NEGATION_WINDOW):idx]
            if any(cue in prefix for cue in NEGATION_CUES):
                continue  # упоминание в отрицании — не утверждение
            hits.append(f)
            break
    return hits


def check_currency_invention(answer: str, context_text: str) -> list[str]:
    """Числа с валютой/тарифом, которых нет в контексте → выдуманная цена."""
    a = _norm(answer)
    ctx = _norm(context_text)
    money = re.findall(r"\d[\d\s.,]*\s*(?:руб\w*|₽)", a)
    invented = []
    for m in money:
        num = re.sub(r"\D", "", m)
        if num and num not in re.sub(r"\D", "", ctx):
            invented.append(m.strip())
    return invented


def check_unit_equivalence(answer: str, question: str) -> dict:
    """Подозрение на приравнивание разных единиц/объектов.

    Флаг, а не приговор: «300 квартир покрываются лимитом 500
    тепловых приборов» — разные сущности, нужен ручной разбор.
    """
    ans = _norm(answer)
    q = _norm(question)
    has_coverage_verb = any(v in ans for v in COVERAGE_VERBS)
    # В вопросе — счётный объект (квартиры/станки/...), в ответе —
    # счётный лимит из БЗ (приборы/точки) + глагол покрытия.
    q_units = {u for u in COUNTABLE_UNITS if u in q}
    a_units = {u for u in COUNTABLE_UNITS if u in ans}
    # Лимитные единицы БЗ — те, в которых заданы ограничения
    # (приборы/точки учёта). Если вопрос про «квартиры/станки», а
    # ответ покрывает их «лимитом приборов» — это подозрительное
    # приравнивание разных сущностей.
    kb_limit_units = {"прибор", "точек", "точка", "счетчик", "счётчик", "датчик"}
    q_is_kb_unit = bool(q_units & kb_limit_units)
    a_has_kb_unit = bool(a_units & kb_limit_units)
    suspect = (has_coverage_verb and bool(q_units)
               and a_has_kb_unit and not q_is_kb_unit)
    return {"suspect": suspect, "question_units": sorted(q_units),
            "answer_units": sorted(a_units), "has_coverage_verb": has_coverage_verb}


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


def verdict_v2(case: dict, answer: str, meta: dict,
               context_text: str = "") -> dict:
    """Оценка v2: метки correct/incomplete/unsupported/incorrect/
    needs_manual_review + флаги. Автоматика НЕ выносит экспертных
    приговоров — сомнительное помечается needs_manual_review."""
    facts = check_fact_coverage(answer, case.get("required_facts", []))
    forbidden_hits = check_forbidden(answer, case.get("forbidden", []))
    refusal = check_excessive_refusal(answer, bool(case.get("context_ids")))
    length = check_length(answer)
    last_reply = check_last_reply(answer, case.get("last_user_text"))
    unit_equiv = check_unit_equivalence(answer, case.get("question", ""))
    currency = check_currency_invention(answer, context_text) if context_text else []
    finish = meta.get("finish_reason")

    # incorrect — только детерминированные паттерны из кейса
    incorrect_hits = []
    for pat in case.get("incorrect_patterns", []):
        if re.search(pat, _norm(answer)):
            incorrect_hits.append(pat)

    # «Есть ли X?» → ответ «Нет…» при отсутствии данных в БЗ —
    # подозрительный вывод из неполных данных (см. c10). Флаг,
    # не приговор: «нет данных» — нормальный ответ, «нет» — нет.
    capability_denial = False
    q = _norm(case.get("question", ""))
    if re.match(r"^(есть ли|может ли|умеет ли|поддерживает ли|возможн)", q):
        first = _norm(answer.strip())[:40]
        if re.match(r"^нет\b|^не\b", first) and not re.search(
                r"нет данных|не указан|не подтвержд|отсутству|не располага|не упомина", first):
            capability_denial = True

    missing = facts["total"] - facts["covered"]
    empty = not answer.strip()
    truncated = finish == "length"

    if incorrect_hits:
        verdict = "incorrect"
    elif forbidden_hits or currency:
        verdict = "unsupported"
    elif empty or truncated or unit_equiv["suspect"] or capability_denial:
        verdict = "needs_manual_review"
    elif missing > 0 or refusal or last_reply.get("needs_review"):
        verdict = "incomplete" if missing > 0 else "needs_manual_review"
    else:
        verdict = "correct"

    review = bool(
        verdict in ("incomplete", "needs_manual_review")
        or unit_equiv["suspect"] or capability_denial
        or last_reply.get("needs_review")
        or missing > 0
    )
    return {
        "verdict": verdict,
        "coverage": facts,
        "missing_facts": missing,
        "forbidden_hits": forbidden_hits,
        "currency_invention": currency,
        "incorrect_hits": incorrect_hits,
        "unit_equiv_suspect": unit_equiv["suspect"],
        "capability_denial": capability_denial,
        "unit_equiv": unit_equiv,
        "excessive_refusal": refusal,
        "length": length,
        "last_reply": last_reply,
        "truncated": truncated,
        "empty": empty,
        "needs_manual_review": review,
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
