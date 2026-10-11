"""The sidebar fits its folder names (with their counts), within limits: short names, a long nested
name, bigger text, a very long name (capped, and shortened with … rather than drawn under its count),
collapsing. And at many window widths nothing overlaps in the title bar (title, search, lock) or the
list's heading."""
import sys
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, finish
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem
from pykeepass import PyKeePass

app = QApplication(sys.argv)
import vault, store

w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1300, 760); w.show(); QTest.qWaitForWindowExposed(w)
v = w.vault


def open_db(extra):
    path = helpers.copy_db("foldericons41.kdbx", "sidebar41.kdbx")
    kp = PyKeePass(str(path), password=helpers.PW)
    parent = kp.root_group
    for name in extra:
        parent = kp.add_group(parent, name)
    kp.save()
    v.load(store.Database(path, helpers.PW, "")); w.locked = False
    QTest.qWait(400)


def cut_off():
    """Folder names shown shortened (…) in the sidebar."""
    names = []
    it = vault.QTreeWidgetItemIterator(v.tree)
    while it.value():
        item = it.value()
        rect = v.tree.visualItemRect(item)
        if rect.isValid() and item.data(0, Qt.UserRole) != vault.FOLDERS_HEADING:
            option = QStyleOptionViewItem()
            option.rect = rect
            option.decorationSize = v.tree.iconSize()
            v.folder_delegate.initStyleOption(option, v.tree.indexFromItem(item))
            name = vault.FolderRowDelegate.split(item.text(0))[0]
            if option.text != name:
                names.append(name)
        it += 1
    return names


width = lambda: w.sidebar.width()
open_db([])
short = width()
ok("short names: none cut off", not cut_off(), cut_off())
ok("…and the sidebar is its narrowest", short == 230, short)
open_db(["Household and utilities", "Energy suppliers archive"])
longer = width()
ok("long nested name: sidebar grows to fit it", longer > short and not cut_off(), (short, longer, cut_off()))
v.set_list_text_size(125); QTest.qWait(300)
ok("bigger list text: grows, still fits", width() > longer and not cut_off(), (longer, width(), cut_off()))
v.set_list_text_size(100); QTest.qWait(300)
open_db(["A really very extremely long folder name that goes on", "and on and on and on forever more"])
ok("very long name: capped at 340 px", width() == 340, width())
ok("…and shortened with … rather than run under its count", cut_off(), cut_off())
open_db(["Household and utilities", "Energy suppliers archive"])
deep = width()
v.tree.collapseAll(); QTest.qWait(300)
ok("collapsing everything: sidebar narrows again", width() < deep, (deep, width()))


def rect(widget, parent):
    return QRect(widget.mapTo(parent, widget.rect().topLeft()), widget.size())


bar = w.titleBar
for size in (w.minimumWidth(), 1000, 1150, 1300, 1600):
    w.resize(size, 760)
    QTest.qWait(250)
    top = {"title": bar.titleLabel, "search": v.search, "lock": w.lock_btn, "minimise": bar.minBtn}
    top_rects = {k: rect(x, bar) for k, x in top.items()}
    head = {"name": v.list_title, "count": v.count, "status": v.save_status, "sort": v.sort_btn, "check": v.check_btn}
    head_rects = {k: rect(x, v) for k, x in head.items() if x.isVisible() and x.width() > 1}
    overlaps = [f"{a}/{b}" for rects in (top_rects, head_rects) for i, a in enumerate(rects)
                for b in list(rects)[i + 1:] if rects[a].intersects(rects[b])]
    ok(f"window {w.width()}: nothing overlaps in the title bar or list heading", not overlaps, overlaps)
    ok(f"window {w.width()}: search box usable (at least 220 px)", v.search.width() >= 220, v.search.width())
finish()
