# API-контракт

Базовый URL: `http://localhost:8000` (в Docker frontend обращается через
`/api` → `backend:8000`). Формат — JSON, `Content-Type: application/json`.

Все ответы об ошибках: `{"detail": "<человекочитаемое сообщение>"}` + HTTP-код.

## GET /api/health

Проверка работоспособности backend.

**200 OK**
```json
{
  "status": "ok",
  "ai_mode": "MOCK",
  "ai_status": "mock",
  "version": "0.1.0"
}
```

## POST /api/sessions

Создать новый диалог. История предыдущих сессий сохраняется.

**201 Created**
```json
{
  "id": "9f1c2e4a-...",
  "title": "Новый диалог",
  "created_at": "2026-11-11T12:00:00Z"
}
```

## GET /api/sessions

Список сохранённых сессий (новые первыми).

**200 OK**
```json
{
  "sessions": [
    {"id": "9f1c2e4a-...", "title": "Новый диалог",
     "created_at": "2026-11-11T12:00:00Z", "message_count": 4}
  ]
}
```

Поле `title` при создании сессии — «Новый диалог». После первого
сообщения пользователя оно автоматически заменяется сокращённым текстом
первого вопроса (до ~60 символов, без LLM) и сохраняется в базе.

## GET /api/sessions/{session_id}/messages

История сообщений сессии (по возрастанию времени).

**200 OK**
```json
{
  "session_id": "9f1c2e4a-...",
  "messages": [
    {
      "id": 1,
      "role": "user",
      "content": "У нас несколько магазинов...",
      "sources": null,
      "latency_ms": null,
      "ai_status": null,
      "created_at": "2026-11-11T12:00:01Z"
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "Для такой задачи может подойти облачная платформа учёта...",
      "sources": [{"file": "22-askue.md", "mock": true}],
      "latency_ms": 12,
      "ai_status": "mock",
      "created_at": "2026-11-11T12:00:01Z"
    }
  ]
}
```

`role`: `"user"` | `"assistant"`. У сообщений пользователя `sources`,
`latency_ms`, `ai_status` = `null`.

**404** — сессия не найдена.

## POST /api/chat

Отправить сообщение консультанту.

**Запрос**
```json
{
  "session_id": "9f1c2e4a-...",
  "message": "У нас несколько магазинов, хотим контролировать расход электроэнергии."
}
```

| Поле | Тип | Правила |
|---|---|---|
| `session_id` | string (uuid) | обязателен; сессия должна существовать, иначе 404 |
| `message` | string | обязателен; 1–4000 символов после trim |

**200 OK**
```json
{
  "session_id": "9f1c2e4a-...",
  "answer": "Для такой задачи может подойти облачная платформа учёта. Сколько у вас объектов?",
  "sources": [
    {"file": "22-askue.md", "mock": true}
  ],
  "latency_ms": 120,
  "suggest_lead": false,
  "ai_status": "mock"
}
```

| Поле | Тип | Описание |
|---|---|---|
| `answer` | string | текст ответа ассистента |
| `sources` | array | источники; в MOCK-режиме помечены `"mock": true` |
| `latency_ms` | integer | реальное время генерации ответа, мс |
| `suggest_lead` | boolean | подсказка фронтенду показать форму заявки |
| `ai_status` | string | `"mock"` \| `"real"` \| `"not_implemented"` |

**Ошибки:** `400` — пустое/слишком длинное сообщение; `404` — нет сессии;
`422` — невалидный JSON/отсутствуют поля.

В режиме `AI_MODE=REAL` без реализованного AI Core ответ содержит
`ai_status: "not_implemented"` и диагностический текст — это не ошибка HTTP,
а честный статус заглушки.

## POST /api/leads

Создать заявку менеджеру.

**Запрос**
```json
{
  "name": "Иван Иванов",
  "phone": "+7 900 000-00-00",
  "company": "ООО Ромашка",
  "session_id": "9f1c2e4a-..."
}
```

`session_id` — опционален (nullable). Все строки trim, `name` 2–200,
`phone` 5–32, `company` до 200. Только синтетические/тестовые данные.

**201 Created**
```json
{
  "id": 1,
  "name": "Иван Иванов",
  "phone": "+7 900 000-00-00",
  "company": "ООО Ромашка",
  "session_id": "9f1c2e4a-...",
  "created_at": "2026-11-11T12:05:00Z"
}
```

**422** — нарушения валидации.

## GET /api/leads

Список заявок (демонстрационный режим, новые первыми). **200 OK**
`{"leads": [Lead, ...]}` — тот же формат элемента, что в POST-ответе.
