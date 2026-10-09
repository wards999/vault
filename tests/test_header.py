"""Vault's header row at many window widths: nothing overlaps, buttons drop their text only when narrow."""
import os, shutil, sys
from pathlib import Path
import helpers  # repo path; temporary folder, settings and test databases
from PySide6.QtCore import QSettings, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

s = helpers.WORK
db_path = s / "header41.kdbx"
shutil.copy(s / "rt41.kdbx", db_path)
ini = s / "header_settings.ini"
ini.unlink(missing_ok=True)
fails = []


def ok(label, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{extra}]"), flush=True)
    if not cond:
        fails.append(label)


app = QApplication(sys.argv)
import vault, store
vault.settings = QSettings(str(ini), QSettings.IniFormat)
store.backup_dir = lambda: s / "header_backups"
w = vault.MainWindow()
w.setMicaEffectEnabled(False)
w.show()
QTest.qWaitForWindowExposed(w)
db = store.Database(db_path, "test-pw-123", "")
w.vault.load(db); w.saver.attach(db); w.health.set_db(db); w.locked = False
v = w.vault
v.set_save_status("All changes saved")
print("measured limits (panel px): Show passwords text below", v._header_widths()[0], "· New entry text below", v._header_widths()[1], flush=True)


def rect(widget):
    return QRect(widget.mapTo(v.right_box, widget.rect().topLeft()), widget.size())


for width in (w.minimumWidth() or 700, 760, 820, 900, 980, 1100, 1300, 1600):
    w.resize(width, 760)
    QTest.qWait(250)
    panel = v.right_box.width()
    parts = {"search": v.search, "show passwords": v.reveal, "refresh": v.check_btn, "new entry": v.new_btn}
    rects = {k: rect(x) for k, x in parts.items()}
    overlaps = [f"{a}/{b}" for i, a in enumerate(rects) for b in list(rects)[i + 1:] if rects[a].intersects(rects[b])]
    title_right = rect(v.list_title).right()
    inside = all(r.right() <= v.right_box.width() for r in rects.values())
    ok(f"window {w.width()} (panel {panel}): no overlaps, all inside, titles left of search",
       not overlaps and inside and title_right < rects["search"].left(),
       f"overlaps={overlaps} inside={inside} title_right={title_right} search_left={rects['search'].left()}")
    print(f"      search {v.search.width()}px · reveal text '{v.reveal.text()}' · new text '{v.new_btn.text()}'", flush=True)

w.resize(820, 760); QTest.qWait(250)
v.reveal.setChecked(True)
ok("toggling Show passwords while narrow keeps it icon-only, tooltip says Hide",
   v.reveal.text() == "" and v.reveal.toolTip() == "Hide passwords", (v.right_box.width(), v.reveal.text(), v.reveal.toolTip()))
w.resize(1600, 760); QTest.qWait(250)
ok("…and widening brings back 'Hide passwords'", v.reveal.text() == "Hide passwords", v.reveal.text())
print(f"--- {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}", flush=True)
os._exit(1 if fails else 0)
