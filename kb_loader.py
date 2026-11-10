"""Загрузка базы знаний МТС (knowledge-base.zip) для RAG.

Зона ответственности ML-участника. Должен читать архив из DATA_DIR,
распаковывать/индексировать документы (md/docx/pdf — по необходимости)
и отдавать доступ к загруженному корпусу для retrieval.py.

Реальные материалы организаторов НЕ коммитятся в репозиторий — они
передаются платформой через DATA_DIR в момент проверки.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def get_data_dir() -> Path:
    """Каталог данных платформы (questions.csv, knowledge-base.zip)."""
    return Path(os.environ.get("DATA_DIR", "./data"))


def knowledge_base_zip_path() -> Path:
    return get_data_dir() / "knowledge-base.zip"


def load_corpus() -> list[dict[str, Any]]:
    """Загрузить и распарсить базу знаний.

    Returns:
        Список документов/чанков, готовых для индексации retrieval.
    """
    raise NotImplementedError("kb_loader.load_corpus is not implemented yet (ML owner).")
