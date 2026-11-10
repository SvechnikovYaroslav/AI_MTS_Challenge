"""Сборка ZIP-сабмита для платформы МТС.

Ограничения МТС: в корне архива — только .py-файлы и requirements.txt
(без вложенных папок и посторонних файлов).

Скрипт ОТКАЗЫВАЕТСЯ собирать архив, пока ai_engine.AI_CORE_READY != True,
чтобы не отправить заглушку как готовое решение. Для осознанной сборки
черновика используйте флаг --force (архив помечается DRAFT в имени).

Usage:
    python scripts/build_submission.py [--force]
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ai_engine  # noqa: E402

# Конкурсное ядро: только корневые .py + requirements.txt.
ENTRY_FILES = [
    "solution.py",
    "ai_engine.py",
    "retrieval.py",
    "kb_loader.py",
    "prompts.py",
    "requirements.txt",
]


def main() -> int:
    force = "--force" in sys.argv[1:]

    missing = [name for name in ENTRY_FILES if not (ROOT / name).exists()]
    if missing:
        print(f"ERROR: missing required files: {missing}", file=sys.stderr)
        return 2

    if not ai_engine.AI_CORE_READY and not force:
        print(
            "ERROR: AI Core is not ready (ai_engine.AI_CORE_READY = False).\n"
            "Сабмит НЕ собран, чтобы не отправить заглушку как решение.\n"
            "ML-участник: реализуйте RAG и выставьте AI_CORE_READY = True.\n"
            "Для черновой сборки используйте --force.",
            file=sys.stderr,
        )
        return 3

    out_name = "submission_DRAFT.zip" if (force and not ai_engine.AI_CORE_READY) else "submission.zip"
    out_path = ROOT / out_name

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ENTRY_FILES:
            zf.write(ROOT / name, arcname=name)

    print(f"Built {out_path}")
    for name in zipfile.ZipFile(out_path).namelist():
        print(f"  {name}")
    if force and not ai_engine.AI_CORE_READY:
        print("WARNING: черновой архив с нереализованным AI Core — не для сдачи.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
