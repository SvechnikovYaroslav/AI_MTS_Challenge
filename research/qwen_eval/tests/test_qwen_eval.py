"""Офлайн-тесты Groq Eval Lab — БЕЗ сети и БЕЗ API-ключа."""

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import cases  # noqa: E402
import evaluate  # noqa: E402
import groq_client  # noqa: E402
import prompts_eval  # noqa: E402
import synth_kb  # noqa: E402


def test_cases_valid():
    assert cases.validate_cases() == []
    assert len(cases.CASES) == 20


def test_synth_kb_no_mts_terms():
    """Синтетическая БЗ не должна содержать терминов МТС-продуктов."""
    forbidden = ("энерджитул", "mts", "аскуэ", "орэм", "магадан",
                 "энергосбыт", "smart metering")
    for c in synth_kb.CHUNKS:
        low = c["text"].lower()
        for f in forbidden:
            assert f not in low, f"{c['id']} contains {f}"


def test_prompt_modes_differ_only_in_answer_first():
    a = prompts_eval.SYSTEM_A
    b = prompts_eval.SYSTEM_B
    # B = A + answer-first блок; общий префикс идентичен
    assert b.startswith(a)
    assert "сначала" in b.lower() and "прямой ответ" in b.lower()


def test_prompt_has_no_mts_data():
    blob = prompts_eval.SYSTEM_A + prompts_eval.SYSTEM_B
    for term in ("мтс", "energytool", "энерджитул", "орэм", "аскуэ"):
        assert term not in blob.lower()


def test_fact_coverage_groups():
    ans = "Нужна проверка совместимости приборов протокола МЭК 62056-21."
    cov = evaluate.check_fact_coverage(
        ans, [["совместимост"], ["мэк", "62056", "протокол"]])
    assert cov["covered"] == 2 and cov["total"] == 2
    cov2 = evaluate.check_fact_coverage("Нет данных.", [["совместимост"]])
    assert cov2["covered"] == 0


def test_forbidden_and_refusal():
    assert evaluate.check_forbidden("Стоимость 5000 руб в месяц", ["руб"]) == ["руб"]
    assert evaluate.check_excessive_refusal(
        "Не могу ответить, нет данных в базе знаний.", True) is True
    assert evaluate.check_excessive_refusal(
        "Вот подробный ответ с фактами из базы знаний...", True) is False


def test_evaluate_case_c01():
    case = next(c for c in cases.CASES if c["case_id"] == "c01-vector-compat")
    good = "Сначала нужна проверка совместимости приборов — поддерживается протокол МЭК 62056-21."
    bad = "Подключайте, всё просто."
    ev_good = evaluate.evaluate_answer(case, good, {"finish_reason": "stop"})
    ev_bad = evaluate.evaluate_answer(case, bad, {"finish_reason": "stop"})
    assert ev_good["missing_facts"] == 0
    assert ev_bad["missing_facts"] > 0


def test_budget_exhausted():
    b = groq_client.Budget(max_requests=1)
    b.spend()
    with pytest.raises(groq_client.BudgetExhausted):
        b.spend()


def test_no_network_on_import():
    """Импорт модулей не должен требовать ключ или сеть."""
    import importlib
    import run_eval  # noqa: F401  (тяжёлый CLI-модуль тоже импортируется)
    for m in ("groq_client", "run_eval", "evaluate", "cases", "synth_kb", "prompts_eval"):
        importlib.reload(sys.modules[m])


def test_last_reply_check():
    case = next(c for c in cases.CASES if c["case_id"] == "c15-dialog-compat")
    ev = evaluate.check_last_reply("Приборы до 2005 года требуют ретрофита.",
                                   case["last_user_text"])
    assert ev["applicable"] and ev["keyword_hits"] > 0
    ev2 = evaluate.check_last_reply("Всё отлично, подключайте.", case["last_user_text"])
    assert ev2["needs_review"]
