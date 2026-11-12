"""AI Core — единая точка входа для backend и solution.py.

Пайплайн: retrieval (BM25 по чанкам БЗ) -> prompts -> LLM
(OpenAI-совместимый /chat/completions, по умолчанию Qwen через
прокси организаторов).

Конфигурация — только через переменные окружения (см. _settings):
  LLM_BASE_URL / BASE_URL / OPENAI_BASE_URL
  LLM_API_KEY  / OPENAI_API_KEY
  LLM_MODEL   / GEN_MODEL / OPENAI_MODEL   (без дефолтной «настоящей» модели)
  TEMPERATURE, MAX_TOKENS, MAX_WORKERS, TOP_K, LLM_TIMEOUT, LLM_RETRIES

Модель не хардкодится: без LLM_MODEL используется имя из окружения;
если прокси недоступен — answer_question честно поднимает AICoreError,
а не возвращает фиктивный ответ.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import httpx

import kb_loader
import prompts
import retrieval

# Флаг готовности: пайплайн реализован. Сборка сабмита разрешена.
AI_CORE_READY: bool = True

MAX_ANSWER_CHARS = 10_000  # лимит регламента на один ответ


class AICoreError(RuntimeError):
    """Инфраструктурная ошибка AI Core (сеть, API, пустой ответ модели)."""


# Минимальная техническая телеметрия LLM (Preflight): только агрегированные
# счётчики — без ключей, текстов вопросов, БЗ и reasoning_content.
# Нужна для диагностики finish_reason=length / usage на прокси МТС.
_LLM_STATS_LOCK = threading.Lock()
_LLM_STATS = {
    "requests": 0,          # успешных HTTP-ответов 200 с валидным JSON
    "empty": 0,             # пустой content после 200
    "finish_length": 0,     # ответов с finish_reason="length"
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "reasoning_tokens": 0,  # когда прокси возвращает details
    "latency_ms": 0,
}


def llm_stats() -> dict[str, int]:
    """Копия агрегированных счётчиков LLM для диагностики."""
    with _LLM_STATS_LOCK:
        return dict(_LLM_STATS)


def reset_llm_stats() -> None:
    """Сброс счётчиков (для тестов)."""
    with _LLM_STATS_LOCK:
        for k in _LLM_STATS:
            _LLM_STATS[k] = 0


def _record_llm_stats(data: dict[str, Any], latency_ms: int, empty: bool) -> None:
    usage = data.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    reasoning = details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0
    finish = ""
    try:
        finish = str(data["choices"][0].get("finish_reason") or "")
    except (KeyError, IndexError, TypeError):
        pass
    with _LLM_STATS_LOCK:
        _LLM_STATS["requests"] += 1
        _LLM_STATS["latency_ms"] += latency_ms
        if empty:
            _LLM_STATS["empty"] += 1
        if finish == "length":
            _LLM_STATS["finish_length"] += 1
        _LLM_STATS["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        _LLM_STATS["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        _LLM_STATS["reasoning_tokens"] += int(reasoning or 0)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    # Защита от подстановки "NAME=value" вместо значения (как в примере МТС).
    if not value or value == name or value.startswith(name + "="):
        return default
    return value


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(_env(name) or default)))
    except ValueError:
        return default


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(_env(name) or default)))
    except ValueError:
        return default


def _settings() -> dict[str, Any]:
    base_url = (
        _env("LLM_BASE_URL")
        or _env("QWEN_BASE_URL")
        or _env("BASE_URL")
        or _env("OPENAI_BASE_URL")
    ).rstrip("/")
    api_key = _env("LLM_API_KEY") or _env("QWEN_API_KEY") or _env("OPENAI_API_KEY")
    model = _env("LLM_MODEL") or _env("QWEN_MODEL") or _env("GEN_MODEL") or _env("OPENAI_MODEL")
    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "temperature": _env_float("TEMPERATURE", 0.0, 0.0, 2.0),
        "max_tokens": _env_int("MAX_TOKENS", 1200, 128, 8192),
        "timeout": _env_float("LLM_TIMEOUT", 60.0, 5.0, 600.0),
        "retries": _env_int("LLM_RETRIES", 2, 0, 5),
    }


def _post_chat(messages: list[dict[str, str]], settings: dict[str, Any]) -> str:
    """POST /chat/completions к OpenAI-совместимому endpoint.

    Повторные попытки при 429, 5xx и сетевых ошибках/таймаутах.
    Остальные HTTP-ошибки и невалидные ответы — сразу AICoreError.
    """
    if not settings["base_url"] or not settings["api_key"] or not settings["model"]:
        raise AICoreError(
            "LLM не настроен: задайте LLM_BASE_URL, LLM_API_KEY и LLM_MODEL "
            "(или OPENAI_* / GEN_MODEL)."
        )

    payload = {
        "model": settings["model"],
        "temperature": settings["temperature"],
        "max_tokens": settings["max_tokens"],
        "messages": messages,
    }
    headers = {"Authorization": f"Bearer {settings['api_key']}"}
    url = settings["base_url"] + "/chat/completions"

    last_exc: Exception | None = None
    for attempt in range(settings["retries"] + 1):
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=settings["timeout"]) as client:
                resp = client.post(url, headers=headers, json=payload)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise _RetryableHTTP(resp.status_code)
            if resp.status_code >= 400:
                raise AICoreError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")
            try:
                data = resp.json()
            except ValueError as exc:
                raise AICoreError(f"LLM вернул невалидный JSON: {exc}") from exc
            content = data["choices"][0]["message"].get("content") or ""
            empty = not isinstance(content, str) or not content.strip()
            _record_llm_stats(data, int((time.perf_counter() - t0) * 1000), empty)
            if empty:
                raise AICoreError("LLM вернула пустой ответ")
            return content.strip()
        except _RetryableHTTP as exc:
            last_exc = exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
        if attempt < settings["retries"]:
            time.sleep(0.5 * (attempt + 1))
    raise AICoreError(f"LLM недоступен после {settings['retries'] + 1} попыток: {last_exc}")


class _RetryableHTTP(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"retryable HTTP {status}")
        self.status = status


def _llm_chat(system: str, user: str) -> str:
    """Единая точка обращения к модели. Тесты подменяют эту функцию."""
    return _post_chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        _settings(),
    )


_LEAD_KEYWORDS = (
    "купить", "цена", "стоимость", "тариф", "подключить", "подключение",
    "внедрить", "внедрение", "заказать", "заявк", "менеджер", "консультац",
    "связаться", "позвоните", "коммерческое предложение", "договор",
)


def _suggest_lead(question: str, answer: str) -> bool:
    """Эвристика: есть ли смысл предложить живую консультацию."""
    q = question.lower()
    if any(k in q for k in _LEAD_KEYWORDS):
        return True
    a = answer.lower()
    return "специалист" in a or "консультац" in a


def _clean_answer(text: str) -> str:
    """Нормализация ответа под контракт submission.csv."""
    # Схлопнуть 3+ пустых строк, обрезать до лимита по границе слова.
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if ln.strip():
            blank = 0
            out.append(ln)
        else:
            blank += 1
            if blank < 2:
                out.append("")
    answer = "\n".join(out).strip()
    if len(answer) > MAX_ANSWER_CHARS:
        answer = answer[: MAX_ANSWER_CHARS - 1].rsplit(" ", 1)[0] + "…"
    return answer


def _retrieval_query(question: str, session_context: list[dict[str, Any]] | None) -> str:
    """Поисковый запрос для BM25.

    - Конкурсные тесты (session_context=None) используют вопрос как есть —
      включая историю, уже встроенную в текст вопроса.
    - Follow-up в диалоге («А сколько это стоит?») без темы бесполезен:
      добавляем ПРЕДЫДУЩЕЕ user-сообщение из контекста (до 400 символов),
      чтобы retrieval нашёл фрагменты нужного продукта.
    - Длинную историю целиком в BM25 не отправляем — только последнее
      сообщение клиента, это сохраняет сигнал без шума.
    """
    q = question.strip()
    if not session_context or len(q) > 200:
        return q
    prev_users = [
        " ".join(str(m.get("content") or "").split())
        for m in session_context
        if m.get("role") == "user" and str(m.get("content") or "").strip()
    ]
    if not prev_users:
        return q
    prev = prev_users[-1][:400]
    return f"{q} {prev}"


def answer_question(
    question: str,
    session_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ответить на вопрос пользователя через RAG + LLM.

    Args:
        question: текст вопроса/проблемы (может содержать историю диалога
            внутри текста — обрабатывается как есть).
        session_context: опциональная история [{"role", "content"}, ...]
            текущего клиента. Не путать с независимыми тестами solution.py —
            там всегда None.

    Returns:
        {"answer": str, "sources": [{"file","chunk_id","score"}, ...],
         "suggest_lead": bool}

    Raises:
        AICoreError: инфраструктурный сбой (нет БЗ, LLM недоступна и т.п.).
    """
    question = (question or "").strip()
    if not question:
        raise AICoreError("Пустой вопрос")

    chunks = retrieval.retrieve(_retrieval_query(question, session_context))
    sources = [
        {
            "file": c.get("file", ""),
            "chunk_id": c.get("id", ""),
            "score": c.get("score"),
        }
        for c in chunks
    ]

    # Явный путь без LLM, когда база ничего не нашла: не тратим токены
    # и не даём модели выдумывать факты.
    if not chunks:
        answer = (
            "В доступной базе знаний МТС EnergyTool не нашлось подтверждённых "
            "материалов по этому вопросу, поэтому дать точный ответ не могу. "
            "Опишите задачу чуть подробнее (продукт, объект, вводные) — "
            "или обсудите её напрямую со специалистом."
        )
        return {
            "answer": answer,
            "sources": [],
            "suggest_lead": _suggest_lead(question, answer),
        }

    user_prompt = prompts.build_user_prompt(question, chunks, session_context)
    raw = _llm_chat(prompts.system_prompt(), user_prompt)
    answer = _clean_answer(raw)
    if not answer:
        raise AICoreError("LLM вернула пустой ответ после очистки")

    return {
        "answer": answer,
        "sources": sources,
        "suggest_lead": _suggest_lead(question, answer),
    }
