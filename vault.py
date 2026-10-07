"""Vault: a simple KeePass client (PySide6 + PySide6-Fluent-Widgets + pykeepass).

Opens .kdbx files (any extension) such as one synced by Google Drive for Desktop, and
auto-saves edits safely (see store.py: backups, verified atomic writes, merging changes
made by other devices or apps).
Run:  python vault.py
"""
import hashlib
import os
from collections import Counter
import sys
import threading
import time
import uuid as uuidlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import (
    Qt, QAbstractTableModel, QEvent, QModelIndex, QObject, QRect, QSettings, QSize,
    QTimer, QUrl, Signal, QMimeData, QByteArray,
)
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QInputMethodEvent, QKeySequence,
    QPainter, QPalette, QPen, QPixmap, QShortcut, QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QTreeWidgetItem, QTreeWidgetItemIterator,
    QFileDialog, QHeaderView, QAbstractItemView, QSplitter, QSplitterHandle, QLineEdit, QTableWidgetItem,
    QStyledItemDelegate, QDialog,
)
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon as FIF, setTheme, Theme,
    isDarkTheme, SearchLineEdit, SimpleCardWidget, TitleLabel, SubtitleLabel,
    BodyLabel, StrongBodyLabel, CaptionLabel, LineEdit, PasswordLineEdit, PlainTextEdit,
    TransparentToolButton, TransparentToggleToolButton, TransparentTogglePushButton, TransparentPushButton,
    PushButton, PrimaryPushButton, SwitchButton, CheckBox, Slider, ProgressBar,
    SegmentedWidget, InfoBar, InfoBarIcon, InfoBarPosition, MessageBox, MessageBoxBase, TreeWidget,
    TableView, RoundMenu, Action, qconfig, getFont, SmoothMode, ComboBox, setCustomStyleSheet,
    setThemeColor, themeColor, ProgressRing, ListWidget, CardWidget, TableWidget, ScrollArea,
)
from qfluentwidgets.components.widgets.table_view import TableItemDelegate

import favicon
import generator
import health
import store
import totp
from store import Database, Op

VERSION = "1.0.0"  # releases are tagged v<VERSION> (see .github/workflows/build.yml)
IDLE_LOCK_MINUTES = 5
CLIPBOARD_CHOICES = {"Never": 0, "10 seconds": 10, "20 seconds": 20, "30 seconds": 30,
                     "1 minute": 60, "2 minutes": 120, "5 minutes": 300}
ROW_DENSITIES = {"Compact": (30, 16), "Comfortable": (40, 22), "Spacious": (52, 26)}  # row height, icon size
AVATAR_COLORS = ["#0f6cbd", "#c239b3", "#038387", "#ca5010", "#8764b8", "#498205", "#d13438", "#4f6bed"]

# name: (light/dark/auto base, accent colour, window background or None for the default Windows look)
THEMES = {
    "System": (Theme.AUTO, "#009faa", None),
    "Light": (Theme.LIGHT, "#009faa", None),
    "Dark": (Theme.DARK, "#29c5d1", None),
    "Ocean": (Theme.LIGHT, "#0f6cbd", "#e8f1fb"),
    "Rose": (Theme.LIGHT, "#c4314b", "#fbedf0"),
    "Sand": (Theme.LIGHT, "#b45f06", "#f5eee3"),
    "Midnight": (Theme.DARK, "#5b9bff", "#131a2b"),
    "Forest": (Theme.DARK, "#5fc77a", "#16231b"),
    "Grape": (Theme.DARK, "#b48cf2", "#1f1a2c"),
    "Graphite": (Theme.DARK, "#f0b400", "#1b1b1d"),
}
DEFAULT_BACKGROUNDS = ("#f0f4f9", "#202020")  # the UI library's defaults (light, dark)


def theme_name():
    name = setting("theme", "System")
    return {"auto": "System", "light": "Light", "dark": "Dark"}.get(name, name if name in THEMES else "System")


def apply_theme(name, window=None):
    """Sets the light/dark base and accent colour, and the window background if given a window."""
    mode, accent, background = THEMES.get(name, THEMES["System"])
    setTheme(mode)
    setThemeColor(accent)
    if window is not None:
        if background:
            window.setMicaEffectEnabled(False)  # Mica would show the desktop through the tint
            window.setCustomBackgroundColor(background, background)
        else:
            window.setCustomBackgroundColor(*DEFAULT_BACKGROUNDS)
            window.setMicaEffectEnabled(True)


