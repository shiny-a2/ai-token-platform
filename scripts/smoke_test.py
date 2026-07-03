"""In-process smoke test: boots the app (lifespan seeds db) and hits every page."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.config import settings
from run import app

PAGES = [
    "/admin", "/admin/users", "/admin/receipts", "/admin/packages",
    "/admin/modes", "/admin/conversations", "/admin/usage",
    "/admin/payment-methods", "/admin/api-keys", "/admin/settings",
]


def main() -> int:
    failures = []
    with TestClient(app) as client:
        # health
        r = client.get("/health")
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        print("health: ok")

        # unauthenticated dashboard -> redirect to login
        r = client.get("/admin", follow_redirects=False)
        assert r.status_code in (303, 307), r.status_code
        print("auth gate: redirect ok")

        # login page
        r = client.get("/admin/login")
        assert r.status_code == 200 and "رمز عبور" in r.text
        print("login page: ok")

        # login
        r = client.post(
            "/admin/login",
            data={"password": settings.admin_panel_password},
            follow_redirects=False,
        )
        assert r.status_code == 303, r.status_code
        print("login: ok")

        # every page renders
        for path in PAGES:
            r = client.get(path)
            if r.status_code != 200:
                failures.append(f"{path} -> {r.status_code}")
            else:
                print(f"{path}: {r.status_code}")

        # create a package via the form, confirm it persists
        r = client.post(
            "/admin/packages/create",
            data={"name": "SmokePkg", "price_usd": "4", "ai_tokens": "7000",
                  "validity_days": "30"},
            follow_redirects=True,
        )
        assert "SmokePkg" in r.text, "package create failed"
        print("package create: ok")

    # cleanup: remove test packages so they never show to real users
    import asyncio

    from sqlalchemy import delete

    from app.db import SessionLocal
    from app.models import Package

    async def _cleanup():
        async with SessionLocal() as db:
            await db.execute(delete(Package).where(Package.name == "SmokePkg"))
            await db.commit()

    asyncio.run(_cleanup())
    print("cleanup: ok")

    if failures:
        print("FAILURES:", failures)
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
