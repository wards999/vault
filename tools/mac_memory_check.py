"""Where does Vault's memory go on macOS? Measures the figure Activity Monitor shows ("Memory", the
physical footprint) at each step of starting, unlocking and minimising Vault, what each Mac-only
library costs on its own (each in a fresh process), and macOS's own breakdown (`footprint`) of the
running app. Run on a Mac (see .github/workflows/mac-memory-check.yml):
    python tools/mac_memory_check.py
"""
import ctypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()) / "vault-memcheck"
DB = WORK / "memcheck.kdbx"
PW = "memcheck-pw"
ENTRIES = 640  # about the size of a real database


def footprint_mb():
    """Activity Monitor's "Memory" for this process: phys_footprint from proc_pid_rusage."""
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    buf = (ctypes.c_uint64 * 64)()
    libc.proc_pid_rusage(os.getpid(), 0, buf)  # RUSAGE_INFO_V0: 16-byte uuid, then uint64 fields
    return buf[2 + 7] / 2**20  # ri_phys_footprint


def resident_mb():
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    buf = (ctypes.c_uint64 * 64)()
    libc.proc_pid_rusage(os.getpid(), 0, buf)
    return buf[2 + 6] / 2**20  # ri_resident_size


_last = [0.0]
_rows = []


def mark(label):
    now = footprint_mb()
    row = f"{label:<58} {now:6.0f} MB  ({now - _last[0]:+5.0f})   resident {resident_mb():5.0f} MB"
    _last[0] = now
    _rows.append(row)
    print(row, flush=True)


def macos_breakdown(title):
    """macOS's own split of this process's footprint by kind (IOSurface, malloc, images…)."""
    for cmd in (["footprint", str(os.getpid())], ["sudo", "-n", "footprint", str(os.getpid())]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0 and r.stdout.strip():
            print(f"\n--- footprint: {title}\n{r.stdout}", flush=True)
            return r.stdout
    print(f"\n--- footprint: {title}: not available", flush=True)
    return ""


def build_db():
    from pykeepass import create_database
    WORK.mkdir(parents=True, exist_ok=True)
    DB.unlink(missing_ok=True)
    kp = create_database(str(DB), password=PW)
    kp.kdbx.header.value.minor_version = 1
    folders = [kp.add_group(kp.root_group, name) for name in ("Work", "Personal", "Banking", "Shopping", "Email")]
    for i in range(ENTRIES):
        e = kp.add_entry(folders[i % len(folders)], f"Site {i}", f"user{i}@example.com", f"pw-{i}-Xq9!zz{i * 7}",
                         url=f"https://site{i}.example.com", notes="Some notes\n" * (i % 4))
        for n in range(i % 3):  # a little history, as real entries have
            e.password = f"old-{n}-{i}"
            e.save_history()
    kp.save()


# Each in a fresh process: what one library costs by itself.
ISOLATED = {
    "bare Python": "",
    "import objc (pyobjc core)": "import objc",
    "import Foundation": "import Foundation",
    "import AppKit": "import AppKit",
    "import LocalAuthentication": "import LocalAuthentication",
    "objc.lookUpClass NSWorkspace + NSDistributedNotificationCenter":
        "import objc; objc.lookUpClass('NSWorkspace').sharedWorkspace(); objc.lookUpClass('NSDistributedNotificationCenter').defaultCenter()",
    "import pykeepass": "import pykeepass",
    "import zxcvbn + one check": "from zxcvbn import zxcvbn; zxcvbn('Correct-Horse-9')",
    "QApplication": "from PySide6.QtWidgets import QApplication; app = QApplication([])",
    "QApplication + import qfluentwidgets":
        "from PySide6.QtWidgets import QApplication; app = QApplication([]); import qfluentwidgets",
    "QApplication + empty 1400x900 window shown":
        "from PySide6.QtWidgets import QApplication, QWidget; from PySide6.QtTest import QTest; app = QApplication([]);"
        " w = QWidget(); w.resize(1400, 900); w.show(); QTest.qWaitForWindowExposed(w); QTest.qWait(1500)",
}


def isolated(code):
    script = (f"import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); import mac_memory_check as m\n"
              f"before = m.footprint_mb()\n{code}\nprint(f'RESULT {{m.footprint_mb():.0f}} {{m.footprint_mb() - before:.0f}}')")
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=300)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), None)
    if not line:
        return f"FAILED: {r.stderr.strip()[-300:]}"
    total, extra = line.split()[1:]
    return f"total {total:>4} MB   (+{extra} MB for this)"


