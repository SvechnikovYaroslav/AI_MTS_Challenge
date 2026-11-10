"""AI Core — единая точка входа для backend и solution.py.

Этот модуль НЕ зависит от FastAPI/frontend и лежит в корне репозитория,
поэтому переносится в конкурсный ZIP МТС без изменений.

ML-участник реализует RAG здесь (совместно с retrieval.py, kb_loader.py,
prompts.py). Пока AI_CORE_READY = False:
  - backend в режиме AI_MODE=REAL вернёт диагностическое сообщение;
  - scripts/build_submission.py откажется собирать сабмит.
"""

from __future__ import annotations

import time
from typing import Any

# Флаг готовности. ML-участник выставляет True, когда RAG реально работает.
AI_CORE_READY: bool = False


def answer_question(question: str, session_context: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Ответить на вопрос пользователя.

    Args:
        question: текст вопроса/проблемы пользователя.
        session_context: опциональная история диалога
            ([{"role": "user"|"assistant", "content": str}, ...]).

    Returns:
        {
            "answer": str,
            "sources": [{"file": str, "score": float?, ...}, ...],
            "suggest_lead": bool,
        }

    Raises:
        NotImplementedError: пока AI Core не реализован.
    """
    if not AI_CORE_READY:
        raise NotImplementedError(
            "AI Core is not implemented yet. "
            "ML owner: implement RAG in ai_engine.py / retrieval.py / kb_loader.py / prompts.py."
        )

    # TODO(ML): реализовать пайплайн retrieval -> prompts -> Qwen API.
    raise NotImplementedError("AI Core pipeline is not implemented.")
