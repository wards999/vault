"""Find site icons dialog, with the website guessing faked (no network): grid, ticking, correcting,
country, Apply (icons + website fields) and Undo. Steps run from timers (the dialog has its own loop)."""
import os, shutil, sys, time
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pykeepass import PyKeePass

s = helpers.WORK
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


db_path = s / "findicons41.kdbx"
shutil.copy(s / "rt41.kdbx", db_path)
kp = PyKeePass(str(db_path), password="test-pw-123")
for e in list(kp.entries):  # start clean: only our entries
    kp.delete_entry(e)
kp.add_entry(kp.root_group, "British Gas login", "me", "pw1")
kp.add_entry(kp.root_group, "BBC", "me", "pw2")
kp.add_entry(kp.root_group, "Zzqx nonsense", "me", "pw3")
kp.add_entry(kp.root_group, "GitHub", "me", "pw4", url="https://github.com")
kp.save()

app = QApplication(sys.argv)


def png(color):
    img = QImage(16, 16, QImage.Format_ARGB32); img.fill(QColor(color))
    data = QByteArray(); buf = QBuffer(data); buf.open(QIODevice.WriteOnly); img.save(buf, "PNG")
    return bytes(data)


import vault, store
from PySide6.QtCore import QProcess
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes from tests")))
ini = s / "findicons.ini"; ini.unlink(missing_ok=True)
vault.settings = QSettings(str(ini), QSettings.IniFormat)
store.backup_dir = lambda: s / "findicons_backups"
w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1300, 800); w.show(); QTest.qWaitForWindowExposed(w)
ok("the website-guessing code isn't loaded until it's used", "sitefinder" not in sys.modules)
db = store.Database(db_path, "test-pw-123", "")
w.vault.load(db); w.saver.attach(db); w.locked = False

import sitefinder  # fake the network parts
calls = []
FOUND = {"British Gas login": ("britishgas.co.uk", png("#0050aa")), "BBC": ("bbc.co.uk", png("#000000"))}
sitefinder.find = lambda title, country, ddg=False: (calls.append((title, country)), FOUND.get(title, (None, None)))[1]
sitefinder.icon_for = lambda typed, ddg=False: (typed, png("#22aa22")) if typed == "example.org" else (None, None)

dialog = lambda: next((d for d in w.findChildren(vault.FindIconsDialog) if d.isVisible()), None)
rows = lambda d: {d.table.item(r, d.ENTRY).text(): r for r in range(d.table.rowCount())}
entry = lambda title: next(e for e in w.saver.db.entries if e["title"] == title)


def steps():
    QTimer.singleShot(0, w.find_icons_by_name); yield dialog
    d = dialog()
    ok("only entries without a website are listed (GitHub has one)", set(rows(d)) == {"British Gas login", "BBC", "Zzqx nonsense"}, set(rows(d)))
    ok("country defaults to United Kingdom", d.country.currentText() == "United Kingdom")
    yield lambda: d._pending == 0 and len(calls) >= 3
    r = rows(d)
    use = lambda name: d.table.item(r[name], d.USE).checkState() == Qt.Checked
    site = lambda name: d.table.item(r[name], d.SITE).text()
    ok("found guesses are filled in and ticked", site("British Gas login") == "britishgas.co.uk" and use("British Gas login") and use("BBC"))
    ok("no match: unticked, says so", not use("Zzqx nonsense") and d.table.item(r["Zzqx nonsense"], d.STATUS).text().startswith("No match"))
    d.table.item(r["Zzqx nonsense"], d.SITE).setText("example.org")  # the user types the right website
    yield lambda: use("Zzqx nonsense")
    ok("typing a website fetches its icon and ticks the row", use("Zzqx nonsense") and d._icon(r["Zzqx nonsense"]))
    d.table.item(r["BBC"], d.USE).setCheckState(Qt.Unchecked)  # the user rejects this guess
    before = len(calls)
    d.country.setCurrentText("Ireland")
    yield lambda: d._pending == 0 and len(calls) >= before + 2
    ok("changing the country searches again with it, and is remembered",
       calls[-1][1] == "Ireland" and vault.settings.value("icon_country") == "Ireland")
    ok("…but a website the user typed is kept (not searched again)",
       site("Zzqx nonsense") == "example.org" and use("Zzqx nonsense") and len(calls) == before + 2, len(calls) - before)
    d.country.setCurrentText("United Kingdom")
    yield lambda: d._pending == 0 and len(calls) >= before + 4
    d.table.item(r["BBC"], d.USE).setCheckState(Qt.Unchecked)
    d.yesButton.click()  # Apply
    yield lambda: not w.saver.pending and dialog() is None
    QTest.qWait(500)
    gas, bbc, odd = entry("British Gas login"), entry("BBC"), entry("Zzqx nonsense")
    ok("Apply: ticked entries get their icon", gas["icon"][1] is not None and odd["icon"][1] is not None)
    ok("…and their website filled in", gas["url"] == "https://britishgas.co.uk" and odd["url"] == "https://example.org", (gas["url"], odd["url"]))
    ok("unticked entries are left alone", bbc["icon"][1] is None and bbc["url"] == "")
    w.vault.undo()
    yield lambda: not w.saver.pending
    QTest.qWait(500)
    gas = entry("British Gas login")
    ok("Undo takes it all back", gas["icon"][1] is None and gas["url"] == "" and entry("Zzqx nonsense")["url"] == "", (gas["icon"], gas["url"]))


def run(gen):
    current, deadline = [None], [time.time() + 20]

    def tick():
        try:
            if current[0] is not None and not current[0]():
                if time.time() > deadline[0]:
                    ok("step finished in time", False); return finish()
                return QTimer.singleShot(50, tick)
            QTest.qWait(150)
            current[0] = next(gen); deadline[0] = time.time() + 20
            QTimer.singleShot(50, tick)
        except StopIteration:
            finish()
        except Exception as exc:
            import traceback; traceback.print_exc(); ok("no exceptions", False, exc); finish()
    QTimer.singleShot(200, tick)


def finish():
    print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
    sys.stdout.flush(); os._exit(1 if fails else 0)


run(steps())
QTimer.singleShot(120_000, lambda: (ok("whole test in time", False), finish()))
app.exec()
