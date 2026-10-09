"""Copied secrets carry Windows' "keep out of clipboard history / cloud" formats. Restores the clipboard text afterwards."""
import os, sys
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import win32clipboard as wc
s = str(helpers.WORK)
app = QApplication(sys.argv)
import vault
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes from tests")))
vault.settings = QSettings(s + r"\cliphist.ini", QSettings.IniFormat)
fails = []
def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond: fails.append(label)

saved = QApplication.clipboard().text()
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.show(); QTest.qWaitForWindowExposed(w)
try:
    w.copy_secret("made-up-Pa55!", "Password", notify=False); QTest.qWait(300)
    wc.OpenClipboard()
    try:
        formats, f = {}, 0
        while True:
            f = wc.EnumClipboardFormats(f)
            if not f: break
            try: name = wc.GetClipboardFormatName(f)
            except Exception: name = str(f)
            formats[name] = f
        text = wc.GetClipboardData(wc.CF_UNICODETEXT)
        values = {n: bytes(wc.GetClipboardData(formats[n])) for n in ("CanIncludeInClipboardHistory", "CanUploadToCloudClipboard") if n in formats}
    finally:
        wc.CloseClipboard()
    ok("text pastes normally", text == "made-up-Pa55!", text)
    for n in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"):
        ok(f"{n} present", n in formats, list(formats))
    ok("history / cloud flags are DWORD 0", all(v[:4] == bytes(4) for v in values.values()) and len(values) == 2, values)
    w._clear_clipboard(); QTest.qWait(100)
    ok("auto-clear still works", QApplication.clipboard().text() == "")
finally:
    QApplication.clipboard().setText(saved); QTest.qWait(100)
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
sys.stdout.flush(); os._exit(1 if fails else 0)
