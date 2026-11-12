"""Офлайн-тесты Groq Eval Lab — БЕЗ сети и БЕЗ API-ключа."""

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import cases  # noqa: E402
import cases_h5  # noqa: E402
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


def test_forbidden_negation_aware():
    # «не могу предоставить прогноз» — отказ, не запрещённое утверждение
    hits = evaluate.check_forbidden(
        "Я не могу предоставить прогноз погоды.", ["прогноз"])
    assert hits == []
    # а прямое утверждение — запрещено
    hits2 = evaluate.check_forbidden("Прогноз: солнечно, +20 градусов.", ["прогноз"])
    assert hits2 == ["прогноз"]


def test_unit_equivalence_flags_apartments():
    ans = ("Подходит: лимит 500 тепловых приборов покрывает "
           "ваши 300 квартир.")
    q = "Нам нужен учёт для котельной на 300 квартир."
    r = evaluate.check_unit_equivalence(ans, q)
    assert r["suspect"] is True
    # вопрос про приборы — не флаг
    r2 = evaluate.check_unit_equivalence(
        "Лимит 500 приборов покрывает ваши 300 приборов.",
        "У нас 300 приборов.")
    assert r2["suspect"] is False


def test_capability_denial_flag():
    case = next(c for c in cases.CASES if c["case_id"] == "c10-vector-ai")
    bad = "Нет, Вектор-А не предсказывает аварии."
    v = evaluate.verdict_v2(case, bad, {"finish_reason": "stop"}, "ctx")
    assert v["capability_denial"] is True
    assert v["verdict"] == "needs_manual_review"
    good = "В базе знаний нет данных о прогнозировании аварий."
    v2 = evaluate.verdict_v2(case, good, {"finish_reason": "stop"}, "ctx")
    assert v2["capability_denial"] is False


def test_h5_cases_valid():
    assert cases_h5.validate_h5() == []
    assert len(cases_h5.H5_CASES) == 8


def test_h5_prompt_is_a_plus_rule():
    assert prompts_eval.SYSTEM_H5.startswith(prompts_eval.SYSTEM_A)
    assert "не приравнивай" in prompts_eval.SYSTEM_H5.lower()


def test_verdict_v2_labels():
    case = cases.CASES[0]
    v = evaluate.verdict_v2(case, "Сначала проверка совместимости, протокол МЭК 62056-21.",
                            {"finish_reason": "stop"}, "ctx")
    assert v["verdict"] == "correct"


def test_last_reply_check():
    case = next(c for c in cases.CASES if c["case_id"] == "c15-dialog-compat")
    ev = evaluate.check_last_reply("Приборы до 2005 года требуют ретрофита.",
                                   case["last_user_text"])
    assert ev["applicable"] and ev["keyword_hits"] > 0
    ev2 = evaluate.check_last_reply("Всё отлично, подключайте.", case["last_user_text"])
    assert ev2["needs_review"]
