# AI_MTS_Challenge — MTS EnergyTool AI Consultant

B2B ИИ-консультант для МТС EnergyTool (хакатон МТС Hack&Change 2026).

Пользователь описывает проблему с энергопотреблением — система консультирует,
задаёт уточняющие вопросы (RAG по базе знаний МТС) и помогает оформить заявку
менеджеру.

## Структура каталогов

```
Challenge/
├── frontend/            # React + TypeScript + Vite + Tailwind (веб-чат)
│   ├── src/
│   │   ├── api/         # HTTP-клиент к backend
│   │   ├── components/  # UI-компоненты чата, список сессий, форма заявки
│   │   ├── pages/       # страницы приложения
│   │   ├── types/       # TypeScript-типы (соответствуют API-контракту)
│   │   └── styles/      # Tailwind CSS
│   ├── package.json
│   ├── package-lock.json
│   ├── Dockerfile
│   └── nginx.conf       # статика + прокси /api -> backend
│
├── backend/             # FastAPI + SQLite (REST API, хранение сессий/заявок)
│   ├── app/
│   │   ├── main.py
│   │   ├── routes/      # health, sessions, chat, leads
│   │   ├── schemas.py   # Pydantic-модели
│   │   ├── storage.py   # SQLite-слой
│   │   └── services/    # AI-адаптер (MOCK/REAL)
│   ├── requirements.txt
│   └── Dockerfile
│
├── ai_engine.py         # AI Core: единая точка входа для backend и solution.py
├── retrieval.py         # (заглушка) слой поиска по базе знаний — зона ML-участника
├── kb_loader.py         # (заглушка) загрузка knowledge-base.zip — зона ML-участника
├── prompts.py           # (заглушка) промпты — зона ML-участника
├── solution.py          # конкурсный entry point: questions.csv -> submission.csv
├── requirements.txt     # зависимости КОНКУРСНОЙ среды (корень архива МТС)
│
├── scripts/
│   ├── build_submission.py  # сборка ZIP-сабмита (только когда AI Core готов)
│   └── smoke_test.py        # проверка backend end-to-end
│
├── tests/               # тесты backend API
├── docs/
│   ├── architecture.md
│   └── api-contract.md
│
├── compose.yaml
├── .env.example
├── .gitignore
└── .dockerignore
```

Материалы организаторов (`Knowledge-base/`, `Sample_submissions/`, PDF/DOCX
регламентов, `demo_*.csv`) хранятся локально и **не коммитятся** — см. `.gitignore`.

## Стек

- **Frontend:** React 18, TypeScript, Vite 5, Tailwind CSS 3, npm.
- **Backend:** Python 3.11, FastAPI, Uvicorn, SQLite (stdlib `sqlite3`), Pydantic 2.
- **AI:** Python, RAG, модель Qwen через API организаторов (пока только интерфейсы).
- **Инфраструктура:** Docker, Docker Compose.

## Запуск через Docker

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Swagger: http://localhost:8000/docs

SQLite-база хранится в Docker-volume `backend-data` (`/data/app.db`).

## Запуск локально без Docker

Backend (Python 3.11+):

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
set AI_MODE=MOCK                # Windows; export AI_MODE=MOCK — Linux/macOS
uvicorn app.main:app --reload --port 8000
```

Frontend (Node.js 20+):

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173, /api проксируется на :8000
```

## Проверка работоспособности

```bash
curl http://localhost:8000/api/health
# {"status":"ok", ...}
```

Тестовое сообщение:

```bash
curl -X POST http://localhost:8000/api/sessions
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<session_id>","message":"У нас несколько магазинов, хотим контролировать расход электроэнергии."}'
```

Или через браузер: откройте http://localhost:5173, нажмите «Новый диалог»,
отправьте сообщение. Полный контракт — в `docs/api-contract.md`.

## MOCK vs REAL

- `AI_MODE=MOCK` (по умолчанию): backend возвращает заранее подготовленный
  **тестовый** ответ с явно помеченными mock-источниками и замеренной
  latency. Работает без ключа модели и базы знаний.
- `AI_MODE=REAL`: backend вызывает AI Core (`ai_engine.py` в корне). Пока
  ML-участник не реализовал RAG, возвращается явное диагностическое сообщение
  `AI core is not implemented` — fallback на MOCK отсутствует.

## Задачи AI-участника (ML)

1. Реализовать `retrieval.py`, `kb_loader.py`, `prompts.py`, `ai_engine.py`
   в **корне** репозитория — их переносят в конкурсный ZIP как есть.
2. `solution.py` должен читать `questions.csv` из `DATA_DIR`, отвечать через
   AI Core и писать `submission.csv` (`id,answer`).
3. Подключить модель Qwen (ключи — через `.env`, не коммитить).
4. После готовности выставить `AI_CORE_READY = True` в `ai_engine.py`,
   чтобы `scripts/build_submission.py` разрешил сборку архива.

## Git workflow

- **`develop` — основная ветка активной разработки команды.**
- `main` — стабильные релизы.
- Задачи разрабатываются в коротких feature-ветках **от `develop`**,
  после тестов вливаются обратно в `develop`.
- Коммиты на русском/английском, осмысленные сообщения.
- **Никогда** не коммитить: `Knowledge-base/`, `Sample_submissions/`,
  PDF/DOCX организаторов, `demo_*.csv`, `.env`, `*.db`, `submission.*`,
  `data/` (диагностика БЗ).
- Перед PR проверять `git status` и staged-файлы.

### Ветки и baseline

| Ветка/тег | Назначение |
|---|---|
| `develop` | актуальная разработка: web-app + AI Core + Retrieval V2 + RAG-исследования |
| `main` | стабильные релизы |
| `mts-score-0.4533` | annotated tag — версия с официальным баллом **0,4533** (коммит `4461e7e`, submission-hardening). Восстановимый baseline первого успешного конкурса. |

> Retrieval V2 (стемминг + нормализация «сим-карт*» + TOP_K=8) входит в
> `develop`, но **ещё не имеет нового официального score** — первый
> сабмит с ним не выполнялся.

### Быстрый старт для участника

```bash
git clone https://github.com/SvechnikovYaroslav/AI_MTS_Challenge.git
cd AI_MTS_Challenge
git checkout develop

# backend (Python 3.11+)
python -m venv backend/.venv
backend/.venv/Scripts/pip install -r backend/requirements.txt   # Windows
# backend/.venv/bin/pip install -r backend/requirements.txt     # Linux/macOS

# frontend
cd frontend && npm install && npm run dev

# тесты
backend/.venv/Scripts/python -m pytest tests/ -q   # ожидается 69 passed
cd frontend && npm run build

# backend локально (MOCK-режим)
cd .. && AI_MODE=MOCK backend/.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000
```

Переменные окружения — по `.env.example` (`AI_MODE`, `TOP_K`, `LLM_*`,
`EXPOSE_LEADS` и др.).

## Изоляция конфиденциальных материалов

Исходная база знаний, регламенты и демо-данные организаторов нужны только
локально. `.gitignore` и `.dockerignore` исключают их по конкретным путям
и именам; `.dockerignore` дополнительно не даёт им попасть в образы.
Рабочие API-ключи задаются только через `.env` (шаблон — `.env.example`).
