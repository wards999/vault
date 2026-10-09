"""Shared set-up for Vault's tests. Every test imports this first, before vault or store:

- the repo folder goes on sys.path;
- WORK is a temporary folder (shared by run_all.py, or a fresh one) holding the test databases
  from fixtures.py, plus anything a test writes;
- settings and backups go to WORK (VAULT_SETTINGS / VAULT_BACKUPS), never the real ones;
- QProcess.startDetached raises: a test must never start another copy of anything.

Tests print "OK ..." / "FAIL ..." lines; run_all.py treats a FAIL line, a traceback or a timeout as a failure.
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

WORK = Path(os.environ.get("VAULT_TEST_WORK") or tempfile.mkdtemp(prefix="vault-tests-"))
WORK.mkdir(parents=True, exist_ok=True)
os.environ["VAULT_SETTINGS"] = str(WORK / f"settings-{Path(sys.argv[0]).stem}.ini")
Path(os.environ["VAULT_SETTINGS"]).unlink(missing_ok=True)  # every test starts with default settings
os.environ["VAULT_BACKUPS"] = str(WORK / "backups")

import fixtures  # noqa: E402
fixtures.build(WORK)

from PySide6.QtCore import QProcess  # noqa: E402


def _no_processes(*args, **kwargs):
    raise RuntimeError("tests must not start processes")


QProcess.startDetached = staticmethod(_no_processes)

PW = fixtures.PW
_failures = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        _failures.append(label)
    return cond


def wait(cond, timeout=20):
    from PySide6.QtTest import QTest
    end = time.time() + timeout
    while not cond() and time.time() < end:
        QTest.qWait(50)
    return cond()


def finish():
    print(f"--- {'ALL PASSED' if not _failures else str(len(_failures)) + ' FAILED'}", flush=True)
    sys.stdout.flush()
    os._exit(1 if _failures else 0)


def skip(reason):
    print(f"SKIP {reason}", flush=True)
    sys.stdout.flush()
    os._exit(0)


def copy_db(name, new_name):
    """A fresh copy of a test database (tests change their copy, never the original)."""
    shutil.copy(WORK / name, WORK / new_name)
    return WORK / new_name


def need_cli():
    """keepassxc-cli, to check files the way KeePassXC sees them; skips the test without it."""
    for candidate in (shutil.which("keepassxc-cli"), r"C:\Program Files\KeePassXC\keepassxc-cli.exe",
                      "/Applications/KeePassXC.app/Contents/MacOS/keepassxc-cli"):
        if candidate and Path(candidate).exists():
            return candidate
    skip("KeePassXC (keepassxc-cli) isn't installed")


def need_network():
    """Tests that download site icons: only with VAULT_TEST_NETWORK=1."""
    if os.environ.get("VAULT_TEST_NETWORK") != "1":
        skip("needs the internet (set VAULT_TEST_NETWORK=1)")
