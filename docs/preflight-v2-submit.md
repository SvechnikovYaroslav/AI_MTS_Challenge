# Preflight перед третьим сабмитом — Retrieval V2 + LLM-телеметрия

Ветка: `feature/qwen-evaluation` (планируется merge в `develop`).
Кандидат: Retrieval V2 (стемминг + SIM-нормализация + TOP_K=8) +
минимальная LLM-телеметрия. Промпты, temperature, max_tokens,
thinking-параметры НЕ менялись.

## 1. Effective configuration

Приоритет env (одинаков для solution.py и backend):
`LLM_BASE_URL|QWEN_BASE_URL|BASE_URL|OPENAI_BASE_URL`,
`LLM_API_KEY|QWEN_API_KEY|OPENAI_API_KEY`,
`LLM_MODEL|QWEN_MODEL|GEN_MODEL|OPENAI_MODEL`,
`TOP_K` (default 8, 1–30), `MAX_TOKENS` (default 1200),
`TEMPERATURE` (default 0.0), `MAX_WORKERS` (default 3),
`LLM_TIMEOUT` (60с), `LLM_RETRIES` (2).

**Риск:** платформа может иметь собственные env-переменные.
Если она выставит `TOP_K=5`, кандидат молча превратится в baseline.

**Исправление (внесено):** `solution.py::main()` теперь жёстко
фиксирует `TOP_K=8`, `MAX_TOKENS=1200`, `TEMPERATURE=0.0` перед
обработкой — конкурсный прогон всегда идёт с задокументированной
конфигурацией V2. На веб-приложение не влияет: `solution.py`
не импортируется backend'ом (ai_engine/retrieval читают env
в своём процессе). Покрыто тестом `test_solution_pins_contest_config`.
`LLM_MODEL` НЕ пинится — имя модели задаёт платформа через env,
это входные данные эксперимента, а не наш параметр.

## 2. Сверка gold-разметки

`labeled_n=16` (R4) — корректно: 5 demo + 6 P0 + 5 E-проб.
Число «29» в первом аудите было ошибкой отчёта (знаменатель
gold-покрытия) — исправлено в `docs/qwen-gen-audit.md`.

Таблица gold vs контексты (16 размеченных вопросов; «hit» =
gold chunk_id присутствует в top-k соответствующей версии):

| id | gold chunk | baseline_hit | v2_hit |
|---|---|---|---|
| 1 | 23-solar.md#c008 | yes | yes |
| 3 | 23-solar.md#c003 | NO | yes |
| 5 | 22-askue.md#c015 | NO | yes |
| 11 | 21-orem.md#c017 | yes | yes |
| 13 | 21-orem.md#c017 | yes | yes |
| p0_magadan | 02-scope#c001 | NO | yes |
| p0_magadan | 10-market#c003 | NO | yes |
| p0_magadan | 26-general#c004 | NO | yes |
| p0_market750 | 12-thresholds#c004 | NO | **NO** |
| p0_market750 | 02-scope#c001 | yes | yes |
| p0_market750 | 10-market#c002 | yes | yes |
| p0_ses_expand | 23-solar.md#c003 | NO | yes |
| p0_sim | 22-askue.md#c015 | NO | yes |
| p0_units750 | 01-numbers#c000 | yes | yes |
| p0_units750 | 02-scope#c001 | NO | yes |
| p0_units750 | 21-orem.md#c003 | yes | yes |
| p0_units750 | 21-orem.md#c024 | yes | yes |
| p0_unprofitable | 21-orem.md#c017 | yes | yes |
| e_sim_kol | 22-askue.md#c015 | NO | yes |
| e_sim_upper | 22-askue.md#c015 | NO | yes |
| e_sim_hyphen | 22-askue.md#c015 | yes | yes |
| e_sim_phrase | 22-askue.md#c015 | NO | yes |
| e_sim_svyaz | 22-askue.md#c015 | NO | NO (артефакт разметки) |

Итог: baseline покрыл gold ≥1 чанком у 7/16, V2 — у 15/16.
Частичные промахи V2: p0_market750 (1 из 3 gold-чанков вне top-8)
и e_sim_svyaz (разметка).

## 3. LLM-телеметрия (добавлена)

`ai_engine.py`: потокобезопасные агрегированные счётчики
`llm_stats()` — requests, empty, finish_length, prompt/completion/
reasoning_tokens (когда прокси отдаёт), latency_ms. Без ключей,
текстов вопросов, БЗ и reasoning_content. `finish_reason=length`
только считается — повторов не добавлено (лимит 20 мин важнее).
`solution.py` печатает `llm={...}` в stderr-строке STATS.

Mock-проверки: finish_reason=stop/length, пустой content,
отсутствующий usage, лишние поля (`reasoning_content`, unknown
fields) — всё обработано, поведение генерации не изменилось.

## 4. Тесты и сборка

- `pytest tests/ -q` → **74 passed** (69 + 5 новых telemetry/pin).
- `npm run build` → OK. Backend smoke → **7/7**.
- ZIP E2E (subprocess, mock LLM) — в составе pytest, passed.
- Кандидатный `submission.zip`: ровно 6 корневых файлов.
  **SHA256: `866e38f6e12e2329b6751be90159b0b90f6cc3d2b4954a7cf10c079d74f7b424`**

## 5. Отличия кандидата от baseline `4461e7e` (score 0.4533)

1. `retrieval.py`: стеммер + SIM-нормализация + TOP_K default 8.
2. `solution.py`: пин env-конфигурации + `llm=` телеметрия в STATS.
3. `ai_engine.py`: счётчики llm_stats (поведение ответов неизменно).
4. `tests/`, `scripts/`, `docs/` — не входят в ZIP.
`prompts.py`, `kb_loader.py`, `requirements.txt` — идентичны baseline.

## 6. Нерешённые риски

- **G1 (главный):** thinking-mode Qwen3.8-27B (xhigh, включён по
  умолчанию) может исчерпать max_tokens=1200 на reasoning →
  пустые/обрезанные ответы. Телеметрия `finish_length`/
  `reasoning_tokens` в STATS даст ответ после прогона.
- KB-QA-046 и p0_market750#c004 — gold вне top-8 (phrase/bigram —
  следующий retrieval-эксперимент).
- `e_sim_svyaz` — артефакт разметки, не дефект.
- Качество генерации на 8 чанках vs 5 не проверено живой моделью.
- 60с таймаут может быть мал при xhigh-мышлении (LLM_TIMEOUT
  остаётся env-настраиваемым; в solution не пинится).

## 7. Готовность

Кандидат функционально готов к ОДНОМУ официальному сабмиту:
конфигурация зафиксирована, телеметрия даст данные для следующего
решения (thinking/params/промпты), baseline сохранён тегом
`mts-score-0.4533`. Загрузка ZIP — по решению после отчёта.
