"""Шаблоны промптов для консультанта МТС EnergyTool.

Зона ответственности ML-участника. Здесь должны жить:
  - системный промпт консультанта (роль, тон, ограничения);
  - шаблон сборки user-prompt из найденных фрагментов БЗ;
  - при необходимости — промпты для уточняющих вопросов.
"""

from __future__ import annotations

from typing import Any


def system_prompt() -> str:
    """Системный промпт консультанта."""
    raise NotImplementedError("prompts.system_prompt is not implemented yet (ML owner).")


def build_user_prompt(question: str, chunks: list[dict[str, Any]], session_context: list[dict[str, Any]] | None = None) -> str:
    """Собрать user-prompt из вопроса, найденных чанков и истории диалога."""
    raise NotImplementedError("prompts.build_user_prompt is not implemented yet (ML owner).")