def app_run():
    """Vault as it really starts, step by step, in this process."""
    os.environ["VAULT_SETTINGS"] = str(WORK / "settings.ini")
    os.environ["VAULT_BACKUPS"] = str(WORK / "backups")
    Path(os.environ["VAULT_SETTINGS"]).unlink(missing_ok=True)
    sys.path.insert(0, str(REPO))
    mark("Python started")
    import pykeepass  # noqa: F401  (Vault loads it in the background at start)
    mark("pykeepass imported")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    app = QApplication(sys.argv)
    mark("QApplication")
    import vault
    import store
    mark("vault + qfluentwidgets imported")
    vault.use_system_ui_font()
    vault.apply_theme(vault.theme_name())
    w = vault.MainWindow()
    vault.apply_theme(vault.theme_name(), w)
    mark(f"MainWindow created (AppKit loaded: {'AppKit' in sys.modules})")
    w.resize(1400, 900)
    w.show()
    QTest.qWaitForWindowExposed(w)
    QTest.qWait(1500)
    mark(f"window shown 1400x900 (device pixel ratio {w.devicePixelRatioF():g})")
    db = store.Database(DB, PW, "")
    mark(f"database decrypted ({len(db.entries)} entries)")
    w.vault.load(db)
    w.saver.attach(db)
    w.locked = False
    w.vault.refresh()
    QTest.qWait(6000)  # includes the health check (zxcvbn) 1.5 s after loading
    mark("unlocked, shown in the list, health checked")
    e = db.entries[0]
    w.vault.refresh(select_uuid=e["uuid"])
    QTest.qWait(1500)
    mark("an entry selected")
    macos_breakdown("unlocked, window showing")
    _last[0] = footprint_mb()
    w.showMinimized()
    QTest.qWait(3000)
    mark("minimised 3 s (Vault's own trim ran at 1.5 s)")
    QTest.qWait(30000)
    mark("minimised 33 s")
    macos_breakdown("minimised")
    _last[0] = footprint_mb()
    w.showNormal()
    QTest.qWait(2000)
    mark("restored")
    w.lock()
    QTest.qWait(4000)
    mark("locked 4 s (database dropped, trimmed at 2 s)")
    print("\nLoaded Qt plugins/frameworks:", flush=True)
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    libc._dyld_get_image_name.restype = ctypes.c_char_p
    names = [libc._dyld_get_image_name(i).decode() for i in range(libc._dyld_image_count())]
    for n in sorted(n for n in names if "/Qt" in n or "PySide6" in n or "plugins" in n):
        print("  ", n.split("site-packages/")[-1])
    print(f"({len(names)} images loaded in all)", flush=True)
    os._exit(0)


def main():
    print(f"macOS {subprocess.run(['sw_vers', '-productVersion'], capture_output=True, text=True).stdout.strip()},"
          f" Python {sys.version.split()[0]}", flush=True)
    subprocess.run([sys.executable, __file__, "--build"], check=True)
    print("\n=== each library on its own (fresh process each)", flush=True)
    for name, code in ISOLATED.items():
        print(f"{name:<62} {isolated(code)}", flush=True)
    print("\n=== Vault, step by step (Activity Monitor's \"Memory\")", flush=True)
    r = subprocess.run([sys.executable, __file__, "--app"], timeout=600)
    sys.exit(r.returncode)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--build"]:
        build_db()
    elif sys.argv[1:2] == ["--app"]:
        app_run()
    else:
        main()
