"""Тесты AI Core baseline: kb_loader, retrieval (BM25), ai_engine, solution.

Все тесты работают на синтетическом корпусе — реальная база знаний
организаторов в тесты и Git не попадает.
"""

from __future__ import annotations

import csv
import io
import os
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_engine  # noqa: E402
import kb_loader  # noqa: E402
import retrieval  # noqa: E402
import solution  # noqa: E402


# ---------- синтетический корпус ----------

KB_MD = """# Учёт электроэнергии

## Облачная платформа ASKUE

ASKUE — облачная платформа учёта электроэнергии МТС. Приборы учёта
передают показания на платформу, клиент видит потребление и отчёты
в веб-кабинете. Подходит сетевым компаниям и предприятиям с несколькими
объектами. Монтаж и настройка выполняются под ключ.

## Цены

Точную стоимость рассчитывает специалист после обследования объекта.
Публичного прайса на платформу нет.
"""

KB_MD2 = """# Солнечная генерация

## Сетевая солнечная станция

Сетевая станция работает только при наличии внешней сети: при отключении
электроснабжения она не питает объект. Для автономной работы нужны
аккумуляторы — это уже гибридная станция.

## Выбор мощности

Мощность подбирают по годовому потреблению и профилю нагрузки.
"""


def make_kb_zip(path: Path, files: dict[str, str] | None = None) -> Path:
    files = files or {"20-products/22-askue.md": KB_MD, "20-products/23-solar.md": KB_MD2}
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return path


@pytest.fixture()
def kb_dir(tmp_path, monkeypatch):
    """DATA_DIR с questions.csv и knowledge-base.zip."""
    data = tmp_path / "data"
    data.mkdir()
    make_kb_zip(data / "knowledge-base.zip")
    monkeypatch.setenv("DATA_DIR", str(data))
    retrieval.reset_index()
    yield data
    retrieval.reset_index()


# ---------- kb_loader ----------

def test_kb_loader_reads_markdown_zip(kb_dir):
    corpus = kb_loader.load_corpus(kb_dir / "knowledge-base.zip")
    assert corpus
    for c in corpus:
        assert c["id"].startswith(c["file"])
        assert c["file"].endswith(".md")
        assert c["text"].strip()
        assert "section" in c


def test_kb_loader_chunking_metadata(kb_dir):
    corpus = kb_loader.load_corpus(kb_dir / "knowledge-base.zip")
    askue = [c for c in corpus if "askue" in c["file"]]
    solar = [c for c in corpus if "solar" in c["file"]]
    assert askue and solar
    # Разные документы не смешиваются в одном чанке.
    for c in corpus:
        assert c["file"] in ("20-products/22-askue.md", "20-products/23-solar.md")
    # Секции сохранены.
    sections = {c["section"] for c in corpus}
    assert any("ASKUE" in s or "платформа" in s.lower() for s in sections)
    # ID стабильны и уникальны.
    ids = [c["id"] for c in corpus]
    assert len(ids) == len(set(ids))


def test_kb_loader_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "empty"))
    # Нет zip и нет локального Knowledge-base -> FileNotFoundError
    # (find_kb_path проверяет и корень репозитория — там каталог есть,
    #  поэтому тестируем только явный путь)
    with pytest.raises((FileNotFoundError, ValueError)):
        kb_loader.load_corpus(tmp_path / "nonexistent.zip")


# ---------- retrieval ----------

def test_retrieval_finds_relevant_chunk(kb_dir):
    index = retrieval.build_index(kb_loader.load_corpus(kb_dir / "knowledge-base.zip"))
    hits = retrieval.retrieve("Как контролировать расход электроэнергии на нескольких объектах?")
    assert hits
    assert hits[0]["file"].endswith("askue.md")
    assert hits[0]["score"] > 0
    assert hits[0]["content"].strip()
    # Формат ответа
    assert set(hits[0]) >= {"id", "file", "section", "score", "content"}


def test_retrieval_no_match_returns_empty(kb_dir):
    retrieval.build_index(kb_loader.load_corpus(kb_dir / "knowledge-base.zip"))
    # Запрос из слов, которых нет в корпусе вообще.
    hits = retrieval.retrieve("квантовая запутанность блокчейн")
    assert hits == []


def test_retrieval_product_names(kb_dir):
    retrieval.build_index(kb_loader.load_corpus(kb_dir / "knowledge-base.zip"))
    hits = retrieval.retrieve("ASKUE")
    assert hits and hits[0]["file"].endswith("askue.md")


# ---------- ai_engine ----------

def _fake_chunks():
    return [
        {
            "id": "20-products/22-askue.md#c000",
            "file": "20-products/22-askue.md",
            "section": "Облачная платформа ASKUE",
            "score": 5.0,
            "content": "ASKUE — облачная платформа учёта электроэнергии.",
        }
    ]


def test_answer_question_with_fake_llm(kb_dir, monkeypatch):
    monkeypatch.setattr(retrieval, "retrieve", lambda q, top_k=None: _fake_chunks())
    seen = {}

    def fake_llm(system, user):
        seen["system"] = system
        seen["user"] = user
        return "ASKUE подойдёт для учёта на нескольких объектах."

    monkeypatch.setattr(ai_engine, "_llm_chat", fake_llm)
    result = ai_engine.answer_question("Как контролировать несколько объектов?")
    assert "ASKUE" in result["answer"]
    assert result["sources"] and result["sources"][0]["file"].endswith("askue.md")
    assert result["sources"][0]["chunk_id"] == "20-products/22-askue.md#c000"
    assert "баз" in seen["system"].lower() or "факт" in seen["system"].lower()
    assert "ASKUE" in seen["user"]


