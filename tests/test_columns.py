"""Entry table columns: all resizable (incl. Website), only the last one stretches; an old saved layout
(Website stretching, squeezed) is repaired. In-app only; temporary settings."""
import os, sys
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHeaderView

s = helpers.WORK
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


app = QApplication(sys.argv)
import vault
from PySide6.QtCore import QProcess
QProcess.startDetached = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no processes from tests")))
E = vault.EntryModel

for case in ("fresh", "old layout"):
    ini = s / f"columns_{case.replace(' ', '_')}.ini"; ini.unlink(missing_ok=True)
    vault.settings = QSettings(str(ini), QSettings.IniFormat)
    if case == "old layout":  # what the previous version saved: Website stretching, squeezed to 30 px
        t = vault.TableView(); t.setModel(vault.EntryModel()); h = t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive); h.setSectionResizeMode(E.WEBSITE, QHeaderView.Stretch)
        for col, width in ((E.TITLE, 220), (E.USERNAME, 200), (E.PASSWORD, 190), (E.FOLDER, 160), (E.MODIFIED, 150)):
            t.setColumnWidth(col, width)
        t.resize(950, 400); t.show(); QTest.qWait(100)
        vault.settings.setValue("table_header", h.saveState()); t.close()
    w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1250, 720); w.show(); QTest.qWaitForWindowExposed(w)
    QTest.qWait(200)
    h = w.vault.table.horizontalHeader()
    modes = [h.sectionResizeMode(c) for c in range(h.count())]
    ok(f"{case}: every column resizable by dragging (incl. Website)", all(m == QHeaderView.Interactive for m in modes), modes)
    ok(f"{case}: the last column fills the remaining space", h.stretchLastSection())
    ok(f"{case}: Website has a sensible width", h.sectionSize(E.WEBSITE) >= 120, h.sectionSize(E.WEBSITE))
    before = h.sectionSize(E.WEBSITE)
    h.resizeSection(E.WEBSITE, before + 80); QTest.qWait(100)
    ok(f"{case}: Website can be widened", h.sectionSize(E.WEBSITE) == before + 80, (before, h.sectionSize(E.WEBSITE)))
    w.close()
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
sys.stdout.flush(); os._exit(1 if fails else 0)
