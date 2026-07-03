"""End-to-end Mini App API test with genuinely signed initData.

Uses a FAKE bot token via env override so the test app never starts polling
(the live server keeps the real token). initData is signed with the same fake
token, so signature validation is exercised for real.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set BEFORE importing app.config (settings are cached at import).
FAKE_TOKEN = "1234567:FAKE-test-token-no-polling"
os.environ["BOT_TOKEN"] = FAKE_TOKEN

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from run import app  # noqa: E402

TEST_ID = 987654321


def sign_init_data(user_id: int, first_name: str = "تستر") -> str:
    user = json.dumps(
        {"id": user_id, "first_name": first_name, "username": "tester",
         "language_code": "fa"},
        separators=(",", ":"), ensure_ascii=False,
    )
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "AAtest",
        "user": user,
    }
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", FAKE_TOKEN.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def main() -> int:  # noqa: PLR0915
    assert settings.bot_token == FAKE_TOKEN, "env override failed"
    user_h = {"X-Init-Data": sign_init_data(TEST_ID)}
    admin_h = {"X-Init-Data": sign_init_data(settings.admin_telegram_id, "Admin")}

    with TestClient(app) as c:
        # 0) mini app page served
        r = c.get("/app")
        assert r.status_code == 200 and "AI Token" in r.text
        print("GET /app: ok")

        # 1) auth: no header -> 401 ; tampered -> 401
        assert c.get("/api/webapp/bootstrap").status_code == 401
        bad = user_h["X-Init-Data"].replace("hash=", "hash=0")
        assert c.get("/api/webapp/bootstrap",
                     headers={"X-Init-Data": bad}).status_code == 401
        print("auth rejections: ok")

        # 2) bootstrap
        r = c.get("/api/webapp/bootstrap", headers=user_h)
        assert r.status_code == 200, r.text
        boot = r.json()
        assert boot["user"]["is_admin"] is False
        assert len(boot["modes"]) >= 5
        assert len(boot["packages"]) >= 1
        print(f"bootstrap: ok ({len(boot['modes'])} modes, "
              f"{len(boot['packages'])} packages)")

        # 3) admin gating: normal user must NOT reach admin endpoints
        assert c.get("/api/webapp/admin/users", headers=user_h).status_code == 403
        print("admin gate: ok")

        # 4) set mode
        r = c.post("/api/webapp/mode", headers=user_h, json={"code": "fast_chat"})
        assert r.json()["default_mode"] == "fast_chat"
        print("set mode: ok")

        # 5) estimate
        r = c.post("/api/webapp/chat/estimate", headers=user_h,
                   json={"text": "سلام! یک جمله درباره تهران بگو.", "mode": "fast_chat"})
        est = r.json()
        assert est["min"] >= 1 and est["max"] >= est["min"]
        print(f"estimate: ok (min={est['min']} max={est['max']} "
              f"balance={est['balance']})")

        # 6) admin: find test user id + top-up so the send gate passes
        r = c.get("/api/webapp/admin/users", headers=admin_h)
        assert r.status_code == 200, r.text
        users = r.json()
        uid = next(u["id"] for u in users if u["telegram_id"] == TEST_ID)
        r = c.post(f"/api/webapp/admin/users/{uid}/adjust", headers=admin_h,
                   json={"delta_total": 500, "expiry_days": 30})
        assert r.json()["ok"] and r.json()["remaining"] >= 500 - est["balance"]
        print("admin adjust: ok")

        # 7) real chat turn (tiny, cheap, via real OpenAI key)
        r = c.post("/api/webapp/chat/send", headers=user_h,
                   json={"text": "فقط بگو: سلام", "mode": "fast_chat",
                         "cap": est["max"] + 10})
        body = r.json()
        assert body.get("ok"), body
        assert body["reply"].strip() and body["charged"] >= 1 and body["conv_id"]
        conv_id = body["conv_id"]
        print(f"chat send: ok (charged={body['charged']} "
              f"remaining={body['remaining']})")

        # 8) chats + messages persisted
        r = c.get("/api/webapp/chats", headers=user_h)
        assert any(ch["id"] == conv_id for ch in r.json())
        r = c.get(f"/api/webapp/chats/{conv_id}/messages", headers=user_h)
        msgs = r.json()["messages"]
        assert len(msgs) >= 2 and msgs[-1]["role"] == "assistant"
        print("history: ok")

        # 8b) another user must NOT read this conversation
        other_h = {"X-Init-Data": sign_init_data(TEST_ID + 1, "دیگری")}
        assert c.get(f"/api/webapp/chats/{conv_id}/messages",
                     headers=other_h).status_code == 404
        print("conversation isolation: ok")

        # 9) usage
        r = c.get("/api/webapp/usage", headers=user_h)
        u = r.json()
        assert any(pm["mode"] == "fast_chat" for pm in u["per_mode"])
        print("usage: ok")

        # 10) receipt (txid) -> pending -> admin reject (leave db clean)
        pkg_id = boot["packages"][0]["id"]
        r = c.post("/api/webapp/receipt", headers=user_h,
                   data={"package_id": pkg_id, "txid": "TEST-TX-123"})
        assert r.json()["ok"], r.text
        rec_id = r.json()["receipt_id"]
        r = c.get("/api/webapp/admin/overview", headers=admin_h)
        assert any(p["id"] == rec_id for p in r.json()["pending"])
        r = c.post(f"/api/webapp/admin/receipts/{rec_id}/reject", headers=admin_h,
                   json={"note": "تست خودکار"})
        assert r.json()["ok"]
        print("receipt flow: ok")

        # 11) settings: language ok for everyone; unrestricted is ADMIN-ONLY
        r = c.post("/api/webapp/settings", headers=user_h, json={"language": "en"})
        assert r.json()["language"] == "en"
        r = c.post("/api/webapp/settings", headers=user_h,
                   json={"unrestricted": True})
        assert r.status_code == 403, "non-admin must NOT toggle unrestricted"
        r = c.post("/api/webapp/settings", headers=admin_h,
                   json={"unrestricted": True})
        assert r.status_code == 200 and r.json()["unrestricted"] is True
        c.post("/api/webapp/settings", headers=admin_h, json={"unrestricted": False})
        c.post("/api/webapp/settings", headers=user_h, json={"language": "fa"})
        print("settings + unrestricted admin-gate: ok")

        # 12) client-supplied cap must be IGNORED (server derives its own)
        r = c.post("/api/webapp/chat/send", headers=user_h,
                   json={"text": "فقط بگو: باشه", "mode": "fast_chat", "cap": 0})
        body = r.json()
        assert body.get("ok") and body["charged"] >= 1, \
            f"cap=0 must not zero the charge: {body}"
        print(f"server-side cap enforcement: ok (charged={body['charged']})")

        # 13) file upload -> estimate grows -> charged Q&A about the file
        secret = "زرافه آبی ۴۲"
        content = ("گزارش داخلی\n" + ("متن پرکننده. " * 300)
                   + f"\nرمز پروژه: {secret}\n")
        r = c.post("/api/webapp/chat/upload", headers=user_h,
                   files={"file": ("report.txt", content.encode("utf-8"),
                                   "text/plain")})
        assert r.status_code == 200, r.text
        up = r.json()
        assert up["file_id"] and up["tokens"] > 100
        base = c.post("/api/webapp/chat/estimate", headers=user_h,
                      json={"text": "رمز چیست؟", "mode": "fast_chat"}).json()
        with_file = c.post("/api/webapp/chat/estimate", headers=user_h,
                           json={"text": "رمز چیست؟", "mode": "fast_chat",
                                 "file_id": up["file_id"]}).json()
        assert with_file["in_tokens"] > base["in_tokens"] + 100, \
            "file tokens must be billed into the estimate"
        r = c.post("/api/webapp/chat/send", headers=user_h,
                   json={"text": "طبق فایل پیوست، رمز پروژه دقیقاً چیست؟ فقط خود رمز را بنویس.",
                         "mode": "fast_chat", "file_id": up["file_id"]})
        body = r.json()
        assert body.get("ok") and body["charged"] >= 1, body
        assert "زرافه" in body["reply"], f"file content unused? reply={body['reply'][:120]}"
        print(f"file Q&A: ok (file={up['tokens']}tok, charged={body['charged']})")

        # 13b) another user must NOT use my file
        r = c.post("/api/webapp/chat/estimate", headers=other_h,
                   json={"text": "رمز چیست؟", "mode": "fast_chat",
                         "file_id": up["file_id"]})
        assert r.json()["in_tokens"] <= base["in_tokens"] + 20, \
            "foreign file_id must be ignored"
        print("file isolation: ok")

        # 14) export needs the bot (offline in tests) -> clean 503
        r = c.post("/api/webapp/export", headers=user_h,
                   json={"text": "hello", "filename": "x.md"})
        assert r.status_code == 503
        print("export gating: ok")

        # 15) bogus TxID -> verification fails -> stays pending (not auto-approved)
        r = c.post("/api/webapp/receipt", headers=user_h,
                   data={"package_id": pkg_id, "txid": "a" * 64})
        body = r.json()
        assert body["ok"] and body.get("auto_approved") is False, body
        rec2 = body["receipt_id"]
        c.post(f"/api/webapp/admin/receipts/{rec2}/reject", headers=admin_h,
               json={"note": "تست"})
        print("crypto verify plumbing: ok (bogus txid stayed pending)")

    print("ALL WEBAPP TESTS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
