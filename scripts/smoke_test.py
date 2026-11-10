"""End-to-end smoke test backend API.

Проверяет: health -> create session -> chat (MOCK) -> history -> lead.
Запуск: python scripts/smoke_test.py [--base-url http://localhost:8000]
Использует только stdlib (urllib), зависимостей не требует.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "http://localhost:8000"


def request(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    base = DEFAULT_BASE
    if "--base-url" in sys.argv:
        base = sys.argv[sys.argv.index("--base-url") + 1]

    results: list[bool] = []

    code, body = request("GET", f"{base}/api/health")
    results.append(check("GET /api/health", code == 200 and body.get("status") == "ok", f"HTTP {code}"))

    code, body = request("POST", f"{base}/api/sessions", {})
    session_id = body.get("id", "")
    results.append(check("POST /api/sessions", code == 201 and bool(session_id), f"HTTP {code}, id={session_id[:8]}..."))

    code, body = request(
        "POST",
        f"{base}/api/chat",
        {"session_id": session_id, "message": "Smoke test: хотим контролировать расход электроэнергии."},
    )
    ok = (
        code == 200
        and bool(body.get("answer"))
        and isinstance(body.get("sources"), list)
        and "latency_ms" in body
        and "suggest_lead" in body
    )
    results.append(check("POST /api/chat", ok, f"HTTP {code}, ai_status={body.get('ai_status')}"))

    code, body = request("GET", f"{base}/api/sessions/{session_id}/messages")
    msgs = body.get("messages", [])
    results.append(check("GET messages", code == 200 and len(msgs) >= 2, f"HTTP {code}, {len(msgs)} msgs"))

    code, body = request(
        "POST",
        f"{base}/api/leads",
        {"name": "Smoke Test", "phone": "+7 000 000-00-00", "company": "Test Co", "session_id": session_id},
    )
    results.append(check("POST /api/leads", code == 201 and body.get("id"), f"HTTP {code}"))

    code, body = request("GET", f"{base}/api/leads")
    results.append(check("GET /api/leads", code == 200 and isinstance(body.get("leads"), list), f"HTTP {code}"))

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
