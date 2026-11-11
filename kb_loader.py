"""Загрузка базы знаний МТС (knowledge-base.zip) для RAG.

Читает ZIP из DATA_DIR (questions.csv + knowledge-base.zip),
разбирает Markdown-документы, делит их на осмысленные чанки
по заголовкам разделов и абзацам. Реальные материалы организаторов
не коммитятся — они передаются платформой через DATA_DIR.

Для локальной диагностики поддерживается и распакованный каталог
(``Knowledge-base/`` или ``data/knowledge-base/`` с .md/.txt).
"""

from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path
from typing import Any, Iterator

# Размер чанка: целевой ~1400 символов, жёсткий потолок ~2400.
# База состоит из структурированных md-документов с разделами;
# чанки меньше ~200 символов бесполезны для BM25 и сливаются.
DEFAULT_CHUNK_TARGET = 1400
DEFAULT_CHUNK_MAX = 2400
MIN_CHUNK_CHARS = 200

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_WORD_RE = re.compile(r"\S+")


def get_data_dir() -> Path:
    """Каталог данных платформы (questions.csv, knowledge-base.zip)."""
    return Path(os.environ.get("DATA_DIR", "./data"))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def chunk_target() -> int:
    return max(400, _env_int("KB_CHUNK_CHARS", DEFAULT_CHUNK_TARGET))


def chunk_max() -> int:
    return max(chunk_target() + 400, _env_int("KB_CHUNK_MAX", DEFAULT_CHUNK_MAX))


def knowledge_base_zip_path() -> Path:
    return get_data_dir() / "knowledge-base.zip"


def _candidate_kb_paths() -> list[Path]:
    """Возможные расположения базы знаний (ZIP или каталог)."""
    data = get_data_dir()
    names = ["knowledge-base.zip", "knowledge_base.zip", "kb.zip"]
    candidates = [data / n for n in names]
    # Запасные варианты для локального запуска из корня репозитория.
    root = Path(__file__).resolve().parent
    candidates += [
        root / "data" / "knowledge-base.zip",
        root / "Knowledge-base",
        root / "knowledge-base",
        Path.cwd() / "Knowledge-base",
    ]
    # Уникальные существующие пути.
    seen: set[str] = set()
    out: list[Path] = []
    for p in candidates:
        key = str(p).lower()
        if key not in seen and p.exists():
            seen.add(key)
            out.append(p)
    return out


def find_kb_path() -> Path:
    for p in _candidate_kb_paths():
        if p.is_file() or p.is_dir():
            return p
    raise FileNotFoundError(
        "База знаний не найдена: ожидается knowledge-base.zip в DATA_DIR "
        f"({get_data_dir()}) или распакованный каталог Knowledge-base/"
    )


def _iter_markdown(path: Path) -> Iterator[tuple[str, str]]:
    """Отдать (имя_файла, текст) для всех .md/.txt внутри ZIP или каталога."""
    if path.is_dir():
        for f in sorted(path.rglob("*")):
            if f.is_file() and f.suffix.lower() in (".md", ".txt"):
                try:
                    yield str(f.relative_to(path)).replace("\\", "/"), f.read_text(
                        encoding="utf-8-sig", errors="replace"
                    )
                except OSError:
                    continue
        return

    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            norm = name.replace("\\", "/")
            if norm.startswith("__MACOSX/") or norm.endswith("/"):
                continue
            if Path(norm).suffix.lower() not in (".md", ".txt"):
                continue
            try:
                raw = archive.read(name)
            except (KeyError, zipfile.BadZipFile):
                continue
            yield norm, raw.decode("utf-8-sig", errors="replace")


def _split_long_block(block: str, max_chars: int) -> list[str]:
    """Разбить слишком большой абзац по границам предложений/слов."""
    if len(block) <= max_chars:
        return [block]
    parts: list[str] = []
    rest = block
    while len(rest) > max_chars:
        cut = rest.rfind(". ", 0, max_chars)
        if cut < max_chars // 2:
            cut = rest.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        parts.append(rest[:cut].strip())
        rest = rest[cut:].lstrip(". ")
    if rest.strip():
        parts.append(rest.strip())
    return [p for p in parts if p]