def test_answer_question_no_chunks_no_llm(kb_dir, monkeypatch):
    monkeypatch.setattr(retrieval, "retrieve", lambda q, top_k=None: [])

    def boom(system, user):  # pragma: no cover - не должен вызываться
        raise AssertionError("LLM не должен вызываться без чанков")

    monkeypatch.setattr(ai_engine, "_llm_chat", boom)
    result = ai_engine.answer_question("абракадабра неизвестный продукт")
    assert result["sources"] == []
    assert "не нашлось" in result["answer"].lower() or "нет" in result["answer"].lower()
    assert result["suggest_lead"] is True or result["suggest_lead"] is False  # bool


def test_answer_question_session_context(kb_dir, monkeypatch):
    monkeypatch.setattr(retrieval, "retrieve", lambda q, top_k=None: _fake_chunks())
    seen = {}
    monkeypatch.setattr(
        ai_engine, "_llm_chat", lambda s, u: seen.setdefault("user", u) or "ok"
    )
    ctx = [{"role": "user", "content": "У нас 5 магазинов"},
           {"role": "assistant", "content": "Понял"}]
    ai_engine.answer_question("А сколько это стоит?", session_context=ctx)
    assert "5 магазинов" in seen["user"]


def test_answer_question_llm_error_propagates(kb_dir, monkeypatch):
    monkeypatch.setattr(retrieval, "retrieve", lambda q, top_k=None: _fake_chunks())

    def fail(system, user):
        raise ai_engine.AICoreError("timeout")

    monkeypatch.setattr(ai_engine, "_llm_chat", fail)
    with pytest.raises(ai_engine.AICoreError):
        ai_engine.answer_question("вопрос")


def test_answer_question_truncates_long_answer(kb_dir, monkeypatch):
    monkeypatch.setattr(retrieval, "retrieve", lambda q, top_k=None: _fake_chunks())
    monkeypatch.setattr(ai_engine, "_llm_chat", lambda s, u: "x " * 6000)
    result = ai_engine.answer_question("вопрос")
    assert len(result["answer"]) <= ai_engine.MAX_ANSWER_CHARS


def test_answer_question_empty_question(kb_dir):
    with pytest.raises(ai_engine.AICoreError):
        ai_engine.answer_question("   ")


def test_llm_settings_missing_env(monkeypatch):
    for v in ("LLM_BASE_URL", "BASE_URL", "OPENAI_BASE_URL", "LLM_API_KEY",
              "OPENAI_API_KEY", "LLM_MODEL", "GEN_MODEL", "OPENAI_MODEL"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(ai_engine.AICoreError):
        ai_engine._post_chat([{"role": "user", "content": "hi"}], ai_engine._settings())


def test_ai_engine_backend_compat_signature():
    # Контракт backend/app/services/ai_service.py: answer_question(message)
    import inspect
    sig = inspect.signature(ai_engine.answer_question)
    params = list(sig.parameters)
    assert params[0] == "question"
    assert sig.parameters["session_context"].default is None


# ---------- solution.py ----------

def _write_questions(data: Path, rows: list[tuple[str, str]]) -> None:
    with (data / "questions.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "question"])
        w.writerows(rows)


def test_solution_writes_submission(kb_dir, tmp_path, monkeypatch):
    _write_questions(
        kb_dir,
        [
            ("1", "Как контролировать электроэнергию на объектах?"),
            ("2", 'Вопрос с "кавычками" и\nпереносом строки'),
        ],
    )
    monkeypatch.setenv("SUBMISSION_PATH", str(tmp_path / "submission.csv"))
    monkeypatch.setattr(
        ai_engine,
        "_llm_chat",
        lambda s, u: "Консультант: подойдёт ASKUE для нескольких объектов.",
    )
    # MAX_WORKERS=1 для детерминизма порядка
    monkeypatch.setenv("MAX_WORKERS", "1")

    assert solution.main() == 0

    out = tmp_path / "submission.csv"
    assert out.exists()
    with out.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["id"] for r in rows] == ["1", "2"]
    assert all(r["answer"].strip() for r in rows)
    assert "кавычками" in rows[1]["answer"] or "ASKUE" in rows[1]["answer"]


def test_solution_empty_questions(kb_dir, tmp_path, monkeypatch):
    _write_questions(kb_dir, [])
    monkeypatch.setenv("SUBMISSION_PATH", str(tmp_path / "submission.csv"))
    assert solution.main() == 0
    with (tmp_path / "submission.csv").open("r", encoding="utf-8") as f:
        assert f.read().strip() == "id,answer"


def test_solution_llm_failure_is_honest(kb_dir, tmp_path, monkeypatch):
    _write_questions(kb_dir, [("1", "Как работает ASKUE для нескольких объектов?")])
    monkeypatch.setenv("SUBMISSION_PATH", str(tmp_path / "submission.csv"))

    def fail(system, user):
        raise ai_engine.AICoreError("proxy down")

    monkeypatch.setattr(ai_engine, "_llm_chat", fail)
    # Прогон не роняется, но фиксируется failure -> exit code 1
    assert solution.main() == 1
    with (tmp_path / "submission.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["answer"] == solution.ERROR_ANSWER


def test_solution_duplicate_ids_warn(kb_dir, tmp_path, monkeypatch, capsys):
    _write_questions(kb_dir, [("1", "вопрос"), ("1", "другой вопрос")])
    monkeypatch.setenv("SUBMISSION_PATH", str(tmp_path / "submission.csv"))
    monkeypatch.setattr(ai_engine, "_llm_chat", lambda s, u: "ok")
    assert solution.main() == 0
    err = capsys.readouterr().err
    assert "duplicate" in err.lower()
    with (tmp_path / "submission.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2  # строка на каждый входной ID
