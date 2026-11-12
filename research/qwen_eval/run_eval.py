"""CLI Groq Eval Lab.

Команды (PowerShell, из корня репозитория):

  # 1. Проверка кейсов без сети
  backend\\.venv\\Scripts\\python.exe research\\qwen_eval\\run_eval.py check

  # 2. Один безопасный smoke-вызов (синтетика, не МТС)
  backend\\.venv\\Scripts\\python.exe research\\qwen_eval\\run_eval.py smoke

  # 3. A/B прогон: 20 кейсов × 2 режима = 40 запросов
  backend\\.venv\\Scripts\\python.exe research\\qwen_eval\\run_eval.py run --max-requests 45

  # 4. Отчёт по последнему прогону
  backend\\.venv\\Scripts\\python.exe research\\qwen_eval\\run_eval.py report

СЕТЬ вызывается только в smoke/run. check/report — полностью офлайн.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cases as cases_mod  # noqa: E402
import evaluate  # noqa: E402
import groq_client  # noqa: E402
import prompts_eval  # noqa: E402
import synth_kb  # noqa: E402

DATA_DIR = HERE / "data"
REPORTS_DIR = HERE / "reports"


def cmd_check() -> int:
    errors = cases_mod.validate_cases()
    if errors:
        for e in errors:
            print("ERROR:", e)
        return 1
    print(f"OK: {len(cases_mod.CASES)} cases, {len(synth_kb.CHUNKS)} synthetic chunks")
    return 0


def cmd_smoke() -> int:
    budget = groq_client.Budget(max_requests=1)
    messages = [
        {"role": "system", "content": "Ты — тестовый ассистент. Ответь одним словом."},
        {"role": "user", "content": "Скажи 'работает'."},
    ]
    print(f"POST {groq_client.API_URL} model={groq_client.MODEL}")
    try:
        resp = groq_client.chat(messages, budget)
    except Exception as exc:  # noqa: BLE001
        print("FAIL:", exc)
        return 1
    answer, meta = groq_client.extract_answer(resp)
    print(f"HTTP {meta['status']} | {meta['latency_ms']} ms")
    print(f"finish_reason={meta['finish_reason']} usage={meta['usage']}")
    print(f"answer={answer[:300]!r}")
    return 0


def cmd_run(args) -> int:
    errors = cases_mod.validate_cases()
    if errors:
        print("Fix cases first:", errors)
        return 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    resume_path = Path(args.resume) if args.resume else None
    done_pairs: set[tuple[str, str]] = set()
    if resume_path and resume_path.exists():
        for line in resume_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if "answer" in r:
                done_pairs.add((r["case_id"], r["mode"]))
        ts = json.loads(resume_path.read_text(encoding="utf-8").splitlines()[0])["run_id"]
        out_path = resume_path
        print(f"resuming {out_path}: {len(done_pairs)} pairs already answered")
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_path = DATA_DIR / f"run_{ts}.jsonl"
    budget = groq_client.Budget(max_requests=args.max_requests)
    done = skipped = 0

    with out_path.open("a", encoding="utf-8") as f:
        for case in cases_mod.CASES:
            context_text = synth_kb.format_context(case["context_ids"])
            for mode in ("A", "B"):
                if (case["case_id"], mode) in done_pairs:
                    continue
                messages = prompts_eval.build_messages(
                    prompts_eval.mode_system(mode), case["question"], context_text)
                record = {
                    "run_id": ts, "case_id": case["case_id"], "mode": mode,
                    "category": case["category"], "model": groq_client.MODEL,
                    "params": groq_client.GEN_PARAMS,
                    "prompt_version": prompts_eval.PROMPT_VERSION,
                    "question": case["question"],
                }
                try:
                    resp = groq_client.chat(messages, budget)
                    answer, meta = groq_client.extract_answer(resp)
                    record.update({
                        "answer": answer, "meta": meta,
                        "eval": evaluate.evaluate_answer(case, answer, meta),
                    })
                except groq_client.BudgetExhausted:
                    print("BUDGET exhausted — stopping.")
                    record["error"] = "budget_exhausted"
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    print(f"saved partial -> {out_path}")
                    return 0
                except Exception as exc:  # noqa: BLE001
                    record["error"] = str(exc)[:300]
                    skipped += 1
                    print(f"ERROR {case['case_id']}/{mode}: {exc}")
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                done += 1
                time.sleep(args.delay)

    print(f"done: {done} calls, {skipped} errors -> {out_path}")
    return 0


def cmd_report(args) -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    runs = sorted(DATA_DIR.glob("run_*.jsonl"))
    if not runs:
        print("no run_*.jsonl in data/")
        return 1
    run_path = Path(args.run) if args.run else runs[-1]
    records = [json.loads(line) for line in run_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # Сводка по режимам
    summary = {}
    for mode in ("A", "B"):
        recs = [r for r in records if r.get("mode") == mode and "eval" in r]
        summary[mode] = evaluate.aggregate([r["eval"] for r in recs])

    # Регрессии B vs A по case_id
    by_case = {}
    for r in records:
        if "eval" not in r:
            continue
        by_case.setdefault(r["case_id"], {})[r["mode"]] = r
    regressions, improvements = [], []
    for cid, modes in by_case.items():
        if "A" in modes and "B" in modes:
            a, b = modes["A"]["eval"], modes["B"]["eval"]
            score_a = a["coverage"]["covered"] - len(a["forbidden_hits"]) - a["excessive_refusal"]
            score_b = b["coverage"]["covered"] - len(b["forbidden_hits"]) - b["excessive_refusal"]
            if score_b < score_a:
                regressions.append(cid)
            elif score_b > score_a:
                improvements.append(cid)

    out_md = REPORTS_DIR / f"report_{run_path.stem}.md"
    with out_md.open("w", encoding="utf-8") as f:
        f.write(f"# Groq Eval Report — {run_path.stem}\n\n")
        f.write(f"- model: `{groq_client.MODEL}`\n")
        f.write(f"- params: `{json.dumps(groq_client.GEN_PARAMS, ensure_ascii=False)}`\n")
        f.write(f"- prompt_version: `{prompts_eval.PROMPT_VERSION}`\n")
        f.write(f"- records: {len(records)}\n\n")
        f.write("## Aggregates\n\n```json\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n```\n\n")
        f.write(f"## B vs A: regressions={regressions} improvements={improvements}\n\n")
        f.write("## Cases (A | B side by side)\n\n")
        for r in records:
            if "answer" not in r:
                f.write(f"### {r['case_id']} [{r['mode']}] ERROR: {r.get('error')}\n\n")
                continue
            ev = r["eval"]
            f.write(f"### {r['case_id']} [{r['mode']}] ({r['category']})\n\n")
            f.write(f"**Q:** {r['question']}\n\n**A:**\n\n{r['answer']}\n\n")
            f.write(f"- coverage {ev['coverage']['covered']}/{ev['coverage']['total']}, "
                    f"missing={ev['missing_facts']}, forbidden={ev['forbidden_hits']}, "
                    f"refusal={ev['excessive_refusal']}, words={ev['length']['words']}, "
                    f"finish={ev['finish_reason']}, manual={ev['needs_manual_review']}\n\n")
    print(f"report -> {out_md}")
    print(json.dumps({"summary": summary, "regressions": regressions,
                      "improvements": improvements}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Groq Eval Lab (synthetic KB only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("smoke")
    p_run = sub.add_parser("run")
    p_run.add_argument("--max-requests", type=int, default=45)
    p_run.add_argument("--delay", type=float, default=0.5)
    p_run.add_argument("--resume", default=None,
                       help="JSONL прошлого прогона: пропустить уже отвеченные пары")
    p_rep = sub.add_parser("report")
    p_rep.add_argument("--run", default=None)
    args = ap.parse_args()
    return {"check": cmd_check, "smoke": cmd_smoke,
            "run": cmd_run, "report": cmd_report}[args.cmd](args) if args.cmd != "check" and args.cmd != "smoke" else {"check": cmd_check, "smoke": cmd_smoke}[args.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