def chunk_markdown(name: str, text: str) -> list[dict[str, Any]]:
    """Разбить один markdown-документ на чанки с метаданными.

    Границы — по заголовкам (## и глубже) и абзацам. Маленький хвост
    присоединяется к предыдущему чанку.
    """
    target = chunk_target()
    max_chars = chunk_max()

    # Разбор на секции: [(section_title, body_text)]
    sections: list[tuple[str, list[str]]] = []
    current_section = ""
    buf: list[str] = []
    for line in text.splitlines():
        m = _HEADER_RE.match(line.strip())
        if m:
            if buf:
                sections.append((current_section, buf))
            buf = []
            current_section = m.group(2).strip()
        else:
            buf.append(line)
    if buf:
        sections.append((current_section, buf))

    chunks: list[dict[str, Any]] = []
    cur_text_parts: list[str] = []
    cur_section = ""
    cur_len = 0

    def flush() -> None:
        nonlocal cur_text_parts, cur_section, cur_len
        body = "\n".join(p for p in cur_text_parts if p.strip()).strip()
        if body:
            chunks.append({"file": name, "section": cur_section, "text": body})
        cur_text_parts, cur_section, cur_len = [], "", 0

    for section, lines in sections:
        # Граница раздела = граница чанка: нельзя смешивать разные
        # смысловые разделы в одном чанке с чужой меткой section.
        if cur_text_parts and cur_section != section:
            flush()
        # Абзацы = группы непустых строк.
        paragraphs: list[str] = []
        para: list[str] = []
        for line in lines:
            if line.strip():
                para.append(line.rstrip())
            elif para:
                paragraphs.append("\n".join(para))
                para = []
        if para:
            paragraphs.append("\n".join(para))

        for para_text in paragraphs:
            for piece in _split_long_block(" ".join(para_text.split()), max_chars):
                if cur_len and cur_len + len(piece) + 2 > target:
                    flush()
                if not cur_text_parts:
                    cur_section = section or cur_section
                cur_text_parts.append(piece)
                cur_len += len(piece) + 2
                if cur_len >= target:
                    flush()

    flush()

    # Слить слишком короткие чанки с соседом внутри того же файла,
    # чтобы не было мусорных фрагментов с бесполезными метаданными.
    merged: list[dict[str, Any]] = []
    for c in chunks:
        if (
            merged
            and len(c["text"]) < MIN_CHUNK_CHARS
            and merged[-1]["file"] == c["file"]
            and merged[-1]["section"] == c["section"]
            and len(merged[-1]["text"]) + len(c["text"]) + 2 <= max_chars * 2
        ):
            merged[-1]["text"] += "\n\n" + c["text"]
            merged[-1]["section"] = merged[-1]["section"] or c["section"]
        else:
            merged.append(c)
    chunks = merged

    # Стабильные ID: файл + порядковый номер чанка.
    for i, c in enumerate(chunks):
        c["id"] = f"{c['file']}#c{i:03d}"
    return chunks


def load_corpus(kb_path: Path | None = None) -> list[dict[str, Any]]:
    """Загрузить и разбить базу знаний на чанки.

    Returns:
        [{"id", "file", "section", "text"}, ...]

    Raises:
        FileNotFoundError: база знаний не найдена.
        ValueError: архив есть, но не содержит md/txt-документов.
    """
    path = kb_path or find_kb_path()
    docs = 0
    errors = 0
    corpus: list[dict[str, Any]] = []
    for name, text in _iter_markdown(path):
        if not text.strip():
            continue
        docs += 1
        try:
            corpus.extend(chunk_markdown(name, text))
        except Exception as exc:  # noqa: BLE001 — не роняем весь корпус
            errors += 1
            print(f"[kb_loader] chunk error in {name}: {exc}", file=os.sys.stderr)

    if not corpus:
        raise ValueError(f"База знаний пуста или не содержит .md/.txt: {path}")

    print(
        f"[kb_loader] source={path} docs={docs} chunks={len(corpus)} errors={errors}",
        file=os.sys.stderr,
    )
    return corpus
