# Контекст сборки — КОРЕНЬ репозитория (см. compose.yaml),
# чтобы AI Core из корневых .py-файлов попал в образ.
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# AI Core (ai_engine.py и др.) — модули корня проекта.
COPY ai_engine.py retrieval.py kb_loader.py prompts.py /project-root/
ENV PYTHONPATH=/project-root

ENV DATABASE_PATH=/data/app.db \
    AI_MODE=MOCK

RUN mkdir -p /data
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
