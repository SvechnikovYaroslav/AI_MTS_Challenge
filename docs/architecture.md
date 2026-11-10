# Архитектура

## Компоненты

```
┌─────────────┐   HTTP/JSON    ┌──────────────────┐   import    ┌─────────────┐
│  Frontend   │ ─────────────► │  Backend         │ ──────────► │  AI Core    │
│  (React/Vite│  /api/*        │  (FastAPI)       │  AI_MODE    │  (корень)   │
│   +Nginx)   │                │  SQLite + роуты  │             │ ai_engine.. │
└─────────────┘                └──────────────────┘             └──────┬──────┘
                                                                      │
                                              ┌───────────────────────┼───────────┐
                                              ▼                       ▼           ▼
                                        retrieval.py            kb_loader.py   prompts.py
                                        (поиск по БЗ)          (knowledge-    (шаблоны
                                                              base.zip)      промптов)
```

AI Core — python-модули в **корне** репозитория (`ai_engine.py`,
`retrieval.py`, `kb_loader.py`, `prompts.py`). Они не зависят от backend и
frontend и одинаково используются веб-приложением и конкурсным `solution.py`.

## Поток 1: Frontend → Backend → AI Core

1. Пользователь вводит сообщение в чат (`frontend/src/pages/ChatPage.tsx`).
2. `frontend/src/api/client.ts` отправляет `POST /api/chat`
   `{session_id, message}` (в Docker — через nginx-прокси `/api` → `backend:8000`).
3. Backend (`app/routes/chat.py`) валидирует запрос, сохраняет сообщение
   пользователя в SQLite (`storage.py`), вызывает `services/ai_service.py`.
4. `ai_service` смотрит на `AI_MODE`:
   - `MOCK` — возвращает тестовый ответ (sources помечены как mock,
     latency измеряется реально).
   - `REAL` — импортирует `ai_engine` из корня проекта и вызывает
     `answer_question(...)`. Если AI Core не реализован
     (`AI_CORE_READY = False` / `NotImplementedError`), возвращается
     диагностический ответ `ai_status: "not_implemented"` — без скрытого
     переключения на MOCK.
5. Backend сохраняет ответ ассистента в SQLite и возвращает JSON по
     контракту `docs/api-contract.md`.
6. Frontend отображает ответ, debug-панель (sources, latency_ms,
   ai_status) и при `suggest_lead=true` предлагает форму заявки.

Сессии: `POST /api/sessions` создаёт новый `session_id` (uuid), история
хранится в `sessions`/`messages` и не удаляется. Список — `GET /api/sessions`,
история — `GET /api/sessions/{id}/messages`.

Заявки: `POST /api/leads` (ФИО, телефон, компания, session_id) → таблица
`leads`; `GET /api/leads` — просмотр в демонстрационном режиме.

## Поток 2: solution.py → AI Core → submission.csv

Конкурсная среда МТС переносит **только корневые `.py` и `requirements.txt`**:

1. Платформа задаёт `DATA_DIR` (содержит `questions.csv` и
   `knowledge-base.zip`).
2. `solution.py` читает `questions.csv`, для каждого `id` вызывает
   `ai_engine.answer_question(question)`.
3. AI Core (`kb_loader` → `retrieval` → `prompts` → Qwen API) формирует ответ.
4. Результат пишется в `submission.csv` в рабочем каталоге с колонками
   `id,answer`. Тесты независимы по `id` — каждый вопрос обрабатывается
   отдельно.
5. `scripts/build_submission.py` собирает ZIP только из корневых `.py` +
   `requirements.txt` и **отказывается** собирать архив, пока
   `ai_engine.AI_CORE_READY != True`.

## Хранение данных

SQLite (`DATABASE_PATH`, по умолчанию `/data/app.db` в контейнере):

- `sessions(id, title, created_at)`
- `messages(id, session_id, role, content, sources_json, latency_ms, created_at)`
- `leads(id, name, phone, company, session_id, created_at)`

`storage.py` — тонкий слой на stdlib `sqlite3`, без ORM (SQLAlchemy не
требуется).

## Режимы и конфигурация

| Переменная | Назначение |
|---|---|
| `AI_MODE` | `MOCK` / `REAL` |
| `DATABASE_PATH` | путь к SQLite |
| `DATA_DIR` | каталог данных для AI Core / solution.py |
| `QWEN_API_KEY`, `QWEN_BASE_URL`, `QWEN_MODEL` | доступ к модели (REAL) |

См. `.env.example`. Секреты не коммитятся.
