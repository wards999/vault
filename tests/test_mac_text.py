"""Settings/tooltip text on Windows vs macOS (platform faked after import; temporary settings, no processes)."""
import os, sys
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, QProcess
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest
s = str(helpers.WORK)
app = QApplication(sys.argv)
import vault
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes")))
vault.settings = QSettings(s + r"\mactext.ini", QSettings.IniFormat)
fails = []
for plat in ("win32", "darwin"):
    real = sys.platform
    sys.platform = plat
    vault.quickunlock._verifier = False  # check again for this "platform"
    try:
        texts = [l.text() for l in vault.SettingsView(*[lambda *a: None] * 8).findChildren(QLabel)]
        tips = [vault.shortcut_text("New entry (Ctrl+N)")]
    finally:
        sys.platform = real
    joined = " | ".join(texts + tips)
    for want in (["Windows' light", "Ctrl + mouse wheel", "Ctrl+0", "(Ctrl+N)"] if plat == "win32"
                 else ["macOS's light", "⌘ mouse wheel", "⌘0", "(⌘N)"]):
        ok = want in joined
        print(("OK   " if ok else "FAIL ") + plat + ": " + want, flush=True)
        if not ok: fails.append(want)
    bad = [b for b in (["⌘", "macOS"] if plat == "win32" else ["Ctrl", "Windows'", "Windows+L", "Windows Hello"]) if b in joined]
    print(("OK   " if not bad else "FAIL ") + plat + f": no wrong-platform words {bad}", flush=True)
    if bad: fails.append(plat)
print("--- ALL PASSED" if not fails else f"--- {len(fails)} FAILED", flush=True)
os._exit(1 if fails else 0)


