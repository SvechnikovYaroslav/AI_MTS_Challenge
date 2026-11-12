"""Минимальный клиент Groq OpenAI-compatible API (только stdlib).

БЕЗОПАСНОСТЬ:
- ключ читается ТОЛЬКО из env GROQ_API_KEY (или .env в этой папке,
  которая в .gitignore). Никаких ключей в коде/логах/отчётах.
- Сетевые вызовы происходят ТОЛЬКО при явном вызове chat()/smoke —
  импорт модуля ничего не отправляет.
- Лимит запросов на запуск + ограниченные повторы при 429/5xx.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "qwen/qwen3.8-27b"

# Фиксированные параметры первого эксперимента (как в Playground).
# Это НЕ обязательно параметры прокси МТС.
GEN_PARAMS = {
    "model": MODEL,
    "temperature": 0.6,
    "max_completion_tokens": 2048,
    "top_p": 0.95,
    "reasoning_effort": "default",
}

MAX_RETRIES = 2
RETRY_BACKOFF_S = 2.0


class BudgetExhausted(RuntimeError):
    """Исчерпан лимит запросов на запуск."""


def load_env_file(path: Path | None = None) -> None:
    """Подхватить GROQ_API_KEY из .env рядом с пакетом (не из Git)."""
    env_path = path or Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api_key() -> str:
    load_env_file()
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY не задан. Создайте research/qwen_eval/.env "
            "(он в .gitignore) или переменную окружения."
        )
    return key


class Budget:
    """Счётчик запросов с жёстким лимитом."""

    def __init__(self, max_requests: int = 45) -> None:
        self.max_requests = max_requests
        self.used = 0

    def spend(self) -> None:
        if self.used >= self.max_requests:
            raise BudgetExhausted(f"budget exhausted: {self.used}/{self.max_requests}")
        self.used += 1


def chat(messages: list[dict[str, str]], budget: Budget,
         params: dict | None = None) -> dict:
    """Один вызов /chat/completions. Возвращает сырой JSON ответа + meta.

    Никаких ретраев при 400/401 — только 429/5xx/сетевые ошибки,
    не более MAX_RETRIES повторов.
    """
    key = api_key()
    payload = dict(GEN_PARAMS)
    if params:
        payload.update(params)
    payload["messages"] = messages
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # Cloudflare перед api.groq.com блокирует дефолтный
        # Python-urllib UA (error 1010) — задаём свой.
        "User-Agent": "EnergyTool-EvalLab/1.0 (+https://github.com/SvechnikovYaroslav/AI_MTS_Challenge)",
    }

    last_err = ""
    for attempt in range(MAX_RETRIES + 1):
        budget.spend()
        t0 = time.perf_counter()
        req = urllib.request.Request(API_URL, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read() or b""
            last_err = f"HTTP {status}: {raw[:200]!r}"
            if status in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_S * (attempt + 1))
                continue
            raise RuntimeError(last_err) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = f"network: {exc}"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_S * (attempt + 1))
                continue
            raise RuntimeError(last_err) from exc

        latency_ms = int((time.perf_counter() - t0) * 1000)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid JSON (HTTP {status}): {raw[:200]!r}") from exc
        return {"status": status, "data": data, "latency_ms": latency_ms}
    raise RuntimeError(f"failed after retries: {last_err}")


def extract_answer(resp: dict) -> tuple[str, dict]:
    """Достать content + finish_reason + usage из ответа."""
    choice = (resp["data"].get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    meta = {
        "finish_reason": choice.get("finish_reason"),
        "usage": resp["data"].get("usage") or {},
        "latency_ms": resp["latency_ms"],
        "status": resp["status"],
        "reasoning_content": bool(message.get("reasoning_content")),
    }
    return content, meta
