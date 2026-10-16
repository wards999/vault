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


def app_run(retina=False):
    """Vault as it really starts, step by step, in this process; then rounds of ordinary use, to see
    whether memory keeps growing. retina: drawn at 2x (as on a Retina screen); start-up only."""
    os.environ["VAULT_SETTINGS"] = str(WORK / f"settings{'-retina' if retina else ''}.ini")
    os.environ["VAULT_BACKUPS"] = str(WORK / "backups")
    if retina:
        os.environ["QT_SCALE_FACTOR"] = "2"
    Path(os.environ["VAULT_SETTINGS"]).unlink(missing_ok=True)
    sys.path.insert(0, str(REPO))
    mark("Python started")
    import pykeepass  # noqa: F401  (Vault loads it in the background at start)
    mark("pykeepass imported")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    app = QApplication(sys.argv)
    mark("QApplication")
    import vault
    import store
    mark("vault + qfluentwidgets imported")
    vault.settings.setValue("last_file", str(DB))  # the unlock dialog opens this database
    vault.settings.setValue("last_keyfile", "")
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

    def dialog():
        return next((d for d in w.findChildren(vault.UnlockDialog) if d.isVisible()), None)

    def unlock():
        QTimer.singleShot(0, w.lock)
        yield dialog
        d = dialog()
        d.pw.setText(PW)
        d.yesButton.click()
        yield lambda: not w.locked and w.vault.db is not None
        yield 1.0

    def steps():
        yield from unlock()  # the real way: the unlock dialog, as at every start
        yield 6.0  # includes the health check (zxcvbn) 1.5 s after loading
        mark(f"unlocked ({len(w.vault.db.entries)} entries), list shown, health checked")
        if retina:
            macos_breakdown("Retina (2x), unlocked")
            return
        macos_breakdown("unlocked, window showing")
        _last[0] = footprint_mb()
        w.showMinimized()
        yield 33.0
        mark("minimised 33 s (Vault's own trim ran at 1.5 s)")
        w.showNormal()
        yield 2.0
        mark("restored")

        print("\n=== rounds of ordinary use (does memory keep growing?)", flush=True)
        for rnd in range(1, 4):
            for i in range(60):  # browsing: select entries, search, clear the search
                entries = w.vault.db.entries
                w.vault.refresh(select_uuid=entries[(i * 37 + rnd) % len(entries)]["uuid"])
                w.vault.search.setText(f"site {i % 9}")
                yield 0.05
                w.vault.search.clear()
                yield 0.05
            mark(f"round {rnd}: 60 entries looked at, 60 searches")
            for i in range(20):  # copying passwords (with the "copied" message)
                w.copy_secret(f"pw-{i}", "Password")
                yield 0.1
            yield 3.0
            mark(f"round {rnd}: 20 passwords copied")
            for i in range(5):  # edits, each saved (encrypt, verify, write)
                e = w.vault.db.entries[(rnd * 5 + i) % len(w.vault.db.entries)]
                w.saver.submit(store.Op("update", e["uuid"], fields={"notes": f"edit {rnd}.{i}"},
                                        all_fields={**e["raw"], "notes": f"edit {rnd}.{i}"}, folder=e["folder_id"],
                                        base_mtime=e["base_mtime"], title=e["title"]))
                w.saver.save_now()
                yield lambda: not w.saver.pending
            yield 2.0
            mark(f"round {rnd}: 5 edits saved")
            for i in range(3):  # minimise and restore
                w.showMinimized()
                yield 2.0
                w.showNormal()
                yield 1.0
            mark(f"round {rnd}: minimised and restored 3 times")
            for i in range(3):  # lock and unlock
                yield from unlock()
            yield 3.0
            mark(f"round {rnd}: locked and unlocked 3 times")
        macos_breakdown("after 3 rounds of use")

    def run(gen):
        def tick(cond=None):
            try:
                if callable(cond) and not cond():
                    return QTimer.singleShot(50, lambda: tick(cond))
                nxt = next(gen)
                if callable(nxt):
                    QTimer.singleShot(50, lambda: tick(nxt))
                else:
                    QTimer.singleShot(int(nxt * 1000), tick)
            except StopIteration:
                done()
            except Exception:
                import traceback
                traceback.print_exc()
                done()
        QTimer.singleShot(0, tick)

    def done():
        print(flush=True)
        os._exit(0)

    QTimer.singleShot(480_000, lambda: (print("TIMED OUT", flush=True), done()))
    run(steps())
    app.exec()


def main():
    print(f"macOS {subprocess.run(['sw_vers', '-productVersion'], capture_output=True, text=True).stdout.strip()},"
          f" Python {sys.version.split()[0]}", flush=True)
    subprocess.run([sys.executable, __file__, "--build"], check=True)
    print("\n=== each library on its own (fresh process each)", flush=True)
    for name, code in ISOLATED.items():
        print(f"{name:<62} {isolated(code)}", flush=True)
    print("\n=== Vault, step by step (Activity Monitor's \"Memory\")", flush=True)
    r = subprocess.run([sys.executable, __file__, "--app"], timeout=600)
    print("\n=== start-up drawn at 2x, as on a Retina screen", flush=True)
    subprocess.run([sys.executable, __file__, "--app", "retina"], timeout=300)
    sys.exit(r.returncode)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--build"]:
        build_db()
    elif sys.argv[1:2] == ["--app"]:
        app_run(retina=sys.argv[2:3] == ["retina"])
    else:
        main()
