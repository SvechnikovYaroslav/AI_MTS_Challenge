"""Слой поиска по базе знаний МТС (RAG retrieval).

Зона ответственности ML-участника. Модуль должен предоставлять функцию
вида ``retrieve(query, top_k) -> list[dict]`` с фрагментами базы знаний
и метаданными источников (имя файла и т.п.).

Реализация (эмбеддинги/гибридный поиск/реранкинг) — на усмотрение ML.
"""

from __future__ import annotations

from typing import Any


def retrieve(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Найти релевантные фрагменты базы знаний для запроса.

    Returns:
        Список фрагментов: {"text": str, "file": str, "score": float, ...}
    """
    raise NotImplementedError("retrieval.retrieve is not implemented yet (ML owner).")
