"""End-to-end smoke test backend API.

Проверяет: health -> create session (token) -> chat (MOCK) -> history -> lead.
Запуск: python scripts/smoke_test.py [--base-url http://localhost:8000]
Использует только stdlib (urllib), зависимостей не требует.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
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
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
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
    token = body.get("token", "")
    results.append(
        check(
            "POST /api/sessions",
            code == 201 and bool(session_id) and bool(token),
            f"HTTP {code}, token={'yes' if token else 'NO'}",
        )
    )

    code, body = request(
        "POST",
        f"{base}/api/chat",
        {"session_id": session_id, "message": "Smoke test: хотим контролировать расход электроэнергии.", "session_token": token},
    )
    ok = (
        code == 200
        and bool(body.get("answer"))
        and isinstance(body.get("sources"), list)
        and "latency_ms" in body
        and "suggest_lead" in body
    )
    results.append(check("POST /api/chat", ok, f"HTTP {code}, ai_status={body.get('ai_status')}"))

    # Без токена история закрыта
    code_wo, _ = request("GET", f"{base}/api/sessions/{session_id}/messages")
    results.append(check("GET messages без токена -> 403", code_wo == 403, f"HTTP {code_wo}"))

    qs = urllib.parse.urlencode({"token": token})
    code, body = request("GET", f"{base}/api/sessions/{session_id}/messages?{qs}")
    msgs = body.get("messages", [])
    results.append(check("GET messages", code == 200 and len(msgs) >= 2, f"HTTP {code}, {len(msgs)} msgs"))

    code, body = request(
        "POST",
        f"{base}/api/leads",
        {
            "name": "Smoke Test",
            "phone": "+7 900 000-00-00",
            "company": "Test Co",
            "session_id": session_id,
            "session_token": token,
        },
    )
    lead_ok = (
        code == 201
        and body.get("id")
        and body.get("phone") == "+79000000000"
        and "summary" in body
        and "conversation_snapshot" in body
    )
    results.append(check("POST /api/leads", lead_ok, f"HTTP {code}, phone={body.get('phone')}"))

    # GET /api/leads доступен только при EXPOSE_LEADS=1 — принимаем 200 или 404.
    code, body = request("GET", f"{base}/api/leads")
    leads_ok = code == 404 or (code == 200 and isinstance(body.get("leads"), list))
    results.append(check("GET /api/leads (gated)", leads_ok, f"HTTP {code}"))

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
