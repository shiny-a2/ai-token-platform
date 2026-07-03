"""Daily backup: SQLite db + storage/ into a dated zip under backups/.

Retention: zips older than RETENTION_DAYS are deleted.
Run manually or via the scheduled task:
    .venv\\Scripts\\python.exe scripts\\backup.py
"""
from __future__ import annotations

import sqlite3
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import BACKUP_DIR, DATA_DIR, STORAGE_DIR  # noqa: E402

RETENTION_DAYS = 30


def snapshot_sqlite(src: Path, dst: Path) -> None:
    """Consistent copy even while the app is writing (sqlite backup API).

    Note: sqlite3's context manager does NOT close connections — close
    explicitly or the snapshot file stays locked on Windows.
    """
    conn = sqlite3.connect(str(src))
    out = sqlite3.connect(str(dst))
    try:
        conn.backup(out)
    finally:
        out.close()
        conn.close()


def main() -> int:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_path = BACKUP_DIR / f"backup_{stamp}.zip"

    db_src = DATA_DIR / "app.db"
    db_snap = BACKUP_DIR / f"_snap_{stamp}.db"
    if db_src.exists():
        snapshot_sqlite(db_src, db_snap)

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if db_snap.exists():
                zf.write(db_snap, "app.db")
            if STORAGE_DIR.exists():
                for f in STORAGE_DIR.rglob("*"):
                    if f.is_file():
                        zf.write(f, f"storage/{f.relative_to(STORAGE_DIR)}")
    finally:
        db_snap.unlink(missing_ok=True)

    # retention
    cutoff = time.time() - RETENTION_DAYS * 86400
    removed = 0
    for old in BACKUP_DIR.glob("backup_*.zip"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
            removed += 1

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"backup ok: {zip_path.name} ({size_mb:.1f} MB); removed {removed} old")
    return 0


if __name__ == "__main__":
    sys.exit(main())
