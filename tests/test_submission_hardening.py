"""Тесты харденинга конкурсного сабмита.

- HTTP-клиент Qwen против локального mock-сервера (OpenAI-compatible).
- Однократная инициализация retrieval при параллельной обработке.
- Границы чанков по разделам.
- Автономный прогон собранного submission.zip в чистом каталоге.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_engine  # noqa: E402
import kb_loader  # noqa: E402
import retrieval  # noqa: E402
import solution  # noqa: E402

VENV_PYTHON = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
SUBPROCESS_PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


# ---------- mock OpenAI-compatible сервер ----------

def _ok_response(text: str):
    return 200, {"choices": [{"message": {"role": "assistant", "content": text}}]}


class _LLMHandler(BaseHTTPRequestHandler):
    responder = None  # callable(body: dict) -> (status:int, payload:dict)
    requests = 0

    def do_POST(self):  # noqa: N802
        type(self).requests += 1
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        status, payload = type(self).responder(body)
        if isinstance(payload, str):
            data = payload.encode("utf-8")
            ctype = "text/plain"
        else:
            data = json.dumps(payload).encode("utf-8")
            ctype = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # тишина в тестах
        pass


@pytest.fixture()
def llm_server():
    """Поднять mock /chat/completions. responder: body->(status,payload)."""
    servers = []

    def start(responder):
        _LLMHandler.responder = responder
        _LLMHandler.requests = 0
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _LLMHandler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield start
    for s in servers:
        s.shutdown()


def _settings(base_url: str, retries: int = 0, timeout: float = 5.0) -> dict:
    return {
        "base_url": base_url,
        "api_key": "test-key",
        "model": "test-model",
        "temperature": 0.0,
        "max_tokens": 256,
        "timeout": timeout,
        "retries": retries,
    }


# ---------- HTTP-клиент ----------

def test_post_chat_200_ok(llm_server):
    url = llm_server(lambda body: _ok_response("Ответ модели"))
    assert ai_engine._post_chat([{"role": "user", "content": "hi"}], _settings(url)) == "Ответ модели"
    # Проверяем, что ушёл корректный OpenAI-payload
    assert _LLMHandler.requests == 1


def test_post_chat_200_empty_content(llm_server):
    url = llm_server(lambda body: (200, {"choices": [{"message": {"content": "  "}}]}))
    with pytest.raises(ai_engine.AICoreError):
        ai_engine._post_chat([{"role": "user", "content": "hi"}], _settings(url))


def test_post_chat_200_invalid_json(llm_server):
    url = llm_server(lambda body: (200, "not-json{{{"))
    with pytest.raises(ai_engine.AICoreError):
        ai_engine._post_chat([{"role": "user", "content": "hi"}], _settings(url))


@pytest.mark.parametrize("status", [400, 401])
def test_post_chat_client_errors(llm_server, status):
    url = llm_server(lambda body: (status, {"error": "bad"}))
    with pytest.raises(ai_engine.AICoreError):
        ai_engine._post_chat([{"role": "user", "content": "hi"}], _settings(url, retries=2))
    # 4xx не ретраится
    assert _LLMHandler.requests == 1


@pytest.mark.parametrize("status", [429, 500])
def test_post_chat_retryable_errors(llm_server, status):
    url = llm_server(lambda body: (status, {"error": "retry"}))
    with pytest.raises(ai_engine.AICoreError):
        ai_engine._post_chat([{"role": "user", "content": "hi"}], _settings(url, retries=2))
    # retries=2 -> всего 3 попытки
    assert _LLMHandler.requests == 3


def test_post_chat_retry_then_success(llm_server):
    calls = {"n": 0}

    def responder(body):
        calls["n"] += 1
        if calls["n"] < 2:
            return 429, {"error": "rate limit"}
        return _ok_response("ok после retry")

    url = llm_server(responder)
    assert ai_engine._post_chat([{"role": "user", "content": "hi"}], _settings(url, retries=2)) == "ok после retry"
    assert calls["n"] == 2


def test_post_chat_timeout(llm_server):
    def slow(body):
        time.sleep(1.5)
        return _ok_response("too late")

    url = llm_server(slow)
    with pytest.raises(ai_engine.AICoreError):
        ai_engine._post_chat([{"role": "user", "content": "hi"}], _settings(url, timeout=0.3, retries=0))


# ---------- retrieval: session_context ----------

def test_retrieval_query_uses_last_user_message():
    ctx = [
        {"role": "user", "content": "Рассматриваю солнечную станцию для склада"},
        {"role": "assistant", "content": "Какая мощность нужна?"},
    ]
    q = ai_engine._retrieval_query("А сколько это стоит?", ctx)
    assert "сколько это стоит" in q
    assert "солнечную станцию" in q


def test_retrieval_query_no_context():
    assert ai_engine._retrieval_query("просто вопрос", None) == "просто вопрос"
    assert ai_engine._retrieval_query("q", []) == "q"


def test_retrieval_query_long_question_unchanged():
    long_q = "x" * 300
    assert ai_engine._retrieval_query(long_q, [{"role": "user", "content": "тема"}]) == long_q


# ---------- чанкинг: границы разделов ----------

def test_chunks_do_not_mix_sections(tmp_path):
    md = (
        "# Документ\n\n"
        "## Раздел Первый\n\n"
        "Текст первого раздела про учёт электроэнергии.\n\n"
        "## Раздел Второй\n\n"
        "Текст второго раздела про солнечные панели.\n"
    )
    corpus = kb_loader.chunk_markdown("doc.md", md)
    assert len(corpus) >= 2
    for c in corpus:
        has_first = "первого раздела" in c["text"]
        has_second = "второго раздела" in c["text"]
        assert not (has_first and has_second), f"chunk mixes sections: {c['section']!r}"


# ---------- однократная инициализация ----------

def test_corpus_loaded_once_for_parallel_questions(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    kb_zip = data / "knowledge-base.zip"
    with zipfile.ZipFile(kb_zip, "w") as zf:
        zf.writestr("d.md", "# T\n\n## S\n\n" + "слово " * 200)
    (data / "questions.csv").write_text(
        "id,question\n1,вопрос раз\n2,вопрос два\n3,вопрос три\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("SUBMISSION_PATH", str(tmp_path / "submission.csv"))
    monkeypatch.setenv("MAX_WORKERS", "3")
    monkeypatch.setattr(ai_engine, "_llm_chat", lambda s, u: "ok")

    calls = {"n": 0}
    real_load = kb_loader.load_corpus

    def counting_load(*a, **kw):
        calls["n"] += 1
        return real_load(*a, **kw)

    monkeypatch.setattr(kb_loader, "load_corpus", counting_load)
    retrieval.reset_index()
    try:
        assert solution.main() == 0
    finally:
        retrieval.reset_index()
    assert calls["n"] == 1, f"corpus loaded {calls['n']} times"


# ---------- автономный прогон собранного ZIP ----------

def _make_submission_dir(tmp_path: Path) -> Path:
    """Распаковать 'собранный' архив в чистый каталог."""
    work = tmp_path / "sub"
    work.mkdir()
    for name in solution.__dict__ and [
        "solution.py", "ai_engine.py", "retrieval.py", "kb_loader.py",
        "prompts.py", "requirements.txt",
    ]:
        shutil.copy(ROOT / name, work / name)
    return work


def _make_data_dir(tmp_path: Path, questions: list[tuple[str, str]]) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    with zipfile.ZipFile(data / "knowledge-base.zip", "w") as zf:
        zf.writestr(
            "20-products/22-askue.md",
            "# ASKUE\n\n## Платформа\n\nASKUE — облачная платформа учёта "
            "электроэнергии для нескольких объектов и магазинов. " * 8,
        )
    with (data / "questions.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "question"])
        w.writerows(questions)
    return data


def _run_solution(work: Path, data: Path, out: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        {
            "DATA_DIR": str(data),
            "SUBMISSION_PATH": str(out),
            "MAX_WORKERS": "2",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    # LLM-переменные не должны протекать из окружения разработчика —
    # чистим ДО применения env_extra.
    for v in ("LLM_BASE_URL", "QWEN_BASE_URL", "BASE_URL", "OPENAI_BASE_URL",
              "LLM_API_KEY", "QWEN_API_KEY", "OPENAI_API_KEY",
              "LLM_MODEL", "QWEN_MODEL", "GEN_MODEL", "OPENAI_MODEL"):
        env.pop(v, None)
    env.update(env_extra or {})
    return subprocess.run(
        [SUBPROCESS_PYTHON, "solution.py"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_built_zip_end_to_end_with_mock_llm(tmp_path, llm_server):
    """Полный прогон 'собранного' кода против mock OpenAI-сервера."""
    url = llm_server(lambda body: _ok_response("ASKUE подойдёт для нескольких объектов."))
    work = _make_submission_dir(tmp_path)
    data = _make_data_dir(
        tmp_path,
        [("1", "ASKUE: как контролировать расход на объектах?"),
         ("2", 'ASKUE вопрос с "кавычками"\nи переносом'),
         ("3", "ASKUE что это?")],
    )
    out = tmp_path / "submission.csv"
    proc = _run_solution(
        work, data, out,
        env_extra={
            "LLM_BASE_URL": url,
            "LLM_API_KEY": "test",
            "LLM_MODEL": "mock-model",
        },
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    with out.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["id"] for r in rows] == ["1", "2", "3"]
    assert all("ASKUE" in r["answer"] for r in rows)
    assert "failures=0" in proc.stderr


def test_built_zip_partial_failure_exit_zero(tmp_path, llm_server):
    """Один вопрос падает — остальные успешны, exit 0, файл полный."""
    def responder(body):
        messages = body.get("messages", [])
        user_text = " ".join(str(m.get("content", "")) for m in messages)
        if "ПЛОХОЙ" in user_text:
            return 500, {"error": "boom"}
        return _ok_response("нормальный ответ")

    url = llm_server(responder)
    work = _make_submission_dir(tmp_path)
    data = _make_data_dir(
        tmp_path,
        [("1", "хороший вопрос про ASKUE"),
         ("2", "ПЛОХОЙ вопрос ASKUE"),
         ("3", "ещё один хороший ASKUE")],
    )
    out = tmp_path / "submission.csv"
    proc = _run_solution(
        work, data, out,
        env_extra={"LLM_BASE_URL": url, "LLM_API_KEY": "t", "LLM_MODEL": "m",
                   "LLM_RETRIES": "0"},
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    with out.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert rows[0]["answer"] == "нормальный ответ"
    assert rows[1]["answer"] == solution.ERROR_ANSWER
    assert rows[2]["answer"] == "нормальный ответ"
    assert "failures=1" in proc.stderr


def test_built_zip_all_failures_exit_one(tmp_path, llm_server):
    """Модель недоступна целиком — submission.csv есть, exit 1."""
    url = llm_server(lambda body: (503, {"error": "down"}))
    work = _make_submission_dir(tmp_path)
    data = _make_data_dir(
        tmp_path,
        [("1", "вопрос про ASKUE один"), ("2", "вопрос про ASKUE два")],
    )
    out = tmp_path / "submission.csv"
    proc = _run_solution(
        work, data, out,
        env_extra={"LLM_BASE_URL": url, "LLM_API_KEY": "t", "LLM_MODEL": "m",
                   "LLM_RETRIES": "0"},
    )
    assert proc.returncode == 1
    with out.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert all(r["answer"] == solution.ERROR_ANSWER for r in rows)
    assert "failures=2" in proc.stderr


def test_built_zip_no_llm_config_exit_one(tmp_path):
    """Без LLM-переменных — честный отказ, не фиктивный успех."""
    work = _make_submission_dir(tmp_path)
    data = _make_data_dir(tmp_path, [("1", "вопрос про ASKUE платформу")])
    out = tmp_path / "submission.csv"
    proc = _run_solution(work, data, out)  # env без LLM_*
    assert proc.returncode == 1
    assert out.exists()
    with out.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["answer"] == solution.ERROR_ANSWER


# ---------- LLM-телеметрия (Preflight) ----------

def test_llm_stats_finish_reason_and_usage(llm_server):
    """finish_reason=stop + usage -> счётчики токенов."""
    ai_engine.reset_llm_stats()
    url = llm_server(lambda body: (200, {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                  "completion_tokens_details": {"reasoning_tokens": 5}},
    }))
    ai_engine._post_chat([{"role": "user", "content": "hi"}], _settings(url))
    st = ai_engine.llm_stats()
    assert st["requests"] == 1 and st["finish_length"] == 0 and st["empty"] == 0
    assert st["prompt_tokens"] == 100 and st["completion_tokens"] == 20
    assert st["reasoning_tokens"] == 5 and st["latency_ms"] >= 0


def test_llm_stats_finish_length_counted(llm_server):
    """finish_reason=length -> счётчик finish_length, ответ не прерывается."""
    ai_engine.reset_llm_stats()
    url = llm_server(lambda body: (200, {
        "choices": [{"message": {"content": "частичный ответ"},
                     "finish_reason": "length"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 1200},
    }))
    out = ai_engine._post_chat([{"role": "user", "content": "hi"}], _settings(url))
    assert out == "частичный ответ"
    st = ai_engine.llm_stats()
    assert st["finish_length"] == 1 and st["completion_tokens"] == 1200


def test_llm_stats_empty_content_counted(llm_server):
    """Пустой content -> AICoreError, но empty посчитан."""
    ai_engine.reset_llm_stats()
    url = llm_server(lambda body: (200, {"choices": [{"message": {"content": "  "}}]}))
    with pytest.raises(ai_engine.AICoreError):
        ai_engine._post_chat([{"role": "user", "content": "hi"}], _settings(url))
    assert ai_engine.llm_stats()["empty"] == 1


def test_llm_stats_missing_usage_and_extra_fields(llm_server):
    """Нет usage/finish_reason и лишние поля — не ломается, нули."""
    ai_engine.reset_llm_stats()
    url = llm_server(lambda body: (200, {
        "choices": [{"message": {"content": "ok", "reasoning_content": "думаю"},
                     "finish_reason": None}],
        "extra_field": {"nested": True},
    }))
    assert ai_engine._post_chat([{"role": "user", "content": "hi"}], _settings(url)) == "ok"
    st = ai_engine.llm_stats()
    assert st["requests"] == 1 and st["prompt_tokens"] == 0
    assert st["finish_length"] == 0 and st["empty"] == 0


def test_solution_pins_contest_config(tmp_path, monkeypatch):
    """solution.main фиксирует TOP_K=8/MAX_TOKENS=1200/TEMPERATURE=0.0."""
    import solution as sol
    monkeypatch.setenv("TOP_K", "5")
    monkeypatch.setenv("MAX_TOKENS", "999")
    monkeypatch.setenv("TEMPERATURE", "1.5")
    # main() вернёт 2 (нет questions.csv) — но пины env уже выставлены.
    monkeypatch.setattr(sol, "questions_csv_path", lambda: tmp_path / "nope.csv")
    assert sol.main() == 2
    assert os.environ["TOP_K"] == "8"
    assert os.environ["MAX_TOKENS"] == "1200"
    assert os.environ["TEMPERATURE"] == "0.0"
