# Groq Eval Lab — локальная лаборатория LLM-тестов

Изолированная песочница для проверки гипотез генерации **до**
официальных сабмитов МТС. Работает только с **синтетической БЗ**
(`synth_kb.py`) — вымышленные компании «ТехноУчёт», «Вектор-А»,
«ТеплоСеть-М», «ОптАналитик», «СтатусГард». Реальная БЗ МТС,
конкурсные вопросы и `knowledge-base.zip` сюда не загружаются
и никуда не отправляются.

## Модель и доступ

- API: `https://api.groq.com/openai/v1` (OpenAI-compatible)
- Model: `qwen/qwen3.8-27b`
- Ключ: только `GROQ_API_KEY` — в `research/qwen_eval/.env`
  (gitignored) или в окружении. Ключ не попадает в код/логи/Git.
- Параметры первого эксперимента (фиксированы, НЕ обязательно
  совпадают с прокси МТС): `temperature=0.6`,
  `max_completion_tokens=2048`, `top_p=0.95`,
  `reasoning_effort=default`.

## Структура

```
research/qwen_eval/
├── groq_client.py    # клиент API: budget, retry 429/5xx, extract answer
├── synth_kb.py       # синтетическая БЗ (10 чанков, вымышленные продукты)
├── cases.py          # 20 кейсов: факты, запреты, ожидаемое поведение
├── prompts_eval.py   # режим A (baseline) / B (answer-first)
├── evaluate.py       # эвристики: coverage, forbidden, refusal, length
├── run_eval.py       # CLI: check / smoke / run / report
├── tests/            # офлайн-тесты без сети
├── data/             # JSONL прогонов (gitignored)
└── reports/          # Markdown-отчёты (gitignored)
```

## Команды (PowerShell, из корня репозитория)

```powershell
# 0. Один раз — проверить кейсы без сети
.\backend\.venv\Scripts\python.exe research\qwen_eval\run_eval.py check

# 1. Один безопасный smoke-вызов (синтетика)
.\backend\.venv\Scripts\python.exe research\qwen_eval\run_eval.py smoke

# 2. Офлайн-тесты (без API)
.\backend\.venv\Scripts\python.exe -m pytest research\qwen_eval\tests -q

# 3. A/B прогон: 20 кейсов × 2 режима = 40 запросов
.\backend\.venv\Scripts\python.exe research\qwen_eval\run_eval.py run --max-requests 45 --delay 0.5

# 4. Отчёт по последнему прогону
.\backend\.venv\Scripts\python.exe research\qwen_eval\run_eval.py report

# 5. Переоценка сохранённых ответов (офлайн, evaluator v2 + manual_labels)
.\backend\.venv\Scripts\python.exe research\qwen_eval\run_eval.py recheck

# 6. H5-эксперимент (holdout, 8 кейсов × A/H5 = 16 запросов) — вручную:
.\backend\.venv\Scripts\python.exe research\qwen_eval\run_eval.py run --case-set h5 --modes AH5 --max-requests 20 --delay 10
```

`run` последовательно вызывает модель; лимит запросов
(`--max-requests`, default 45) и повторы при 429/5xx встроены —
при исчерпании бюджета прогон останавливается и сохраняет
частичный JSONL.

## Что измеряется

На каждый ответ: покрытие обязательных фактов (группы-альтернативы),
запрещённые утверждения, чрезмерный отказ, длина, finish_reason,
usage, latency. Эвристики — черновые: кейсы с проблемами помечаются
`needs_manual_review` и выносятся на ручную проверку. Это **не**
официальный score МТС.

## Режимы A/B

- **A** — нейтральный промпт (факты только из контекста, уточнение
  при нехватке).
- **B** — то же + единственное отличие: «сначала прямой ответ,
  затем ограничения, затем уточнение» (answer-first, гипотеза H2).

Retrieval, reasoning_effort, temperature и длина генерации между
режимами НЕ меняются.

## Дальнейшие эксперименты (не смешивать с A/B)

- `reasoning_effort`: default vs high — отдельный прогон.
- Контекст: подбор TOP-K/состава чанков — отдельный прогон.