def theme_swatch(name, size=16):
    """Small icon: the theme's background with its accent colour as a dot."""
    mode, accent, background = THEMES[name]
    bg = background or (DEFAULT_BACKGROUNDS[1] if mode == Theme.DARK else DEFAULT_BACKGROUNDS[0])
    scale = 3
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(128, 128, 128, 120))
    p.setBrush(QColor(bg))
    p.drawRoundedRect(pm.rect().adjusted(1, 1, -2, -2), 9, 9)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(accent))
    d = size * scale // 2
    p.drawEllipse(pm.rect().center().x() - d // 2, pm.rect().center().y() - d // 2, d, d)
    p.end()
    pm.setDevicePixelRatio(scale)
    return QIcon(pm)
MASK = "•" * 8  # fixed length, so the mask doesn't reveal password length

FROZEN = getattr(sys, "frozen", False)  # running as the packaged Vault.exe
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # bundled icons etc.

# The packaged app is portable: settings live in Vault.ini next to Vault.exe, not the registry.
if FROZEN and sys.platform == "win32":
    settings = QSettings(str(Path(sys.executable).parent / "Vault.ini"), QSettings.IniFormat)
else:  # registry when run from source; on macOS ~/Library/Preferences (never inside Vault.app)
    settings = QSettings("Vault", "Vault")


def setting(key, default):
    value = settings.value(key, default)
    if isinstance(default, bool):
        return value in (True, "true", "1", 1)
    return value


def make_dialogs_instant():
    """The UI library fades every dialog in (0.2 s) and out (0.1 s), which makes the app feel slow
    to respond. Show and close them instantly instead (applies to all its dialogs)."""
    from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase

    def show_event(self, event):
        QDialog.showEvent(self, event)

    def done(self, code):
        self.setGraphicsEffect(None)
        QDialog.done(self, code)

    MaskDialogBase.showEvent = show_event
    MaskDialogBase.done = done


make_dialogs_instant()


def google_drive_folder():
    """Google Drive for Desktop's "My Drive" folder, if present (G: on Windows, CloudStorage on macOS)."""
    if sys.platform == "darwin":
        candidates = sorted((Path.home() / "Library" / "CloudStorage").glob("GoogleDrive-*/My Drive"))
    else:
        candidates = [Path(f"{letter}:/My Drive") for letter in "GHIJKLMNOPQRSTUVWXYZ"]
    return next((c for c in candidates if c.exists()), None)


def clipboard_seconds():
    """How long copied secrets stay on the clipboard (0 = never cleared)."""
    value = settings.value("clipboard_seconds")
    if value is None:  # older versions had an on/off switch (30 seconds when on)
        return 30 if setting("clear_clipboard", True) else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 30


def duration_text(seconds):
    return next((name for name, s in CLIPBOARD_CHOICES.items() if s == seconds), f"{seconds} seconds")


def icon(*names):
    """First FluentIcon that exists in the installed version."""
    for name in names:
        if hasattr(FIF, name):
            return getattr(FIF, name)
    return FIF.FOLDER


# ---------------------------------------------------------------- database

def in_folder(entry, folder_id):
    """True if the entry is in the folder or any of its subfolders (None is the root)."""
    if folder_id is None:
        return not entry["in_bin"]
    return folder_id in entry["folder_ids"]


# ---------------------------------------------------------------- entry table

_avatar_cache = {}


def avatar_icon(title, size=22):
    """Small rounded square with the title's first letter, like the mockup's avatars."""
    letter = title[:1].upper()
    color = AVATAR_COLORS[sum(map(ord, title)) % len(AVATAR_COLORS)]
    key = (letter, color, size)
    if key not in _avatar_cache:
        scale = 3
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(pm.rect(), size * scale / 4, size * scale / 4)
        p.setPen(Qt.white)
        font = getFont(size * scale // 2, QFont.DemiBold)
        font.setPixelSize(size * scale // 2)
        p.setFont(font)
        p.drawText(pm.rect(), Qt.AlignCenter, letter)
        p.end()
        pm.setDevicePixelRatio(scale)
        _avatar_cache[key] = QIcon(pm)
    return _avatar_cache[key]


STANDARD_ICON_DIR = RESOURCE_DIR / "icons" / "database"


class EntryIcons:
    """Entry icons for one open database: the site's favicon stored in the database, else a
    KeePass built-in icon the user picked, else a letter avatar."""

    def __init__(self, db):
        self.db = db
        self.cache = {}

    def get(self, entry):
        icon_id, custom = entry["icon"]
        key = custom or icon_id
        if key not in self.cache:
            self.cache[key] = self._custom(custom) or self._standard(icon_id)
        return self.cache[key] or avatar_icon(entry["title"])

    def _custom(self, uuid):
        data = self.db.custom_icons.get(uuid) if uuid else None
        if not data:
            return None
        pm = QPixmap()
        return QIcon(pm) if pm.loadFromData(data) else None

    @staticmethod
    def _standard(icon_id):
        if icon_id == 0:  # the default key icon: the letter avatar is more useful
            return None
        match = next(STANDARD_ICON_DIR.glob(f"C{icon_id:02d}_*.svg"), None)
        return QIcon(str(match)) if match else None


PASSWORD_COLORS = {  # (light theme, dark theme); lowercase uses the normal text colour
    "upper": ("#0f6cbd", "#6cb8f6"),
    "digit": ("#c75300", "#ffb86c"),
    "symbol": ("#8b3fd9", "#d4a6ff"),
}


def char_kind(ch):
    if ch.isupper():
        return "upper"
    if ch.islower():
        return "lower"
    if ch.isdigit():
        return "digit"
    return "symbol"


R_DISPLAY, R_DECORATION, R_TOOLTIP, R_FOREGROUND, R_USER = (
    Qt.DisplayRole.value, Qt.DecorationRole.value, Qt.ToolTipRole.value, Qt.ForegroundRole.value, Qt.UserRole.value)
_DATA_ROLES = frozenset((R_DISPLAY, R_DECORATION, R_TOOLTIP, R_FOREGROUND, R_USER))
EXPIRED_COLOR = QColor("#a0a0a0")


class EntryDelegate(TableItemDelegate):
    """Draws revealed passwords in a monospaced font, colour-coded by character type."""

    PADDING = 20

    def __init__(self, view, model):
        super().__init__(view)
        self.model = model
        self.colorize = setting("color_passwords", True)
        self.mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.mono.setFamilies(["Cascadia Mono", "Consolas", "Menlo", "SF Mono", self.mono.family()])
        self.mono.setPixelSize(14)
        self.font = getFont(13)
        self._update_text_color()
        qconfig.themeChanged.connect(self._update_text_color)

    def _update_text_color(self):
        self.text_color = QColor(Qt.white if isDarkTheme() else Qt.black)

    def _is_revealed_password(self, index):
        if index.column() != 2:  # EntryModel.PASSWORD
            return False
        e = self.model.entries[index.row()]
        return bool(e["password"] and self.model.is_revealed(e))

    def initStyleOption(self, option, index):
        # Replaces the UI library's version, which builds a new font for every cell painted.
        QStyledItemDelegate.initStyleOption(self, option, index)
        option.font = self.font
        color = self.model.data(index, R_FOREGROUND) or self.text_color
        option.palette.setColor(QPalette.Text, color)
        option.palette.setColor(QPalette.HighlightedText, color)
        if self._is_revealed_password(index):
            option.text = ""  # drawn by paint() instead

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not self._is_revealed_password(index):
            return
        password = self.model.data(index, Qt.UserRole)["password"]
        dark = isDarkTheme()
        normal = QColor(Qt.white if dark else Qt.black)
        painter.save()
        painter.setFont(self.mono)
        fm = painter.fontMetrics()
        r = option.rect
        x, right = r.x() + self.PADDING, r.right() - 6
        baseline = r.y() + (r.height() + fm.ascent() - fm.descent()) // 2
        ellipsis_w = fm.horizontalAdvance("…")
        for i, ch in enumerate(password):
            w = fm.horizontalAdvance(ch)
            if x + w > right - (ellipsis_w if i < len(password) - 1 else 0):
                painter.setPen(normal)
                painter.drawText(x, baseline, "…")
                break
            kind = char_kind(ch) if self.colorize else "lower"
            painter.setPen(QColor(PASSWORD_COLORS[kind][dark]) if kind in PASSWORD_COLORS else normal)
            painter.drawText(x, baseline, ch)
            x += w
        painter.restore()


ENTRY_MIME = "application/x-vault-entries"
FOLDER_MIME = "application/x-vault-folder"


class FolderTree(TreeWidget):
    """Folder tree that accepts entries and folders dragged onto a folder.

    It never moves items itself: drops are reported through signals, the view turns them into
    edits, and the tree is rebuilt from the database.
    """

    entriesDropped = Signal(list, object)  # entry uuids, target folder id (None = root)
    folderDropped = Signal(str, object)  # folder id, target folder id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setDropIndicatorShown(False)
        self.bin_id = None
        self._hover = None

    # dragging a folder
    def mimeTypes(self):
        return [FOLDER_MIME]

    def mimeData(self, items):
        data = QMimeData()
        data.setData(FOLDER_MIME, QByteArray((items[0].data(0, Qt.UserRole) or "").encode()))
        return data

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    # dropping onto a folder
    def _target(self, event):
        """The folder item under the cursor if the dragged thing may be dropped there."""
        item = self.itemAt(event.position().toPoint())
        md = event.mimeData()
        if item is None:
            return None
        target = item.data(0, Qt.UserRole)
        target_in_bin = bool(item.data(0, Qt.UserRole + 1))
        if target_in_bin and target != self.bin_id:
            return None  # only the Recycle Bin itself, not folders inside it
        if md.hasFormat(ENTRY_MIME):
            return item
        if md.hasFormat(FOLDER_MIME):
            dragged = bytes(md.data(FOLDER_MIME)).decode()
            if not dragged:
                return None
            ancestor = item  # not onto itself or one of its own subfolders
            while ancestor is not None:
                if ancestor.data(0, Qt.UserRole) == dragged:
                    return None
                ancestor = ancestor.parent()
            source = self._item_for(dragged)
            parent = source.parent() if source else None
            if parent is not None and parent.data(0, Qt.UserRole) == target:
                return None  # already there
            return item
        return None

    def _item_for(self, folder_id):
        it = QTreeWidgetItemIterator(self)
        while it.value():
            if it.value().data(0, Qt.UserRole) == folder_id:
                return it.value()
            it += 1
        return None

    def _set_hover(self, item):
        if self._hover is not item:
            self._hover = item
            self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._hover is None:
            return
        # Drop target: an accent-coloured box (the fluent delegate ignores item backgrounds).
        try:
            row = self.visualItemRect(self._hover)
        except RuntimeError:  # item deleted by a rebuild
            self._hover = None
            return
        rect = QRect(4, row.y() + 1, self.viewport().width() - 8, row.height() - 2)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        accent = QColor(themeColor())
        fill = QColor(accent)
        fill.setAlpha(45)
        painter.setBrush(fill)
        painter.setPen(QPen(accent, 1.5))
        painter.drawRoundedRect(rect, 5, 5)
        painter.end()

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasFormat(ENTRY_MIME) or md.hasFormat(FOLDER_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        item = self._target(event)
        self._set_hover(item)
        if item is None:
            event.ignore()
        else:
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dragLeaveEvent(self, event):
        self._set_hover(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        item = self._target(event)
        self._set_hover(None)
        if item is None:
            event.ignore()
            return
        target = item.data(0, Qt.UserRole)
        md = event.mimeData()
        # Copy, not Move, so Qt doesn't remove the dragged rows itself.
        event.setDropAction(Qt.CopyAction)
        event.accept()
        if md.hasFormat(ENTRY_MIME):
            uuids = [u for u in bytes(md.data(ENTRY_MIME)).decode().split(",") if u]
            QTimer.singleShot(0, lambda: self.entriesDropped.emit(uuids, target))
        else:
            folder_id = bytes(md.data(FOLDER_MIME)).decode()
            QTimer.singleShot(0, lambda: self.folderDropped.emit(folder_id, target))


class EntryModel(QAbstractTableModel):
    COLUMNS = ["Title", "Username", "Password", "Website", "Folder", "Modified"]
    TITLE, USERNAME, PASSWORD, WEBSITE, FOLDER, MODIFIED = range(6)
    # Sorting is done here in one Python sort; a QSortFilterProxyModel would call data()
    # tens of thousands of times per sort, which made searching and sorting laggy.
    SORT_KEYS = {
        TITLE: lambda e: e["title"].lower(),
        USERNAME: lambda e: e["username"].lower(),
        PASSWORD: lambda e: 0,
        WEBSITE: lambda e: e["url"].lower(),
        FOLDER: lambda e: e["folder"].lower(),
        MODIFIED: lambda e: e["modified_key"],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.show_passwords = False
        self.revealed = set()  # id()s of entries whose password is shown individually
        self.draggable = False  # rows can be dragged onto folders (editable databases only)
        self.icons = None  # EntryIcons for the open database
        self.sort_column, self.sort_order = self.TITLE, Qt.AscendingOrder

    def set_entries(self, entries):
        self.beginResetModel()
        self.entries = self._sorted(entries)
        self.endResetModel()

    def _sorted(self, entries):
        return sorted(entries, key=self.SORT_KEYS[self.sort_column],
                      reverse=self.sort_order == Qt.DescendingOrder)

    def sort(self, column, order=Qt.AscendingOrder):
        self.sort_column, self.sort_order = column, order
        self.layoutAboutToBeChanged.emit()
        self.entries = self._sorted(self.entries)
        self.layoutChanged.emit()

    def set_show_passwords(self, show):
        self.show_passwords = show
        self.revealed.clear()
        self.refresh_passwords()

    def is_revealed(self, e):
        return self.show_passwords or id(e) in self.revealed

    def toggle_revealed(self, e):
        """Show or hide one entry's password, independently of "Show passwords"."""
        self.revealed.symmetric_difference_update({id(e)})
        self.refresh_passwords()

    def refresh_passwords(self):
        if self.entries:
            self.dataChanged.emit(self.index(0, self.PASSWORD), self.index(len(self.entries) - 1, self.PASSWORD))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    # Precomputed: combining Qt flags in Python is slow and flags() runs for every cell painted.
    FLAGS = Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemNeverHasChildren
    DRAG_FLAGS = FLAGS | Qt.ItemIsDragEnabled

    def flags(self, index):
        return self.DRAG_FLAGS if self.draggable else self.FLAGS

    def mimeTypes(self):
        return [ENTRY_MIME]

    def mimeData(self, indexes):
        uuids = list(dict.fromkeys(self.entries[i.row()]["uuid"] for i in indexes if i.isValid()))
        data = QMimeData()
        data.setData(ENTRY_MIME, QByteArray(",".join(uuids).encode()))
        return data

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=R_DISPLAY):
        # Called tens of thousands of times while scrolling, so: compare roles as plain ints
        # (comparing Qt enums in Python is ~70x slower) and return early for unused roles.
        if type(role) is not int:
            role = role.value
        if role not in _DATA_ROLES:
            return None
        e = self.entries[index.row()]
        col = index.column()
        if role == R_DISPLAY:
            if col == 2:  # PASSWORD
                return (e["password"] if self.is_revealed(e) else MASK) if e["password"] else ""
            cells = e.get("_cells")
            if cells is None:
                cells = e["_cells"] = (e["title"], e["username"], "", e["url"], e["folder"], e["modified"])
            return cells[col]
        if role == R_USER:
            return e
        if role == R_DECORATION:
            if col != 0:
                return None
            return self.icons.get(e) if self.icons else avatar_icon(e["title"])
        if role == R_FOREGROUND:
            return EXPIRED_COLOR if e["expired"] else None
        if role == R_TOOLTIP:
            if col == 0 and e["expired"]:
                return "This entry has expired"
            if col in (1, 2):
                return "Double-click to copy and minimise"
            if col == 3 and e["url"]:
                return f"{e['url']}\nDouble-click to open"
        return None


class CellDoubleClick(QObject):
    """Calls `callback(index)` when a cell in `view` is double-clicked.

    The frameless FluentWindow doesn't receive real double-click events on Windows,
    so this also detects two quick presses on the same cell.
    """

    def __init__(self, view, callback):
        super().__init__(view)
        self.view = view
        self.callback = callback
        self.last = (None, 0.0)
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() not in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            return False
        if event.button() != Qt.LeftButton:
            return False
        index = self.view.indexAt(event.position().toPoint())
        if not index.isValid():
            return False
        cell = (index.row(), index.column())
        if event.type() == QEvent.MouseButtonDblClick:
            self.last = (None, 0.0)
            self.callback(index)
            return True
        now = time.monotonic()
        last_cell, last_time = self.last
        if last_cell == cell and now - last_time <= QApplication.styleHints().mouseDoubleClickInterval() / 1000:
            self.last = (None, 0.0)
            self.callback(index)
            return True
        self.last = (cell, now)
        return False


def local_shortcut(keys, widget, handler):
    """Keyboard shortcut that only works while `widget` (or a child of it) has focus.

    The context must be set with setContext(): PySide ignores a `context=` constructor argument,
    which left shortcuts window-wide (e.g. Ctrl+C in the search box copied a password)."""
    shortcut = QShortcut(QKeySequence(keys), widget)
    shortcut.setContext(Qt.WidgetWithChildrenShortcut)
    shortcut.activated.connect(handler)
    return shortcut


def caption(text):
    label = CaptionLabel(text)
    label.setTextColor("#6b6b6b", "#a0a0a0")
    return label


class GripHandle(QSplitterHandle):
    """Splitter handle drawn as a short rounded grip that darkens on hover."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WA_Hover)

    def event(self, e):
        if e.type() in (QEvent.HoverEnter, QEvent.HoverLeave):
            self.update()
        return super().event(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(128, 128, 128, 150 if self.underMouse() else 70))
        length, thickness = 40, 4
        c = self.rect().center()
        if self.orientation() == Qt.Vertical:  # handle between stacked widgets: horizontal grip
            r = QRect(c.x() - length // 2, c.y() - thickness // 2 + 1, length, thickness)
        else:
            r = QRect(c.x() - thickness // 2 + 1, c.y() - length // 2, thickness, length)
        p.drawRoundedRect(r, 2, 2)


class GripSplitter(QSplitter):
    """Splitter with grip handles whose position is saved in settings under `key`.

    When the window resizes, side panels keep their size: the last widget grows in a
    horizontal splitter (tree | table) and the first in a vertical one (table / notes)."""

    def __init__(self, orientation, key, widgets, default_sizes, parent=None):
        super().__init__(orientation, parent)
        self.setChildrenCollapsible(False)
        self.setHandleWidth(16)
        for w in widgets:
            self.addWidget(w)
        grow = len(widgets) - 1 if orientation == Qt.Horizontal else 0
        for i in range(len(widgets)):
            self.setStretchFactor(i, 1 if i == grow else 0)
        self.setSizes(default_sizes)
        state = settings.value(key)
        if state is not None:
            self.restoreState(state)
        self.splitterMoved.connect(lambda *_: settings.setValue(key, self.saveState()))

    def createHandle(self):
        return GripHandle(self.orientation(), self)


class NotesPanel(SimpleCardWidget):
    """Shows the selected entry's title, folder, notes and modified date under the table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(90)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(8)
        head = QHBoxLayout()
        self.title = StrongBodyLabel("")
        head.addWidget(self.title)
        self.path = caption("")
        head.addWidget(self.path, 1)
        self.modified = caption("")
        head.addWidget(self.modified)
        root.addLayout(head)

        # Live 2FA code, shown only for entries that have one
        self.totp_box = QWidget()
        t = QHBoxLayout(self.totp_box)
        t.setContentsMargins(0, 0, 0, 0)
        t.setSpacing(10)
        t.addWidget(caption("2FA code"))
        self.totp_code = StrongBodyLabel("")
        qss = f"StrongBodyLabel {{ {mono_font_qss(18)} letter-spacing: 2px; }}"
        setCustomStyleSheet(self.totp_code, qss, qss)
        t.addWidget(self.totp_code)
        self.totp_ring = ProgressRing()
        self.totp_ring.setFixedSize(22, 22)
        self.totp_ring.setStrokeWidth(3)
        self.totp_ring.setTextVisible(False)
        t.addWidget(self.totp_ring)
        self.totp_left = caption("")
        t.addWidget(self.totp_left)
        copy = TransparentToolButton(FIF.COPY)
        copy.setToolTip("Copy 2FA code (Ctrl+T)")
        copy.clicked.connect(lambda: self.window().vault.copy_totp())
        t.addWidget(copy)
        t.addStretch(1)
        root.addWidget(self.totp_box)
        self.totp_timer = QTimer(self, interval=1000, timeout=self._tick)
        self.entry = None

        self.notes = PlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setPlaceholderText("No notes")
        root.addWidget(self.notes, 1)
        self.set_entry(None)

    def set_entry(self, e):
        self.entry = e
        self.totp_box.setVisible(bool(e and e["totp"]))
        if e and e["totp"]:
            self._tick()
            self.totp_timer.start()
        else:
            self.totp_timer.stop()
        if e is None:
            self.title.setText("No entry selected")
            self.path.setText("")
            self.modified.setText("")
            self.notes.clear()
            return
        self.title.setText(e["title"])
        self.path.setText("   " + (" › ".join(e["path"]) or "Root"))
        status = f"Modified {e['modified']}" if e["modified"] else ""
        if e["expired"]:
            status = "Expired  ·  " + status
        self.modified.setText(status)
        self.notes.setPlainText(e["notes"])

    def _tick(self):
        if not self.entry or not self.entry["totp"]:
            return
        value, left = totp.code(self.entry["totp"])
        half = len(value) // 2
        self.totp_code.setText(f"{value[:half]} {value[half:]}")
        period = self.entry["totp"]["period"]
        self.totp_ring.setRange(0, period)
        self.totp_ring.setValue(left)
        self.totp_left.setText(f"{left}s")


class VaultView(QWidget):
    """KeePass-style layout: folder tree | entry table with notes underneath."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("view-vault")
        self.db = None
        self.folder = None

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 24, 24)
        root.setSpacing(0)

        # Folder tree
        tree_col = QVBoxLayout()
        tree_col.setSpacing(12)
        tree_head = QHBoxLayout()
        tree_head.addWidget(SubtitleLabel("Folders"), 1)
        self.new_folder_btn = TransparentToolButton(icon("FOLDER_ADD", "ADD"))
        self.new_folder_btn.setToolTip("New folder")
        self.new_folder_btn.clicked.connect(lambda: self.new_folder())
        tree_head.addWidget(self.new_folder_btn)
        tree_col.addLayout(tree_head)
        self.tree = FolderTree()
        self.tree.entriesDropped.connect(self._on_entries_dropped)
        self.tree.folderDropped.connect(self._on_folder_dropped)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._folder_menu)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.scrollDelagate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        self.tree.currentItemChanged.connect(self._on_folder)
        tree_col.addWidget(self.tree, 1)
        tree_box = QWidget()
        tree_box.setLayout(tree_col)
        tree_box.setMinimumWidth(150)

        # Header, table, notes
        right = QVBoxLayout()
        right.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(8)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.list_title = SubtitleLabel("")
        titles.addWidget(self.list_title)
        sub = QHBoxLayout()
        sub.setSpacing(12)
        self.count = caption("")
        sub.addWidget(self.count)
        self.save_status = caption("")
        sub.addWidget(self.save_status)
        sub.addStretch(1)
        titles.addLayout(sub)
        head.addLayout(titles, 1)
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("Search all folders")
        self.search.setFixedWidth(280)
        # Wait for a short pause in typing before filtering.
        self.search_timer = QTimer(self, singleShot=True, interval=120, timeout=self.refresh)
        self.search.textChanged.connect(self.search_timer.start)
        head.addWidget(self.search, 0, Qt.AlignVCenter)
        self.reveal = TransparentTogglePushButton(FIF.VIEW, "Show passwords")
        self.reveal.toggled.connect(self._on_reveal)
        head.addWidget(self.reveal, 0, Qt.AlignVCenter)
        self.check_btn = TransparentToolButton(FIF.SYNC)
        self.check_btn.setToolTip("Check for changes made on other devices or apps (F5)")
        self.check_btn.clicked.connect(self.check_for_changes)
        head.addWidget(self.check_btn, 0, Qt.AlignVCenter)
        self.new_btn = PrimaryPushButton(FIF.ADD, "New entry")
        self.new_btn.setToolTip("New entry (Ctrl+N)")
        self.new_btn.clicked.connect(self.new_entry)
        head.addWidget(self.new_btn, 0, Qt.AlignVCenter)
        right.addLayout(head)
        local_shortcut("Ctrl+N", self, self.new_entry)
        local_shortcut("Ctrl+Z", self, self.undo)
        local_shortcut("F5", self, self.check_for_changes)

        self.model = EntryModel(self)
        self.table = TableView()
        self.table.setModel(self.model)
        self.table.setDragDropMode(QAbstractItemView.DragOnly)
        self.table.setDefaultDropAction(Qt.CopyAction)
        self.delegate = EntryDelegate(self.table, self.model)
        self.table.setItemDelegate(self.delegate)
        self.table.scrollDelagate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.set_density(setting("row_density", "Comfortable"))
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(EntryModel.TITLE, Qt.AscendingOrder)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(EntryModel.WEBSITE, QHeaderView.Stretch)
        for col, width in ((EntryModel.TITLE, 220), (EntryModel.USERNAME, 200), (EntryModel.PASSWORD, 190),
                           (EntryModel.FOLDER, 160), (EntryModel.MODIFIED, 150)):
            self.table.setColumnWidth(col, width)
        # Remember sorting, column widths and column order.
        header.setSectionsMovable(True)
        state = settings.value("table_header")
        if state is not None and header.restoreState(state):
            self.table.sortByColumn(header.sortIndicatorSection(), header.sortIndicatorOrder())
        self.header_timer = QTimer(self, singleShot=True, interval=400,
                                   timeout=lambda: settings.setValue("table_header", header.saveState()))
        header.sortIndicatorChanged.connect(self.header_timer.start)
        header.sectionResized.connect(self.header_timer.start)
        header.sectionMoved.connect(self.header_timer.start)
        self.table.selectionModel().currentRowChanged.connect(self._on_row)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self._dbl = CellDoubleClick(self.table, self._on_double_click)
        for keys, handler in (("Ctrl+C", self.copy_password), ("Ctrl+B", self.copy_username),
                              ("Ctrl+U", self.open_url), ("Return", self.edit_entry), ("Enter", self.edit_entry),
                              ("Ctrl+E", self.edit_entry), ("Delete", self.delete_entry),
                              ("Ctrl+T", self.copy_totp), ("Ctrl+D", self.duplicate_entry)):
            local_shortcut(keys, self.table, handler)
        self.table.setMinimumHeight(120)

        self.notes = NotesPanel()

        self.splitter = GripSplitter(Qt.Vertical, "notes_splitter", [self.table, self.notes], [600, 170])
        right.addWidget(self.splitter, 1)
        right_box = QWidget()
        right_box.setLayout(right)
        right_box.setMinimumWidth(400)
        self.tree_splitter = GripSplitter(Qt.Horizontal, "tree_splitter", [tree_box, right_box], [240, 1000])
        root.addWidget(self.tree_splitter)
        qconfig.themeChanged.connect(self._set_tree_icons)

    # ---- loading

    def load(self, db, keep_state=False, select_uuid=None):
        """Shows `db`. With keep_state, stays on the same folder, search and selected entry
        (used after edits and reloads)."""
        folder, query = self.folder, self.search.text()
        current = self.current_entry()
        select_uuid = select_uuid or (current["uuid"] if current and keep_state else None)
        self.db = db
        self.model.icons = EntryIcons(db)
        self.folder = None
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.new_btn.setVisible(db.writable)
        self.new_folder_btn.setVisible(db.writable)
        self.model.draggable = db.writable
        self.table.setDragEnabled(db.writable)
        self.tree.setDragEnabled(db.writable)
        self.tree.setAcceptDrops(db.writable)
        self.tree.bin_id = db.bin_id
        self.tree.blockSignals(True)
        self.tree._hover = None
        self.tree.clear()
        root_item = QTreeWidgetItem([f"{db.name}  ({sum(not e['in_bin'] for e in db.entries)})"])
        root_item.setData(0, Qt.UserRole, None)
        root_item.setFlags(root_item.flags() & ~Qt.ItemIsDragEnabled)
        self.tree.addTopLevelItem(root_item)
        items = {None: root_item}
        for f in db.folders:
            n = sum(in_folder(e, f["id"]) for e in db.entries)
            item = QTreeWidgetItem([f"{f['name']}  ({n})"])
            item.setData(0, Qt.UserRole, f["id"])
            item.setData(0, Qt.UserRole + 1, f["in_bin"])
            if f["id"] == db.bin_id or f["in_bin"]:
                item.setFlags(item.flags() & ~Qt.ItemIsDragEnabled)
            items[f["parent"]].addChild(item)
            items[f["id"]] = item
        self.tree.expandAll()
        self._set_tree_icons()
        if not keep_state:  # opening the database: go back to the folder used last time,
            folder = self._remembered_folder(db)  # unless it has since been moved to the Recycle Bin
            if folder in items and folder != db.bin_id and items[folder].data(0, Qt.UserRole + 1):
                folder = None
        if folder in items:
            self.folder = folder
            self.tree.setCurrentItem(items[folder])
            self.tree.scrollToItem(items[folder])
        else:
            self.tree.setCurrentItem(root_item)
        self.tree.blockSignals(False)
        if keep_state and query:
            self.search.blockSignals(True)
            self.search.setText(query)
            self.search.blockSignals(False)
        self.refresh(select_uuid=select_uuid)

    def clear(self):
        """Forget everything that came from the database (used when locking)."""
        self.db = None
        self.tree.blockSignals(True)
        self.tree.clear()
        self.tree.blockSignals(False)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.reveal.setChecked(False)
        self.model.revealed.clear()
        self.model.set_entries([])
        self.model.icons = None
        self.list_title.setText("")
        self.count.setText("")
        self.save_status.setText("")
        self.notes.set_entry(None)

    def _set_tree_icons(self):
        """Icons are rendered for the current theme, so redo them when it changes."""
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            if not item.parent():
                ico = icon("LIBRARY", "FOLDER")
            elif item.data(0, Qt.UserRole + 1):
                ico = FIF.DELETE
            else:
                ico = FIF.FOLDER
            item.setIcon(0, ico.icon())
            it += 1

    @staticmethod
    def _folder_key(db):
        # One remembered folder per database file (keys can't contain the path itself).
        return "last_folder/" + hashlib.sha1(os.path.normcase(os.path.abspath(db.path)).encode()).hexdigest()[:16]

    def _remembered_folder(self, db):
        return setting(self._folder_key(db), "") or None

    def _on_folder(self, item, _previous):
        if item is None:
            return
        self.folder = item.data(0, Qt.UserRole)
        if self.db is not None:
            settings.setValue(self._folder_key(self.db), self.folder or "")
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.search_timer.stop()
        self.refresh()

    def refresh(self, select_uuid=None):
        if self.db is None:
            return
        q = self.search.text().strip().lower()
        if q:
            entries = [e for e in self.db.entries if not e["in_bin"] and q in e["search"]]
            self.list_title.setText("Search results")
        else:
            entries = [e for e in self.db.entries if in_folder(e, self.folder)]
            item = self.tree.currentItem()
            self.list_title.setText(item.text(0).rsplit("  (", 1)[0] if item else self.db.name)
        self.count.setText(f"{len(entries)} entries")
        self.model.set_entries(entries)
        rows = [i for i, e in enumerate(self.model.entries) if e["uuid"] == select_uuid]
        if rows:
            self.table.selectRow(rows[0])
            self.table.scrollTo(self.model.index(rows[0], 0))
        elif entries:
            self.table.selectRow(0)
        else:
            self.notes.set_entry(None)

    # ---- selection and actions

    def current_entry(self):
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return self.model.data(index, Qt.UserRole)

    def _on_row(self, current, _previous):
        self.notes.set_entry(self.model.data(current, Qt.UserRole) if current.isValid() else None)

    def _on_reveal(self, on):
        self.model.set_show_passwords(on)
        self.reveal.setIcon(FIF.HIDE if on else FIF.VIEW)
        self.reveal.setText("Hide passwords" if on else "Show passwords")

    def set_density(self, name):
        row_height, icon_size = ROW_DENSITIES.get(name, ROW_DENSITIES["Comfortable"])
        self.table.verticalHeader().setDefaultSectionSize(row_height)
        self.table.setIconSize(QSize(icon_size, icon_size))

    def set_colorize(self, on):
        self.delegate.colorize = on
        self.table.viewport().update()

    def toggle_password(self):
        e = self.current_entry()
        if e:
            self.model.toggle_revealed(e)

    def _on_double_click(self, index):
        self.table.selectRow(index.row())
        e = self.model.data(index, Qt.UserRole)
        col = index.column()
        if col in (EntryModel.USERNAME, EntryModel.PASSWORD):
            field, label = ("username", "Username") if col == EntryModel.USERNAME else ("password", "Password")
            if e[field]:
                self.window().copy_secret(e[field], label, notify=False)
                self.window().minimize_privately()
        elif col == EntryModel.WEBSITE and e["url"]:
            self.open_url()
        else:
            self.edit_entry()

    # ---- editing

    def _editable(self):
        return self.db is not None and self.db.writable

    def new_entry(self):
        if not self._editable():
            return
        folder = None if self.folder == self.db.bin_id else self.folder
        if folder and any(f["id"] == folder and f["in_bin"] for f in self.db.folders):
            folder = None
        editor = EntryEditor(self.window(), self.db, folder_id=folder)
        if editor.exec() and editor.op:
            self.window().saver.submit(editor.op, f"New entry “{editor.op.title}”")
            self.load(self.db, keep_state=True, select_uuid=editor.op.uuid)
            self._auto_icon(editor.op)

    def edit_entry(self):
        e = self.current_entry()
        if not e or not self._editable():
            return
        editor = EntryEditor(self.window(), self.db, entry=e)
        if editor.exec() and editor.op:
            self.window().saver.submit(editor.op, f"Edit of “{e['title']}”")
            if "url" in editor.op.fields:
                self._auto_icon(editor.op)

    def _auto_icon(self, op):
        """Downloads the site's icon for a new entry or a changed website, if enabled."""
        url = (op.all_fields or op.fields).get("url", "")
        if setting("icons_auto", True) and favicon.site_host(url):
            self.window().icons.fetch([{"uuid": op.uuid, "title": op.title, "url": url}])

    def delete_entry(self):
        e = self.current_entry()
        if not e or not self._editable():
            return
        permanent = e["in_bin"] or not self.db.recycle_bin_enabled
        if permanent:
            box = MessageBox("Delete permanently?",
                             f"“{e['title']}” will be deleted for good. This can't be undone "
                             "(except from Vault's backups).", self.window())
            box.yesButton.setText("Delete permanently")
        else:
            box = MessageBox("Move to Recycle Bin?",
                             f"“{e['title']}” will be moved to the Recycle Bin. "
                             "You can still find it there.", self.window())
            box.yesButton.setText("Move to Recycle Bin")
        box.cancelButton.setText("Cancel")
        if box.exec():
            self.window().saver.submit(Op("delete" if permanent else "trash", e["uuid"], title=e["title"]))
            self.window().undo_toast("Deleted" if permanent else "Moved to Recycle Bin", f"“{e['title']}”")

    def undo(self):
        if not self._editable():
            return
        label = self.window().saver.undo()
        if label is None:
            InfoBar.info("Nothing to undo", "", orient=Qt.Horizontal, isClosable=True,
                         position=InfoBarPosition.TOP_RIGHT, duration=1500, parent=self.window())
        else:
            InfoBar.success("Undone", label, orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP_RIGHT, duration=2000, parent=self.window())

    def check_for_changes(self):
        if self.db is not None:
            self.window().saver.check_external(manual=True)

    def duplicate_entry(self):
        e = self.current_entry()
        if not e or not self._editable():
            return
        op = store.duplicate_op(self.db.kp, e["uuid"])
        self.window().saver.submit(op, f"Duplicate of “{e['title']}”")
        self.load(self.db, keep_state=True, select_uuid=op.uuid)

    def move_entry(self):
        e = self.current_entry()
        if not e or not self._editable():
            return
        dialog = FolderPickerDialog(self.window(), self.db, f"Move “{e['title']}” to", e["folder_id"])
        if dialog.exec() and dialog.folder != e["folder_id"]:
            self.window().saver.submit(Op("move", e["uuid"], folder=dialog.folder, title=e["title"]),
                                       f"Move of “{e['title']}”")

    def copy_totp(self):
        e = self.current_entry()
        if e and e["totp"]:
            self.window().copy_secret(totp.code(e["totp"])[0], "2FA code")

    def download_icon(self):
        e = self.current_entry()
        if e and self._editable():
            self.window().icons.fetch([e], announce=True)

    # ---- folders

    def _folder_record(self, folder_id):
        return next((f for f in self.db.folders if f["id"] == folder_id), None)

    def new_folder(self, parent=False):
        if not self._editable():
            return
        if parent is False:
            parent = self.folder
        record = self._folder_record(parent)
        if record and record["in_bin"]:
            parent = None
        dialog = NameDialog(self.window(), "New folder", "Folder name", "",
                            f"Inside: {' › '.join(record['path']) if record and not record['in_bin'] else self.db.name}")
        if dialog.exec():
            op = Op("folder_create", uuidlib.uuid4().hex, fields={"name": dialog.name}, folder=parent,
                    title=dialog.name)
            self.window().saver.submit(op, f"New folder “{dialog.name}”")
            self.folder = op.uuid
            self.load(self.db, keep_state=True)

    def rename_folder(self, folder_id):
        record = self._folder_record(folder_id)
        if not record or not self._editable():
            return
        dialog = NameDialog(self.window(), "Rename folder", "Folder name", record["name"])
        if dialog.exec() and dialog.name != record["name"]:
            self.window().saver.submit(Op("folder_rename", folder_id, fields={"name": dialog.name}, title=dialog.name),
                                       f"Rename of “{record['name']}”")

    def delete_folder(self, folder_id):
        record = self._folder_record(folder_id)
        if not record or not self._editable() or folder_id == self.db.bin_id:
            return
        count = sum(in_folder(e, folder_id) for e in self.db.entries)
        permanent = record["in_bin"] or not self.db.recycle_bin_enabled
        contents = f" and the {count} entr{'y' if count == 1 else 'ies'} in it" if count else ""
        if permanent:
            box = MessageBox("Delete folder permanently?",
                             f"“{record['name']}”{contents} will be deleted for good.", self.window())
            box.yesButton.setText("Delete permanently")
        else:
            box = MessageBox("Move folder to Recycle Bin?",
                             f"“{record['name']}”{contents} will be moved to the Recycle Bin.", self.window())
            box.yesButton.setText("Move to Recycle Bin")
        box.cancelButton.setText("Cancel")
        if box.exec():
            kind = "folder_delete" if permanent else "folder_trash"
            self.window().saver.submit(Op(kind, folder_id, title=record["name"]), f"Folder “{record['name']}”")
            self.window().undo_toast("Deleted folder" if permanent else "Moved folder to Recycle Bin",
                                     f"“{record['name']}”")

    def _on_entries_dropped(self, uuids, target):
        if not self._editable():
            return
        by_id = {e["uuid"]: e for e in self.db.entries}
        moving = [by_id[u] for u in uuids if u in by_id and by_id[u]["folder_id"] != target]
        if not moving:
            return
        names = ", ".join(f"“{e['title']}”" for e in moving[:3]) + (" …" if len(moving) > 3 else "")
        if target is not None and target == self.db.bin_id:
            ops = [Op("trash", e["uuid"], title=e["title"]) for e in moving]
            self.window().saver.submit_many(ops, f"Delete of {names}")
            self.window().undo_toast("Moved to Recycle Bin", names)
        else:
            ops = [Op("move", e["uuid"], folder=target, title=e["title"]) for e in moving]
            self.window().saver.submit_many(ops, f"Move of {names}")
            record = self._folder_record(target)
            self.window().undo_toast("Moved", f"{names} to {record['name'] if record else self.db.name}")

    def _on_folder_dropped(self, folder_id, target):
        record = self._folder_record(folder_id)
        if not record or not self._editable() or record["parent"] == target or folder_id == target:
            return
        if target is not None and target == self.db.bin_id:
            self.delete_folder(folder_id)  # asks first, like the menu
            return
        self.window().saver.submit(Op("folder_move", folder_id, folder=target, title=record["name"]),
                                   f"Move of folder “{record['name']}”")
        destination = self._folder_record(target)
        self.window().undo_toast("Moved folder", f"“{record['name']}” into "
                                 f"{destination['name'] if destination else self.db.name}")

    def move_folder(self, folder_id):
        record = self._folder_record(folder_id)
        if not record or not self._editable():
            return
        dialog = FolderPickerDialog(self.window(), self.db, f"Move folder “{record['name']}” into", record["parent"],
                                    exclude=folder_id)
        if dialog.exec() and dialog.folder != record["parent"]:
            self.window().saver.submit(Op("folder_move", folder_id, folder=dialog.folder, title=record["name"]),
                                       f"Move of folder “{record['name']}”")

    def _folder_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None or not self._editable():
            return
        folder_id = item.data(0, Qt.UserRole)
        in_bin = bool(item.data(0, Qt.UserRole + 1))
        is_bin = folder_id is not None and folder_id == self.db.bin_id
        menu = RoundMenu(parent=self)
        if not in_bin:
            menu.addAction(Action(icon("FOLDER_ADD", "ADD"), "New folder inside…",
                                  triggered=lambda: self.new_folder(folder_id)))
        if folder_id is not None and not is_bin:
            menu.addAction(Action(FIF.EDIT, "Rename…", triggered=lambda: self.rename_folder(folder_id)))
            menu.addAction(Action(icon("MOVE", "FOLDER"), "Move to…", triggered=lambda: self.move_folder(folder_id)))
            menu.addSeparator()
            permanent = in_bin or not self.db.recycle_bin_enabled
            menu.addAction(Action(FIF.DELETE, "Delete permanently…" if permanent else "Move to Recycle Bin…",
                                  triggered=lambda: self.delete_folder(folder_id)))
        if menu.actions():
            menu.exec(self.tree.viewport().mapToGlobal(pos), ani=False)

    def set_save_status(self, text):
        self.save_status.setText(f"·  {text}" if text else "")

    def copy_username(self):
        e = self.current_entry()
        if e:
            self.window().copy_secret(e["username"], "Username")

    def copy_password(self):
        e = self.current_entry()
        if e:
            self.window().copy_secret(e["password"], "Password")

    def copy_url(self):
        e = self.current_entry()
        if e:
            self.window().copy_secret(e["url"], "Website")

    def open_url(self):
        e = self.current_entry()
        if e and e["url"]:
            QDesktopServices.openUrl(QUrl.fromUserInput(e["url"]))

    def _context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        self.table.selectRow(index.row())
        e = self.model.data(index, Qt.UserRole)
        menu = RoundMenu(parent=self)
        actions = [
            (FIF.PEOPLE, "Copy username", "Ctrl+B", self.copy_username, e["username"]),
            (FIF.COPY, "Copy password", "Ctrl+C", self.copy_password, e["password"]),
            (FIF.LINK, "Copy website", None, self.copy_url, e["url"]),
            (icon("GLOBE", "LINK"), "Open website", "Ctrl+U", self.open_url, e["url"]),
        ]
        for ico, text, keys, handler, value in actions:
            action = Action(ico, text, triggered=handler)
            if keys:
                action.setShortcut(QKeySequence(keys))
            action.setEnabled(bool(value))
            menu.addAction(action)
        if not self.model.show_passwords:
            menu.addSeparator()
            shown = self.model.is_revealed(e)
            action = Action(FIF.HIDE if shown else FIF.VIEW, "Hide password" if shown else "Show password",
                            triggered=self.toggle_password)
            action.setEnabled(bool(e["password"]))
            menu.addAction(action)
        if e["totp"]:
            totp_action = Action(icon("STOP_WATCH", "HISTORY"), "Copy 2FA code", triggered=self.copy_totp)
            totp_action.setShortcut(QKeySequence("Ctrl+T"))
            menu.addAction(totp_action)
        if self._editable():
            menu.addSeparator()
            edit = Action(FIF.EDIT, "Edit…", triggered=self.edit_entry)
            edit.setShortcut(QKeySequence("Enter"))
            menu.addAction(edit)
            duplicate = Action(FIF.COPY, "Duplicate", triggered=self.duplicate_entry)
            duplicate.setShortcut(QKeySequence("Ctrl+D"))
            menu.addAction(duplicate)
            menu.addAction(Action(icon("MOVE", "FOLDER"), "Move to…", triggered=self.move_entry))
            fetch = Action(icon("GLOBE", "PHOTO"), "Download site icon", triggered=self.download_icon)
            fetch.setEnabled(bool(favicon.site_host(e["url"])))
            menu.addAction(fetch)
            permanent = e["in_bin"] or not self.db.recycle_bin_enabled
            delete = Action(FIF.DELETE, "Delete permanently…" if permanent else "Move to Recycle Bin…",
                            triggered=self.delete_entry)
            delete.setShortcut(QKeySequence("Del"))
            menu.addAction(delete)
        menu.exec(self.table.viewport().mapToGlobal(pos), ani=False)


# ---------------------------------------------------------------- editing

def run_in_background(parent, fn, on_done):
    """Runs fn() on a worker thread, then calls on_done(result, error) on the GUI thread."""
    box = {}

    def work():
        try:
            box["result"] = fn()
        except Exception as exc:  # handed to on_done
            box["error"] = exc

    thread = threading.Thread(target=work, daemon=True)
    thread.start()

    def poll():
        if thread.is_alive():
            QTimer.singleShot(40, poll)
        else:
            on_done(box.get("result"), box.get("error"))

    QTimer.singleShot(40, poll)


def mono_font_qss(size=15):
    return f"font-family: 'Cascadia Mono', 'Consolas', 'Menlo', 'SF Mono', monospace; font-size: {size}px;"


class ColoredPasswordEdit(LineEdit):
    """Password field in a monospaced font that colour-codes characters while shown."""

    def __init__(self, parent=None):
        super().__init__(parent)
        qss = f"LineEdit {{ {mono_font_qss()} }}"
        setCustomStyleSheet(self, qss, qss)
        self.setEchoMode(QLineEdit.Password)
        self.textChanged.connect(self._recolor)
        qconfig.themeChanged.connect(self._recolor)

    def set_revealed(self, on):
        self.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        self._recolor()

    def _recolor(self):
        # QLineEdit can't style individual characters directly; input-method text formats can.
        attributes = []
        if self.echoMode() == QLineEdit.Normal and setting("color_passwords", True):
            dark = isDarkTheme()
            cursor = self.cursorPosition()
            for i, ch in enumerate(self.text()):
                kind = char_kind(ch)
                if kind in PASSWORD_COLORS:
                    fmt = QTextCharFormat()
                    fmt.setForeground(QColor(PASSWORD_COLORS[kind][dark]))
                    attributes.append(QInputMethodEvent.Attribute(
                        QInputMethodEvent.TextFormat, i - cursor, 1, fmt))
        QApplication.sendEvent(self, QInputMethodEvent("", attributes))


class PasswordGenerator(SimpleCardWidget):
    """Password / passphrase generator; emits each new value with its entropy in bits."""

    generated = Signal(str, float)
    closed = Signal()  # options hidden (or their height changed)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.mode = SegmentedWidget()
        self.mode.addItem("password", "Password", lambda: self._set_mode("password"))
        self.mode.addItem("passphrase", "Passphrase", lambda: self._set_mode("passphrase"))
        top.addWidget(self.mode)
        top.addStretch(1)
        again = TransparentToolButton(FIF.SYNC)
        again.setToolTip("Generate another")
        again.clicked.connect(self.generate)
        top.addWidget(again)
        close = TransparentToolButton(FIF.CLOSE)
        close.setToolTip("Hide generator options")
        close.clicked.connect(self.hide)
        close.clicked.connect(self.closed)
        top.addWidget(close)
        root.addLayout(top)

        # Password options
        self.password_opts = QWidget()
        p = QVBoxLayout(self.password_opts)
        p.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(BodyLabel("Length"))
        self.length = Slider(Qt.Horizontal)
        self.length.setRange(8, 64)
        self.length.setValue(int(setting("gen/length", 20)))
        row.addWidget(self.length, 1)
        self.length_label = BodyLabel("")
        self.length_label.setFixedWidth(28)
        row.addWidget(self.length_label)
        p.addLayout(row)
        boxes = QHBoxLayout()
        self.classes = {}
        for key, text in (("upper", "A–Z"), ("lower", "a–z"), ("digits", "0–9"), ("symbols", "!@#$")):
            box = CheckBox(text)
            box.setChecked(setting(f"gen/{key}", True))
            self.classes[key] = box
            boxes.addWidget(box)
        boxes.addStretch(1)
        p.addLayout(boxes)
        self.avoid = CheckBox("Avoid look-alike characters (l 1 I | O 0 o)")
        self.avoid.setChecked(setting("gen/avoid", False))
        p.addWidget(self.avoid)
        root.addWidget(self.password_opts)

        # Passphrase options
        self.phrase_opts = QWidget()
        q = QVBoxLayout(self.phrase_opts)
        q.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(BodyLabel("Words"))
        self.word_count = Slider(Qt.Horizontal)
        self.word_count.setRange(3, 10)
        self.word_count.setValue(int(setting("gen/words", 5)))
        row.addWidget(self.word_count, 1)
        self.words_label = BodyLabel("")
        self.words_label.setFixedWidth(28)
        row.addWidget(self.words_label)
        q.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(BodyLabel("Separator"))
        self.separator = ComboBox()
        self.separator.addItems(["-", ".", "_", "space"])
        self.separator.setCurrentText(setting("gen/separator", "-"))
        row.addWidget(self.separator)
        self.capitalize = CheckBox("Capitalise")
        self.capitalize.setChecked(setting("gen/capitalize", True))
        row.addWidget(self.capitalize)
        self.add_number = CheckBox("Add a number")
        self.add_number.setChecked(setting("gen/number", False))
        row.addWidget(self.add_number)
        row.addStretch(1)
        q.addLayout(row)
        root.addWidget(self.phrase_opts)

        for slider in (self.length, self.word_count):
            slider.valueChanged.connect(self.generate)
        for box in (*self.classes.values(), self.avoid, self.capitalize, self.add_number):
            box.stateChanged.connect(self.generate)
        self.separator.currentTextChanged.connect(self.generate)
        mode = setting("gen/mode", "password")
        self.mode.setCurrentItem(mode)
        self._mode = mode
        self._show_mode()

    def _set_mode(self, mode):
        self._mode = mode
        self._show_mode()
        self.generate()
        self.closed.emit()  # password and passphrase options differ in height

    def _show_mode(self):
        self.password_opts.setVisible(self._mode == "password")
        self.phrase_opts.setVisible(self._mode == "passphrase")

    def generate(self):
        self.length_label.setText(str(self.length.value()))
        self.words_label.setText(str(self.word_count.value()))
        # Keep at least one character type ticked.
        if not any(b.isChecked() for b in self.classes.values()):
            self.classes["lower"].setChecked(True)
            return  # setChecked triggers generate again
        if self._mode == "password":
            value, bits = generator.generate_password(
                self.length.value(), upper=self.classes["upper"].isChecked(),
                lower=self.classes["lower"].isChecked(), digits=self.classes["digits"].isChecked(),
                symbols=self.classes["symbols"].isChecked(), avoid_look_alikes=self.avoid.isChecked())
        else:
            separator = " " if self.separator.currentText() == "space" else self.separator.currentText()
            value, bits = generator.generate_passphrase(
                self.word_count.value(), separator, self.capitalize.isChecked(), self.add_number.isChecked())
        self._save_options()
        self.generated.emit(value, bits)

    def _save_options(self):
        settings.setValue("gen/mode", self._mode)
        settings.setValue("gen/length", self.length.value())
        settings.setValue("gen/words", self.word_count.value())
        settings.setValue("gen/separator", self.separator.currentText())
        settings.setValue("gen/avoid", self.avoid.isChecked())
        settings.setValue("gen/capitalize", self.capitalize.isChecked())
        settings.setValue("gen/number", self.add_number.isChecked())
        for key, box in self.classes.items():
            settings.setValue(f"gen/{key}", box.isChecked())


STRENGTH_COLORS = ["#d13438", "#ca5010", "#5c9e31", "#107c10"]  # weak, fair, good, excellent


class EntryEditor(MessageBoxBase):
    """Create or edit an entry. After exec(), `op` holds the change (or None)."""

    def __init__(self, parent, db, entry=None, folder_id=None):
        super().__init__(parent)
        self.db = db
        self.entry = entry
        self.op = None
        self._generated = None  # (value, bits) of the last generated password
        raw = entry["raw"] if entry else {f: "" for f in store.FIELDS}

        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel("Edit entry" if entry else "New entry"))

        # The fields scroll if the window is too short to show them all (nothing gets squashed).
        self.body = QWidget()
        self.body.setStyleSheet("background: transparent;")
        self.form = QVBoxLayout(self.body)
        self.form.setContentsMargins(0, 0, 10, 0)  # room for the scroll bar
        self.form.setSpacing(6)
        self.scroll = ScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.enableTransparentBackground()
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.scrollDelagate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        self.scroll.setWidget(self.body)
        self.viewLayout.addWidget(self.scroll)

        self.title = LineEdit()
        self.title.setText(raw["title"])
        self.title.setPlaceholderText("e.g. GitHub")
        self.username = LineEdit()
        self.username.setText(raw["username"])
        self.url = LineEdit()
        self.url.setText(raw["url"])
        self.url.setPlaceholderText("https://")
        self.password = ColoredPasswordEdit()
        self.password.setText(raw["password"])
        self.password.textChanged.connect(self._update_strength)

        self._field("Title", self.title)
        self._field("Username", self.username)
        self._setup_username_suggestions()

        self.form.addWidget(caption("Password"))
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.password, 1)
        self.show_pw = TransparentToggleToolButton(FIF.VIEW)
        self.show_pw.setToolTip("Show password")
        self.show_pw.toggled.connect(self._on_show)
        row.addWidget(self.show_pw)
        self.gen_btn = TransparentPushButton(icon("SYNC", "ROBOT"), "Generate")
        self.gen_btn.setToolTip("Generate a new password (and show the options)")
        self.gen_btn.clicked.connect(self._generate)
        row.addWidget(self.gen_btn)
        self.form.addLayout(row)

        strength = QHBoxLayout()
        self.strength_bar = ProgressBar()
        self.strength_bar.setRange(0, 100)
        strength.addWidget(self.strength_bar, 1)
        self.strength_label = caption("")
        self.strength_label.setFixedWidth(150)
        strength.addWidget(self.strength_label)
        self.form.addLayout(strength)

        self.generator = PasswordGenerator()
        self.generator.generated.connect(self._use_generated)
        self.generator.closed.connect(self._fit)
        self.generator.hide()
        self.form.addWidget(self.generator)

        self._field("Website", self.url)

        self.otp = LineEdit()
        self.otp.setText(raw["otp"])
        self.otp.setPlaceholderText("Optional: the site's 2FA secret key or otpauth:// link")
        self._field("2FA (authenticator code)", self.otp)

        self.folder = ComboBox()
        current = entry["folder_id"] if entry else folder_id
        choices = [(db.name, None)] + [(" › ".join(f["path"]), f["id"]) for f in db.folders
                                       if not f["in_bin"] or f["id"] == current]
        for text, folder in choices:
            self.folder.addItem(text, userData=folder)
        ids = [folder for _, folder in choices]
        self.folder.setCurrentIndex(ids.index(current) if current in ids else 0)
        self._field("Folder", self.folder)

        self.form.addWidget(caption("Notes"))
        self.notes = PlainTextEdit()
        self.notes.setPlainText(raw["notes"])
        self.notes.setFixedHeight(76)
        self.form.addWidget(self.notes)

        self.error = CaptionLabel("")
        self.error.setTextColor("#d13438", "#ff99a4")
        self.error.hide()
        self.viewLayout.addWidget(self.error)

        self.yesButton.setText("Save" if entry else "Add entry")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(560)

        for line in (self.title, self.username, self.password, self.url):
            line.returnPressed.connect(self.yesButton.click)
        if entry is None:  # new entries start with a generated password
            self._generate()
        self._update_strength()
        self._fit()
        self.title.setFocus()

    def _field(self, label, widget):
        self.form.addWidget(caption(label))
        self.form.addWidget(widget)

    # ---- username suggestions
    # Shown as a small list inside the dialog, under the field. (A pop-up suggestion menu
    # captures the next click anywhere, so the first click on Cancel only closed the menu.)

    SUGGESTION_ROWS = 5
    SUGGESTION_ROW_HEIGHT = 30

    def _setup_username_suggestions(self):
        counts = Counter(e["raw"]["username"] for e in self.db.entries
                         if not e["in_bin"] and e["raw"]["username"] and not e["raw"]["username"].startswith("{REF:"))
        self._usernames = [name for name, _ in counts.most_common()]  # most used first
        self.suggestions = ListWidget()
        self.suggestions.setFocusPolicy(Qt.NoFocus)  # typing stays in the Username field
        self.suggestions.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.suggestions.itemClicked.connect(lambda item: self._use_suggestion(item.text()))
        setCustomStyleSheet(
            self.suggestions,
            "ListWidget { border: 1px solid rgba(0, 0, 0, 0.12); border-radius: 6px; background: rgba(255, 255, 255, 0.9); }",
            "ListWidget { border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 6px; background: rgba(255, 255, 255, 0.05); }")
        self.suggestions.hide()
        self.form.addWidget(self.suggestions)
        if not self._usernames:
            return
        self.username.textEdited.connect(lambda _: self._update_suggestions())
        self.username.installEventFilter(self)

    def _update_suggestions(self):
        text = self.username.text().strip().lower()
        matches = [n for n in self._usernames if text in n.lower() and n.lower() != text][:self.SUGGESTION_ROWS]
        if not matches or not self.username.hasFocus():
            self._hide_suggestions()
            return
        self.suggestions.clear()
        self.suggestions.addItems(matches)
        for i in range(self.suggestions.count()):
            self.suggestions.item(i).setSizeHint(QSize(0, self.SUGGESTION_ROW_HEIGHT))
        self.suggestions.setFixedHeight(len(matches) * self.SUGGESTION_ROW_HEIGHT + 8)
        if not self.suggestions.isVisible():
            self.suggestions.show()
            self._fit()

    def _hide_suggestions(self):
        if self.suggestions.isVisible():
            self.suggestions.hide()
            self._fit()

    def _use_suggestion(self, name):
        self.username.setText(name)
        self.username.setFocus()
        self._hide_suggestions()

    def eventFilter(self, obj, event):
        if obj is getattr(self, "username", None):
            kind = event.type()
            if kind == QEvent.FocusIn:
                QTimer.singleShot(0, self._update_suggestions)
            elif kind == QEvent.FocusOut:
                self._hide_suggestions()
            elif kind == QEvent.KeyPress and self.suggestions.isVisible():
                key, rows, row = event.key(), self.suggestions.count(), self.suggestions.currentRow()
                if key == Qt.Key_Down:
                    self.suggestions.setCurrentRow(min(row + 1, rows - 1))
                    return True
                if key == Qt.Key_Up:
                    self.suggestions.setCurrentRow(max(row - 1, -1))
                    if row - 1 < 0:
                        self.suggestions.clearSelection()
                    return True
                if key in (Qt.Key_Return, Qt.Key_Enter) and row >= 0:
                    self._use_suggestion(self.suggestions.item(row).text())
                    return True
                if key == Qt.Key_Escape:  # hide the list, don't close the dialog
                    self._hide_suggestions()
                    return True
        return super().eventFilter(obj, event)

    def entry_raw(self, name):
        return self.entry["raw"][name] if self.entry else ""

    def _on_show(self, on):
        self.password.set_revealed(on)
        self.show_pw.setIcon(FIF.HIDE if on else FIF.VIEW)

    def _generate(self):
        """Always makes a new password; also shows the generator options if they're hidden."""
        self.generator.show()
        self.generator.generate()
        self._fit()

    def _fit(self):
        """Sizes the form to its contents, scrolling only if the window is too short."""
        self.body.adjustSize()
        needed = self.body.sizeHint().height()
        self.body.setMinimumHeight(needed)  # never squash fields; scroll instead
        window = self.parent().window() if self.parent() else None
        available = (window.height() if window else 800) - 196  # title, buttons and margins
        self.scroll.setFixedHeight(max(200, min(needed, available)))

    def _use_generated(self, value, bits):
        self._generated = (value, bits)
        self.show_pw.setChecked(True)
        self.password.setText(value)

    def _update_strength(self):
        value = self.password.text()
        if not value:
            self.strength_bar.setValue(0)
            self.strength_label.setText("No password")
            return
        bits = self._generated[1] if self._generated and self._generated[0] == value else generator.estimate_bits(value)
        label, score, level = generator.strength_label(bits)
        color = QColor(STRENGTH_COLORS[level])
        self.strength_bar.setCustomBarColor(color, color)
        self.strength_bar.setValue(max(score, 4))
        self.strength_label.setText(f"{label} · ~{int(bits)} bits")

    def validate(self):
        if not self.title.text().strip():
            self.error.setText("Give the entry a title.")
            self.error.show()
            self.title.setFocus()
            return False
        otp_error = totp.validate(self.otp.text())
        if otp_error and self.otp.text().strip() != self.entry_raw("otp"):
            self.error.setText(otp_error)
            self.error.show()
            self.otp.setFocus()
            return False
        values = dict(title=self.title.text().strip(), username=self.username.text(), password=self.password.text(),
                      url=self.url.text().strip(), notes=self.notes.toPlainText(), otp=self.otp.text().strip())
        folder = self.folder.currentData()
        if self.entry is None:
            self.op = Op("create", uuidlib.uuid4().hex, fields=values, all_fields=values, folder=folder,
                         title=values["title"])
        else:
            changed = {k: v for k, v in values.items() if v != self.entry["raw"][k]}
            if changed or folder != self.entry["folder_id"]:
                self.op = Op("update", self.entry["uuid"], fields=changed, all_fields=values, folder=folder,
                             base_mtime=self.entry["base_mtime"], title=values["title"])
        return True


class NameDialog(MessageBoxBase):
    """Asks for a name (new folder, rename). After exec(), `name` holds it."""

    def __init__(self, parent, title, label, value="", hint=""):
        super().__init__(parent)
        self.name = value
        self.viewLayout.addWidget(SubtitleLabel(title))
        if hint:
            self.viewLayout.addWidget(caption(hint))
        self.viewLayout.addWidget(caption(label))
        self.edit = LineEdit()
        self.edit.setText(value)
        self.edit.selectAll()
        self.edit.returnPressed.connect(self.yesButton.click)
        self.viewLayout.addWidget(self.edit)
        self.yesButton.setText("OK")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(420)
        self.edit.setFocus()

    def validate(self):
        self.name = self.edit.text().strip()
        return bool(self.name)


class FolderPickerDialog(MessageBoxBase):
    """Asks for a folder (outside the Recycle Bin). After exec(), `folder` holds its id (None = root)."""

    def __init__(self, parent, db, title, current=None, exclude=None):
        super().__init__(parent)
        self.folder = current
        self.viewLayout.addWidget(SubtitleLabel(title))
        self.combo = ComboBox()
        excluded = set()
        if exclude:  # a folder can't move into itself or its subfolders
            excluded = {exclude} | {f["id"] for f in db.folders if exclude in folder_ancestors(db, f["id"])}
        choices = [(db.name, None)] + [(" › ".join(f["path"]), f["id"]) for f in db.folders
                                       if not f["in_bin"] and f["id"] not in excluded]
        for text, folder in choices:
            self.combo.addItem(text, userData=folder)
        ids = [folder for _, folder in choices]
        self.combo.setCurrentIndex(ids.index(current) if current in ids else 0)
        self.viewLayout.addWidget(self.combo)
        self.yesButton.setText("Move")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(460)

    def validate(self):
        self.folder = self.combo.currentData()
        return True


def folder_ancestors(db, folder_id):
    by_id = {f["id"]: f for f in db.folders}
    out = []
    while folder_id in by_id:
        folder_id = by_id[folder_id]["parent"]
        if folder_id is not None:
            out.append(folder_id)
    return out


class IconFetcher(QObject):
    """Downloads site icons in the background and stores them in the database."""

    ICON_THREADS = 8

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.running = False

    def fetch(self, entries, label="Site icon", announce=False):
        saver = self.window.saver
        db = saver.db
        if db is None or not db.writable or self.running:
            return
        jobs = [(e["uuid"], e["title"], e["url"]) for e in entries if favicon.site_host(e["url"])]
        if not jobs:
            if announce:
                self._info("No website", "This entry has no website address to get an icon from.")
            return
        self.running = True
        progress = {"done": 0}
        allow_ddg = setting("icons_duckduckgo", False)
        bar = None
        if len(jobs) > 1:
            bar = InfoBar.info("Downloading site icons", f"0 of {len(jobs)}…", orient=Qt.Horizontal,
                               isClosable=False, position=InfoBarPosition.BOTTOM_RIGHT, duration=-1,
                               parent=self.window)

        def work():
            def one(job):
                png = favicon.fetch(job[2], allow_ddg)
                progress["done"] += 1
                return job, png
            with ThreadPoolExecutor(self.ICON_THREADS) as pool:
                return list(pool.map(one, jobs))

        def update_progress():
            if self.running and bar is not None:
                bar.contentLabel.setText(f"{progress['done']} of {len(jobs)}…")
                QTimer.singleShot(300, update_progress)

        def done(results, error):
            self.running = False
            if bar is not None:
                bar.close()
            if error or saver.db is not db:
                return
            ops = [Op("set_icon", uuid, icon=png, icon_name=favicon.site_host(url) or "", title=title)
                   for (uuid, title, url), png in results if png]
            saver.submit_many(ops, label)
            missing = len(jobs) - len(ops)
            if announce or len(jobs) > 1:
                text = f"Updated {len(ops)} icon{'s' if len(ops) != 1 else ''}."
                if missing:
                    text += f" {missing} site{'s' if missing != 1 else ''} had no icon we could get."
                    if not allow_ddg:
                        text += " Turning on the DuckDuckGo fallback in Settings may help."
                self._info("Site icons", text)

        update_progress()
        run_in_background(self, work, done)

    def _info(self, title, text):
        InfoBar.info(title, text, orient=Qt.Vertical, isClosable=True, position=InfoBarPosition.TOP_RIGHT,
                     duration=5000, parent=self.window)


class ConflictDialog(MessageBoxBase):
    """Asks what to do when an entry was changed or deleted elsewhere. `choice` is set to
    "mine", "theirs" or "both"."""

    def __init__(self, parent, conflict):
        super().__init__(parent)
        self.choice = "theirs"
        name = conflict.op.title or "An entry"
        self.viewLayout.addWidget(SubtitleLabel("Changed in two places"))
        if conflict.reason == "changed":
            text = (f"“{name}” was changed by another device or app after you started editing it.\n\n"
                    "Keep mine: your version is saved; theirs is kept in the entry's history.\n"
                    "Keep theirs: your edit is discarded.\n"
                    "Keep both: your version is saved as a separate copy.")
            mine, theirs = "Keep mine", "Keep theirs"
        else:
            text = (f"“{name}” was deleted by another device or app after you started editing it.\n\n"
                    "Restore it with your changes, or leave it deleted?")
            mine, theirs = "Restore with my changes", "Leave it deleted"
        body = BodyLabel(text)
        body.setWordWrap(True)
        self.viewLayout.addWidget(body)
        self.yesButton.setText(mine)
        self.cancelButton.setText(theirs)
        if conflict.reason == "changed":
            both = PushButton("Keep both")
            both.clicked.connect(self._both)
            self.buttonLayout.insertWidget(1, both, 1, Qt.AlignVCenter)
        self.widget.setMinimumWidth(520)

    def validate(self):
        self.choice = "mine"
        return True

    def _both(self):
        self.choice = "both"
        self.accept()


class SaveController(QObject):
    """Auto-saves edits, merges changes made elsewhere, and reloads when the file changes.

    Edits are applied to the open database straight away and saved after a short pause.
    `unsaved` holds edits not yet on disk, so they can be re-applied if the file turns out
    to have been changed by another device or app in the meantime.
    """

    status = Signal(str)
    reloaded = Signal()  # the snapshot was rebuilt from a changed file

    SAVE_DELAY_MS = 1500

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.db = None
        self.unsaved = []
        self.queued = []  # (ops, label, undoable, force) batches made while a save is running
        self.undo_stack = []
        self.busy = False  # a save or reload is running
        self.failed = False
        self.last_backup = 0.0
        self.flush_callbacks = []
        self.last_stat = None
        self.save_timer = QTimer(self, singleShot=True, interval=self.SAVE_DELAY_MS, timeout=self.save_now)
        self.retry_timer = QTimer(self, singleShot=True, interval=15000, timeout=self.save_now)
        self.poll_timer = QTimer(self, interval=4000, timeout=self.check_external)

    def attach(self, db):
        self.db = db
        self.unsaved, self.queued, self.flush_callbacks = [], [], []
        self.undo_stack = []  # (label, inverse ops) for this session
        self.busy = self.failed = False
        self.last_backup = 0.0
        self.last_stat = self._stat()
        self.poll_timer.start()
        self.status.emit("All changes saved" if db.writable else "Read-only")

    def detach(self):
        self.save_timer.stop()
        self.retry_timer.stop()
        self.poll_timer.stop()
        self.db = None
        self.undo_stack = []  # holds old values (passwords), so drop it when locking

    @property
    def pending(self):
        return bool(self.unsaved or self.queued or self.busy)

    def _stat(self):
        try:
            st = os.stat(self.db.path)
            return st.st_size, st.st_mtime_ns
        except OSError:
            return None

    # ---- edits

    def submit(self, op, label=None, undoable=True):
        self.submit_many([op], label or op.title, undoable)

    def submit_many(self, ops, label="", undoable=True, force=False):
        """Applies several edits as one step (one snapshot rebuild, one undo step)."""
        if not ops:
            return
        if self.busy:
            self.queued.append((ops, label, undoable, force))
            self.status.emit("Saving…")
            return
        self._apply_batch(ops, label, undoable, force)

    def _apply_batch(self, ops, label, undoable, force):
        kp = self.db.kp
        inverses = []
        for op in ops:
            inverse = store.inverse_op(kp, op) if undoable else None
            conflict = store.apply_op(kp, op, force=force)
            if conflict is None:
                self.unsaved.append(op)
                inverses.append(inverse)
                continue
            # The entry changed since the editor was opened (e.g. after a reload).
            for resolved in self._resolve(conflict):
                inverses.append(store.inverse_op(kp, resolved) if undoable else None)
                store.apply_op(kp, resolved, force=True)
                self.unsaved.append(resolved)
        inverses = [i for i in reversed(inverses) if i]
        if undoable and inverses:
            self.undo_stack.append((label, inverses))
            del self.undo_stack[:-50]
        self.db.build_snapshot()
        self.reloaded.emit()
        self.status.emit("Unsaved changes")
        self.save_timer.start()

    def undo(self):
        """Undoes the most recent change made in this session. Returns its label, or None."""
        if not self.undo_stack or self.db is None:
            return None
        label, inverses = self.undo_stack.pop()
        self.submit_many(inverses, label, undoable=False, force=True)
        return label

    def _resolve(self, conflict):
        """Asks the user; returns the operations to apply (with force=True)."""
        dialog = ConflictDialog(self.window, conflict)
        dialog.exec()
        if dialog.choice == "mine":
            return [conflict.op]
        if dialog.choice == "both":
            return [store.keep_both_op(conflict.op)]
        return []

    # ---- saving

    def save_now(self):
        if self.busy or not self.unsaved or self.db is None:
            return
        self.busy = True
        self.status.emit("Saving…")
        backup = time.time() - self.last_backup > store.BACKUP_INTERVAL
        db = self.db
        run_in_background(self, lambda: store.save_database(db.kp, db.path, db.digest, backup=backup),
                          lambda result, error: self._saved(db, result, error, backup))

    def _saved(self, db, new_digest, error, backup):
        if db is not self.db:
            return
        if isinstance(error, store.FileChanged):
            self._merge(error.data)
            return
        self.busy = False
        if error:
            self.failed = True
            self.status.emit("Couldn't save — will retry")
            InfoBar.error("Couldn't save your changes", f"{error}\nVault will keep trying.", orient=Qt.Vertical,
                          isClosable=True, position=InfoBarPosition.TOP_RIGHT, duration=8000, parent=self.window)
            if self.flush_callbacks:
                self._ask_flush_failed(error)
            else:
                self.retry_timer.start()
            return
        db.digest = new_digest
        if backup:
            self.last_backup = time.time()
        self.unsaved.clear()
        self.failed = False
        self.last_stat = self._stat()
        queued, self.queued = self.queued, []
        for batch in queued:
            self._apply_batch(*batch)
        if not self.unsaved:
            self.status.emit("All changes saved")
            callbacks, self.flush_callbacks = self.flush_callbacks, []
            for callback in callbacks:
                callback()
        elif self.flush_callbacks:
            self.save_now()

    def _merge(self, data):
        """The file changed elsewhere: reload it and re-apply our unsaved edits on top."""
        self.status.emit("Merging changes from another device…")
        db = self.db
        run_in_background(self, lambda: store.open_kp(data, db.kp.password, db.kp.keyfile),
                          lambda fresh, error: self._merged(db, data, fresh, error))

    def _merged(self, db, data, fresh, error):
        if db is not self.db:
            return
        self.busy = False
        if error:
            self._saved(db, None, error, False)
            return
        replayed = []
        for op in self.unsaved:
            conflict = store.apply_op(fresh, op)
            if conflict is None:
                replayed.append(op)
            else:
                for resolved in self._resolve(conflict):
                    store.apply_op(fresh, resolved, force=True)
                    replayed.append(resolved)
        db.replace_kp(fresh, data)
        self.unsaved = replayed
        self.last_stat = self._stat()
        self.reloaded.emit()
        InfoBar.info("Merged", "The database had been changed elsewhere; your edits were added on top.",
                     orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.TOP_RIGHT,
                     duration=4000, parent=self.window)
        if self.unsaved:
            self.save_now()
        else:
            self._saved(db, db.digest, None, False)

    def flush(self, callback):
        """Calls `callback` once everything is saved (immediately if nothing is pending)."""
        if not self.pending or self.db is None:
            callback()
            return
        self.flush_callbacks.append(callback)
        self.save_timer.stop()
        self.save_now()

    def _ask_flush_failed(self, error):
        box = MessageBox("Couldn't save your changes",
                         f"{error}\n\nTry again, or continue and lose the unsaved changes?", self.window)
        box.yesButton.setText("Try again")
        box.cancelButton.setText("Continue without saving")
        if box.exec():
            self.save_now()
        else:
            self.unsaved, self.queued = [], []
            callbacks, self.flush_callbacks = self.flush_callbacks, []
            for callback in callbacks:
                callback()

    # ---- changes made elsewhere

    def check_external(self, manual=False):
        """Reloads the database if another device or app changed the file. Runs every few seconds;
        `manual` (the Check for changes button / F5) checks even if the file looks untouched."""
        if self.db is None:
            return
        if self.pending:
            if manual:  # saving detects outside changes and merges them with ours
                self.save_timer.stop()
                self.save_now()
                self._info("Checking for changes", "Saving your edits; anything changed elsewhere is merged in.")
            return
        stat = self._stat()
        if stat is None:
            if manual:
                self._info("Can't read the file", "The database file isn't available right now. Is Google "
                           "Drive running?", warning=True)
            return
        if stat == self.last_stat and not manual:
            return
        self.last_stat = stat
        db = self.db
        self.busy = True

        def load():
            data = Path(db.path).read_bytes()
            if store.digest(data) == db.digest:
                return None
            return data, store.open_kp(data, db.kp.password, db.kp.keyfile)

        run_in_background(self, load, lambda result, error: self._external_loaded(db, result, error, manual))

    def _info(self, title, text, warning=False):
        (InfoBar.warning if warning else InfoBar.info)(
            title, text, orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.TOP_RIGHT,
            duration=3000, parent=self.window)

    def _external_loaded(self, db, result, error, manual=False):
        self.busy = False
        if db is not self.db or error or result is None:
            if manual and db is self.db:
                if error:
                    self._info("Couldn't check for changes", str(error), warning=True)
                else:
                    self._info("Up to date", "No changes have been made elsewhere.")
            if self.queued:
                queued, self.queued = self.queued, []
                for batch in queued:
                    self._apply_batch(*batch)
            return
        data, fresh = result
        db.replace_kp(fresh, data)
        self.reloaded.emit()
        self.status.emit(f"Updated from elsewhere at {datetime.now():%H:%M}")
        self._info("Updated", "Loaded changes made by another device or app.")
        queued, self.queued = self.queued, []
        for batch in queued:
            self._apply_batch(*batch)


# ---------------------------------------------------------------- other screens

ISSUE_COLORS = {"weak": "#d13438", "reused": "#ca5010", "empty": "#8764b8", "expired": "#c239b3", "old": "#0f6cbd"}


class HealthCard(CardWidget):
    def __init__(self, issue, parent=None):
        super().__init__(parent)
        self.issue = issue
        self.setFixedHeight(84)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(0)
        self.count = TitleLabel("–")
        self.count.setTextColor(QColor(ISSUE_COLORS[issue]), QColor(ISSUE_COLORS[issue]).lighter(150))
        layout.addWidget(self.count)
        layout.addWidget(caption(health.ISSUES[issue][0]))

    def set_selected(self, on):
        self.setProperty("selected", on)
        self.setStyleSheet(f"HealthCard {{ border: 2px solid {ISSUE_COLORS[self.issue]}; border-radius: 6px; }}"
                           if on else "")


class HealthView(QWidget):
    """Password health report: weak, reused, empty, expired and old passwords."""

    COLUMNS = ["Problem", "Title", "Username", "Folder", "Details"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("view-health")
        self.db = None
        self.issues = []
        self.filter = None
        self.dirty = True
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 28, 36, 28)
        root.setSpacing(14)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(TitleLabel("Password health"))
        self.subtitle = caption("Entries in the Recycle Bin aren't checked. Double-click an entry to fix it.")
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        refresh = PushButton(FIF.SYNC, "Check again")
        refresh.clicked.connect(self.refresh)
        head.addWidget(refresh, 0, Qt.AlignVCenter)
        root.addLayout(head)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.cards = {}
        for issue in health.ISSUES:
            card = HealthCard(issue)
            card.clicked.connect(lambda i=issue: self._toggle_filter(i))
            self.cards[issue] = card
            cards.addWidget(card)
        root.addLayout(cards)

        self.table = TableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setWordWrap(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setDefaultSectionSize(36)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        for col, width in enumerate((210, 220, 200, 170)):
            self.table.setColumnWidth(col, width)
        self.table.scrollDelagate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        self._dbl = CellDoubleClick(self.table, self._open)
        root.addWidget(self.table, 1)
        self.empty = BodyLabel("")
        self.empty.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty)

    def set_db(self, db):
        self.db = db
        self.dirty = True
        if db is None:
            self.issues = []
            self._show()
        elif self.isVisible():
            self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if self.dirty and self.db is not None:
            self.refresh()

    def refresh(self):
        if self.db is None:
            return
        self.dirty = False
        entries = list(self.db.entries)
        self.empty.setText("Checking passwords…")
        run_in_background(self, lambda: health.report(entries), self._done)

    def _done(self, issues, error):
        if error:
            self.empty.setText(f"Couldn't check passwords: {error}")
            return
        self.issues = issues or []
        self._show()

    def _toggle_filter(self, issue):
        self.filter = None if self.filter == issue else issue
        self._show()

    def _show(self):
        counts = health.summary(self.issues)
        for issue, card in self.cards.items():
            card.count.setText(str(counts[issue]))
            card.set_selected(self.filter == issue)
        rows = [i for i in self.issues if self.filter in (None, i["issue"])]
        self.table.setRowCount(len(rows))
        self.rows = rows
        for r, issue in enumerate(rows):
            e = issue["entry"]
            values = [health.ISSUES[issue["issue"]][0], e["title"], e["username"], e["folder"], issue["detail"]]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if c == 0:
                    item.setForeground(QColor(ISSUE_COLORS[issue["issue"]]))
                self.table.setItem(r, c, item)
        if self.db is None:
            self.empty.setText("")
        elif not self.issues:
            self.empty.setText("No problems found. 🎉")
        else:
            self.empty.setText("")

    def _open(self, index):
        if 0 <= index.row() < len(self.rows):
            self.window().show_entry(self.rows[index.row()]["entry"]["uuid"], edit=True)


class SettingsView(ScrollArea):
    def __init__(self, on_colorize, on_density, on_fetch_missing, on_refresh_icons, parent=None):
        super().__init__(parent)
        self.setObjectName("view-settings")
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self.scrollDelagate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        self.setWidget(page)
        root = QVBoxLayout(page)
        root.setContentsMargins(36, 28, 36, 36)
        root.setSpacing(14)
        root.addWidget(TitleLabel("Settings"))

        themes = ComboBox()
        for name in THEMES:
            themes.addItem(name, theme_swatch(name))
        themes.setCurrentText(theme_name())
        themes.currentTextChanged.connect(self._set_theme)
        root.addWidget(self._row("Theme", "Colours for the whole app. System follows Windows' light or dark mode.",
                                 themes))
        clipboard = ComboBox()
        clipboard.addItems(list(CLIPBOARD_CHOICES))
        clipboard.setCurrentText(duration_text(clipboard_seconds()))
        clipboard.currentTextChanged.connect(lambda name: settings.setValue("clipboard_seconds", CLIPBOARD_CHOICES[name]))
        root.addWidget(self._row(
            "Clear clipboard after", "How long copied usernames, passwords and 2FA codes stay on the clipboard "
            "before Vault wipes them.", clipboard))
        root.addWidget(self._row(
            "Lock when idle", f"Lock the database after {IDLE_LOCK_MINUTES} minutes without keyboard or mouse use.",
            self._bool_switch("lock_idle")))
        root.addWidget(self._row(
            "Colour-code passwords",
            "When shown, colour uppercase, lowercase, digits and symbols differently.",
            self._bool_switch("color_passwords", on_colorize)))
        density = ComboBox()
        density.addItems(list(ROW_DENSITIES))
        density.setCurrentText(setting("row_density", "Comfortable"))
        density.currentTextChanged.connect(lambda name: settings.setValue("row_density", name))
        density.currentTextChanged.connect(on_density)
        root.addWidget(self._row("Row density", "How tightly entries are packed in the table.", density))

        root.addSpacing(8)
        root.addWidget(SubtitleLabel("Site icons"))
        root.addWidget(self._row(
            "Download icons automatically",
            "Get the website's icon when you add an entry or change its website. Icons are saved in the "
            "database, so KeePass and KeePassXC show them too.",
            self._bool_switch("icons_auto")))
        root.addWidget(self._row(
            "Use DuckDuckGo as a fallback",
            "Icons come straight from each website. If a site has none, ask DuckDuckGo's icon service "
            "(this tells DuckDuckGo which site you're looking up).",
            self._bool_switch("icons_duckduckgo", default=False)))
        buttons = QWidget()
        b = QHBoxLayout(buttons)
        b.setContentsMargins(0, 0, 0, 0)
        missing = PushButton(icon("DOWNLOAD", "GLOBE"), "Download missing icons")
        missing.clicked.connect(on_fetch_missing)
        b.addWidget(missing)
        refresh = PushButton(FIF.SYNC, "Refresh all icons")
        refresh.clicked.connect(on_refresh_icons)
        b.addWidget(refresh)
        root.addWidget(self._row("Update icons", "For entries that have a website address. Refreshing picks up "
                                 "sites that have changed their icon.", buttons))
        root.addStretch(1)
        root.addWidget(caption(f"Vault {VERSION}"), 0, Qt.AlignRight)

    def _set_theme(self, name):
        settings.setValue("theme", name)
        apply_theme(name, self.window())

    @staticmethod
    def _bool_switch(key, on_change=None, default=True):
        sw = SwitchButton()
        sw.setChecked(setting(key, default))
        sw.checkedChanged.connect(lambda on: settings.setValue(key, on))
        if on_change:
            sw.checkedChanged.connect(on_change)
        return sw

    @staticmethod
    def _row(title, desc, control):
        card = SimpleCardWidget()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 14, 20, 14)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(BodyLabel(title))
        text.addWidget(caption(desc))
        layout.addLayout(text, 1)
        layout.addWidget(control)
        return card


class UnlockDialog(MessageBoxBase):
    """Asks for the database file, master password and optional key file, then opens it."""

    def __init__(self, parent):
        super().__init__(parent)
        self.db = None
        self.path = setting("last_file", "")
        self.keyfile = setting("last_keyfile", "")
        self._worker = None

        self.viewLayout.setSpacing(10)
        self.viewLayout.addWidget(SubtitleLabel("Unlock database"))

        file_row = QHBoxLayout()
        self.file_label = caption("")
        file_row.addWidget(self.file_label, 1)
        choose = PushButton(FIF.FOLDER, "Choose…")
        choose.clicked.connect(self._choose_file)
        file_row.addWidget(choose)
        self.viewLayout.addLayout(file_row)

        self.pw = PasswordLineEdit()
        self.pw.setPlaceholderText("Master password")
        self.pw.returnPressed.connect(self.yesButton.click)
        self.viewLayout.addWidget(self.pw)

        key_row = QHBoxLayout()
        self.key_label = caption("")
        key_row.addWidget(self.key_label, 1)
        self.key_clear = TransparentToolButton(FIF.CLOSE)
        self.key_clear.setToolTip("Don't use a key file")
        self.key_clear.clicked.connect(lambda: self._set_keyfile(""))
        key_row.addWidget(self.key_clear)
        key_btn = PushButton(icon("FINGERPRINT", "CERTIFICATE"), "Key file…")
        key_btn.clicked.connect(self._choose_keyfile)
        key_row.addWidget(key_btn)
        self.viewLayout.addLayout(key_row)

        self.error = CaptionLabel("")
        self.error.setTextColor("#d13438", "#ff99a4")
        self.error.setWordWrap(True)
        self.error.hide()
        self.viewLayout.addWidget(self.error)

        self.yesButton.setText("Unlock")
        self.cancelButton.setText("Quit")
        self.widget.setMinimumWidth(460)
        self._set_path(self.path if self.path and Path(self.path).exists() else "")
        self._set_keyfile(self.keyfile if self.keyfile and Path(self.keyfile).exists() else "")
        self.pw.setFocus()

    def _start_dir(self, current):
        if current:
            return str(Path(current).parent)
        return str(google_drive_folder() or Path.home())

    def _set_path(self, path):
        self.path = path
        self.file_label.setText(Path(path).name if path else "No database chosen")
        self.file_label.setToolTip(path)

    def _set_keyfile(self, path):
        self.keyfile = path
        self.key_label.setText(f"Key file: {Path(path).name}" if path else "No key file")
        self.key_label.setToolTip(path)
        self.key_clear.setVisible(bool(path))

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open KeePass database", self._start_dir(self.path),
            "KeePass databases (*.kdbx *.k);;All files (*)")
        if path:
            self._set_path(path)
            self.pw.setFocus()

    def _choose_keyfile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose key file", self._start_dir(self.keyfile or self.path))
        if path:
            self._set_keyfile(path)

    def _show_error(self, text):
        self.error.setText(text)
        self.error.setVisible(bool(text))

    def validate(self):
        """Starts unlocking in the background; the dialog closes itself when it succeeds."""
        if self._worker is not None:
            return False
        if not self.path:
            self._show_error("Choose your database file first.")
            return False
        if not self.pw.text() and not self.keyfile:
            self._show_error("Enter your master password.")
            return False
        self._show_error("")
        self.yesButton.setEnabled(False)
        self.yesButton.setText("Unlocking…")
        result = {}

        def work(path=self.path, password=self.pw.text(), keyfile=self.keyfile):
            from pykeepass.exceptions import CredentialsError, HeaderChecksumError, PayloadChecksumError
            try:
                result["db"] = Database(path, password, keyfile)
            except CredentialsError:
                result["error"] = "Wrong password or key file."
            except (HeaderChecksumError, PayloadChecksumError):
                result["error"] = "The database file is damaged or isn't a KeePass file."
            except FileNotFoundError:
                result["error"] = "The database file can't be found. Is Google Drive running?"
            except Exception as exc:  # show anything unexpected rather than crash
                result["error"] = f"Couldn't open the database: {exc}"

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()
        self._poll(result)
        return False

    def _poll(self, result):
        if self._worker.is_alive():
            QTimer.singleShot(50, lambda: self._poll(result))
            return
        self._worker = None
        self.yesButton.setEnabled(True)
        self.yesButton.setText("Unlock")
        if "db" in result:
            self.db = result["db"]
            self.pw.clear()
            settings.setValue("last_file", self.path)
            settings.setValue("last_keyfile", self.keyfile)
            self.accept()
        else:
            self._show_error(result["error"])
            self.pw.selectAll()
            self.pw.setFocus()


class IdleWatcher(QObject):
    """Calls `on_idle` after a period with no keyboard or mouse input anywhere in the app."""

    INPUT_EVENTS = {QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.Wheel}

    def __init__(self, minutes, on_idle):
        super().__init__()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(minutes * 60_000)
        self.timer.timeout.connect(on_idle)
        QApplication.instance().installEventFilter(self)
        self.timer.start()

    def eventFilter(self, obj, event):
        if event.type() in self.INPUT_EVENTS:
            self.timer.start()
        return False


class PrivacyCover(QWidget):
    """Covers the whole window with a plain screen (padlock + "Vault") so that pictures the system
    takes of the window, such as macOS's minimise animation and Dock thumbnail, or Windows' taskbar
    previews, don't show any passwords."""

    def __init__(self, window):
        super().__init__(window)
        self.hide()

    def show_over(self):
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        mode, _, background = THEMES.get(theme_name(), THEMES["System"])
        p.fillRect(self.rect(), QColor(background or DEFAULT_BACKGROUNDS[1 if isDarkTheme() else 0]))
        size = 96
        c = self.rect().center()
        QIcon(str(RESOURCE_DIR / "icons" / "vault.png")).paint(p, QRect(c.x() - size // 2, c.y() - size, size, size))
        p.setPen(QColor("#ffffff" if isDarkTheme() else "#1f1f1f"))
        font = getFont(28, QFont.DemiBold)
        p.setFont(font)
        p.drawText(QRect(0, c.y() + 12, self.width(), 44), Qt.AlignHCenter | Qt.AlignTop, "Vault")


class MainWindow(FluentWindow):
    COVER_DELAY_MS = 150  # time for the covered frame to reach the screen before minimising

    def __init__(self):
        super().__init__()
        self.stackedWidget.setAnimationEnabled(False)  # switch pages instantly (no 0.25 s slide)
        self.privacy_cover = PrivacyCover(self)
        self.setWindowTitle("Vault")
        self.resize(1360, 800)
        self.locked = True
        self._copied = None

        self.vault = VaultView()
        self.addSubInterface(self.vault, FIF.HOME, "Vault")
        self.navigationInterface.addItem(
            routeKey="lock", icon=icon("LOCK", "FINGERPRINT", "CLOSE"), text="Lock",
            onClick=self.lock, selectable=False, position=NavigationItemPosition.BOTTOM)
        self.health = HealthView()
        self.addSubInterface(self.health, icon("HEART", "CERTIFICATE"), "Password health")
        self.addSubInterface(SettingsView(on_colorize=self.vault.set_colorize, on_density=self.vault.set_density,
                                          on_fetch_missing=lambda: self.fetch_icons(missing_only=True),
                                          on_refresh_icons=lambda: self.fetch_icons(missing_only=False)),
                             FIF.SETTING, "Settings", NavigationItemPosition.BOTTOM)
        self.icons = IconFetcher(self)
        self.idle = IdleWatcher(IDLE_LOCK_MINUTES, self._on_idle)
        self.saver = SaveController(self)
        self.saver.status.connect(self.vault.set_save_status)
        self.saver.reloaded.connect(self._on_reloaded)
        self._closing = False

        # Window size and position (including maximised) are remembered.
        geometry = settings.value("window_geometry")
        if geometry is None or not self.restoreGeometry(geometry):
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.center() - self.rect().center())
        QApplication.instance().aboutToQuit.connect(self.save_geometry)

    # ---- hiding contents when minimised

    def minimize_privately(self):
        """Covers the window, lets the covered frame reach the screen, then minimises, so the
        minimise animation / Dock thumbnail / taskbar preview never shows passwords."""
        self.privacy_cover.show_over()
        self.repaint()
        QApplication.processEvents()
        QTimer.singleShot(self.COVER_DELAY_MS, self.showMinimized)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            if self.isMinimized():
                self.privacy_cover.show_over()  # best effort when minimised by the system (e.g. Cmd+M)
            elif self.privacy_cover.isVisible():
                QTimer.singleShot(self.COVER_DELAY_MS, self._uncover)

    def _uncover(self):
        if not self.isMinimized():
            self.privacy_cover.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "privacy_cover") and self.privacy_cover.isVisible():
            self.privacy_cover.setGeometry(self.rect())

    def save_geometry(self):
        settings.setValue("window_geometry", self.saveGeometry())

    def _on_reloaded(self):
        self.vault.load(self.saver.db, keep_state=True)
        self.health.set_db(self.saver.db)

    def show_entry(self, uuid, edit=False):
        """Shows an entry in the main view (clearing folder and search), optionally editing it."""
        self.switchTo(self.vault)
        v = self.vault
        v.folder = None
        v.tree.setCurrentItem(v.tree.topLevelItem(0))
        v.search.blockSignals(True)
        v.search.clear()
        v.search.blockSignals(False)
        entry = next((e for e in v.db.entries if e["uuid"] == uuid), None)
        if entry and entry["in_bin"] and v.db.bin_id:  # show the Recycle Bin folder instead
            v.load(v.db, select_uuid=uuid)
        v.refresh(select_uuid=uuid)
        if edit:
            QTimer.singleShot(150, v.edit_entry)

    def fetch_icons(self, missing_only):
        db = self.saver.db
        if db is None or not db.writable:
            return
        entries = [e for e in db.entries if not e["in_bin"] and favicon.site_host(e["url"])
                   and not (missing_only and e["icon"][1])]
        if not entries:
            InfoBar.info("Site icons", "Every entry with a website already has an icon." if missing_only
                         else "No entries have a website address.", orient=Qt.Horizontal, isClosable=True,
                         position=InfoBarPosition.TOP_RIGHT, duration=3000, parent=self)
            return
        self.icons.fetch(entries, "Missing icons download" if missing_only else "Icon refresh")

    def undo_toast(self, title, detail):
        """A confirmation message with an Undo button."""
        # Build it before showing, so its size includes the Undo button.
        bar = InfoBar(InfoBarIcon.SUCCESS, title, detail, orient=Qt.Horizontal, isClosable=True,
                      duration=8000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        button = TransparentPushButton(FIF.RETURN, "Undo")
        button.clicked.connect(lambda: (self.vault.undo(), bar.close()))
        bar.addWidget(button)
        bar.show()

    def copy_secret(self, text, label, notify=True):
        if not text:
            return
        cb = QApplication.clipboard()
        cb.setText(text)
        self._copied = text
        seconds = clipboard_seconds()
        if seconds:
            QTimer.singleShot(seconds * 1000, lambda: self._clear_clipboard(text))
        if notify:
            note = f"Clipboard clears in {duration_text(seconds).replace('1 minute', 'a minute')}." if seconds else ""
            InfoBar.success(f"{label} copied", note, orient=Qt.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP_RIGHT, duration=2000, parent=self)

    def _clear_clipboard(self, text=None):
        """Clears the clipboard if it still holds something we copied."""
        cb = QApplication.clipboard()
        if self._copied and cb.text() == self._copied and (text is None or text == self._copied):
            cb.clear()
            self._copied = None

    def _on_idle(self):
        if not self.locked and setting("lock_idle", True):
            self.lock()

    def lock(self):
        if self.locked and self.saver.db is None:
            self._show_unlock()
            return
        self.saver.flush(self._lock_now)  # save any pending edits first

    def _lock_now(self):
        self.locked = True
        self.saver.detach()
        self.vault.clear()
        self.health.set_db(None)
        self._clear_clipboard()
        self.setWindowTitle("Vault")
        self.switchTo(self.vault)
        if self.isMinimized():
            self.showNormal()
        self._show_unlock()

    def _show_unlock(self):
        dialog = UnlockDialog(self)
        if dialog.exec() and dialog.db:
            db = dialog.db
            self.vault.load(db)
            self.saver.attach(db)
            self.health.set_db(db)
            self.locked = False
            self.idle.timer.start()
            name = Path(dialog.path).name
            self.setWindowTitle(f"Vault — {name}" if db.writable else f"Vault — {name} (read-only)")
            if not db.writable:
                InfoBar.warning(
                    "Read-only", f"This database uses the older KDBX {db.version} format, which Vault can "
                    "only view. To edit it here, upgrade it to KDBX 4 in KeePassXC's database settings.",
                    orient=Qt.Vertical, isClosable=True, position=InfoBarPosition.TOP_RIGHT,
                    duration=-1, parent=self)
        else:
            self._closing = True
            QApplication.quit()

    def closeEvent(self, event):
        # Save pending edits before closing.
        if not self._closing and self.saver.pending:
            event.ignore()
            self.saver.flush(self._close_now)
            return
        self.save_geometry()
        super().closeEvent(event)

    def _close_now(self):
        self._closing = True
        self.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        # Own taskbar identity, so Windows shows Vault's icon rather than Python's (when run from source).
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Vault.PasswordManager")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(RESOURCE_DIR / "icons" / "vault_app.png")))
    apply_theme(theme_name())
    window = MainWindow()
    apply_theme(theme_name(), window)
    window.show()
    # Load pykeepass (crypto, Argon2, XML) in the background while the password is being typed.
    threading.Thread(target=lambda: __import__("pykeepass"), daemon=True).start()
    QTimer.singleShot(0, window.lock)
    sys.exit(app.exec())
