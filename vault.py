"""Vault: a simple KeePass client (PySide6 + PySide6-Fluent-Widgets + pykeepass).

Opens .kdbx files (any extension) such as one synced by Google Drive for Desktop, and
auto-saves edits safely (see store.py: backups, verified atomic writes, merging changes
made by other devices or apps).
Run:  python vault.py
"""
import hashlib
import hmac
import math
import os
import re
from collections import Counter
import sys

if __name__ == "__main__" and sys.argv[1:2] == ["--ask-path"]:  # Windows' file dialog for Vault (see ask_path),
    import pathpicker                                          # before the rest of the app is loaded
    sys.exit(pathpicker.main(sys.argv[2]))

import json
import subprocess
import tempfile
import threading
import time
import uuid as uuidlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import (
    Qt, QAbstractTableModel, QEvent, QEventLoop, QModelIndex, QObject, QRect, QSettings, QSize,
    QTimer, QUrl, Signal, QMimeData, QByteArray, QPoint, QPointF, QRectF,
)
from PySide6.QtGui import (
    QColor, QCursor, QDesktopServices, QFont, QFontDatabase, QFontInfo, QFontMetrics, QIcon, QImage, QInputMethodEvent,
    QKeySequence, QPainter, QPainterPath, QPalette, QPen, QPixmap, QShortcut, QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication, QAbstractButton, QLabel, QWidget, QHBoxLayout, QVBoxLayout, QTreeWidgetItem, QTreeWidgetItemIterator,
    QFileDialog, QHeaderView, QAbstractItemView, QSplitter, QSplitterHandle, QLineEdit, QTableWidgetItem,
    QStyledItemDelegate, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QGridLayout, QButtonGroup,
    QStyle, QStyleOptionViewItem, QToolTip, QStackedWidget, QFrame,
)
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon as FIF, setTheme, Theme,
    isDarkTheme, SearchLineEdit, SimpleCardWidget, TitleLabel, SubtitleLabel,
    BodyLabel, StrongBodyLabel, CaptionLabel, LineEdit, PasswordLineEdit, PlainTextEdit,
    TransparentToolButton, TransparentToggleToolButton, TransparentTogglePushButton, TransparentPushButton,
    PushButton, PrimaryPushButton, SwitchButton, CheckBox, Slider, ProgressBar,
    SegmentedWidget, InfoBar, InfoBarIcon, InfoBarPosition, MessageBox, MessageBoxBase, TreeWidget,
    TableView, RoundMenu, Action, qconfig, getFont, SmoothMode, ComboBox, setCustomStyleSheet,
    setThemeColor, themeColor, ProgressRing, ListWidget, CardWidget, TableWidget, ScrollArea, setFontFamilies,
    CheckableMenu, FluentIconBase, getIconColor, HyperlinkButton,
)
from qfluentwidgets.components.widgets.table_view import TableItemDelegate
from qfluentwidgets.components.widgets.tree_view import TreeItemDelegate

import favicon
import generator
import health
import quickunlock
import store
import systemlock
import totp
from store import Database, Op

if sys.platform == "win32":  # for smooth resizing and the taskbar pictures (MainWindow.nativeEvent)
    from ctypes import cast
    from ctypes.wintypes import MSG, RECT
    from qframelesswindow.windows.c_structures import LPNCCALCSIZE_PARAMS
    import taskbarpreview

VERSION = "1.4.3"  # releases are tagged v<VERSION> (see .github/workflows/build.yml)
IDLE_LOCK_CHOICES = {"Never": 0, "After 1 minute": 1, "After 2 minutes": 2, "After 5 minutes": 5,
                     "After 10 minutes": 10, "After 15 minutes": 15, "After 30 minutes": 30, "After 1 hour": 60,
                     "After 2 hours": 120, "After 5 hours": 300}


LIST_TEXT_SIZES = [80, 90, 100, 110, 125, 140, 160]  # % of normal, for the entry list, folders and notes


def list_text_size():
    try:
        size = int(float(settings.value("list_text_size", 100)))
    except (TypeError, ValueError):
        return 100
    return size if size in LIST_TEXT_SIZES else 100


def idle_lock_minutes():
    """Minutes without use before Vault locks (0 = never). Earlier versions had an on/off switch
    ("lock_idle") for a fixed 5 minutes: honour it until a time is chosen."""
    saved = settings.value("lock_idle_minutes")
    if saved is None:
        return 5 if setting("lock_idle", True) else 0
    try:
        minutes = int(saved)
    except (TypeError, ValueError):
        return 5
    return minutes if minutes in IDLE_LOCK_CHOICES.values() else 5
CLIPBOARD_CHOICES = {"Never": 0, "10 seconds": 10, "20 seconds": 20, "30 seconds": 30,
                     "1 minute": 60, "2 minutes": 120, "5 minutes": 300}
CARD_DENSITIES = {"Compact": (26, 18), "Comfortable": (38, 26), "Spacious": (46, 30)}  # card height, icon size
FOLDER_ROW_HEIGHTS = {"Compact": 22, "Comfortable": 33, "Spacious": 42}  # the folder tree's rows, per density
AVATAR_COLORS = ["#0f6cbd", "#c239b3", "#038387", "#ca5010", "#8764b8", "#498205", "#d13438", "#4f6bed"]

# name: (light/dark/auto base, accent colour, window background or None for the default Windows look)
THEMES = {
    "System": (Theme.AUTO, "#009faa", None),
    "Light": (Theme.LIGHT, "#009faa", None),
    "Dark": (Theme.DARK, "#29c5d1", None),
    "Ocean": (Theme.LIGHT, "#0f6cbd", "#e8f1fb"),
    "Rose": (Theme.LIGHT, "#c4314b", "#fbedf0"),
    "Sand": (Theme.LIGHT, "#b45f06", "#f5eee3"),
    "Mint": (Theme.LIGHT, "#0f7b6c", "#e9f5f1"),
    "Lavender": (Theme.LIGHT, "#6b4fbb", "#f1edfa"),
    "Slate": (Theme.LIGHT, "#3d5a80", "#eceff3"),
    "Peach": (Theme.LIGHT, "#c2410c", "#fcefe8"),
    "Midnight": (Theme.DARK, "#5b9bff", "#131a2b"),
    "Forest": (Theme.DARK, "#5fc77a", "#16231b"),
    "Grape": (Theme.DARK, "#b48cf2", "#1f1a2c"),
    "Graphite": (Theme.DARK, "#f0b400", "#1b1b1d"),
    "Arctic": (Theme.DARK, "#88c0d0", "#2b303b"),
    "Deep sea": (Theme.DARK, "#4fd1c5", "#0f1e22"),
    "Ember": (Theme.DARK, "#ff8a4c", "#211917"),
    "Rosewood": (Theme.DARK, "#f17ea0", "#241a1f"),
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
# VAULT_SETTINGS (a file path) overrides both; the tests use it so they never touch real settings.
if os.environ.get("VAULT_SETTINGS"):
    settings = QSettings(os.environ["VAULT_SETTINGS"], QSettings.IniFormat)
elif FROZEN and sys.platform == "win32":
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

    # Menus (right-click menus and dropdown lists) are revealed a few rows at a time by default;
    # exec()'s `ani` flag is ignored by the library, so force "no animation" for all of them.
    from qfluentwidgets.components.widgets.menu import MenuAnimationType, RoundMenu
    original_exec = RoundMenu.exec

    def instant_exec(self, pos, ani=True, aniType=MenuAnimationType.DROP_DOWN):
        if aniType in (MenuAnimationType.PULL_UP, MenuAnimationType.FADE_IN_PULL_UP):
            # Menus that open upwards (e.g. dropdowns near the bottom of the window): place them
            # where the upward animation would have ended. The no-animation placement drops down.
            self.adjustSize()
            top = QApplication.screenAt(pos).availableGeometry().top() if QApplication.screenAt(pos) else 0
            pos = QPoint(pos.x(), max(pos.y() - self.height() + 10, top + 4) + 4)
        return original_exec(self, pos, False, MenuAnimationType.NONE)

    RoundMenu.exec = instant_exec


make_dialogs_instant()


def cache_svg_icons():
    """The UI library re-reads, recolours (via XML) and re-parses every SVG icon on every paint, which
    made each redraw (e.g. every step of a window resize) noticeably slower. The results only depend
    on the inputs, so keep them: recoloured SVG text, and one parsed renderer per icon."""
    from functools import lru_cache
    from PySide6.QtCore import QRectF
    from PySide6.QtSvg import QSvgRenderer
    import qfluentwidgets.common as common
    import qfluentwidgets.common.icon as icon_module
    import qfluentwidgets.components.widgets.info_bar as info_bar
    write_svg = icon_module.writeSvg

    @lru_cache(maxsize=1024)
    def written(path, indexes, attributes):
        return write_svg(path, list(indexes) if indexes else None, **dict(attributes))

    def writeSvg(iconPath, indexes=None, **attributes):
        return written(iconPath, tuple(indexes) if indexes else None, tuple(sorted(attributes.items())))

    renderers = {}

    def drawSvgIcon(icon, painter, rect):
        key = icon.data() if isinstance(icon, QByteArray) else icon
        renderer = renderers.get(key)
        if renderer is None:
            if len(renderers) > 1024:
                renderers.clear()
            renderer = renderers[key] = QSvgRenderer(icon)
        renderer.render(painter, QRectF(rect))

    for module in (icon_module, common, info_bar):
        module.writeSvg, module.drawSvgIcon = writeSvg, drawSvgIcon


cache_svg_icons()

# Fonts: name exactly one font that the system has. Lists with fonts that aren't installed (the UI
# library's default "Segoe UI, Microsoft YaHei, PingFang SC", or "Cascadia Mono, Consolas, Menlo…")
# make Qt load the details of every font on the computer: about 40 MB each, kept for good.
MONO_FAMILY = "Menlo" if sys.platform == "darwin" else "Consolas"  # built into every Mac / Windows


def shortcut_text(text):
    """Shortcut text as this system writes it: Qt's Ctrl is the Command key on macOS ("Ctrl+N" → "⌘N")."""
    return text.replace("Ctrl + ", "⌘ ").replace("Ctrl+", "⌘") if sys.platform == "darwin" else text


def trim_memory(light=False):
    """Vault runs all day, mostly minimised or locked: then hand the memory it isn't using back to the
    system. Windows: empty the working set (pages come back as soon as they're needed). macOS:
    return the memory malloc keeps after it's been freed (e.g. the decrypted database after locking);
    memory still in use is left alone, and macOS compresses idle apps' memory by itself.
    light: only hand pages back (the later trims while minimised: nothing has been freed since the first,
    so a garbage collection, ~0.1 s through a large database, would gain nothing)."""
    if not light:
        import gc
        from PySide6.QtGui import QPixmapCache
        QPixmapCache.clear()  # rebuilt when next drawn; empty, its 30-second clean-up timer stops too
        gc.collect()
    if sys.platform == "win32":
        import ctypes
        kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
        psapi.EmptyWorkingSet(kernel32.GetCurrentProcess())
    elif sys.platform == "darwin":
        _mac_malloc_relief()


def _mac_malloc_relief():
    """macOS: hand back the memory malloc keeps after it's been freed (all zones, as much as they can)."""
    try:
        import ctypes
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        libc.malloc_zone_pressure_relief.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        libc.malloc_zone_pressure_relief.restype = ctypes.c_size_t
        libc.malloc_zone_pressure_relief(None, 0)
    except (OSError, AttributeError):
        pass


def release_after_work():
    """After opening, saving or reloading the database. Each briefly needs several copies of it (Argon2's
    64 MB or more; a save copies the whole XML tree, then opens the result again to check it), and
    macOS's malloc keeps freed memory, still counted as Vault's in Activity Monitor (a 2 MB database
    sat at ~300 MB after unlocking), until it's asked for it back. Leaves the pixmap cache (the window is
    showing) and, on Windows, the working set (pages would just come back on the next paint) alone."""
    import gc
    gc.collect()  # ~0.02 s: little garbage is cyclic, but some of it holds the file's bytes
    if sys.platform == "darwin":
        _mac_malloc_relief()


def use_system_ui_font():
    """Called once the QApplication exists (it's needed to ask for the system font)."""
    family = "Segoe UI" if sys.platform == "win32" else QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()
    setFontFamilies([family])


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


def file_size(size):
    for unit in ("bytes", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{size} {unit}" if unit == "bytes" else f"{size:.0f} {unit}" if size >= 10 else f"{size:.1f} {unit}"
        size /= 1024


def _native_dialog(parent, caption, start, name_filter, save, folder):
    if folder:
        return QFileDialog.getExistingDirectory(parent, caption, start)
    ask = QFileDialog.getSaveFileName if save else QFileDialog.getOpenFileName
    return ask(parent, caption, start, name_filter)[0]


def _visible_window_of(pid):
    """A visible top-level window of process `pid` (Windows), or None."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else None


def ask_path(parent, caption, start="", name_filter="", save=False, folder=False):
    """A file (or folder) chosen by the user, or "". The system's own dialog. On Windows it's shown by a helper
    process (pathpicker.py): there it loads every installed shell extension (Google Drive, Dropbox, OneDrive,
    antivirus…), which would otherwise stay in Vault until it quits. Vault waits (its window disabled, as for
    any dialog of its own) and stays responsive. If the helper can't run, the dialog is shown here instead.
    macOS: shown here (its open panel loads nothing into Vault)."""
    if sys.platform != "win32":
        return _native_dialog(parent, caption, start, name_filter, save, folder)
    import ctypes
    window = parent.window()
    owner = int(window.winId())
    fd, result = tempfile.mkstemp(prefix="vault-path-", suffix=".json")
    os.close(fd)
    os.remove(result)  # (just a unique name: the helper writes the file once the dialog closes)
    request = dict(caption=caption, start=start, filter=name_filter, owner=owner, result=result,
                   mode="folder" if folder else "save" if save else "open")
    me = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve())]
    user32 = ctypes.windll.user32
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= 0x80  # STARTF_FORCEOFFFEEDBACK: no "app starting" pointer while the helper loads
    try:
        user32.AllowSetForegroundWindow(-1)  # (ASFW_ANY) so the helper's dialog comes to the front
        helper = subprocess.Popen(me + ["--ask-path", json.dumps(request)], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startup)
    except OSError:
        return _native_dialog(parent, caption, start, name_filter, save, folder)
    user32.EnableWindow(owner, False)  # like a dialog of its own: Vault can't be used meanwhile
    loop = QEventLoop()  # until the result is written (or the helper ends without one)

    def check():
        if os.path.exists(result) or helper.poll() is not None:
            loop.quit()
        elif user32.GetForegroundWindow() == owner:  # Vault clicked: the dialog back in front, as a dialog of its own
            dialog = _visible_window_of(helper.pid)
            if dialog:
                user32.SetForegroundWindow(dialog)

    try:
        poll = QTimer(interval=50, timeout=check)
        poll.start()
        loop.exec()
        poll.stop()
    finally:
        user32.EnableWindow(owner, True)
        window.activateWindow()
    try:
        with open(result, encoding="utf-8") as f:
            return json.load(f).get("path", "")
    except (OSError, ValueError):  # the helper failed: show the dialog here after all
        return _native_dialog(parent, caption, start, name_filter, save, folder)
    finally:
        try:
            os.remove(result)
        except OSError:
            pass


def secret_mime_data(text):
    """Clipboard data for a password etc., marked so it stays out of clipboard history: Windows'
    Clipboard history (Win+V) and cloud clipboard sync, macOS and Linux clipboard managers (as KeePassXC does)."""
    data = QMimeData()
    data.setText(text)
    if sys.platform == "win32":
        zero = bytes(4)  # DWORD 0
        for name in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory",
                     "CanUploadToCloudClipboard"):
            data.setData(f'application/x-qt-windows-mime;value="{name}"', zero)
    elif sys.platform == "darwin":
        data.setData("application/x-nspasteboard-concealed-type", text.encode())
    else:
        data.setData("x-kde-passwordManagerHint", b"secret")
    return data


class AppIcon(FluentIconBase):
    """Vault's own icons (icons/<name>_black.svg and _white.svg) for ones the UI library lacks: "lock" (a
    padlock; its fingerprint looked like "unlock with Touch ID") and "attach" (a paperclip)."""

    def __init__(self, name):
        self.name = name

    def path(self, theme=Theme.AUTO):
        return str(RESOURCE_DIR / "icons" / f"{self.name}_{getIconColor(theme)}.svg")


# ---------------------------------------------------------------- database

FAVOURITES = "*favourites"  # the sidebar's Favourites row (real folder ids are hex UUIDs)
NOTES = "*notes"  # the sidebar's Notes row: the secure notes, wherever they're filed
FOLDERS_HEADING = "*heading"  # the sidebar's "Folders" heading row
VIEWS = (FAVOURITES, NOTES)  # sidebar rows that list entries but aren't folders


def in_folder(entry, folder_id):
    """True if the entry is in the folder or any of its subfolders (None is the root: everything
    outside the Recycle Bin; FAVOURITES: the starred entries; NOTES: the secure notes)."""
    if folder_id is None:
        return not entry["in_bin"]
    if folder_id == FAVOURITES:
        return entry["favourite"] and not entry["in_bin"]
    if folder_id == NOTES:
        return entry["note"] and not entry["in_bin"]
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

    MAX_PIXELS = 72  # the largest tile's icon (56 points x 0.6) on a 2x (Retina) screen, with a little to spare

    def __init__(self, db):
        self.db = db
        self.cache = {}

    def get(self, entry):
        return self.own(entry) or avatar_icon(entry["title"])

    def own(self, entry):
        """The entry's own icon (the site's, or a KeePass icon chosen for it), or None."""
        icon_id, custom = entry["icon"]
        key = custom or icon_id
        if key not in self.cache:
            self.cache[key] = self._custom(custom) or self._standard(icon_id)
        return self.cache[key]

    def _custom(self, uuid):
        data = self.db.custom_icons.get(uuid) if uuid else None
        if not data:
            return None
        pm = QPixmap()
        if not pm.loadFromData(data):
            return None
        # Icons from KeePassXC or other apps can be 128 px or more: 64 KB+ each once decoded, kept for
        # every entry (a 1.9 MB database of them took ~70 MB). None is ever drawn bigger than ~34 points.
        if max(pm.width(), pm.height()) > self.MAX_PIXELS:
            pm = pm.scaled(self.MAX_PIXELS, self.MAX_PIXELS, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return QIcon(pm)

    def folder(self, icon):
        """A folder's own icon from the database, or None for the plain folder icons (48 folder,
        49 open folder), which are drawn with the app's theme-coloured folder instead."""
        icon_id, custom = icon
        key = ("folder", custom or icon_id)
        if key not in self.cache:
            self.cache[key] = self._custom(custom) or (None if icon_id in (48, 49) else self._standard(icon_id, True))
        return self.cache[key]

    @staticmethod
    def _standard(icon_id, allow_key=False):
        if icon_id == 0 and not allow_key:  # the default key icon: for entries the letter avatar is more useful
            return None
        match = next(STANDARD_ICON_DIR.glob(f"C{icon_id:02d}_*.svg"), None)
        return QIcon(str(match)) if match else None


TILE_COLORS = (QColor("#eceff1"), QColor("#2e3338"))  # behind a site's own icon (light, dark)


def draw_entry_tile(painter, rect, entry, icons):
    """An entry's icon as a rounded tile: the site's own icon on a soft grey tile, or else the
    title's first letter on a colour (the same colour every time for the same title)."""
    own = icons.own(entry) if icons else None
    radius = rect.width() / 4.2
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setPen(Qt.NoPen)
    if own:
        painter.setBrush(TILE_COLORS[isDarkTheme()])
        painter.drawRoundedRect(rect, radius, radius)
        s = round(rect.width() * 0.6)
        own.paint(painter, QRect(rect.x() + (rect.width() - s) // 2, rect.y() + (rect.height() - s) // 2, s, s))
    else:
        title = entry["title"]
        painter.setBrush(QColor(AVATAR_COLORS[sum(map(ord, title)) % len(AVATAR_COLORS)]))
        painter.drawRoundedRect(rect, radius, radius)
        font = getFont(13, QFont.DemiBold)
        font.setPixelSize(max(8, round(rect.height() * 0.44)))
        painter.setFont(font)
        painter.setPen(Qt.white)
        painter.drawText(rect, Qt.AlignCenter, title[:1].upper())
    painter.restore()


def star_path(rect):
    """A five-pointed star filling `rect` (for favourites)."""
    cx, cy = rect.center().x(), rect.center().y() + rect.height() * 0.04
    outer, inner = rect.width() / 2, rect.width() / 2 * 0.45
    path = QPainterPath()
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        a = math.radians(-90 + i * 36)
        point = QPointF(cx + r * math.cos(a), cy + r * math.sin(a))
        path.moveTo(point) if i == 0 else path.lineTo(point)
    path.closeSubpath()
    return path


STAR_COLOR = QColor("#d29200")


PASSWORD_COLORS = {  # (light theme, dark theme); lowercase uses the normal text colour
    # Three clearly different hues, strong enough to tell apart at a glance (drawn semi-bold too).
    "upper": ("#0050c8", "#4aa3ff"),   # blue
    "digit": ("#d13800", "#ff8a3d"),   # orange-red
    "symbol": ("#008a2e", "#3ddc6e"),  # green
}
PASSWORD_PLAIN = ("#555555", "#bdbdbd")  # lowercase: grey, so the coloured characters stand out


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
    """Draws each entry as a card: its icon and title, with copy buttons, a star (favourites) and a
    paperclip (attached files) on the right. With the details below the list (`columns`), the card
    runs across the columns (username, password, website, folder, dates) and the buttons have the
    last one to themselves."""

    def __init__(self, view, model):
        super().__init__(view)
        self.view = view
        self.model = model
        self.colorize = setting("color_passwords", True)  # for the passwords shown in the list and details
        self.stripes = setting("list_stripes", True)  # Settings → Striped list
        self.font = getFont(13)  # the same as the folders' (and set_list_text_size scales both)
        self.small = getFont(13)
        self.mono = QFont(MONO_FAMILY)  # passwords, in the columns
        self.mono.setStyleHint(QFont.TypeWriter)
        self.mono.setPixelSize(13)
        self.italic = QFont(self.font)  # old copies in a Backup folder
        self.italic.setItalic(True)
        self.tile = 34
        self.columns = False  # the details are below the list: the card spans the columns shown
        self._today, self._today_until = "", 0.0  # see short_date
        self._update_text_color()
        qconfig.themeChanged.connect(self._update_text_color)

    def _update_text_color(self):
        dark = isDarkTheme()
        self.text_color = QColor(Qt.white if dark else Qt.black)
        self.muted = QColor("#a3a9af" if dark else "#5c656d")
        self.char_colors = {kind: QColor(PASSWORD_COLORS[kind][dark]) if kind in PASSWORD_COLORS
                            else QColor(PASSWORD_PLAIN[dark]) for kind in ("upper", "lower", "digit", "symbol")}

    def row_rect(self, cell):
        """The whole card, from the rect of one of its cells."""
        if not self.columns:
            return cell
        header = self.view.horizontalHeader()
        left = header.sectionViewportPosition(EntryModel.TITLE)
        right = header.sectionViewportPosition(EntryModel.ACTIONS) + header.sectionSize(EntryModel.ACTIONS)
        return QRect(left, cell.y(), right - left, cell.height())

    def short_date(self, stamp):
        """A date for the columns: "Oct 14, 2026", or just the time ("14:32") for today. `stamp` is
        store's "%b %d, %Y %H:%M"."""
        if not stamp:
            return ""
        now = time.time()
        if now >= self._today_until:  # worked out once a day, not for every cell painted
            today = datetime.now()
            self._today = today.strftime("%b %d, %Y")
            midnight = today.replace(hour=0, minute=0, second=0, microsecond=0)
            self._today_until = midnight.timestamp() + 86400
        day = stamp[:-6]
        return stamp[-5:] if day == self._today else day

    ATTACH = AppIcon("attach")
    # Buttons shown on the card under the mouse: (field, icon, tooltip)
    ACTIONS = [("username", AppIcon("person"), "Copy username (Ctrl+B)"),
               ("password", AppIcon("key"), "Copy password (Ctrl+C)"),
               ("totp", icon("STOP_WATCH", "HISTORY"), "Copy 2FA code (Ctrl+T)")]
    BUTTON_WIDTH = 48  # each one is the full height of the card: easy to hit
    COLUMN_BUTTON_WIDTH = 38  # in the columns, where they have a column of their own: narrower
    STAR_WIDTH = 36  # the star, last on every card (so it lines up down the list), stars or unstars it

    hover_pos = None  # the mouse, over the list (for the button under it)
    done = None  # (entry uuid, field) just copied: its button (or cell) shows a tick for a moment

    def button_width(self):
        return self.COLUMN_BUTTON_WIDTH if self.columns else self.BUTTON_WIDTH

    def actions_width(self):
        """The buttons' column: room for all three copy buttons and the star."""
        return 8 + 3 * (self.button_width() + 2) + self.STAR_WIDTH + 8

    def actions(self, e, rect):
        """[(field, icon, tooltip, QRect)] of the hover buttons for the card in `rect` (see row_rect),
        right-aligned: the copy buttons for the fields it has, then the star ("favourite", drawn rather
        than an icon)."""
        shown = [a for a in self.ACTIONS if (e["totp"] if a[0] == "totp" else e[a[0]])]
        if e["favourite"] or self.model.draggable:  # (a read-only database: only a favourite's star)
            shown.append(("favourite", None, "Remove from Favourites" if e["favourite"] else "Add to Favourites"))
        r = rect.adjusted(6, 2, -8, -2)
        widths = [self.STAR_WIDTH if field == "favourite" else self.button_width() for field, _i, _t in shown]
        x = r.right() + 1 - sum(w + 2 for w in widths) + 2
        out = []
        for (field, ico, tip), w in zip(shown, widths):
            out.append((field, ico, tip, QRect(x, r.y(), w, r.height())))
            x += w + 2
        return out

    def title_style(self, e):
        """The title's (font, colour): grey when expired, and grey and italic for old copies in a Backup folder."""
        backup = self.model.is_dimmed_backup(e)
        return (self.italic if backup else self.font), (EXPIRED_COLOR if e["expired"] or backup else self.text_color)

    def paint(self, painter, option, index):
        e = self.model.entries[index.row()]
        col, cell = index.column(), option.rect
        row = self.row_rect(cell)
        r = row.adjusted(6, 2, -8, -2)
        dark = isDarkTheme()
        painter.save()
        if self.columns:  # each cell draws its own part of the card
            painter.setClipRect(cell)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        selected = index.row() in self.selectedRows
        if selected:  # easy to find again (e.g. after copying from it and bringing Vault back)
            fill = QColor(themeColor())
            fill.setAlpha(80 if dark else 58)
        elif index.row() in (self.hoverRow, self.pressedRow):
            fill = QColor(255, 255, 255, 14) if dark else QColor(0, 0, 0, 11)
        elif self.stripes and index.row() % 2:  # zebra stripes: every other row faintly shaded
            fill = QColor(255, 255, 255, 6) if dark else QColor(0, 0, 0, 7)
        else:
            fill = None
        if fill is not None:
            painter.setBrush(fill)
            painter.drawRoundedRect(r, 8, 8)
        if selected:  # a thin outline, and the accent bar the UI library's lists show by the selected row
            edge = QColor(themeColor())
            edge.setAlpha(170 if dark else 150)
            painter.setPen(QPen(edge, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(themeColor()))
            painter.drawRoundedRect(QRectF(r.x() + 1, r.y() + r.height() * 0.2, 4, r.height() * 0.6), 2, 2)

        hovered = index.row() == self.hoverRow
        right = (cell.right() if self.columns else r.right()) - 10
        if col == (EntryModel.ACTIONS if self.columns else EntryModel.TITLE):
            right = min(right, self._paint_buttons(painter, e, row, hovered, dark))
        if col == EntryModel.TITLE:
            self._paint_title(painter, e, r, right)
        elif col != EntryModel.ACTIONS:
            self._paint_value(painter, e, col, cell, hovered, dark)
        painter.restore()

    def _paint_buttons(self, painter, e, row, hovered, dark):
        """The copy buttons and star: always there, very pale, and full strength on the card under the
        mouse (a favourite's star is always gold). Returns how far right the title can go."""
        c = 255 if dark else 0
        right = row.right()
        for field, ico, _tip, rect in self.actions(e, row):
            if hovered and self.hover_pos is not None and rect.contains(self.hover_pos):
                painter.setBrush(QColor(c, c, c, 22 if dark else 16))
                painter.drawRoundedRect(rect, 6, 6)
            s = 16
            spot = QRect(rect.x() + (rect.width() - s) // 2, rect.y() + (rect.height() - s) // 2, s, s)
            done = self.done == (e["uuid"], field)
            if field == "favourite":
                star = star_path(QRectF(spot).adjusted(1, 1, -1, -1))
                if e["favourite"]:
                    painter.setBrush(STAR_COLOR)
                    painter.drawPath(star)
                else:  # quieter than the copy buttons: faint, and only full strength under the mouse
                    on_star = hovered and self.hover_pos is not None and rect.contains(self.hover_pos)
                    painter.setOpacity(1 if on_star else 0.45 if hovered else 0.18)
                    painter.setPen(QPen(self.muted, 1.1))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawPath(star)
                    painter.setPen(Qt.NoPen)
            else:
                painter.setOpacity(1 if hovered or done else 0.28)
                (FIF.ACCEPT if done else ico).render(painter, spot)
            painter.setOpacity(1)
            right = min(right, rect.x() - 6)
        return right

    def _paint_title(self, painter, e, r, right):
        """The icon, the title, and a paperclip at its right if the entry has attached files."""
        tile = QRect(r.x() + 12, r.center().y() - self.tile // 2 + 1, self.tile, self.tile)
        draw_entry_tile(painter, tile, e, self.model.icons)
        x = tile.right() + 13
        if e["attachments"]:
            s = 14
            painter.setOpacity(0.6)
            self.ATTACH.render(painter, QRect(right - s, r.center().y() - s // 2, s, s))
            painter.setOpacity(1)
            right -= s + 8

        title_font, title_color = self.title_style(e)
        fm1 = QFontMetrics(title_font)
        width = max(0, right - x)
        y = r.y() + (r.height() - fm1.height()) // 2
        painter.setFont(title_font)
        painter.setPen(title_color)
        painter.drawText(QRect(x, y, width, fm1.height()), Qt.AlignLeft | Qt.AlignVCenter,
                         fm1.elidedText(e["title"], Qt.ElideRight, width))

    def _paint_value(self, painter, e, col, cell, hovered, dark):
        """One of the columns: the username and password (which copy with a double-click: lit up under
        the mouse), the website, folder and dates (quieter)."""
        M = EntryModel
        if col == M.WEBSITE:
            value = e.get("_site")
            if value is None:  # without "https://" and "www.": the part that tells sites apart
                value = e["_site"] = re.sub(r"^[a-z][a-z0-9+.-]*://(www\.)?", "", e["url"], flags=re.I).rstrip("/")
        elif col in (M.MODIFIED, M.CREATED):
            value = self.short_date(e["modified" if col == M.MODIFIED else "created"])
        else:
            value = {M.USERNAME: e["username"], M.PASSWORD: e["password"], M.FOLDER: e["folder"]}.get(col, "")
        if not value:
            return
        box = cell.adjusted(10, 0, -8, 0)
        field = "username" if col == M.USERNAME else "password" if col == M.PASSWORD else None
        if field:
            if hovered and self.hover_pos is not None and cell.contains(self.hover_pos):
                c = 255 if dark else 0
                painter.setBrush(QColor(c, c, c, 22 if dark else 16))
                painter.drawRoundedRect(cell.adjusted(2, 6, -2, -6), 6, 6)
            if self.done == (e["uuid"], field):  # just copied (double-clicked): a tick for a moment
                s = 14
                FIF.ACCEPT.render(painter, QRect(box.right() - s, cell.center().y() - s // 2, s, s))
                box.setRight(box.right() - s - 6)
        dim = e["expired"] or self.model.is_dimmed_backup(e)
        color = EXPIRED_COLOR if dim else self.text_color if field else self.muted
        if col == M.PASSWORD:
            painter.setFont(self.mono)
            fm = QFontMetrics(self.mono)
            if not self.model.is_revealed(e):
                value = MASK
            text = fm.elidedText(value, Qt.ElideRight, box.width())
            if value is MASK or dim or not self.colorize:
                painter.setPen(color)
                painter.drawText(box, Qt.AlignLeft | Qt.AlignVCenter, text)
                return
            x = box.x()  # colour-coded, like the details (monospaced: every character as wide)
            for ch in text:
                w = fm.horizontalAdvance(ch)
                painter.setPen(self.char_colors[char_kind(ch)])
                painter.drawText(QRect(x, box.y(), w + 1, box.height()), Qt.AlignLeft | Qt.AlignVCenter, ch)
                x += w
            return
        painter.setFont(self.small)
        painter.setPen(color)
        painter.drawText(box, Qt.AlignLeft | Qt.AlignVCenter,
                         QFontMetrics(self.small).elidedText(value, Qt.ElideRight, box.width()))


ENTRY_MIME = "application/x-vault-entries"
FOLDER_MIME = "application/x-vault-folder"


class FolderRowDelegate(TreeItemDelegate):
    """The sidebar's rows (All entries, Favourites, the folders): the UI library's drawing, with each
    row's entry count small and grey on the right, the "Folders" heading (with a + for a new folder),
    and the row height set by the row density."""

    def __init__(self, tree):
        super().__init__(tree)
        self.row_height = None
        self.inactive = False  # Password health or Settings showing: no row looks selected

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)  # the name and icon...
        count = self.split(index.data(Qt.DisplayRole))[1]
        if count:  # ...and the count beside it
            size.setWidth(size.width() + QFontMetrics(self._count_font(index, option)).horizontalAdvance(count) + 26)
        if self.row_height:
            size.setHeight(self.row_height)
        return size

    @staticmethod
    def split(text):
        """("Work", "12") from the row's text "Work  (12)"."""
        name, sep, count = (text or "").rpartition("  (")
        return (name, count.rstrip(")")) if sep else (text or "", "")

    def _count_font(self, index, option):
        font = QFont(index.data(Qt.FontRole) or option.font)
        font.setPixelSize(max(9, round(QFontInfo(font).pixelSize() * 0.86)))
        return font

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        name, count = self.split(option.text)
        option.text = name
        if option.rect.width() > 0:  # drawing (not measuring): shortened (…) before the count, not under it
            room = (option.rect.width() - option.decorationSize.width() - 20
                    - (QFontMetrics(self._count_font(index, option)).horizontalAdvance(count) + 14 if count else 0))
            option.text = QFontMetrics(option.font).elidedText(name, Qt.ElideRight, max(20, room))

    def paint(self, painter, option, index):
        muted = QColor("#a3a9af" if isDarkTheme() else "#5c656d")
        if index.data(Qt.UserRole) == FOLDERS_HEADING:
            painter.save()
            font = self._count_font(index, option)
            font.setWeight(QFont.DemiBold)
            painter.setFont(font)
            painter.setPen(muted)
            rect = option.rect.adjusted(4, 0, -12, -3)
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignBottom, "Folders")
            if index.data(Qt.UserRole + 4):  # editable: + for a new folder
                s = 14
                FIF.ADD.render(painter, QRect(rect.right() - s, rect.bottom() - s, s, s))
            painter.restore()
            return
        if self.inactive:
            option = QStyleOptionViewItem(option)
            option.state &= ~QStyle.State_Selected
        super().paint(painter, option, index)
        count = self.split(index.data(Qt.DisplayRole))[1]
        if count:
            painter.save()
            painter.setFont(self._count_font(index, option))
            painter.setPen(muted)
            painter.drawText(option.rect.adjusted(0, 0, -12, 0), Qt.AlignRight | Qt.AlignVCenter, count)
            painter.restore()


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
        if target in (FOLDERS_HEADING, NOTES):  # (a login dropped on Notes doesn't become a note)
            return None
        if target == FAVOURITES:  # entries dropped there are starred
            return item if md.hasFormat(ENTRY_MIME) else None
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
    # The last column holds the copy buttons and star when the details are below the list (the
    # columns show then); beside it, only the first column shows and the card draws the rest.
    COLUMNS = ["Name", "Username", "Password", "Website", "Folder", "Modified", "Created", ""]
    TITLE, USERNAME, PASSWORD, WEBSITE, FOLDER, MODIFIED, CREATED, ACTIONS = range(8)
    # Sorting is done here in one Python sort; a QSortFilterProxyModel would call data()
    # tens of thousands of times per sort, which made searching and sorting laggy.
    SORT_KEYS = {
        TITLE: lambda e: e["title"].lower(),
        USERNAME: lambda e: e["username"].lower(),
        PASSWORD: lambda e: 0,
        WEBSITE: lambda e: e["url"].lower(),
        FOLDER: lambda e: e["folder"].lower(),
        MODIFIED: lambda e: e["modified_key"],
        CREATED: lambda e: e["created_key"],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.show_passwords = False
        self.revealed = set()  # id()s of entries whose password is shown individually
        self.draggable = False  # rows can be dragged onto folders (editable databases only)
        self.icons = None  # EntryIcons for the open database
        self.sort_column, self.sort_order = self.TITLE, Qt.AscendingOrder
        # Old copies in a Backup folder are greyed and italic, except while browsing that folder itself
        self.dim_backups = True

    def is_dimmed_backup(self, e):
        return self.dim_backups and e["backup"]

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
                cells = e["_cells"] = (e["title"], e["username"], "", e["url"], e["folder"], e["modified"],
                                       e["created"], "")
            return cells[col]
        if role == R_USER:
            return e
        if role == R_DECORATION:
            if col != 0:
                return None
            return self.icons.get(e) if self.icons else avatar_icon(e["title"])
        if role == R_FOREGROUND:
            return EXPIRED_COLOR if e["expired"] or self.is_dimmed_backup(e) else None
        if role == R_TOOLTIP:
            if col == 0 and e["expired"]:
                return "This entry has expired"
            if col == 0 and self.is_dimmed_backup(e):
                return f"An old copy, kept in the Backup folder ({e['folder']})"
            if col in (1, 2) and e["username" if col == 1 else "password"]:
                return "Double-click to copy and minimise" if setting("minimise_on_copy", True) else "Double-click to copy"
            if col == 3 and e["url"]:
                return f"{e['url']}\nDouble-click to open"
            if col == 4:
                return e["folder"]
            if col in (5, 6):
                return e["modified" if col == 5 else "created"] or None
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
        self.set_layout(orientation, key, default_sizes)
        self.splitterMoved.connect(self.save_position)

    def save_position(self, *_):
        settings.setValue(self.key, self.saveState())

    def set_layout(self, orientation, key, default_sizes):
        """Side by side or stacked, with the position saved under `key` (one per orientation: a saved
        position includes it)."""
        self.key = key
        self.setOrientation(orientation)
        grow = self.count() - 1 if orientation == Qt.Horizontal else 0
        for i in range(self.count()):
            self.setStretchFactor(i, 1 if i == grow else 0)
        self._restore(default_sizes)
        # Again once the switch has been laid out: sizes set while the orientation and the panes'
        # contents were still changing were lost
        QTimer.singleShot(0, self, lambda: self.key == key and self._restore(default_sizes))

    def _restore(self, default_sizes):
        self.setSizes(default_sizes)
        state = settings.value(self.key)
        if state is not None:
            self.restoreState(state)

    def createHandle(self):
        return GripHandle(self.orientation(), self)


def star_icon(filled, size=16):
    """A star: filled (a favourite) or an outline (not)."""
    scale = 3
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = star_path(QRectF(2, 2, size * scale - 4, size * scale - 4))
    if filled:
        p.setPen(Qt.NoPen)
        p.setBrush(STAR_COLOR)
    else:
        p.setPen(QPen(QColor("#c5cbd0" if isDarkTheme() else "#5c656d"), 1.4 * scale))
    p.drawPath(path)
    p.end()
    pm.setDevicePixelRatio(scale)
    return QIcon(pm)


def copy_button(tip, on_click):
    """A copy button that turns into a tick for a moment once it has copied."""
    button = TransparentToolButton(FIF.COPY)
    button.setToolTip(shortcut_text(tip))
    button.is_copy = True  # a FieldRow with one copies when clicked anywhere

    def clicked():
        on_click()
        button.setIcon(FIF.ACCEPT)
        QTimer.singleShot(1500, lambda: shiboken_alive(button) and button.setIcon(FIF.COPY))
    button.clicked.connect(clicked)
    return button


def shiboken_alive(widget):
    """False once Qt has deleted the widget (e.g. a details row rebuilt for another entry)."""
    import shiboken6
    return shiboken6.isValid(widget)


# Health problems shown as a small label by the password: (text, style), most serious first
STRENGTH_CHIPS = [("weak", "Weak", "bad"), ("empty", "", None), ("reused", "Reused", "warn"),
                  ("expired", "Expired", "bad"), ("old", "Old", "info")]
CHIP_COLORS = {  # style: ((light background, text), (dark background, text))
    "good": (("#dcf2e2", "#17612d"), ("#173a22", "#8fd9a4")),
    "warn": (("#fbe8d2", "#7f4306"), ("#3d2a12", "#f2b36b")),
    "bad": (("#fde2e1", "#a4262c"), ("#44191b", "#ff9a9e")),
    "info": (("#e1ecf8", "#1d4f8a"), ("#1b2a3d", "#9cc3f0")),
}


def password_html(password, colorize, dark=None):
    """A revealed password as rich text: monospaced, each character coloured by its kind (for a dark
    or light background; by default the theme's)."""
    dark = isDarkTheme() if dark is None else dark
    plain = PASSWORD_PLAIN[dark] if colorize else ("#ffffff" if dark else "#000000")
    out = []
    for ch in password:
        kind = char_kind(ch) if colorize else "lower"
        text = {"<": "&lt;", ">": "&gt;", "&": "&amp;", " ": "&nbsp;"}.get(ch, ch)
        if kind in PASSWORD_COLORS:
            out.append(f'<span style="color:{PASSWORD_COLORS[kind][dark]}; font-weight:600">{text}</span>')
        else:
            out.append(f'<span style="color:{plain}">{text}</span>')
    return "".join(out)


class FieldRow(QWidget):
    """One line of the details pane: a small label over the value, with its buttons on the right.
    A hairline separates it from the row above."""

    def __init__(self, label, value=None, parent=None):
        super().__init__(parent)
        self.first = False
        self.line = QHBoxLayout(self)
        self.line.setContentsMargins(18, 9, 10, 9)
        self.line.setSpacing(2)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.label = caption(label)
        texts.addWidget(self.label)
        self.value = value if value is not None else BodyLabel("")
        if isinstance(self.value, QLabel):
            self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.value.setMinimumWidth(1)  # long values are cut off rather than widening the pane
            self.value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        texts.addWidget(self.value)
        self.line.addLayout(texts, 1)

    copy = None  # its copy button: clicking anywhere on the row copies

    def add_button(self, button):
        button.setFixedSize(34, 34)
        button.setIconSize(QSize(16, 16))
        self.line.addWidget(button, 0, Qt.AlignVCenter)
        if getattr(button, "is_copy", False):
            self.copy = button
            self.setAttribute(Qt.WA_Hover)
            if isinstance(self.value, QLabel) and not self.value.textInteractionFlags() & Qt.LinksAccessibleByMouse:
                self.value.setTextInteractionFlags(Qt.NoTextInteraction)  # its clicks go to the row
            self.setToolTip("Click to copy")
        return button

    def event(self, e):
        if self.copy is not None and e.type() in (QEvent.HoverEnter, QEvent.HoverLeave):
            self.update()
        return super().event(e)

    def mouseReleaseEvent(self, e):
        if self.copy is not None and e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.copy.click()
        else:
            super().mouseReleaseEvent(e)

    def mousePressEvent(self, e):
        if self.copy is None:
            super().mousePressEvent(e)  # (accepted, so the release comes here)

    def paintEvent(self, _event):
        p = QPainter(self)
        dark = isDarkTheme()
        if self.copy is not None and self.underMouse():  # it's all one button
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 10) if dark else QColor(0, 0, 0, 8))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(4, 2, -4, -2), 6, 6)
        if not self.first:
            p.setPen(QColor(255, 255, 255, 22) if dark else QColor(0, 0, 0, 20))
            p.drawLine(18, 0, self.width() - 18, 0)


class NotesPanel(QWidget):
    """The selected entry, beside the list: its icon, title and folder; a row for each field
    (username, password, website, 2FA code, extra fields, attachments) with buttons to copy, show
    or open it; then its notes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(340)
        self.entry = None
        self.revealed = False
        root = self.outer = QVBoxLayout(self)
        root.setContentsMargins(30, 20, 26, 14)
        root.setSpacing(0)
        vault = lambda: self.window().vault
        self.below = False  # under the list: a strip with tabs (see set_below)

        self.head_box = QWidget()  # (not shown below the list: the list shows which entry it is)
        head = self.head = QHBoxLayout(self.head_box)
        head.setContentsMargins(0, 0, 0, 18)
        head.setSpacing(16)
        self.icon = QLabel()
        self.icon.setFixedSize(56, 56)
        head.addWidget(self.icon, 0, Qt.AlignVCenter)
        names = QVBoxLayout()
        names.setSpacing(2)
        self.title = TitleLabel("")
        self.title.setMinimumWidth(1)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        names.addWidget(self.title)
        sub = QHBoxLayout()
        sub.setSpacing(0)
        self.path = caption("")
        self.modified = caption("")
        for label in (self.path, self.modified):
            label.setMinimumWidth(1)
        sub.addWidget(self.path)
        sub.addWidget(self.modified, 1)
        names.addLayout(sub)
        head.addLayout(names, 1)
        self.fav_btn = TransparentToolButton(star_icon(False))
        self.fav_btn.setFixedSize(36, 36)
        self.fav_btn.clicked.connect(lambda: vault().toggle_favourite())
        head.addWidget(self.fav_btn, 0, Qt.AlignVCenter)
        self.history_btn = TransparentToolButton(icon("HISTORY"))
        self.history_btn.setFixedSize(36, 36)
        self.history_btn.setToolTip(shortcut_text("History: earlier versions of this entry (Ctrl+H)"))
        self.history_btn.clicked.connect(lambda: vault().show_history())
        head.addWidget(self.history_btn, 0, Qt.AlignVCenter)
        self.edit_btn = PushButton(FIF.EDIT, "Edit")
        self.edit_btn.setToolTip(shortcut_text("Edit (Enter)"))
        self.edit_btn.clicked.connect(lambda: vault().edit_entry())
        head.addWidget(self.edit_btn, 0, Qt.AlignVCenter)
        root.addWidget(self.head_box)

        # The fields, on a card
        self.card = SimpleCardWidget()
        fields = QVBoxLayout(self.card)
        fields.setContentsMargins(0, 3, 0, 3)
        fields.setSpacing(0)
        self.user_row = FieldRow("Username")
        self.user_row.add_button(copy_button("Copy username (Ctrl+B)", lambda: vault().copy_username()))
        self.pw_value = QLabel()
        self.pw_value.setTextFormat(Qt.RichText)
        self.pw_row = FieldRow("Password", self.pw_value)
        self.chip = QLabel()
        self.pw_row.line.addWidget(self.chip, 0, Qt.AlignVCenter)
        self.pw_row.line.addSpacing(6)
        self.eye = self.pw_row.add_button(TransparentToolButton(FIF.VIEW))
        self.eye.clicked.connect(lambda: vault().toggle_password())  # (the list's column follows it)
        self.pw_row.add_button(copy_button("Copy password (Ctrl+C)", lambda: vault().copy_password()))
        self.url_value = BodyLabel("")
        self.url_value.linkActivated.connect(lambda _link: vault().open_url())
        self.url_row = FieldRow("Website", self.url_value)
        self.url_value.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        opener = self.url_row.add_button(TransparentToolButton(icon("GLOBE", "LINK")))
        opener.setToolTip(shortcut_text("Open website (Ctrl+U)"))
        opener.clicked.connect(lambda: vault().open_url())
        self.url_row.add_button(copy_button("Copy website", lambda: vault().copy_url()))

        # Live 2FA code, shown only for entries that have one
        code = QWidget()
        t = QHBoxLayout(code)
        t.setContentsMargins(0, 0, 0, 0)
        t.setSpacing(10)
        self.totp_code = StrongBodyLabel("")
        qss = f"StrongBodyLabel {{ {mono_font_qss(20)} letter-spacing: 2px; }}"
        setCustomStyleSheet(self.totp_code, qss, qss)
        t.addWidget(self.totp_code)
        self.totp_ring = ProgressRing()
        self.totp_ring.setFixedSize(20, 20)
        self.totp_ring.setStrokeWidth(3)
        self.totp_ring.setTextVisible(False)
        self.totp_ring.setUseAni(False)  # it moves one step a second; animating each step cost ~4% CPU
        t.addWidget(self.totp_ring)
        self.totp_left = caption("")
        # Fixed size: changing its text every second then doesn't re-lay out the whole window.
        self.totp_left.setFixedSize(self.totp_left.fontMetrics().horizontalAdvance("88s") + 6,
                                    self.totp_left.fontMetrics().height() + 4)
        t.addWidget(self.totp_left)
        t.addStretch(1)
        self.totp_box = FieldRow("2FA code", code)
        self.totp_box.add_button(copy_button("Copy 2FA code (Ctrl+T)", lambda: vault().copy_totp()))
        self.totp_timer = QTimer(self, interval=1000, timeout=self._tick)

        # Extra fields (e.g. "PIN") and attached files, shown only for entries that have them
        self.extra_box = QWidget()
        self.extra = QVBoxLayout(self.extra_box)
        self.extra.setContentsMargins(0, 0, 0, 0)
        self.extra.setSpacing(0)
        # Its folder, changed by choosing another one here (a move: undoable)
        self.folder_combo = ComboBox()
        self.folder_combo.setMinimumWidth(1)
        self.folder_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.folder_combo.currentIndexChanged.connect(self._folder_chosen)
        self._loading_folder = False
        self.folder_row = FieldRow("Folder", self.folder_combo)
        self.rows = [self.user_row, self.pw_row, self.url_row, self.totp_box, self.folder_row]
        for row in self.rows[:-1] + [self.extra_box, self.folder_row]:
            fields.addWidget(row)
        root.addWidget(self.card)

        # Below the fields: the notes, then a divider (drag it; it's remembered), then the activity
        details = root
        notes_box, activity_box = self.notes_box, self.activity_box = QWidget(), QWidget()
        for box in (notes_box, activity_box):
            box.setMinimumHeight(60)
        self.details_splitter = GripSplitter(Qt.Vertical, "details_splitter", [notes_box, activity_box], [420, 150])
        self.details_splitter.setHandleWidth(14)
        details.addSpacing(16)
        details.addWidget(self.details_splitter, 1)

        # The notes, typed straight in here (saved a moment after typing stops)
        root = QVBoxLayout(notes_box)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.notes_label = caption("Notes")
        root.addWidget(self.notes_label)
        root.addSpacing(4)
        self.notes = PlainTextEdit()
        self.notes.setPlaceholderText("No notes")
        self.set_notes_px(14)
        self.notes.setMinimumHeight(70)
        self.notes_timer = QTimer(self, singleShot=True, interval=800, timeout=self.save_notes)
        self.notes.textChanged.connect(lambda: self._loading_notes or self.notes_timer.start())
        self.notes.installEventFilter(self)  # leaving the notes saves them straight away
        self._loading_notes = False
        root.addWidget(self.notes, 1)
        # Notes are hidden like passwords (they often hold PINs, security answers…): dots until shown
        # with the eye, Show passwords, or a click here
        self.notes_mask = PlainTextEdit()
        self.notes_mask.setReadOnly(True)
        self.notes_mask.setPlainText("•" * 12)
        self.notes_mask.setToolTip("Click to show the notes")
        self.notes_mask.setMinimumHeight(70)
        self.notes_mask.viewport().setCursor(Qt.PointingHandCursor)
        self.notes_mask.viewport().installEventFilter(self)
        self.notes_mask.hide()
        self._notes_shown = False  # shown with a click, for this entry
        root.addWidget(self.notes_mask, 1)

        # When it was made and changed, its last few changes, and other entries for the same site (they
        # scroll if there are more than the divider leaves room for)
        root = QVBoxLayout(activity_box)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.activity_label = caption("Activity")
        root.addWidget(self.activity_label)
        root.addSpacing(4)
        self.more = QWidget(objectName="moreDetails")
        self.more.setStyleSheet("QWidget#moreDetails { background: transparent; }")
        self.more_scroll = ScrollArea()
        self.more_scroll.setWidget(self.more)
        self.more_scroll.setWidgetResizable(True)
        self.more_scroll.enableTransparentBackground()
        self.more_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.more_scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(self.more_scroll, 1)
        root = QVBoxLayout(self.more)  # the rest goes in there
        root.setContentsMargins(0, 0, 14, 0)  # room for the scroll bar
        root.setSpacing(0)
        self.dates = caption("")
        self.dates.setWordWrap(True)
        root.addWidget(self.dates)
        # What Password health found wrong with this password, with a link to change it
        self.advice = QWidget()
        advice = QHBoxLayout(self.advice)
        advice.setContentsMargins(0, 4, 0, 0)
        advice.setSpacing(8)
        self.advice_text = CaptionLabel("")
        self.advice_text.setWordWrap(True)
        advice.addWidget(self.advice_text, 1)
        self.advice_btn = self._link("Change password", lambda: vault().change_password(),
                                     "Edit the entry with a newly generated password")
        advice.addWidget(self.advice_btn, 0, Qt.AlignVCenter)
        root.addWidget(self.advice)
        self.changes = QVBoxLayout()
        self.changes.setSpacing(2)
        root.addLayout(self.changes)
        self.related_label = caption("")
        root.addSpacing(10)
        root.addWidget(self.related_label)
        self.related = QVBoxLayout()  # one per line, so long names don't run into each other
        self.related.setSpacing(2)
        root.addLayout(self.related)
        root.addStretch(1)
        self.more_layout = root

        # Under the list (set_below), a strip: tabs for the notes, the fields and the activity, with
        # History and Edit beside them. The notes, card and activity above move onto the tabs.
        self.strip_bar = QWidget()
        bar = QHBoxLayout(self.strip_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)
        self.tabs = SegmentedWidget()
        for key, text in (("notes", "Notes"), ("details", "Details"), ("activity", "Activity")):
            self.tabs.addItem(key, text)
        bar.addWidget(self.tabs, 0, Qt.AlignVCenter)
        bar.addStretch(1)
        self.details_page = QWidget(objectName="detailsPage")
        self.details_page.setStyleSheet("QWidget#detailsPage { background: transparent; }")
        self.details_page_layout = QVBoxLayout(self.details_page)
        self.details_page_layout.setContentsMargins(0, 0, 14, 0)  # room for the scroll bar
        self.details_page_layout.setSpacing(8)
        self.details_page_layout.addStretch(1)
        self.details_scroll = ScrollArea()
        self.details_scroll.setWidget(self.details_page)
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.enableTransparentBackground()
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.details_scroll.setFrameShape(QFrame.NoFrame)
        self.details_scroll.scrollDelagate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        self.empty = caption("Pick something from the list to see its notes.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.details_scroll)
        self.pages.addWidget(self.empty)
        tab = setting("details_tab", "notes")
        self.tabs.setCurrentItem(tab if tab in self.tabs.items else "notes")
        self.tabs.currentItemChanged.connect(self._tab_chosen)
        self.strip_bar.hide()
        self.pages.hide()

        qconfig.themeChanged.connect(lambda: self.set_entry(self.entry))
        self.set_entry(None)

    # ---- beside the list, or below it

    def set_below(self, below):
        """Beside the list: the entry's name, its fields, then the notes and activity (with a divider
        between them). Below it: a short strip with the notes, fields and activity on tabs."""
        if below == self.below:
            return
        self.below = below
        root = self.outer
        while root.count():  # (the widgets stay; only the layout's hold on them goes)
            root.takeAt(0)
        if below:
            root.setContentsMargins(16, 8, 16, 10)
            for button in (self.history_btn, self.edit_btn):
                self.strip_bar.layout().addWidget(button, 0, Qt.AlignVCenter)
            self.details_page_layout.insertWidget(0, self.advice)
            self.details_page_layout.insertWidget(1, self.card)
            self.pages.insertWidget(0, self.notes_box)
            self.pages.insertWidget(2, self.activity_box)
            root.addWidget(self.strip_bar)
            root.addSpacing(8)
            root.addWidget(self.pages, 1)
        else:
            root.setContentsMargins(30, 20, 26, 14)
            for button in (self.history_btn, self.edit_btn):
                self.head.addWidget(button, 0, Qt.AlignVCenter)
            self.more_layout.insertWidget(1, self.advice)
            self.pages.removeWidget(self.notes_box)
            self.pages.removeWidget(self.activity_box)
            self.details_splitter.insertWidget(0, self.notes_box)
            self.details_splitter.insertWidget(1, self.activity_box)
            for box in (self.notes_box, self.activity_box):
                box.show()  # (the tabs left all but one hidden)
            self.details_splitter.set_layout(Qt.Vertical, "details_splitter", [420, 150])
            root.addWidget(self.head_box)
            root.addWidget(self.card)
            root.addSpacing(16)
            root.addWidget(self.details_splitter, 1)
        self.head_box.setVisible(not below)
        self.strip_bar.setVisible(below)
        self.pages.setVisible(below)
        self.set_entry(self.entry)

    def _tab_chosen(self, key):
        settings.setValue("details_tab", key)  # the same tab for the next entry, and next time
        self._show_tab()

    def _show_tab(self):
        if not self.below:
            return
        if self.entry is None:
            self.pages.setCurrentWidget(self.empty)
            return
        self.pages.setCurrentWidget({"notes": self.notes_box, "details": self.details_scroll,
                                     "activity": self.activity_box}[self.tabs.currentRouteKey()])


    # ---- the folder, chosen in place

    def _fill_folders(self, e, editable):
        db = self.window().vault.db
        self._loading_folder = True
        self.folder_combo.clear()
        choices = [("Top level (no folder)", None)] + [
            (" › ".join(f["path"]), f["id"]) for f in (db.folders if db else [])
            if not f["in_bin"] or f["id"] == e["folder_id"]]
        for text, folder in choices:
            self.folder_combo.addItem(text, userData=folder)
        ids = [folder for _, folder in choices]
        self.folder_combo.setCurrentIndex(ids.index(e["folder_id"]) if e["folder_id"] in ids else 0)
        self.folder_combo.setEnabled(editable and not e["in_bin"])
        self._loading_folder = False

    def _folder_chosen(self, _index):
        e = self.entry
        if self._loading_folder or e is None:
            return
        folder = self.folder_combo.currentData()
        if folder != e["folder_id"]:
            self.window().saver.submit(Op("move", e["uuid"], folder=folder, title=e["title"]),
                                       f"Move of “{e['title']}”")

    # ---- notes typed in place

    def eventFilter(self, obj, event):
        if obj is self.notes and event.type() == QEvent.FocusOut:
            self.save_notes()
            self._hide_clicked_notes()
        elif (event.type() == QEvent.MouseButtonPress and self._notes_shown and isinstance(obj, QWidget)
              and obj is not self.notes and not self.notes.isAncestorOf(obj)):
            # Shown with a click: a click anywhere else hides them again (not only one that moves the
            # keyboard focus: clicking a label or empty space doesn't)
            self.save_notes()
            self._hide_clicked_notes()
        elif (event.type() == QEvent.MouseButtonRelease and hasattr(self, "notes_mask")
              and obj is self.notes_mask.viewport()):
            self._notes_shown = True
            QApplication.instance().installEventFilter(self)  # watch for clicks elsewhere (see above)
            self._mask_notes()
            self.notes.setFocus()
            return True
        return super().eventFilter(obj, event)

    def _hide_clicked_notes(self):
        if self._notes_shown:
            self._notes_shown = False
            QApplication.instance().removeEventFilter(self)
            self._mask_notes()

    def _mask_notes(self):
        """Dots instead of the notes, unless they're shown (eye, Show passwords or a click) or empty."""
        e = self.entry
        hidden = bool(e and e["notes"] and not (self.revealed or self._notes_shown))
        self.notes.setVisible(e is not None and not hidden)
        self.notes_mask.setVisible(hidden)

    def save_notes(self):
        """Saves notes typed here (as an edit of the entry: undoable, kept in its history)."""
        self.notes_timer.stop()
        e, vault = self.entry, self.window().vault
        if e is None or self.notes.isReadOnly() or not vault._editable():
            return
        text = self.notes.toPlainText()
        if text == e["raw"]["notes"]:
            return
        values = {name: e["raw"][name] for name in store.FIELDS} | {"notes": text}
        self.window().saver.submit(Op("update", e["uuid"], fields={"notes": text}, all_fields=values,
                                      base_mtime=e["base_mtime"], base_version=store.base_version(e), title=e["title"]),
                                   f"Notes of “{e['title']}”")

    # ---- the extra sections

    def _show_advice(self, e, problems):
        shown = [issue for issue in ("weak", "reused", "expired", "old") if issue in (problems or {})]
        self.advice.setVisible(bool(e and e["password"] and shown))
        if not self.advice.isVisible():
            return
        self.advice_text.setText("\n".join(f"{health.ISSUES[issue][0]} · {problems[issue]}" for issue in shown))
        self.advice_btn.setVisible(self.window().vault._editable())
        style = "bad" if {"weak", "expired"} & set(shown) else "warn"  # coloured text, nothing heavier
        self.advice_text.setTextColor(QColor(CHIP_COLORS[style][0][1]), QColor(CHIP_COLORS[style][1][1]))

    @staticmethod
    def _ago(when):
        if when is None:
            return ""
        days = (datetime.now(when.tzinfo) - when).days
        if days < 1:
            return "today"
        if days < 2:
            return "yesterday"
        if days < 60:
            return f"{days} days ago"
        if days < 730:
            return f"{days // 30} months ago"
        return f"{days // 365} years ago"

    def _show_activity(self, e):
        while self.changes.count():
            self.changes.takeAt(0).widget().deleteLater()
        while self.related.count():
            item = self.related.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.activity_label.setVisible(e is not None and not self.below)  # (below the list: its tab says so)
        self.more_scroll.setVisible(e is not None)
        self.related_label.hide()
        if e is None:
            return
        parts = [f"Created {e['created']}" if e["created"] else "", f"modified {e['modified']}" if e["modified"] else ""]
        if e["password"] and e.get("password_changed"):
            parts.append(f"password last changed {self._ago(e['password_changed'])}")
        self.dates.setText(" · ".join(p for p in parts if p))

        # The last few changes, from the entry's history (newest first)
        vault = self.window().vault
        versions = vault.db.history(e["uuid"]) if vault.db else []
        newer, when = e["raw"], None
        names = {"title": "title", "username": "username", "password": "password", "url": "website", "notes": "notes"}
        shown = 0
        for version in versions:
            changed = [label for key, label in names.items() if (newer.get(key) or "") != (version.get(key) or "")]
            stamp = e["modified"] if when is None else when.strftime("%b %d, %Y %H:%M")
            if changed:
                link = self._link(f"{stamp}: {', '.join(changed)} changed", lambda: self.window().vault.show_history(),
                                  "See the earlier versions (History)")
                self.changes.addWidget(link, 0, Qt.AlignLeft)
                shown += 1
            newer, when = version, version["modified"]
            if shown == 3:
                break

        # Other entries for the same site: their name or website contains the site's name, e.g. "yahoo"
        # for Yahoo Mail and Yahoo Finance (8 at most; "… more" searches for the rest)
        key = self._site_word(e)
        live = [x for x in vault.db.entries if x["uuid"] != e["uuid"] and not x["in_bin"]] if vault.db else []
        # Both ways round: "apple" finds "apple2", and "apple2" finds "apple"
        related = [x for x in live if key and (key in x["title"].lower() or key in x["url"].lower()
                                               or (self._site_word(x) or "\0") in key)]
        self.related_label.setVisible(bool(related))
        self.related_label.setText(f"Also for “{key}” ({len(related)}):")
        for other in related[:8]:
            link = self._link(other["title"] + (f" ({other['username']})" if other["username"] else ""),
                              lambda u=other["uuid"]: self.window().show_entry(u))
            self.related.addWidget(link, 0, Qt.AlignLeft)
        if len(related) > 8:
            more = self._link(f"… and {len(related) - 8} more", lambda: self.window().vault.search.setText(key),
                              f"Search for {key}")
            self.related.addWidget(more, 0, Qt.AlignLeft)

    @staticmethod
    def _site_word(e):
        """The site's name in lower case: from its website ("yahoo" for mail.yahoo.co.uk), else the
        first word of the entry's name. "" if too short to be useful."""
        host = favicon.site_host(e["url"]) or ""
        labels = [p for p in host.lower().split(".") if p and p != "www"]
        if len(labels) >= 2:
            labels = labels[:-1]  # the ending: .com, .uk
            if len(labels) >= 2 and labels[-1] in ("co", "com", "org", "net", "gov", "ac", "ltd", "me"):
                labels = labels[:-1]  # .co.uk and the like
            word = labels[-1]
        else:
            word = (re.findall(r"[a-z0-9]+", e["title"].lower()) or [""])[0]
        return word if len(word) >= 3 else ""

    def _small(self, label):
        font = label.font()
        font.setPixelSize(max(9, round(12 * self.text_scale)))
        label.setFont(font)

    def _link(self, text, on_click, tip=""):
        """A small clickable line of text in the accent colour, one line high (the UI library's link
        buttons are as tall as buttons, and clipped their text when squeezed)."""
        link = QLabel()
        link.setTextFormat(Qt.RichText)
        escaped = text.replace("&", "&amp;").replace("<", "&lt;")
        link.setText(f'<a href="#" style="color:{QColor(themeColor()).name()}; text-decoration:none">{escaped}</a>')
        link.setCursor(Qt.PointingHandCursor)
        link.setToolTip(tip)
        link.linkActivated.connect(lambda _href: on_click())
        self._small(link)
        return link

    text_scale = 1.0  # Settings → List text size (1.0 = 100%)

    def set_text_scale(self, k):
        """The fields follow the list text size too: their labels, values, the 2FA code and the label
        by the password (the notes: set_notes_px)."""
        self.text_scale = k
        self._scale_fields()
        self.set_revealed(self.revealed)  # the password's font
        self.update_chip()

    def _scale_fields(self):
        k = self.text_scale
        for row in self.findChildren(FieldRow):
            for label, px in ((row.label, 12), (row.value, 14)):
                if isinstance(label, QLabel) and label is not self.pw_value:
                    font = QFont(label.font())
                    font.setPixelSize(max(9, round(px * k)))
                    label.setFont(font)
        qss = f"StrongBodyLabel {{ {mono_font_qss(round(20 * k))} letter-spacing: 2px; }}"
        setCustomStyleSheet(self.totp_code, qss, qss)
        font = QFont(self.notes_label.font())
        font.setPixelSize(max(9, round(12 * k)))
        self.notes_label.setFont(font)

    def set_notes_px(self, px):
        """The notes' text size (in the usual box, like the other fields you can type in)."""
        qss = f"QPlainTextEdit {{ font-size: {px}px; }}"
        setCustomStyleSheet(self.notes, qss, qss)

    def _show_extra(self, e):
        while self.extra.count():
            self.extra.takeAt(0).widget().deleteLater()
        fields, files = (e["fields"], e["attachments"]) if e else ([], [])
        self.extra_box.setVisible(bool(fields or files))
        for name, value, hidden in fields:
            shown = value.splitlines()[0] + " …" if "\n" in value else value
            label = BodyLabel("•" * 8 if hidden and value else shown)
            row = FieldRow(name, label)
            if not hidden:
                label.setToolTip(value)
            if hidden and value:
                reveal = row.add_button(TransparentToggleToolButton(FIF.VIEW))
                reveal.setToolTip("Show")
                reveal.toggled.connect(lambda on, lbl=label, v=shown: lbl.setText(v if on else "•" * 8))
            if value:
                row.add_button(copy_button(f"Copy {name}", lambda n=name, v=value: self.window().copy_secret(v, n)))
            self.extra.addWidget(row)
        if files:
            box = QWidget()
            line = QHBoxLayout(box)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(4)
            for name, size in files:
                button = TransparentPushButton(AppIcon("attach"), f"{name}  ({file_size(size)})")
                button.setToolTip(f"Save {name}…")
                button.clicked.connect(lambda _=False, n=name: self.save_attachment(n))
                line.addWidget(button)
            line.addStretch(1)
            self.extra.addWidget(FieldRow("Attachments", box))
        self._scale_fields()  # the new rows in the list text size

    def save_attachment(self, name):
        """Saves an attached file where the user chooses (it's only ever written decrypted there)."""
        db = self.window().vault.db
        data = db.attachment(self.entry["uuid"], name) if db and self.entry else None
        if data is None:
            return
        path = ask_path(self, "Save attachment", str(Path.home() / "Downloads" / name), save=True)
        if not path:
            return
        try:
            Path(path).write_bytes(data)
        except OSError as exc:
            InfoBar.error("Couldn't save", str(exc), orient=Qt.Horizontal, isClosable=True,
                          position=InfoBarPosition.TOP_RIGHT, duration=5000, parent=self.window())
            return
        InfoBar.success("Saved", Path(path).name, orient=Qt.Horizontal, isClosable=True,
                        position=InfoBarPosition.TOP_RIGHT, duration=2000, parent=self.window())

    def set_entry(self, e):
        same = e is not None and self.entry is not None and e["uuid"] == self.entry["uuid"]
        if not same and self.notes_timer.isActive():
            self.save_notes()  # notes typed for the previous entry
        if not same:  # another entry: hidden again, unless Show passwords is on (a reload keeps it) or
            # it's shown in the list's password column
            self.revealed = self.window().vault.model.is_revealed(e) if e else False
            if self._notes_shown:
                self._notes_shown = False
                QApplication.instance().removeEventFilter(self)
        self.entry = e
        self._show_extra(e)
        self.totp_box.setVisible(bool(e and e["totp"]))
        if e and e["totp"] and not self.window().isMinimized():
            self._tick()
            self.totp_timer.start()
        else:
            self.totp_timer.stop()
        for part in (self.icon, self.fav_btn, self.history_btn, self.edit_btn, self.card, self.notes):
            part.setVisible(e is not None)
        for part in (self.notes_label, self.details_splitter):  # (below the list: the tabs instead)
            part.setVisible(e is not None and not self.below)
        self.tabs.setVisible(e is not None)
        self._show_activity(e)
        self._show_tab()
        if e is None:
            self.title.setText("No entry selected")
            self.path.setText("")
            self.modified.setText("")
            self._loading_notes = True
            self.notes.clear()
            self._loading_notes = False
            self.advice.hide()
            self.notes_mask.hide()
            return
        self.title.setText(e["title"])
        vault = self.window().vault
        ratio = self.devicePixelRatioF()
        picture = QPixmap(round(56 * ratio), round(56 * ratio))
        picture.fill(Qt.transparent)
        picture.setDevicePixelRatio(ratio)
        painter = QPainter(picture)
        draw_entry_tile(painter, QRect(0, 0, 56, 56), e, vault.model.icons)
        painter.end()
        self.icon.setPixmap(picture)
        self.path.setText(" › ".join(e["path"]))
        self.path.setVisible(bool(e["path"]))  # nothing for entries at the top level
        status = f"Modified {e['modified']}" if e["modified"] else ""
        if e["expired"]:
            status = "Expired  ·  " + status
        self.modified.setText(f"  ·  {status}" if status and self.path.text() else status)
        self.fav_btn.setIcon(star_icon(e["favourite"]))
        self.fav_btn.setToolTip("Remove from Favourites" if e["favourite"] else "Add to Favourites")
        editable = vault._editable()
        self.fav_btn.setEnabled(editable)
        self.edit_btn.setVisible(editable)

        self.user_row.value.setText(e["username"])
        self.user_row.setVisible(bool(e["username"]))
        self.pw_row.setVisible(bool(e["password"]))
        self.set_revealed(self.revealed)
        self.update_chip()
        self.url_row.setVisible(bool(e["url"]))
        url = self.url_value.fontMetrics().elidedText(e["url"], Qt.ElideMiddle, 520)
        self.url_value.setText(f'<a href="open" style="color:{QColor(themeColor()).name()}; text-decoration:none">'
                               f'{url.replace("&", "&amp;").replace("<", "&lt;")}</a>')
        self._fill_folders(e, editable)
        shown = [row for row in self.rows if row.isVisibleTo(self.card)]
        for row in self.rows:
            row.first = bool(shown) and row is shown[0]
        self.card.setVisible(bool(shown) or self.extra_box.isVisibleTo(self.card))
        # The notes, editable here; left alone while being typed in (the list reloads after each save)
        self.notes.setReadOnly(not editable)
        self.notes.setPlaceholderText("Add notes…" if editable else "No notes")
        if not (same and self.notes.hasFocus()):
            self._loading_notes = True
            self.notes.setPlainText(e["raw"]["notes"] if editable else e["notes"])
            self._loading_notes = False
        self._mask_notes()

    def set_revealed(self, on):
        """Shows or hides the password (each entry starts hidden)."""
        self.revealed = on
        e = self.entry
        if e is None:
            return
        if on and e["password"]:
            self.pw_value.setText(password_html(e["password"], setting("color_passwords", True)))
        else:
            self.pw_value.setText(f'<span style="color:{"#ffffff" if isDarkTheme() else "#000000"}">{"•" * 12}</span>')
        mono = QFont(MONO_FAMILY)
        mono.setStyleHint(QFont.TypeWriter)
        mono.setPixelSize(round(15 * self.text_scale))
        self.pw_value.setFont(mono)
        self.eye.setIcon(FIF.HIDE if on else FIF.VIEW)
        self.eye.setToolTip("Hide password and notes" if on else "Show password and notes")
        self._mask_notes()

    def update_chip(self):
        """The password's health problem (weak, reused, …), or "Strong", once the check has run."""
        e = self.entry
        problems = self.window().health.problems(e["uuid"]) if e else None
        self._show_advice(e, problems)
        if not e or not e["password"] or problems is None:
            self.chip.hide()
            return
        text, style = next(((t, s) for issue, t, s in STRENGTH_CHIPS if issue in problems), ("Strong", "good"))
        if text == "Strong" and not self.window().health.full:
            style = None  # strength not measured yet (Password health not opened): no label
        if not style:
            self.chip.hide()
            return
        background, color = CHIP_COLORS[style][isDarkTheme()]
        self.chip.setText(text)
        self.chip.setStyleSheet(f"QLabel {{ background: {background}; color: {color}; border-radius: 10px;"
                                f" padding: 2px 9px; font-size: {round(12 * self.text_scale)}px; }}")
        self.chip.setToolTip("\n".join(problems.values()) if problems else "No problems found in Password health")
        self.chip.show()

    def pause(self, paused):
        """Minimised: stop the 2FA countdown (its ring animates every second); restart it on restore."""
        if paused:
            self.totp_timer.stop()
        elif self.entry and self.entry["totp"]:
            self._tick()
            self.totp_timer.start()

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
    """The entry list (cards) with the selected entry's details beside it. The folders it shows
    (self.tree) and the New entry button live in the window's sidebar; the search box in the title bar."""

    listTextChanged = Signal(int)  # the list text size (%) changed, e.g. with Ctrl+wheel

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("view-vault")
        self.db = None
        self.folder = None
        self.below = False  # the details below the list rather than beside it (set_details_below)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Folders (shown in the sidebar)
        self.tree = FolderTree()
        self.folder_delegate = FolderRowDelegate(self.tree)  # row height follows Settings → Row density
        self.tree.setItemDelegate(self.folder_delegate)
        self.tree.entriesDropped.connect(self._on_entries_dropped)
        self.tree.folderDropped.connect(self._on_folder_dropped)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._folder_menu)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(10)  # compact: each level is still clearly offset
        self.tree.scrollDelagate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        self.tree.currentItemChanged.connect(self._on_folder)
        self.tree.itemClicked.connect(lambda *_: self._show_page())  # e.g. from Settings: back to the list
        for signal in (self.tree.itemExpanded, self.tree.itemCollapsed):  # what's visible changed: fit again
            signal.connect(lambda _item: QTimer.singleShot(0, self._fit_sidebar))
        self.new_btn = SideButton(FIF.ADD, "New entry", checkable=False)  # in the sidebar, by Password health
        self.new_btn.setToolTip(shortcut_text("New entry (Ctrl+N)"))
        self.new_btn.clicked.connect(self.new_entry)

        # The search box (shown in the title bar). Ctrl+F or Ctrl+K: see MainWindow.
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("Search all entries")
        self.search.setToolTip(shortcut_text("Search (Ctrl+F)"))
        # Wait for a short pause in typing before filtering.
        self.search_timer = QTimer(self, singleShot=True, interval=120, timeout=self.refresh)
        self.search.textChanged.connect(self.search_timer.start)
        # Down or Enter moves on to the results (then Ctrl+C copies).
        for keys in ("Down", "Return", "Enter"):
            local_shortcut(keys, self.search, self.focus_results)

        # The list's heading: the folder name with sort and check buttons, and under it
        # "302 entries · All changes saved"
        right = QVBoxLayout()
        right.setContentsMargins(14, 14, 6, 6)
        right.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(8, 0, 0, 0)
        head.setSpacing(6)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.list_title = SubtitleLabel("")
        self.list_title.setMinimumWidth(40)  # cut off rather than push the buttons over each other
        titles.addWidget(self.list_title)
        status = QHBoxLayout()
        status.setSpacing(8)
        self.count = caption("")
        self.save_status = caption("")
        for label in (self.count, self.save_status):
            label.setMinimumWidth(1)
            status.addWidget(label)
        status.addStretch(1)
        titles.addLayout(status)
        head.addLayout(titles, 1)
        self.sort_btn = TransparentToolButton(icon("SCROLL", "UP"))
        self.sort_btn.setToolTip("Sort")
        self.sort_btn.clicked.connect(self._sort_menu)
        head.addWidget(self.sort_btn, 0, Qt.AlignVCenter)
        # The details beside the list or below it (remembered); its icon shows the other layout
        self.layout_btn = TransparentToolButton(AppIcon("layout_below"))
        self.layout_btn.clicked.connect(lambda: self.set_details_below(not self.below))
        head.addWidget(self.layout_btn, 0, Qt.AlignVCenter)
        right.addLayout(head)
        # Show passwords and Check for changes (shown in the title bar)
        self.reveal = TransparentToggleToolButton(FIF.VIEW)
        self.reveal.setToolTip("Show passwords")
        self.reveal.toggled.connect(self._on_reveal)
        self.check_btn = TransparentToolButton(FIF.SYNC)
        self.check_btn.setToolTip("Check for changes made on other devices or apps (F5)")
        self.check_btn.clicked.connect(self.check_for_changes)

        self.model = EntryModel(self)
        self.table = TableView()
        self.table.setModel(self.model)
        self.table.setDragDropMode(QAbstractItemView.DragOnly)
        self.table.setDefaultDropAction(Qt.CopyAction)
        self.delegate = EntryDelegate(self.table, self.model)
        self.table.setItemDelegate(self.delegate)
        self.table.scrollDelagate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        self.table.setBorderVisible(False)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        # Deferred (once per batch of changes, and never while the window is being torn down)
        self.gutter_timer = QTimer(self, singleShot=True, interval=0, timeout=self._scroll_gutters)
        for bar in (self.table.verticalScrollBar(), self.table.horizontalScrollBar()):
            bar.rangeChanged.connect(lambda *_: self.gutter_timer.start())
        self.set_density(setting("row_density", "Comfortable"))
        # One card per entry: beside the details, only the first column shows (the card draws the rest),
        # across the list; above them, the columns too (see set_details_below), and their headings sort.
        header = self.table.horizontalHeader()
        header.hide()
        for col in range(1, len(EntryModel.COLUMNS)):
            header.setSectionHidden(col, True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(EntryModel.TITLE, QHeaderView.Stretch)
        header.setSectionResizeMode(EntryModel.ACTIONS, QHeaderView.Fixed)
        header.setMinimumSectionSize(40)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setHighlightSections(False)
        widths = str(setting("list_column_widths", "")).split(",")  # dragged wider or narrower: remembered
        self._column_widths = {col: int(widths[col]) if col < len(widths) and widths[col].isdigit() else width
                               for col, width in self.COLUMN_WIDTHS.items()}
        for col, width in self._column_widths.items():
            header.resizeSection(col, width)
        header.sectionResized.connect(self._column_resized)
        # Clicking a heading sorts by it (again: the other way round); the Sort menu does the same.
        # Sorted here rather than by the table, so the Password and buttons columns can't be sorted.
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._heading_clicked)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._columns_menu)
        column, order = self._saved_sort()
        self.table.sortByColumn(column, order)
        self.table.selectionModel().currentRowChanged.connect(self._on_row)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self._dbl = CellDoubleClick(self.table, self._on_double_click)
        self.tip_timer = QTimer(self, singleShot=True, interval=0, timeout=self._show_button_tip)  # straight away
        for keys, handler in (("Ctrl+C", self.copy_password), ("Ctrl+B", self.copy_username),
                              ("Ctrl+U", self.open_url), ("Return", self.edit_entry), ("Enter", self.edit_entry),
                              ("Ctrl+E", self.edit_entry), ("Delete", self.delete_entry),
                              ("Ctrl+T", self.copy_totp), ("Ctrl+D", self.duplicate_entry),
                              ("Ctrl+H", self.show_history),
                              # Single keys, like the card's buttons (U, P and T no longer jump to entries
                              # starting with those letters; the other letters still do)
                              ("U", lambda: self._key_copy("username")), ("P", lambda: self._key_copy("password")),
                              ("T", lambda: self._key_copy("totp"))):
            local_shortcut(keys, self.table, handler)
        self.table.setMinimumHeight(120)

        self.notes = NotesPanel()

        # List text size: Ctrl + mouse wheel, Ctrl+= / Ctrl+- and Ctrl+0 (normal) over the folders,
        # entries and notes, or Settings → List text size. Changes straight away.
        self._wheel_zoom = 0
        for area in (self.table.viewport(), self.tree.viewport(), self.notes.notes.viewport()):
            area.installEventFilter(self)
        for keys, step in (("Ctrl+=", 1), ("Ctrl++", 1), ("Ctrl+-", -1)):
            local_shortcut(keys, self, lambda step=step: self.zoom_list_text(step))
        local_shortcut("Ctrl+0", self, lambda: self.set_list_text_size(100))

        right.addWidget(self.table, 1)
        list_box = QWidget()
        list_box.setLayout(right)
        list_box.setMinimumWidth(260)
        # The list and the details (or the entry being edited) side by side, or the details below the
        # list (set_details_below); drag the divider to give the list more room
        self.details = QStackedWidget()
        self.details.addWidget(self.notes)
        self.editor = None  # EntryEditPane while an entry is being edited or added
        self._popup = None  # EntryEditor (a pop-up) instead, with the details below the list
        self._editor_anchor = None  # the entry selected when it opened (staying on it keeps it open)
        self.splitter = GripSplitter(Qt.Horizontal, "list_splitter", [list_box, self.details], [380, 900])
        self.splitter.setHandleWidth(9)
        root.addWidget(self.splitter)
        self.set_details_below(setting("details_layout", "right") == "below", save=False)
        # The UI library pads each folder row by 20 px on the left; 12 still clears the expand arrows.
        row_qss = "QTreeView::item { padding-left: 12px; }"
        setCustomStyleSheet(self.tree, row_qss, row_qss)
        qconfig.themeChanged.connect(self._set_tree_icons)

        # Normal text sizes of the folder tree and notes (set by the UI library's styles), then the
        # saved list text size.
        self.notes.notes.ensurePolished()
        self._notes_base_px = self.notes.notes.fontInfo().pixelSize() or 14
        self._list_text = list_text_size()
        self.set_list_text_size(self._list_text)

    # ---- loading

    def load(self, db, keep_state=False, select_uuid=None):
        """Shows `db`. With keep_state, stays on the same folder, search and selected entry
        (used after edits and reloads)."""
        folder, query = self.folder, self.search.text()
        current = self.current_entry()
        select_uuid = select_uuid or (current["uuid"] if current and keep_state else None)
        self.db = db
        self.model.icons = EntryIcons(db)
        if not keep_state:  # opening the database (at launch, after unlocking): Settings → Show passwords when unlocked
            self.reveal.setChecked(setting("show_passwords_on_open", False))
        self.folder = None
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.new_btn.setVisible(db.writable)
        self.model.draggable = db.writable
        self.table.setDragEnabled(db.writable)
        self.tree.setDragEnabled(db.writable)
        self.tree.setAcceptDrops(db.writable)
        self.tree.bin_id = db.bin_id
        self.tree.blockSignals(True)
        self.tree._hover = None
        self.tree.clear()
        # All entries and Favourites, then the "Folders" heading and the top-level folders under it
        # (the database's root folder is "All entries").
        root_item = QTreeWidgetItem([f"All entries  ({sum(not e['in_bin'] for e in db.entries)})"])
        root_item.setData(0, Qt.UserRole, None)
        root_item.setFlags(root_item.flags() & ~Qt.ItemIsDragEnabled)
        self.tree.addTopLevelItem(root_item)
        favourites = QTreeWidgetItem([f"Favourites  ({sum(in_folder(e, FAVOURITES) for e in db.entries)})"])
        favourites.setData(0, Qt.UserRole, FAVOURITES)
        favourites.setFlags(favourites.flags() & ~Qt.ItemIsDragEnabled)
        favourites.setToolTip(0, "Star an entry to keep it here (drop entries here to star them)")
        self.tree.addTopLevelItem(favourites)
        notes = QTreeWidgetItem([f"Notes  ({sum(in_folder(e, NOTES) for e in db.entries)})"])
        notes.setData(0, Qt.UserRole, NOTES)
        notes.setFlags(notes.flags() & ~Qt.ItemIsDragEnabled)
        notes.setToolTip(0, "Secure notes: text kept in the vault, with no login (New note adds one)")
        self.tree.addTopLevelItem(notes)
        if db.folders:
            heading = QTreeWidgetItem([""])
            heading.setData(0, Qt.UserRole, FOLDERS_HEADING)
            heading.setData(0, Qt.UserRole + 4, db.writable)
            heading.setFlags(Qt.NoItemFlags)  # not selectable; its + is handled in eventFilter
            heading.setToolTip(0, "New folder" if db.writable else "")
            self.tree.addTopLevelItem(heading)
        items = {None: root_item, FAVOURITES: favourites, NOTES: notes}
        for f in db.folders:
            n = sum(in_folder(e, f["id"]) for e in db.entries)
            item = QTreeWidgetItem([f"{f['name']}  ({n})"])
            item.setData(0, Qt.UserRole, f["id"])
            item.setData(0, Qt.UserRole + 1, f["in_bin"])
            item.setData(0, Qt.UserRole + 2, f.get("icon"))
            if f["id"] == db.bin_id or f["in_bin"]:
                item.setFlags(item.flags() & ~Qt.ItemIsDragEnabled)
            if f["parent"] is None:
                self.tree.addTopLevelItem(item)
            else:
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
        if self.editor is not None:  # locked mid-edit: the form goes (unsaved changes with it)
            self._close_editor(self.editor)
        if self._popup is not None:  # likewise the pop-up one (details below the list)
            self._popup.reject()
        self.db = None
        self.tree.blockSignals(True)
        self.tree.clear()
        self.tree.blockSignals(False)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.reveal.setChecked(False)  # passwords hidden again after unlocking
        self.model.revealed.clear()
        self.model.set_entries([])
        self.model.icons = None
        self.list_title.setText("")
        self.count.setText("")
        self.save_status.setText("")
        self.notes.set_entry(None)

    # ---- the details beside the list, or below it (with columns in the list)

    # The columns' starting widths (the name takes the rest)
    COLUMN_WIDTHS = {EntryModel.USERNAME: 180, EntryModel.PASSWORD: 130, EntryModel.WEBSITE: 170,
                     EntryModel.FOLDER: 150, EntryModel.MODIFIED: 100, EntryModel.CREATED: 100}
    # When the list is too narrow for them all, they give way from the end of this list
    COLUMN_PRIORITY = [EntryModel.USERNAME, EntryModel.PASSWORD, EntryModel.WEBSITE, EntryModel.MODIFIED,
                       EntryModel.CREATED, EntryModel.FOLDER]
    NAME_MIN_WIDTH = 220  # the name column keeps at least this much

    def set_details_below(self, below, save=True):
        """The details beside the list, or below it (the list then shows columns: username, password,
        website…). Remembered. False if an entry being edited couldn't be saved: the layout stays."""
        if below != self.below and not self.leave_editor():
            return False
        if below != self.below:  # the panels as they are now (dragged, or changed with the window), for coming back
            self.splitter.save_position()
            if not self.below:
                self.notes.details_splitter.save_position()
        self.below = below
        if save:
            settings.setValue("details_layout", "below" if below else "right")
        if below:  # each layout keeps its own divider position
            self.splitter.set_layout(Qt.Vertical, "list_splitter_below", [520, 260])
        else:
            self.splitter.set_layout(Qt.Horizontal, "list_splitter", [380, 900])
        self.notes.set_below(below)
        self.delegate.columns = below
        header = self.table.horizontalHeader()
        header.setVisible(below)
        header.resizeSection(EntryModel.ACTIONS, self.delegate.actions_width())
        self._fit_columns()
        self.layout_btn.setIcon(AppIcon("layout_right" if below else "layout_below"))
        self.layout_btn.setToolTip("Show the details beside the list" if below else "Show the details below the list")
        self.table.viewport().update()
        return True

    def _chosen_columns(self):
        """The columns ticked in the headings' right-click menu (all of them to start with)."""
        saved = setting("list_columns", "all")
        if saved == "all":
            return set(self.COLUMN_WIDTHS)
        return {int(c) for c in str(saved).split(",") if c.isdigit()} & set(self.COLUMN_WIDTHS)

    def _fit_columns(self):
        """Shows the chosen columns that fit beside the name (the rest give way in COLUMN_PRIORITY's
        order); the folder only where the list mixes folders: All entries, Favourites, Notes, searches."""
        header = self.table.horizontalHeader()
        shown = set()
        if self.below:
            chosen = self._chosen_columns()
            mixed = bool(self.search.text().strip()) or self.folder in (None, *VIEWS)
            room = self.table.viewport().width() - self.NAME_MIN_WIDTH - self.delegate.actions_width()
            for col in self.COLUMN_PRIORITY:
                if col not in chosen or (col == EntryModel.FOLDER and not mixed):
                    continue
                room -= self._column_widths[col]
                if room < 0:
                    break
                shown.add(col)
            shown.add(EntryModel.ACTIONS)
        for col in range(1, len(EntryModel.COLUMNS)):
            if header.isSectionHidden(col) == (col in shown):
                header.setSectionHidden(col, col not in shown)

    def _column_resized(self, col, _old, new):
        if col in self._column_widths and new > 0 and new != self._column_widths[col]:  # (0: hidden)
            self._column_widths[col] = new
            settings.setValue("list_column_widths",
                              ",".join(str(self._column_widths.get(c, 0)) for c in range(len(EntryModel.COLUMNS))))

    def _columns_menu(self, pos):
        """Right-click a heading: which columns to show."""
        menu = CheckableMenu(parent=self)
        chosen = self._chosen_columns()
        for col in sorted(self.COLUMN_WIDTHS):
            action = Action(EntryModel.COLUMNS[col], checkable=True)
            action.setChecked(col in chosen)
            action.triggered.connect(lambda on, c=col: self._choose_column(c, on))
            menu.addAction(action)
        header = self.table.horizontalHeader()
        menu.exec(header.mapToGlobal(pos), ani=False)

    def _choose_column(self, col, on):
        chosen = self._chosen_columns()
        chosen = chosen | {col} if on else chosen - {col}
        settings.setValue("list_columns", ",".join(str(c) for c in sorted(chosen)))
        self._fit_columns()

    def _heading_clicked(self, col):
        """Sorts by that column (clicked again: the other way round). Dates start newest first."""
        if col not in dict(self.SORTS).values():  # the password and the buttons: not sortable
            self.table.horizontalHeader().setSortIndicator(self.model.sort_column, self.model.sort_order)
            return
        if col == self.model.sort_column:
            order = Qt.DescendingOrder if self.model.sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            order = Qt.DescendingOrder if col in (EntryModel.MODIFIED, EntryModel.CREATED) else Qt.AscendingOrder
        self.sort_by(col, order)

    def _set_tree_icons(self):
        """Icons are rendered for the current theme, so redo them when it changes."""
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            if getattr(self, "_tree_font", None) is not None:
                item.setData(0, Qt.FontRole, self._tree_font)  # Settings → List text size
            kind = item.data(0, Qt.UserRole)
            own = None  # the folder's own icon from the database (as KeePass shows it), if it has one
            if (kind not in (None, *VIEWS, FOLDERS_HEADING) and not item.data(0, Qt.UserRole + 1)
                    and self.model.icons and item.data(0, Qt.UserRole + 2)):
                own = self.model.icons.folder(item.data(0, Qt.UserRole + 2))
            if kind == FOLDERS_HEADING:
                pass
            elif own:
                item.setIcon(0, own)
            elif kind is None:
                item.setIcon(0, icon("LIBRARY", "FOLDER").icon())
            elif kind == FAVOURITES:
                item.setIcon(0, star_icon(True))
            elif kind == NOTES:
                item.setIcon(0, icon("QUICK_NOTE", "DOCUMENT").icon())
            elif item.data(0, Qt.UserRole + 1):
                item.setIcon(0, FIF.DELETE.icon())
            else:
                item.setIcon(0, FIF.FOLDER.icon())
            it += 1
        self.tree.doItemsLayout()  # the tree caches row heights: recalculate them for the new size
        QTimer.singleShot(0, self._fit_sidebar)

    def _fit_sidebar(self):
        sidebar = getattr(self.window(), "sidebar", None)
        if sidebar is not None:
            sidebar.fit()

    def _show_page(self):
        """Shows the list (after a folder is clicked while Password health or Settings shows)."""
        window = self.window()
        if hasattr(window, "switchTo") and window.stackedWidget.currentWidget() is not self:
            window.switchTo(self)

    @staticmethod
    def _folder_key(db):
        # One remembered folder per database file (keys can't contain the path itself).
        return "last_folder/" + hashlib.sha1(os.path.normcase(os.path.abspath(db.path)).encode()).hexdigest()[:16]

    def _remembered_folder(self, db):
        return setting(self._folder_key(db), "") or None

    def _on_folder(self, item, _previous):
        if item is None or item.data(0, Qt.UserRole) == FOLDERS_HEADING:
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
        # Browsing the Backup folder itself: everything there is a backup, so show it normally
        self.model.dim_backups = bool(q) or not any(f["id"] == self.folder and f["backup"] for f in self.db.folders)
        noun = ("note", "notes") if self.folder == NOTES and not q else ("entry", "entries")
        self.count.setText(f"{len(entries)} {noun[len(entries) != 1]}")
        note = self.folder == NOTES  # in Notes, the sidebar's button adds a note instead
        self.new_btn.setText("New note" if note else "New entry")
        self.new_btn.setToolTip(shortcut_text(f"New {'note' if note else 'entry'} (Ctrl+N)"))
        self.new_btn.update()
        self.model.set_entries(entries)
        if self.below:  # the folder column shows only where the list mixes folders
            self._fit_columns()
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
        e = self.model.data(current, Qt.UserRole) if current.isValid() else None
        self.notes.set_entry(e)
        # Another entry picked while editing: finish the edit (asking about unsaved changes). The same
        # one again (e.g. after the list reloads) keeps the form.
        if self.editor is not None and (e is None or e["uuid"] != self._editor_anchor):
            QTimer.singleShot(0, self.leave_editor)

    def eventFilter(self, obj, event):
        if obj is self.table.viewport() and event.type() == QEvent.Resize and self.below:
            self._fit_columns()  # as many columns as fit
        if obj is self.table.viewport() and self._card_buttons(event):
            return True
        if (obj is self.tree.viewport() and event.type() == QEvent.MouseButtonRelease
                and event.button() == Qt.LeftButton):
            # The + at the right of the "Folders" heading: a new top-level folder
            item = self.tree.itemAt(event.position().toPoint())
            if (item is not None and item.data(0, Qt.UserRole) == FOLDERS_HEADING and self._editable()
                    and event.position().x() > self.tree.viewport().width() - 40):
                self.new_folder(parent=None)
                return True
        elif event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            # Ctrl + wheel zooms the list text (one step per notch; touchpads send smaller amounts)
            self._wheel_zoom += event.angleDelta().y()
            while abs(self._wheel_zoom) >= 120:
                step = 1 if self._wheel_zoom > 0 else -1
                self._wheel_zoom -= 120 * step
                self.zoom_list_text(step)
            return True
        return False

    def _button_at(self, pos):
        """(entry, field, tooltip) of the card's copy button under `pos`, or None."""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return None
        e = self.model.entries[row]
        rect = self.delegate.row_rect(self.table.visualRect(self.model.index(row, 0)))
        return next(((e, field, tip) for field, _ico, tip, r in self.delegate.actions(e, rect)
                     if r.contains(pos)), None)

    def _card_buttons(self, event):
        """The copy buttons on the card under the mouse: highlight, tooltip, click. True if handled."""
        kind = event.type()
        if kind in (QEvent.MouseMove, QEvent.Leave):
            pos = event.position().toPoint() if kind == QEvent.MouseMove else None
            if pos != self.delegate.hover_pos:
                self.delegate.hover_pos = pos
                self.table.viewport().update()
            # The button's tooltip: shown quickly, and gone as soon as the mouse leaves that button
            hit = self._button_at(pos) if pos is not None else None
            key = (hit[0]["uuid"], hit[1]) if hit else None
            if key != getattr(self, "_tip_key", None):
                self._tip_key = key
                QToolTip.hideText()
                if key:
                    self.tip_timer.start()
                else:
                    self.tip_timer.stop()
            return False
        if kind not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick,
                        QEvent.ToolTip):
            return False
        pos = event.pos() if kind == QEvent.ToolTip else event.position().toPoint()
        hit = self._button_at(pos)
        if hit is None:
            return False
        e, field, tip = hit
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.tip_timer.stop()
            QToolTip.hideText()
            if field == "favourite":  # the star: stars or unstars this card's entry (selected or not)
                self.toggle_favourite(e)
                return True
            # Copies straight away, and selects the entry, so it's still marked when Vault is brought back
            # (nothing starts dragging)
            self.table.selectRow(self.model.entries.index(e))
            self._copy_field(e, field)
        return True  # the button has the click (not the card underneath)

    def _show_button_tip(self):
        """The tooltip of the copy button under the mouse: just what it copies (the username; the
        password only while it's shown with the eye in the details, else dots), kept to that button's area."""
        viewport = self.table.viewport()
        pos = viewport.mapFromGlobal(QCursor.pos())
        hit = self._button_at(pos)
        if hit is None:
            return
        e, field, tip = hit
        shown = self.model.is_revealed(e) or (self.notes.revealed and self.notes.entry is e)
        value = {"username": e["username"], "password": e["password"] if shown else MASK,
                 "totp": totp.code(e["totp"])[0] if field == "totp" else "", "favourite": tip}[field]
        rect = next(r for f, _i, _t, r in self.delegate.actions(e, self.delegate.row_rect(self.table.visualRect(
            self.model.index(self.model.entries.index(e), 0)))) if f == field)
        if field == "password" and shown and value:  # colour-coded, like the details
            dark_tip = QToolTip.palette().color(QPalette.ToolTipBase).lightness() < 128
            value = (f'<span style="font-family:\'{MONO_FAMILY}\'; font-size:14px">'
                     f'{password_html(value, setting("color_passwords", True), dark_tip)}</span>')
        else:
            value = value.replace("&", "&amp;").replace("<", "&lt;")
        QToolTip.showText(viewport.mapToGlobal(rect.bottomLeft()) + QPoint(0, 4), f"<qt>{value}</qt>", viewport, rect)

    def _clear_done(self, done):
        if self.delegate.done == done:
            self.delegate.done = None
            self.table.viewport().update()

    def zoom_list_text(self, step):
        i = LIST_TEXT_SIZES.index(self._list_text) + step
        self.set_list_text_size(LIST_TEXT_SIZES[max(0, min(len(LIST_TEXT_SIZES) - 1, i))])

    # The Sort menu: what to sort by, then which way
    SORTS = [("Name", EntryModel.TITLE), ("Username", EntryModel.USERNAME), ("Website", EntryModel.WEBSITE),
             ("Folder", EntryModel.FOLDER), ("Date modified", EntryModel.MODIFIED), ("Date created", EntryModel.CREATED)]

    def _saved_sort(self):
        try:
            column, order = (int(x) for x in str(setting("list_sort", "")).split(","))
        except ValueError:
            return EntryModel.TITLE, Qt.AscendingOrder
        if column not in dict(self.SORTS).values() or order not in (0, 1):
            return EntryModel.TITLE, Qt.AscendingOrder
        return column, Qt.SortOrder(order)

    def _sort_menu(self):
        menu = CheckableMenu(parent=self)  # ticks the current choices
        column, order = self.model.sort_column, self.model.sort_order
        for name, c in self.SORTS:
            action = Action(name, checkable=True)
            action.setChecked(c == column)
            action.triggered.connect(lambda _=False, c=c: self.sort_by(c, self.model.sort_order))
            menu.addAction(action)
        menu.addSeparator()
        for name, o in (("Ascending (A–Z, oldest first)", Qt.AscendingOrder),
                        ("Descending (Z–A, newest first)", Qt.DescendingOrder)):
            action = Action(name, checkable=True)
            action.setChecked(o == order)
            action.triggered.connect(lambda _=False, o=o: self.sort_by(self.model.sort_column, o))
            menu.addAction(action)
        menu.exec(self.sort_btn.mapToGlobal(QPoint(0, self.sort_btn.height())), ani=False)

    def sort_by(self, column, order):
        settings.setValue("list_sort", f"{column},{order.value}")
        current = self.current_entry()
        self.table.sortByColumn(column, order)
        self.refresh(select_uuid=current["uuid"] if current else None)

    def _scale_header(self, k):
        """The titles, search box and buttons around the list follow the list text size too, so the page
        stays in proportion (a small list under full-size buttons looked odd)."""
        parts = [self.list_title, self.count, self.save_status, self.search, self.sort_btn,
                 self.new_btn, self.notes.title, self.notes.path, self.notes.modified]
        self.tree.setIconSize(QSize(round(16 * k), round(16 * k)))  # folder icons
        if not hasattr(self, "_header_base"):  # their normal sizes, measured once
            for part in parts:
                part.ensurePolished()
            self._header_base = {
                part: (part.fontInfo().pixelSize(),
                       part.height() if part.minimumHeight() == part.maximumHeight() else None,
                       part.iconSize() if hasattr(part, "iconSize") else None)
                for part in parts}
        for part, (px, fixed_height, icon_size) in self._header_base.items():
            font = QFont(part.font())
            font.setPixelSize(max(9, round(px * k)))
            part.setFont(font)
            if fixed_height:
                part.setFixedHeight(round(fixed_height * k))
            if icon_size is not None:
                part.setIconSize(QSize(round(icon_size.width() * k), round(icon_size.height() * k)))

    def set_list_text_size(self, size):
        """Text size (% of normal) of the entry list, folder tree and notes; rows grow with it."""
        size = min(LIST_TEXT_SIZES, key=lambda s: abs(s - size))
        settings.setValue("list_text_size", size)
        self._list_text = size
        k = size / 100
        self.delegate.font.setPixelSize(round(13 * k))
        self.delegate.italic.setPixelSize(round(13 * k))
        self.delegate.small.setPixelSize(round(13 * k))
        self.delegate.mono.setPixelSize(round(13 * k))
        self.set_density(self._density)  # row height and icons follow the text
        # The UI library draws folder names in a fixed 13 px font unless an item carries its own.
        self._tree_font = getFont(round(13 * k))
        self._set_tree_icons()  # also gives every folder item the font
        self.notes.set_notes_px(round(self._notes_base_px * k))
        self.notes.set_text_scale(k)
        self._scale_header(k)
        self.table.viewport().update()
        self.listTextChanged.emit(size)

    def _scroll_gutters(self, *_):
        """The UI library's scrollbars float over the rows, so text showed around them: keep a strip
        free for each scrollbar that's showing (12 px, 1 px in from the edge of the borderless list)."""
        # Its style sheet sets the table's margins, so this goes there too.
        t = self.table
        gutters = (13 if t.verticalScrollBar().maximum() > 0 else 0, 13 if t.horizontalScrollBar().maximum() > 0 else 0)
        if gutters != getattr(self, "_gutters", None):
            self._gutters = gutters
            self._table_qss()

    def _table_qss(self):
        """The list's own style: room for its scrollbar (the list has no border of its own)."""
        right, bottom = getattr(self, "_gutters", (0, 0))
        qss = (f"QTableView {{ padding-right: {right}px; padding-bottom: {bottom}px; border: none;"
               f" background: transparent; }}")
        setCustomStyleSheet(self.table, qss, qss)

    def set_density(self, name):
        self._density = name
        row_height, tile = CARD_DENSITIES.get(name, CARD_DENSITIES["Comfortable"])
        k = getattr(self, "_list_text", 100) / 100  # rows and icons grow with the list text size
        self.table.verticalHeader().setDefaultSectionSize(round(row_height * k))
        self.delegate.tile = round(tile * k)
        # The folder tree follows the same density (and text size), but never clips its text.
        font_px = round(13 * k)
        self._folder_row = max(round(FOLDER_ROW_HEIGHTS.get(name, 33) * k), font_px + 8)
        self.folder_delegate.row_height = self._folder_row
        if hasattr(self, "model"):
            self._set_tree_icons()  # applies the row height to every folder

    def set_colorize(self, on):
        self.delegate.colorize = on
        self.notes.set_revealed(self.notes.revealed)
        self.table.viewport().update()

    def set_stripes(self, on):
        self.delegate.stripes = on
        self.table.viewport().update()

    def _on_reveal(self, on):
        """Show passwords: in the details, the key buttons' tooltips and (with the details below the
        list) its password column, for every entry."""
        self.model.set_show_passwords(on)
        self.reveal.setIcon(FIF.HIDE if on else FIF.VIEW)
        self.reveal.setToolTip("Hide passwords" if on else "Show passwords")
        self.notes.set_revealed(on)
        if self.editor is not None:
            self.editor.password.set_revealed(on)

    def toggle_password(self):
        """Shows or hides the selected entry's password: in the details and the list's password column."""
        e = self.current_entry()
        if not e:
            return
        on = not self.notes.revealed
        self.notes.set_revealed(on)
        if not self.model.show_passwords and (id(e) in self.model.revealed) != on:
            self.model.toggle_revealed(e)

    def change_password(self):
        """Edits the selected entry with a newly generated password (from its health advice)."""
        if self.below:  # in the pop-up editor
            e = self.current_entry()
            if e and self._editable():
                self._open_editor(entry=e, generate=True)
            return
        self.edit_entry()
        if self.editor is not None and self.editor.entry is not None:
            self.editor._generate()
            self.editor.password.setFocus()

    def toggle_favourite(self, e=None):
        e = e or self.current_entry()
        if not e or not self._editable():
            return
        on = not e["favourite"]
        self.window().saver.submit(Op("favourite", e["uuid"], fields={"on": on}, title=e["title"]),
                                   f"{'Starring' if on else 'Unstarring'} “{e['title']}”")

    def _on_double_click(self, index):
        """Double-clicking an entry copies its password, then (Settings → Minimise after copying) gets
        Vault out of the way, ready to paste. No password: opens it for editing. In the columns, a
        username or password copies that (an empty one does nothing), and a website opens."""
        self.table.selectRow(index.row())
        e = self.model.data(index, Qt.UserRole)
        col = index.column()
        if col in (EntryModel.USERNAME, EntryModel.PASSWORD):
            self._copy_field(e, "username" if col == EntryModel.USERNAME else "password")
        elif col == EntryModel.WEBSITE and e["url"]:
            self.open_url()
        elif e["password"]:
            self._copy_field(e, "password")
        else:
            self.edit_entry()

    def _key_copy(self, field):
        """U, P or T in the list: copies the selected entry's username, password or 2FA code as its card's
        button does (a tick on the button, then Settings → Minimise after copying)."""
        e = self.current_entry()
        if e:
            self._copy_field(e, field)

    def _copy_field(self, e, field):
        """Copies an entry's username, password or 2FA code (from its card's buttons, a double-click or
        U, P and T): a tick on its button (and its cell, in the columns) for a moment, then Settings →
        Minimise after copying."""
        if field == "totp":
            value, label = (totp.code(e["totp"])[0] if e["totp"] else ""), "2FA code"
        else:
            value, label = e[field], field.capitalize()
        if not value:
            return
        minimise = setting("minimise_on_copy", True)
        self.window().copy_secret(value, label, notify=not minimise)
        self.delegate.done = (e["uuid"], field)
        self.table.viewport().update()
        QTimer.singleShot(1500, lambda done=self.delegate.done: self._clear_done(done))
        if minimise:
            self._minimise_after_release()

    def _minimise_after_release(self, tries=50):
        """Minimises once the double-click's mouse button is back up (or after a second at most).
        Minimised while it was still down, the list never saw it come up (macOS), so moving the mouse
        then dragged the row: its picture stuck in the middle of the screen."""
        if QApplication.mouseButtons() != Qt.NoButton and tries:
            QTimer.singleShot(20, lambda: self._minimise_after_release(tries - 1))
        else:
            self.window().showMinimized()

    # ---- editing

    def focus_search(self):
        self.window().switchTo(self)
        self.search.setFocus(Qt.ShortcutFocusReason)
        self.search.selectAll()

    def focus_results(self):
        """From the search box to the first result, ready for Ctrl+C / Ctrl+B / Enter."""
        if self.search_timer.isActive():  # still typing: filter now
            self.search_timer.stop()
            self.refresh()
        if self.model.rowCount():
            self.table.setFocus(Qt.ShortcutFocusReason)
            self.table.selectRow(0)

    def _editable(self):
        return self.db is not None and self.db.writable

    def new_entry(self):
        if not self._editable():
            return
        folder = None if self.folder in (self.db.bin_id, *VIEWS) else self.folder
        if folder and any(f["id"] == folder and f["in_bin"] for f in self.db.folders):
            folder = None
        self._open_editor(folder_id=folder, note=self.folder == NOTES)

    def edit_entry(self):
        e = self.current_entry()
        if not e or not self._editable():
            return
        if self.editor is not None and self.editor.entry is not None and self.editor.entry["uuid"] == e["uuid"]:
            self.editor.title.setFocus()  # already editing it
            return
        self._open_editor(entry=e)

    # ---- editing in the details pane

    def _open_editor(self, entry=None, folder_id=None, note=False, generate=False):
        """Shows the form in the details pane, beside the list (any other edit is finished first); with
        the details below the list, in a pop-up instead (the strip is too short for it)."""
        if self.below:
            self._open_popup_editor(entry, folder_id, note, generate)
            return
        if not self.leave_editor():
            return
        self._show_page()
        pane = EntryEditPane(self.details, self.db, entry, folder_id, note)
        pane.password.set_revealed(self.model.show_passwords)  # follows the title bar's Show passwords
        pane.saved.connect(lambda: self._editor_saved(pane))
        pane.cancelled.connect(lambda: self._close_editor(pane))
        current = self.current_entry()
        self._editor_anchor = current["uuid"] if current else None
        self.editor = pane
        self.details.addWidget(pane)
        self.details.setCurrentWidget(pane)
        pane.title.setFocus()
        if entry is None:
            pane.title.selectAll()

    def _close_editor(self, pane):
        if pane is not self.editor:
            return
        self.editor = None
        self.details.setCurrentWidget(self.notes)
        self.details.removeWidget(pane)
        pane.deleteLater()
        if self.isVisible():
            self.table.setFocus()

    def _open_popup_editor(self, entry, folder_id, note, generate):
        editor = self._popup = EntryEditor(self.window(), self.db, entry, folder_id, note)
        if entry is not None:  # a new entry's generated password shows anyway
            editor.show_pw.setChecked(self.model.show_passwords)
        if generate:  # from its health advice: a new password
            editor._generate()
            editor.password.setFocus()
        op = editor.op if editor.exec() else None
        self._popup = None
        editor.deleteLater()
        if self.db is not None:  # (not locked meanwhile: that closes it, unsaved)
            self._submit_edit(entry, op)

    def _editor_saved(self, pane):
        op, entry = pane.op, pane.entry
        self._close_editor(pane)
        self._submit_edit(entry, op)

    def _submit_edit(self, entry, op):
        """Saves what the editor (pane or pop-up) changed, if anything."""
        if op is None:  # nothing changed
            return
        if entry is None:
            self.window().saver.submit(op, f"New {'note' if op.fields.get('note') else 'entry'} “{op.title}”")
            self.load(self.db, keep_state=True, select_uuid=op.uuid)
            self._auto_icon(op)
        else:
            self.window().saver.submit(op, f"Edit of “{entry['title']}”")
            if "url" in op.fields:
                self._auto_icon(op)

    def leave_editor(self):
        """Before showing something else in the details pane: asks whether to save changes being made.
        False if they couldn't be saved (e.g. no title), so the form stays."""
        pane = self.editor
        if pane is None:
            return True
        if pane.has_changes():
            title = pane.title.text().strip() or (pane.entry["title"] if pane.entry else "the new entry")
            box = MessageBox("Save changes?", f"You've changed “{title}” and haven't saved it yet.", self.window())
            box.yesButton.setText("Save")
            box.cancelButton.setText("Don't save")
            if box.exec():
                pane.save()
                return self.editor is None  # saved (else the form shows what's wrong)
        self._close_editor(pane)
        return True

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
        if parent in VIEWS:
            parent = None
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

    def change_folder_icon(self, folder_id):
        record = self._folder_record(folder_id)
        if not record or not self._editable():
            return
        dialog = IconPickerDialog(self.window(), f"Icon for folder “{record['name']}”",
                                  record.get("icon", (store.FOLDER_ICON, None)), "Plain folder", store.FOLDER_ICON)
        if dialog.exec() and dialog.choice:
            self.window().saver.submit(Op("folder_icon", folder_id, title=record["name"], **dialog.choice),
                                       f"Icon of folder “{record['name']}”")

    def change_entry_icon(self):
        e = self.current_entry()
        if not e or not self._editable():
            return
        dialog = IconPickerDialog(self.window(), f"Icon for “{e['title']}”", e["icon"], "Default (letter)", 0)
        if dialog.exec() and dialog.choice:
            self.window().saver.submit(Op("set_icon", e["uuid"], title=e["title"], **dialog.choice),
                                       f"Icon of “{e['title']}”")

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
        if not self._editable() or target == NOTES:  # (the tree doesn't offer Notes as a drop target)
            return
        by_id = {e["uuid"]: e for e in self.db.entries}
        if target == FAVOURITES:  # dropped on Favourites: starred, and left in their folders
            starring = [by_id[u] for u in uuids if u in by_id and not by_id[u]["favourite"]]
            names = ", ".join(f"“{e['title']}”" for e in starring[:3]) + (" …" if len(starring) > 3 else "")
            self.window().saver.submit_many(
                [Op("favourite", e["uuid"], fields={"on": True}, title=e["title"]) for e in starring],
                f"Starring {names}")
            return
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
        if item is None or not self._editable() or item.data(0, Qt.UserRole) in (*VIEWS, FOLDERS_HEADING):
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
            menu.addAction(Action(icon("PHOTO", "PALETTE"), "Change icon…",
                                  triggered=lambda: self.change_folder_icon(folder_id)))
            menu.addAction(Action(icon("MOVE", "FOLDER"), "Move to…", triggered=lambda: self.move_folder(folder_id)))
            menu.addSeparator()
            permanent = in_bin or not self.db.recycle_bin_enabled
            menu.addAction(Action(FIF.DELETE, "Delete permanently…" if permanent else "Move to Recycle Bin…",
                                  triggered=lambda: self.delete_folder(folder_id)))
        if is_bin:
            empty = Action(FIF.DELETE, "Empty Recycle Bin…", triggered=self.empty_recycle_bin)
            empty.setEnabled(any(e["in_bin"] for e in self.db.entries) or
                             any(f["parent"] == folder_id for f in self.db.folders))
            menu.addAction(empty)
        if menu.actions():
            menu.exec(self.tree.viewport().mapToGlobal(pos), ani=False)

    def empty_recycle_bin(self):
        """Permanently deletes everything in the Recycle Bin, after asking. One change, so Undo
        brings it all back."""
        bin_id = self.db.bin_id
        if not bin_id or not self._editable():
            return
        entries = [e for e in self.db.entries if e["folder_id"] == bin_id]  # directly in the bin
        folders = [f for f in self.db.folders if f["parent"] == bin_id]    # deleting these takes their contents
        total_entries = sum(e["in_bin"] for e in self.db.entries)
        if not entries and not folders:
            return
        parts = [f"{total_entries} entr{'y' if total_entries == 1 else 'ies'}"] if total_entries else []
        if folders:
            nested = sum(1 for f in self.db.folders if f["in_bin"] and f["id"] != bin_id)
            parts.append(f"{nested} folder{'s' if nested != 1 else ''}")
        what = " and ".join(parts)
        box = MessageBox("Empty Recycle Bin?", f"{what} will be deleted permanently.", self.window())
        box.yesButton.setText("Empty Recycle Bin")
        box.cancelButton.setText("Cancel")
        if not box.exec():
            return
        ops = [Op("delete", e["uuid"], title=e["title"]) for e in entries]
        ops += [Op("folder_delete", f["id"], title=f["name"]) for f in folders]
        self.window().saver.submit_many(ops, "Emptying the Recycle Bin")
        self.window().undo_toast("Recycle Bin emptied", f"{what} deleted.")

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
        if not index.isValid():  # empty space below the entries: New entry (New note in Notes)
            if self._editable():  # (an edit in progress is finished first, as with the button)
                kind = "note" if self.folder == NOTES else "entry"
                menu = RoundMenu(parent=self)
                action = Action(FIF.ADD, f"New {kind}", triggered=self.new_entry)
                action.setShortcut(QKeySequence("Ctrl+N"))
                menu.addAction(action)
                menu.exec(self.table.viewport().mapToGlobal(pos), ani=False)
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
        menu.addSeparator()
        shown = self.notes.revealed
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
            menu.addAction(Action(star_icon(not e["favourite"]),
                                  "Remove from Favourites" if e["favourite"] else "Add to Favourites",
                                  triggered=self.toggle_favourite))
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
            menu.addAction(Action(icon("PHOTO", "PALETTE"), "Change icon…", triggered=self.change_entry_icon))
            permanent = e["in_bin"] or not self.db.recycle_bin_enabled
            delete = Action(FIF.DELETE, "Delete permanently…" if permanent else "Move to Recycle Bin…",
                            triggered=self.delete_entry)
            delete.setShortcut(QKeySequence("Del"))
            menu.addAction(delete)
        menu.addSeparator()
        history = Action(icon("HISTORY"), "History…", triggered=self.show_history)
        history.setShortcut(QKeySequence("Ctrl+H"))
        menu.addAction(history)
        menu.exec(self.table.viewport().mapToGlobal(pos), ani=False)

    def show_history(self):
        """Earlier versions of the selected entry; restore one, or copy an old password."""
        e = self.current_entry()
        if not e or self.db is None:
            return
        dialog = HistoryDialog(self.window(), e, self.db.history(e["uuid"]), self._editable())
        if dialog.exec() and dialog.op:
            self.window().saver.submit(dialog.op, f"Restore of “{e['title']}”")


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
    return f"font-family: '{MONO_FAMILY}', monospace; font-size: {size}px;"


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
                fmt = QTextCharFormat()
                if kind in PASSWORD_COLORS:
                    fmt.setForeground(QColor(PASSWORD_COLORS[kind][dark]))
                    fmt.setFontWeight(QFont.DemiBold)
                else:
                    fmt.setForeground(QColor(PASSWORD_PLAIN[dark]))
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
        self.close_btn = TransparentToolButton(FIF.CLOSE)
        self.close_btn.setToolTip("Hide generator options")
        self.close_btn.clicked.connect(self.hide)
        self.close_btn.clicked.connect(self.closed)
        top.addWidget(self.close_btn)
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
        self.separator.addItems(["-", ".", "_", "space", "none"])
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
            separator = {"space": " ", "none": ""}.get(self.separator.currentText(), self.separator.currentText())
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


class EntryForm:
    """The entry form (title, username, password with generator, website, 2FA, folder, notes) and its
    checks, shared by the pop-up editor (EntryEditor) and the one in the details pane (EntryEditPane).
    The host provides viewLayout (where the form goes), widget (the area username suggestions float
    in) and yesButton (Enter in a field clicks it). After validate(), `op` holds the change (or None)."""

    in_pane = False  # in the details pane: the notes take the spare height, and the form scrolls there

    def _build_form(self, db, entry=None, folder_id=None, note=False):
        self.db = db
        self.entry = entry
        self.op = None
        self._generated = None  # (value, bits) of the last generated password
        raw = entry["raw"] if entry else {f: "" for f in store.FIELDS}
        self.note = entry["note"] if entry else note  # a secure note: just a title, folder and the text
        kind = "note" if self.note else "entry"

        self.viewLayout.setSpacing(8)
        self.heading = SubtitleLabel(f"Edit {kind}" if entry else f"New {kind}")
        self.viewLayout.addWidget(self.heading)

        # The fields scroll if the window is too short to show them all (nothing gets squashed).
        self.body = QWidget(objectName="formBody")
        # Only the form itself: a plain "background: transparent" reached its tooltips too (drawn black)
        self.body.setStyleSheet("QWidget#formBody { background: transparent; }")
        self.form = QVBoxLayout(self.body)
        self.form.setContentsMargins(0, 0, 10, 0)  # room for the scroll bar
        self.form.setSpacing(6)
        self.scroll = ScrollArea()
        self.scroll.setFocusPolicy(Qt.NoFocus)  # clicking the form's background mustn't steal focus from fields
        self.scroll.setWidgetResizable(True)
        self.scroll.enableTransparentBackground()
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.scrollDelagate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        self.scroll.setWidget(self.body)
        self.viewLayout.addWidget(self.scroll, 1 if self.in_pane else 0)

        self.title = LineEdit()
        self.title.setText(raw["title"])
        self.title.setPlaceholderText("e.g. Wi-Fi details" if self.note else "e.g. GitHub")
        self.username = LineEdit()
        self.username.setText(raw["username"])
        self.url = LineEdit()
        self.url.setText(raw["url"])
        self.url.setPlaceholderText("https://")
        self.password = ColoredPasswordEdit()
        self.password.setText(raw["password"])
        self.password.textChanged.connect(self._update_strength)

        self._field("Title", self.title)
        # The login fields, in a box of their own: hidden for a note (unless it has a login after all,
        # e.g. one added in KeePassXC, which mustn't be hidden while it's edited)
        self.login_box = QWidget()
        outer, self.form = self.form, QVBoxLayout(self.login_box)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(6)
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
        if self.in_pane:  # the title bar's Show passwords button shows or hides it instead
            self.show_pw.hide()
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
        if self.in_pane:  # there's room: the options show from the start (Generate makes a password)
            self.generator.close_btn.hide()
            self.generator.length_label.setText(str(self.generator.length.value()))
            self.generator.words_label.setText(str(self.generator.word_count.value()))
        else:
            self.generator.hide()
        self.form.addWidget(self.generator)

        self._field("Website", self.url)

        self.otp = LineEdit()
        self.otp.setText(raw["otp"])
        self.otp.setPlaceholderText("Optional: the site's 2FA secret key or otpauth:// link")
        self._field("2FA (authenticator code)", self.otp)
        self.form = outer
        self.form.addWidget(self.login_box)
        self.login_box.setVisible(not self.note or any(raw[f] for f in ("username", "password", "url", "otp")))

        self.folder = ComboBox()
        current = entry["folder_id"] if entry else folder_id
        choices = [("Top level (no folder)", None)] + [(" › ".join(f["path"]), f["id"]) for f in db.folders
                                       if not f["in_bin"] or f["id"] == current]
        for text, folder in choices:
            self.folder.addItem(text, userData=folder)
        ids = [folder for _, folder in choices]
        self.folder.setCurrentIndex(ids.index(current) if current in ids else 0)
        self._field("Folder", self.folder)

        self.form.addWidget(caption("Notes"))
        self.notes = PlainTextEdit()
        self.notes.setPlainText(raw["notes"])
        if self.in_pane:  # the notes get whatever height is left
            self.notes.setMinimumHeight(120)
            self.form.addWidget(self.notes, 1)
        else:
            self.notes.setFixedHeight(76)
            self.form.addWidget(self.notes)

        self.error = CaptionLabel("")
        self.error.setTextColor("#d13438", "#ff99a4")
        self.error.hide()
        self.viewLayout.addWidget(self.error)

        for line in (self.title, self.username, self.password, self.url):
            line.returnPressed.connect(self.yesButton.click)
        if entry is None and not self.note:  # new entries start with a generated password
            self._generate()
        self._update_strength()

    def _field(self, label, widget):
        self.form.addWidget(caption(label))
        self.form.addWidget(widget)

    # ---- username suggestions
    # A dropdown list that floats over the fields below the Username field, so the dialog doesn't
    # change size. It's a child of the dialog, not a separate pop-up window: a pop-up captures the
    # next click anywhere, so the first click on Cancel only closed it.

    SUGGESTION_ROWS = 6  # visible at once; the rest scroll
    SUGGESTION_ROW_HEIGHT = 30

    def _setup_username_suggestions(self):
        counts = Counter(e["raw"]["username"] for e in self.db.entries
                         if not e["in_bin"] and e["raw"]["username"] and not e["raw"]["username"].startswith("{REF:"))
        self._usernames = [name for name, _ in counts.most_common()]  # most used first
        self.suggestions = ListWidget(self.widget)  # floats inside the dialog's card
        self.suggestions.setFocusPolicy(Qt.NoFocus)  # typing stays in the Username field
        self.suggestions.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.suggestions.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.suggestions.scrollDelegate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        # Pick on press (like a dropdown), so nothing that happens before release can lose the click.
        self.suggestions.itemPressed.connect(lambda item: self._use_suggestion(item.text()))
        setCustomStyleSheet(  # opaque, since it covers the fields underneath
            self.suggestions,
            "ListWidget { border: 1px solid rgba(0, 0, 0, 0.14); border-radius: 6px; background: #ffffff; }",
            "ListWidget { border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 6px; background: #2c2c2c; }")
        shadow = QGraphicsDropShadowEffect(self.suggestions)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.suggestions.setGraphicsEffect(shadow)
        self.suggestions.hide()
        if not self._usernames:
            return
        self.username.textEdited.connect(lambda _: self._update_suggestions())
        self.username.installEventFilter(self)
        self.scroll.verticalScrollBar().valueChanged.connect(lambda _: self._hide_suggestions())

    def _update_suggestions(self):
        text = self.username.text().strip().lower()
        # Every matching username; typing more narrows the list. Each word (or *-separated part)
        # can appear anywhere in the name, in any order: "simon", "sim*mail", "simon gmail".
        parts = [p for p in re.split(r"[\s*]+", text) if p]
        matches = [n for n in self._usernames
                   if all(p in n.lower() for p in parts) and n.lower() != text]
        if not matches or not self.username.hasFocus():
            self._hide_suggestions()
            return
        self.suggestions.clear()
        self.suggestions.addItems(matches)
        for i in range(self.suggestions.count()):
            self.suggestions.item(i).setSizeHint(QSize(0, self.SUGGESTION_ROW_HEIGHT))
        top_left = self.username.mapTo(self.widget, QPoint(0, self.username.height() + 2))
        rows = min(len(matches), self.SUGGESTION_ROWS)
        room = self.widget.height() - top_left.y() - 16  # stay inside the editor
        height = max(min(rows * self.SUGGESTION_ROW_HEIGHT + 14, room), 2 * self.SUGGESTION_ROW_HEIGHT + 14)
        self.suggestions.setGeometry(top_left.x(), top_left.y(), self.username.width(), height)
        self.suggestions.scrollToTop()
        self.suggestions.show()
        self.suggestions.raise_()

    def _hide_suggestions(self):
        self.suggestions.hide()

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
                # Hide shortly after leaving the field, but not while the mouse is on the list.
                QTimer.singleShot(150, lambda: self.username.hasFocus() or self.suggestions.underMouse()
                                  or self._hide_suggestions())
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
        if self.in_pane:  # the pane's layout gives the form the height it has
            return
        window = self.parent().window() if self.parent() else None
        available = (window.height() if window else 800) - 196  # title, buttons and margins
        self.scroll.setFixedHeight(max(200, min(needed, available)))

    def _use_generated(self, value, bits):
        self._generated = (value, bits)
        if not self.in_pane:  # the pop-up shows a new password; the pane follows Show passwords
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
            self.error.setText(f"Give the {'note' if self.note else 'entry'} a title.")
            self.error.show()
            self.title.setFocus()
            return False
        otp_error = totp.validate(self.otp.text())
        if otp_error and self.otp.text().strip() != self.entry_raw("otp"):
            self.error.setText(otp_error)
            self.error.show()
            self.otp.setFocus()
            return False
        values = self._values()
        folder = self.folder.currentData()
        if self.entry is None:
            if self.note:
                values["note"] = True  # tagged as a note when it's created
            self.op = Op("create", uuidlib.uuid4().hex, fields=values, all_fields=values, folder=folder,
                         title=values["title"])
        else:
            changed = {k: v for k, v in values.items() if v != self.entry["raw"][k]}
            if changed or folder != self.entry["folder_id"]:
                self.op = Op("update", self.entry["uuid"], fields=changed, all_fields=values, folder=folder,
                             base_mtime=self.entry["base_mtime"], base_version=store.base_version(self.entry),
                             title=values["title"])
        return True

    def _values(self):
        return dict(title=self.title.text().strip(), username=self.username.text(), password=self.password.text(),
                    url=self.url.text().strip(), notes=self.notes.toPlainText(), otp=self.otp.text().strip())

    def has_changes(self):
        """Anything typed or changed (a new entry's generated password alone doesn't count)."""
        values = self._values()
        if self.entry is None:
            return any(values[k] for k in ("title", "username", "url", "notes", "otp"))
        return (any(values[k] != self.entry["raw"][k] for k in values)
                or self.folder.currentData() != self.entry["folder_id"])


class EntryEditor(EntryForm, MessageBoxBase):
    """Create or edit an entry in a pop-up (used from Password health, and with the details below the
    list). Ctrl+S saves, Esc cancels. After exec(), `op` holds the change (or None)."""

    def __init__(self, parent, db, entry=None, folder_id=None, note=False):
        MessageBoxBase.__init__(self, parent)
        self._build_form(db, entry, folder_id, note)
        self.yesButton.setText("Save" if entry else "Add note" if note else "Add entry")
        self.yesButton.setToolTip(shortcut_text("Save (Ctrl+S)"))
        local_shortcut("Ctrl+S", self, self.yesButton.click)
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(560)
        self._fit()
        self.title.setFocus()


class EntryEditPane(EntryForm, QWidget):
    """Create or edit an entry in the details pane, beside the list: the same form as the pop-up, with
    Save and Cancel at the bottom (Ctrl+S saves, Esc cancels). Emits saved (op in `op`) or cancelled."""

    saved = Signal()
    cancelled = Signal()
    in_pane = True

    def __init__(self, parent, db, entry=None, folder_id=None, note=False):
        QWidget.__init__(self, parent)
        self.viewLayout = QVBoxLayout(self)
        self.viewLayout.setContentsMargins(30, 20, 26, 14)
        self.widget = self  # username suggestions float over the pane
        self.yesButton = PrimaryPushButton("Save" if entry else "Add note" if note else "Add entry")
        self.cancelButton = PushButton("Cancel")
        self._build_form(db, entry, folder_id, note)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        for button in (self.cancelButton, self.yesButton):
            button.setMinimumWidth(110)
            buttons.addWidget(button)
        self.viewLayout.addSpacing(4)
        self.viewLayout.addLayout(buttons)
        self.yesButton.setToolTip(shortcut_text("Save (Ctrl+S)"))
        self.cancelButton.setToolTip("Cancel (Esc)")
        self.yesButton.clicked.connect(self.save)
        self.cancelButton.clicked.connect(self.cancelled)
        local_shortcut("Ctrl+S", self, self.save)
        # Esc closes the username suggestions first, if they're showing
        local_shortcut("Esc", self, lambda: self._hide_suggestions() if self.suggestions.isVisible()
                       else self.cancelled.emit())
        self._fit()

    def save(self):
        self.op = None
        if self.validate():
            self.saved.emit()


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


class IconPickerDialog(MessageBoxBase):
    """Choose an entry's or folder's icon: one of KeePass's standard icons (as KeePass and KeePassXC
    show them), the default, or an image file. After exec(), `choice` holds the Op fields to apply."""

    COLUMNS = 12

    def __init__(self, parent, title, current, default_label, default_id):
        super().__init__(parent)
        self.choice = None
        self.default_id = default_id
        current_id, current_custom = current
        self.viewLayout.setSpacing(10)
        self.viewLayout.addWidget(SubtitleLabel(title))
        self.viewLayout.addWidget(caption("KeePass's standard icons: they show the same in KeePass and KeePassXC."))

        grid = QGridLayout()
        grid.setSpacing(4)
        self.buttons = QButtonGroup(self)
        for number, path in sorted(self._standard_icons().items()):
            button = TransparentToggleToolButton(QIcon(str(path)))
            button.setFixedSize(40, 40)
            button.setIconSize(QSize(24, 24))
            button.setToolTip(path.stem.split("_", 1)[-1].replace("_", " "))
            button.setChecked(current_custom is None and number == current_id and number != default_id)
            self.buttons.addButton(button, number)
            grid.addWidget(button, number // self.COLUMNS, number % self.COLUMNS)
        self.buttons.idClicked.connect(self._standard_chosen)
        self.viewLayout.addLayout(grid)

        row = QHBoxLayout()
        default = PushButton(default_label)
        default.clicked.connect(self._default_chosen)
        row.addWidget(default)
        image = PushButton(icon("PHOTO", "FOLDER"), "Use an image file…")
        image.clicked.connect(self._image_chosen)
        row.addWidget(image)
        row.addStretch(1)
        self.chosen = caption("")
        row.addWidget(self.chosen)
        self.viewLayout.addLayout(row)
        self.yesButton.setText("Apply")
        self.cancelButton.setText("Cancel")
        self.yesButton.setEnabled(False)  # until something is chosen
        self.widget.setMinimumWidth(self.COLUMNS * 44 + 60)

    @staticmethod
    def _standard_icons():
        icons = {}
        for path in STANDARD_ICON_DIR.glob("C*.svg"):
            match = re.match(r"C(\d+)_", path.name)
            if match:
                icons[int(match.group(1))] = path
        return icons

    def _set(self, choice, label):
        self.choice = choice
        self.chosen.setText(label)
        self.yesButton.setEnabled(True)

    def _uncheck_all(self):
        self.buttons.setExclusive(False)
        for button in self.buttons.buttons():
            button.setChecked(False)
        self.buttons.setExclusive(True)

    def _standard_chosen(self, number):
        self._set({"icon": "", "icon_id": number}, f"Chosen: {self.buttons.button(number).toolTip()}")

    def _default_chosen(self):
        self._uncheck_all()
        self._set({"icon": "", "icon_id": self.default_id}, "Chosen: default")

    def _image_chosen(self):
        path = ask_path(self, "Choose an icon image", str(Path.home()),
                        "Images (*.png *.jpg *.jpeg *.ico *.bmp *.gif *.svg)")
        if not path:
            return
        try:
            png = favicon._to_png(Path(path).read_bytes())
        except OSError:
            png = None
        if not png:
            InfoBar.warning("Icon", "That file isn't an image Vault can use.", orient=Qt.Horizontal,
                            isClosable=True, position=InfoBarPosition.TOP_RIGHT, duration=3000, parent=self.window())
            return
        self._uncheck_all()
        self._set({"icon": png, "icon_name": Path(path).stem}, f"Chosen: {Path(path).name}")


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


class HistoryDialog(MessageBoxBase):
    """An entry's earlier versions (newest first): see what changed, copy an old password, or restore a
    version. Restoring is an ordinary edit, so it can be undone and the current version goes into history."""

    WHEN, USERNAME, PASSWORD, CHANGED = range(4)
    LABELS = {"title": "Title", "username": "Username", "password": "Password", "url": "Website", "notes": "Notes"}

    def __init__(self, parent, entry, versions, writable):
        super().__init__(parent)
        self.entry, self.versions, self.op = entry, versions, None
        self.viewLayout.setSpacing(10)
        self.viewLayout.addWidget(SubtitleLabel(f"History of “{entry['title']}”"))
        self.viewLayout.addWidget(caption(
            "Earlier versions, newest first. Restoring one keeps the current version in history, and can be undone."
            if versions else "No earlier versions yet. Each time you change this entry, the old version is kept here."))
        self.table = TableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Saved", "Username", "Password", "Changed"])
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        for col, width in ((self.WHEN, 150), (self.USERNAME, 170), (self.PASSWORD, 220)):
            self.table.setColumnWidth(col, width)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setRowCount(len(versions))
        newer = entry["raw"]
        for row, version in enumerate(versions):
            changed = [label for key, label in self.LABELS.items() if version[key] != newer[key]]
            when = version["modified"].strftime("%b %d, %Y %H:%M") if version["modified"] else ""
            for col, text in ((self.WHEN, when), (self.USERNAME, version["username"]),
                              (self.CHANGED, ", ".join(changed) or "No visible change")):
                self.table.setItem(row, col, QTableWidgetItem(text))
            newer = version
        self.table.setVisible(bool(versions))
        self.viewLayout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.reveal = TransparentTogglePushButton(FIF.VIEW, "Show passwords")
        self.reveal.toggled.connect(self._show_passwords)
        self.copy = TransparentPushButton(FIF.COPY, "Copy password")
        self.copy.clicked.connect(self._copy)
        for button in (self.reveal, self.copy):
            button.setVisible(bool(versions))
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.viewLayout.addLayout(buttons)
        self._show_passwords(False)

        self.yesButton.setText("Restore this version")
        self.yesButton.setVisible(bool(versions) and writable)
        self.cancelButton.setText("Close")
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(lambda _: self.yesButton.isVisible() and self.yesButton.click())
        if versions:
            self.table.selectRow(0)
        self._update_buttons()
        self.widget.setMinimumWidth(min(820, parent.width() - 80))
        self.widget.setMinimumHeight(min(420 if versions else 0, parent.height() - 120))

    def _row(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _show_passwords(self, on):
        for row, version in enumerate(self.versions):
            password = version["password"]
            item = QTableWidgetItem(password if on else ("•" * min(len(password), 12) if password else ""))
            if on:
                item.setFont(QFont(MONO_FAMILY))
            self.table.setItem(row, self.PASSWORD, item)

    def _update_buttons(self):
        row = self._row()
        self.copy.setEnabled(row is not None and bool(self.versions[row]["password"]))
        self.yesButton.setEnabled(row is not None and self._restore_fields(row) != {})

    def _copy(self):
        row = self._row()
        if row is not None:
            self.window().copy_secret(self.versions[row]["password"], "Old password")

    def _restore_fields(self, row):
        version, raw = self.versions[row], self.entry["raw"]
        return {key: version[key] for key in self.LABELS if version[key] != raw[key]}

    def validate(self):
        row = self._row()
        if row is None:
            return False
        fields = self._restore_fields(row)
        if fields:
            e = self.entry
            self.op = Op("update", e["uuid"], fields=fields, all_fields={**e["raw"], **fields}, folder=False,
                         base_mtime=e["base_mtime"], base_version=store.base_version(e),
                         title=fields.get("title", e["title"]))
        return True


def show_strength(bar, label, value):
    """A password's estimated strength on a bar and label (for master passwords)."""
    if not value:
        bar.setValue(0)
        label.setText("")
        return
    bits = generator.estimate_bits(value)
    text, score, level = generator.strength_label(bits)
    color = QColor(STRENGTH_COLORS[level])
    bar.setCustomBarColor(color, color)
    bar.setValue(max(score, 4))
    label.setText(f"{text} · ~{int(bits)} bits")


def strength_row(dialog):
    """Adds a strength bar and label to a dialog; returns them."""
    row = QHBoxLayout()
    bar = ProgressBar()
    bar.setRange(0, 100)
    bar.setFixedWidth(160)
    row.addWidget(bar)
    label = caption("")
    row.addWidget(label, 1)
    dialog.viewLayout.addLayout(row)
    return bar, label


class NewDatabaseDialog(MessageBoxBase):
    """Creates a new, empty database: a name, where to keep it, and a master password (twice).
    Afterwards `path` and `password` hold what to open."""

    def __init__(self, parent, start_dir):
        super().__init__(parent)
        self.path, self.password = "", None
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel("New database"))
        self.viewLayout.addWidget(caption(
            "A new, empty KeePass database (KDBX 4) that KeePassXC and KeePass apps open too. Keep it in a "
            "synced folder such as Google Drive to use it on your other devices."))
        self.name = LineEdit()
        self.name.setPlaceholderText("Name, e.g. Passwords")
        self.name.setText("Passwords")
        self.viewLayout.addWidget(self.name)
        place = QHBoxLayout()
        self.folder = str(start_dir)
        self.place_label = caption("")
        place.addWidget(self.place_label, 1)
        change = PushButton(FIF.FOLDER, "Change…")
        change.clicked.connect(self._choose_folder)
        place.addWidget(change)
        self.viewLayout.addLayout(place)
        self.name.textChanged.connect(self._update_place)
        self.new = PasswordLineEdit()
        self.new.setPlaceholderText("Master password")
        self.repeat = PasswordLineEdit()
        self.repeat.setPlaceholderText("Master password again")
        for line in (self.new, self.repeat):
            line.setClearButtonEnabled(False)
            line.returnPressed.connect(self.yesButton.click)
            self.viewLayout.addWidget(line)
        self.strength_bar, self.strength_label = strength_row(self)
        self.new.textChanged.connect(lambda text: show_strength(self.strength_bar, self.strength_label, text))
        self.viewLayout.addWidget(caption(
            "Choose a long password you'll remember, e.g. four or five unrelated words. "
            "It can't be recovered if you forget it."))
        self.error = caption("")
        self.error.setStyleSheet("color: #d13438;")
        self.error.hide()
        self.viewLayout.addWidget(self.error)
        self.yesButton.setText("Create")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(520)
        self._update_place()
        QTimer.singleShot(0, lambda: (self.name.setFocus(), self.name.selectAll()))

    def _file(self):
        name = re.sub(r'[<>:"/\\|?*]', "", self.name.text()).strip() or "Passwords"
        return Path(self.folder) / f"{name}.kdbx"

    def _update_place(self):
        self.place_label.setText(f"Saved as {self._file()}")

    def _choose_folder(self):
        folder = ask_path(self, "Where to keep the database", self.folder, folder=True)
        if folder:
            self.folder = folder
            self._update_place()

    def _fail(self, text, focus):
        self.error.setText(text)
        self.error.show()
        focus.setFocus()
        return False

    def validate(self):
        if not self.new.text():
            return self._fail("Choose a master password.", self.new)
        if self.new.text() != self.repeat.text():
            return self._fail("The two passwords don't match.", self.repeat)
        path = self._file()
        try:
            store.create_new_database(path, self.new.text(), self.name.text().strip() or path.stem)
        except FileExistsError:
            return self._fail(f"{path.name} already exists there. Choose another name.", self.name)
        except OSError as exc:
            return self._fail(f"Couldn't create it: {exc.strerror or exc}", self.name)
        self.path, self.password = str(path), self.new.text()
        return True


class ChangeMasterDialog(MessageBoxBase):
    """Change the master password and/or key file. Asks for the current password first, the new one
    twice, and shows how strong it is. The result is in `password` / `keyfile`."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self.password = None
        self.keyfile = db.kp.keyfile or ""
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel("Change master password"))
        self.viewLayout.addWidget(caption(
            "This changes what opens this database, everywhere you use it: KeePassXC and your other devices "
            "will need the new password too. A backup that still opens with the current password is kept."))
        self.current = PasswordLineEdit()
        self.current.setPlaceholderText("Current master password")
        self.new = PasswordLineEdit()
        self.new.setPlaceholderText("New master password")
        self.repeat = PasswordLineEdit()
        self.repeat.setPlaceholderText("New master password again")
        for line in (self.current, self.new, self.repeat):
            line.setClearButtonEnabled(False)
            self.viewLayout.addWidget(line)
            line.returnPressed.connect(self.yesButton.click)
        self.new.textChanged.connect(self._update_strength)
        self.strength_bar, self.strength_label = strength_row(self)

        keys = QHBoxLayout()
        self.key_label = caption("")
        keys.addWidget(self.key_label, 1)
        choose = TransparentPushButton(FIF.FOLDER, "Choose key file…")
        choose.clicked.connect(self._choose_keyfile)
        keys.addWidget(choose)
        self.remove_key = TransparentPushButton(FIF.REMOVE, "No key file")
        self.remove_key.clicked.connect(lambda: self._set_keyfile(""))
        keys.addWidget(self.remove_key)
        self.viewLayout.addLayout(keys)
        self.error = caption("")
        self.error.setStyleSheet("color: #d13438;")
        self.error.hide()
        self.viewLayout.addWidget(self.error)
        self._set_keyfile(self.keyfile)
        self._update_strength()
        self.yesButton.setText("Change password")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(520)
        QTimer.singleShot(0, self.current.setFocus)

    def _set_keyfile(self, path):
        self.keyfile = path
        self.key_label.setText(f"Key file: {Path(path).name}" if path else "No key file (password only)")
        self.remove_key.setVisible(bool(path))

    def _choose_keyfile(self):
        start = str(Path(self.keyfile).parent) if self.keyfile else str(Path(self.db.path).parent)
        path = ask_path(self, "Choose key file", start)
        if path:
            self._set_keyfile(path)

    def _update_strength(self):
        show_strength(self.strength_bar, self.strength_label, self.new.text())

    def _fail(self, text, focus):
        self.error.setText(text)
        self.error.show()
        focus.setFocus()
        focus.selectAll()
        return False

    def validate(self):
        if not hmac.compare_digest((self.current.text() or "").encode(), (self.db.kp.password or "").encode()):
            return self._fail("That isn't the current master password.", self.current)
        if not self.new.text() and not self.keyfile:
            return self._fail("Choose a new password (or a key file).", self.new)
        if self.new.text() != self.repeat.text():
            return self._fail("The two new passwords don't match.", self.repeat)
        if self.new.text() == self.current.text() and self.keyfile == (self.db.kp.keyfile or ""):
            return self._fail("That's the same as the current password.", self.new)
        if self.keyfile and not Path(self.keyfile).is_file():
            return self._fail("The key file can't be found.", self.new)
        self.password = self.new.text()
        return True


class FindIconsDialog(MessageBoxBase):
    """Finds the website and icon for entries that have no website, from their names (see
    sitefinder.py): a grid of guesses to tick or correct. Apply leaves the changes in `ops`."""

    USE, ENTRY, SITE, ICON, STATUS = range(5)
    result = Signal(int, int, object, object)  # row, request number, domain, PNG (from worker threads)

    def __init__(self, parent, entries):
        import sitefinder  # loaded only when this (occasional) tool is opened
        super().__init__(parent)
        self.entries = entries
        self.ops = []
        self._requests = [0] * len(entries)  # newest request per row; older answers are ignored
        self._typed = set()  # rows whose website the user typed: never replaced by a new guess
        self._pending = 0
        self._filling = False
        self._pool = ThreadPoolExecutor(8)
        self.result.connect(self._on_result)

        self.viewLayout.setSpacing(10)
        self.viewLayout.addWidget(SubtitleLabel("Find site icons"))
        self.viewLayout.addWidget(caption(
            "For entries without a website, Vault guesses the site from the entry's name and gets its icon. "
            "Untick any that are wrong, or type the right website, then Apply."))
        top = QHBoxLayout()
        top.addWidget(BodyLabel("Country"))
        self.country = ComboBox()
        self.country.addItems(list(sitefinder.COUNTRIES))
        saved = setting("icon_country", sitefinder.DEFAULT_COUNTRY)
        self.country.setCurrentText(saved if saved in sitefinder.COUNTRIES else sitefinder.DEFAULT_COUNTRY)
        self.country.currentTextChanged.connect(self._country_changed)
        top.addWidget(self.country)
        top.addStretch(1)
        self.progress = caption("")
        top.addWidget(self.progress)
        self.viewLayout.addLayout(top)

        self.table = TableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Use", "Entry", "Suggested website", "Icon", ""])
        self.table.setRowCount(len(entries))
        self.table.verticalHeader().hide()
        self.table.setWordWrap(False)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setIconSize(QSize(20, 20))
        header = self.table.horizontalHeader()
        for col, width in ((self.USE, 56), (self.ENTRY, 260), (self.SITE, 260), (self.ICON, 56)):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, width)
        header.setStretchLastSection(True)
        self._filling = True
        for row, e in enumerate(entries):
            use = QTableWidgetItem()
            use.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            use.setCheckState(Qt.Unchecked)
            name = QTableWidgetItem(e["title"])
            name.setFlags(Qt.ItemIsEnabled)
            name.setToolTip(" › ".join(e["path"]) or "Root")
            site = QTableWidgetItem("")
            site.setToolTip("Type or correct the website, e.g. bbc.co.uk")
            for col, item in ((self.USE, use), (self.ENTRY, name), (self.SITE, site)):
                self.table.setItem(row, col, item)
            for col in (self.ICON, self.STATUS):
                item = QTableWidgetItem("")
                item.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(row, col, item)
        self._filling = False
        self.table.itemChanged.connect(self._item_changed)
        self.viewLayout.addWidget(self.table, 1)

        self.fill_url = CheckBox("Also fill in the Website field of the entries you tick")
        self.fill_url.setChecked(setting("icon_fill_url", True))
        self.fill_url.toggled.connect(lambda on: settings.setValue("icon_fill_url", on))
        self.viewLayout.addWidget(self.fill_url)
        self.yesButton.setText("Apply")
        self.cancelButton.setText("Close")
        self.widget.setMinimumSize(min(900, int(parent.width() * 0.9)), int(parent.height() * 0.8))
        QTimer.singleShot(0, self.search)

    # ---- searching
    def _country_changed(self, country):
        settings.setValue("icon_country", country)
        self.search()

    def search(self):
        """Guesses every row's website from its name (again), for the chosen country."""
        import sitefinder
        country = self.country.currentText()
        ddg = setting("icons_duckduckgo", False)
        for row, e in enumerate(self.entries):
            if row not in self._typed:
                self._request(row, "Searching…", lambda title=e["title"]: sitefinder.find(title, country, ddg))

    def _request(self, row, status, job):
        self._requests[row] += 1
        number = self._requests[row]
        self._set_status(row, status)
        self._pending += 1
        self._update_progress()

        def run():
            try:
                domain, png = job()
            except Exception:
                domain, png = None, None
            self.result.emit(row, number, domain, png)  # delivered on the GUI thread
        self._pool.submit(run)

    def _on_result(self, row, number, domain, png):
        self._pending -= 1
        self._update_progress()
        if number != self._requests[row]:
            return  # superseded (country changed, or the website was edited meanwhile)
        self._filling = True
        if domain:
            self.table.item(row, self.SITE).setText(domain)
        icon_item = self.table.item(row, self.ICON)
        icon_item.setData(Qt.UserRole, png)
        pixmap = QPixmap()
        icon_item.setIcon(QIcon(pixmap) if png and pixmap.loadFromData(png) else QIcon())
        self.table.item(row, self.USE).setCheckState(Qt.Checked if png else Qt.Unchecked)
        self._filling = False
        self._set_status(row, "Found" if png else "No match: type the website")

    def _item_changed(self, item):
        if self._filling or item.column() != self.SITE:
            return
        import sitefinder
        typed = item.text().strip()
        if typed:
            self._typed.add(item.row())
        else:
            self._typed.discard(item.row())  # cleared: guess this one again next time
        ddg = setting("icons_duckduckgo", False)
        self._filling = True
        self.table.item(item.row(), self.ICON).setData(Qt.UserRole, None)
        self.table.item(item.row(), self.ICON).setIcon(QIcon())
        self.table.item(item.row(), self.USE).setCheckState(Qt.Unchecked)
        self._filling = False
        if typed:
            self._request(item.row(), "Checking…", lambda: sitefinder.icon_for(typed, ddg))
        else:
            self._set_status(item.row(), "")

    def _set_status(self, row, text):
        self.table.item(row, self.STATUS).setText(text)

    def _update_progress(self):
        self.progress.setText(f"Searching… {self._pending} left" if self._pending else
                              f"{sum(1 for r in range(self.table.rowCount()) if self._icon(r))} of "
                              f"{len(self.entries)} found")

    def _icon(self, row):
        return self.table.item(row, self.ICON).data(Qt.UserRole)

    # ---- applying
    def validate(self):
        fill = self.fill_url.isChecked()
        for row, e in enumerate(self.entries):
            png = self._icon(row)
            host = favicon.site_host(self.table.item(row, self.SITE).text())
            if self.table.item(row, self.USE).checkState() != Qt.Checked or not png or not host:
                continue
            self.ops.append(Op("set_icon", e["uuid"], icon=png, icon_name=host, title=e["title"]))
            if fill and not e["url"]:
                self.ops.append(Op("update", e["uuid"], fields={"url": f"https://{host}"},
                                   base_mtime=e["base_mtime"], base_version=store.base_version(e), title=e["title"]))
        return True

    def done(self, code):
        self._pool.shutdown(wait=False, cancel_futures=True)  # stop searching when the dialog closes
        super().done(code)


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
        self.own = {}  # the modified times our own edits produced (see store.apply_op): not conflicts
        self.busy = self.failed = False
        self.last_backup = 0.0
        self.last_stat = self._stat()
        self.poll_timer.start()
        self.status.emit("All changes saved" if db.writable else "Read-only")

    def pause(self, paused):
        """Minimised: stop checking the file every few seconds; check once on restore instead."""
        if paused:
            self.poll_timer.stop()
        elif self.db is not None:
            self.poll_timer.start()
            QTimer.singleShot(0, self.check_external)

    def detach(self):
        self.save_timer.stop()
        self.retry_timer.stop()
        self.poll_timer.stop()
        self.db = None
        self.undo_stack = []  # holds old values (passwords), so drop it when locking
        self.own = {}

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
            conflict = store.apply_op(kp, op, force=force, own=self.own)
            if conflict is None:
                self.unsaved.append(op)
                inverses.append(inverse)
                continue
            # The entry changed elsewhere since the editor was opened (e.g. brought in by a reload).
            for resolved in self._resolve(conflict):
                if resolved is conflict.op:  # "keep mine": don't ask again about this entry's other edits
                    store.seen_theirs(kp, resolved, self.own)
                inverses.append(store.inverse_op(kp, resolved) if undoable else None)
                store.apply_op(kp, resolved, force=True, own=self.own)
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
        release_after_work()
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
            conflict = store.apply_op(fresh, op, own=self.own)  # (our earlier edits re-applied here aren't conflicts)
            if conflict is None:
                replayed.append(op)
            else:
                for resolved in self._resolve(conflict):
                    if resolved is conflict.op:  # "keep mine": don't ask again about this entry's other edits
                        store.seen_theirs(fresh, resolved, self.own)
                    store.apply_op(fresh, resolved, force=True, own=self.own)
                    replayed.append(resolved)
        db.replace_kp(fresh, data)
        release_after_work()
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

    def change_credentials(self, password, keyfile, done):
        """A new master password / key file. Saved on its own once other edits are saved, always with a
        backup of the file as it was (which still opens with the old password). If the save fails, the
        old password stays. Calls done(error or None)."""
        def start():
            db = self.db
            if db is None or self.unsaved:
                done(RuntimeError("Your other changes couldn't be saved first."))
                return
            old = store.set_credentials(db.kp, password, keyfile)
            self.busy = True
            self.save_timer.stop()
            self.status.emit("Saving…")
            run_in_background(self, lambda: store.save_database(db.kp, db.path, db.digest, backup=True),
                              lambda new_digest, error: finished(db, old, new_digest, error))

        def finished(db, old, new_digest, error):
            self.busy = False
            if error:
                store.restore_credentials(db.kp, old)
                if isinstance(error, store.FileChanged):
                    error = RuntimeError("The database was just changed on another device. "
                                         "Vault will load those changes; then try again.")
                    QTimer.singleShot(0, lambda: self.check_external(manual=False))
            else:
                db.digest = new_digest
                self.last_backup = time.time()
                self.last_stat = self._stat()
            self.status.emit("All changes saved")
            queued, self.queued = self.queued, []
            for batch in queued:
                self._apply_batch(*batch)
            done(error)

        self.flush(start)

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
        release_after_work()
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
    updated = Signal()  # a check finished (or the database closed): the score and labels can change

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("view-health")
        self.db = None
        self.issues = []
        self._by_entry, self.checked = {}, False
        # Measure password strength (weak passwords) in every check, from unlocking on. (Waiting until
        # Password health was opened saved no memory once a few entries had been looked at.)
        self.strength = True
        self.full = False  # the last check included strength
        self._strengths = {}  # {password: bits} until locked, so checks after an edit are quick
        self.filter = None
        self.dirty = True
        # After unlocking or an edit, checked a little later (zxcvbn takes a moment for big databases)
        self.check_timer = QTimer(self, singleShot=True, interval=1500, timeout=self.refresh)
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 28, 36, 28)
        root.setSpacing(14)

        head = QHBoxLayout()
        back = TransparentToolButton(FIF.LEFT_ARROW)  # it's opened from Settings
        back.setToolTip("Back to Settings")
        back.clicked.connect(self._back)
        head.addWidget(back, 0, Qt.AlignTop)
        head.addSpacing(6)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(TitleLabel("Password health"))
        self.subtitle = caption("Entries in the Recycle Bin and Backup folders aren't checked. "
                                "Double-click an entry to fix it.")
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
            self._by_entry, self.checked, self.full = {}, False, False
            self._strengths = {}  # new dict: a check still running keeps its own (and then drops it)
            self.check_timer.stop()
            self._show()
            self.updated.emit()
        elif self.isVisible():
            self.refresh()
        else:  # for the score and the password labels: soon, in the background
            self.check_timer.start()
            if not self.checked:
                self.updated.emit()  # "Checking…"

    def showEvent(self, event):
        super().showEvent(event)
        if self.dirty and self.db is not None:
            self.refresh()

    def refresh(self):
        if self.db is None:
            return
        self.dirty = False
        self.check_timer.stop()
        entries = list(self.db.entries)
        self.empty.setText("Checking passwords…")
        db, cache, strength = self.db, self._strengths, self.strength
        run_in_background(self, lambda: health.report(entries, strength_cache=cache, strength=strength),
                          lambda issues, error: self._done(db, issues, error, strength))

    def _done(self, db, issues, error, strength=True):
        if db is not self.db:  # locked or reloaded meanwhile
            return
        if error:
            self.empty.setText(f"Couldn't check passwords: {error}")
            return
        self.issues = issues or []
        self._by_entry = {}
        for issue in self.issues:
            self._by_entry.setdefault(issue["entry"]["uuid"], {})[issue["issue"]] = (
                issue["detail"] or health.ISSUES[issue["issue"]][0])
        self.checked, self.full = True, strength
        # Every password's strength is remembered (until locked): the checker's word lists can go
        generator.unload_strength_checker()
        self._show()
        self.updated.emit()

    def problems(self, uuid):
        """An entry's problems as {issue: detail} ({} if none), or None until a check has run. Before
        Password health has been opened, weak passwords aren't included (see `full`)."""
        return self._by_entry.get(uuid, {}) if self.checked else None

    def score(self):
        """(0-100, entries to fix), or None until password strength has been measured (Password health
        opened). Passwords that are only old don't lower the score; weak, reused, missing and expired do."""
        if not self.full or self.db is None:
            return None
        live = [e for e in self.db.entries if not e["in_bin"] and not e["backup"]]
        to_fix = {i["entry"]["uuid"] for i in self.issues if i["issue"] != "old"}
        return (round(100 * (len(live) - len(to_fix)) / len(live)) if live else 100), len(to_fix)

    def _back(self):
        """Back to Settings, scrolled to the Password health card this was opened from."""
        settings_view = self.window().settings_view
        self.window().switchTo(settings_view)
        QTimer.singleShot(0, lambda: settings_view.ensureWidgetVisible(settings_view.health_card, 0, 40))

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
        """Edits the entry right here, so the list of problems stays on screen."""
        if not 0 <= index.row() < len(self.rows) or self.db is None:
            return
        uuid = self.rows[index.row()]["entry"]["uuid"]
        if not self.db.writable:
            self.window().show_entry(uuid)
            return
        e = next((x for x in self.db.entries if x["uuid"] == uuid), None)
        if e is None:
            return
        editor = EntryEditor(self.window(), self.db, entry=e)
        if editor.exec() and editor.op:
            self.window().saver.submit(editor.op, f"Edit of “{e['title']}”")
            if "url" in editor.op.fields:
                self.window().vault._auto_icon(editor.op)
            if self.dirty:
                self.refresh()


class SettingsView(ScrollArea):
    def __init__(self, on_colorize, on_density, on_fetch_missing, on_refresh_icons, on_quick_unlock, on_idle_minutes,
                 on_list_text, on_find_icons, parent=None):
        super().__init__(parent)
        self.setObjectName("view-settings")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # it fits the width (long texts wrap)
        self.enableTransparentBackground()
        self.scrollDelagate.verticalSmoothScroll.setSmoothMode(SmoothMode.NO_SMOOTH)
        page = QWidget(objectName="settingsPage")
        page.setStyleSheet("QWidget#settingsPage { background: transparent; }")  # not its tooltips (black)
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
        system = "macOS's" if sys.platform == "darwin" else "Windows'"
        root.addWidget(self._row("Theme", f"Colours for the whole app. System follows {system} light or dark mode.",
                                 themes))
        self.list_text = ComboBox()
        self.list_text.addItems([f"{size}%" for size in LIST_TEXT_SIZES])
        self.list_text.setCurrentText(f"{list_text_size()}%")
        self.list_text.currentTextChanged.connect(lambda text: (on_list_text(int(text.rstrip("%"))),
                                                                self._preview_list_text(int(text.rstrip("%")))))
        row = self._row(
            "List text size", shortcut_text("Text size of the entry list, folders and notes. Quickest: Ctrl + mouse wheel "
                                   "over the list (Ctrl+0 for normal)."), self.list_text)
        # A sample entry row at the chosen size, so the change shows here too.
        preview = QHBoxLayout()
        preview.setContentsMargins(0, 6, 0, 0)
        preview.setSpacing(18)
        preview.addWidget(caption("Preview:"))
        self.preview_title = BodyLabel("GitHub")
        self.preview_user, self.preview_pass = BodyLabel("alice@example.com"), BodyLabel("•" * 8)
        for label in (self.preview_title, self.preview_user, self.preview_pass):
            preview.addWidget(label)
        preview.addStretch(1)
        row.layout().itemAt(0).layout().addLayout(preview)
        self._preview_list_text(list_text_size())
        root.addWidget(row)
        clipboard = ComboBox()
        clipboard.addItems(list(CLIPBOARD_CHOICES))
        clipboard.setCurrentText(duration_text(clipboard_seconds()))
        clipboard.currentTextChanged.connect(lambda name: settings.setValue("clipboard_seconds", CLIPBOARD_CHOICES[name]))
        root.addWidget(self._row(
            "Clear clipboard after", "How long copied usernames, passwords and 2FA codes stay on the clipboard "
            "before Vault wipes them.", clipboard))
        root.addWidget(self._row(
            "Minimise after copying", "Copying a username or password from the list (its buttons, "
            "double-clicking an entry for the password, or with the details below the list, double-clicking "
            "its username or password) gets Vault out of the way, ready to paste. Off: Vault stays open.",
            self._bool_switch("minimise_on_copy")))
        idle = ComboBox()
        idle.addItems(list(IDLE_LOCK_CHOICES))
        idle.setCurrentText(next(k for k, v in IDLE_LOCK_CHOICES.items() if v == idle_lock_minutes()))
        idle.currentTextChanged.connect(lambda name: (settings.setValue("lock_idle_minutes", IDLE_LOCK_CHOICES[name]),
                                                      on_idle_minutes(IDLE_LOCK_CHOICES[name])))
        root.addWidget(self._row(
            "Lock when not used", "Lock the database after this long without keyboard or mouse use in Vault "
            "(also while it's minimised).", idle))
        lock_keys = "Control-Command-Q" if sys.platform == "darwin" else "Windows+L"
        root.addWidget(self._row(
            "Lock with the computer", f"Also lock the moment you lock the computer ({lock_keys}, or the screen "
            "saver asking for your password), switch user, or the computer goes to sleep.",
            self._bool_switch("lock_with_system")))
        verifier = quickunlock.get_verifier()
        if verifier:
            root.addWidget(self._row(
                f"Unlock with {verifier.name}",
                f"After you've unlocked with your master password, unlock again with {verifier.name} until "
                "you quit Vault. Your master password is never saved.",
                self._bool_switch("quick_unlock", on_quick_unlock)))
        root.addWidget(self._row(
            "Show passwords when unlocked",
            "Start with passwords shown (the eye in the title bar on) each time you open or unlock the "
            "database. Off: they start hidden. Locking always hides them.",
            self._bool_switch("show_passwords_on_open", default=False)))
        root.addWidget(self._row(
            "Colour-code passwords",
            "When shown, colour uppercase, lowercase, digits and symbols differently.",
            self._bool_switch("color_passwords", on_colorize)))
        density = ComboBox()
        density.addItems(list(CARD_DENSITIES))
        density.setCurrentText(setting("row_density", "Comfortable"))
        density.currentTextChanged.connect(lambda name: settings.setValue("row_density", name))
        density.currentTextChanged.connect(on_density)
        root.addWidget(self._row("Row density", "How tightly entries are packed in the list.", density))
        root.addWidget(self._row("Striped list", "Shade every other entry in the list, to follow a row by eye.",
                                 self._bool_switch("list_stripes", lambda on: self.window().vault.set_stripes(on))))

        root.addSpacing(8)
        root.addWidget(SubtitleLabel("Database"))
        change = PushButton(AppIcon("lock"), "Change…")
        change.clicked.connect(lambda: self.window().change_master_password())
        root.addWidget(self._row(
            "Master password", "Change the password (or key file) that opens the open database. A backup that "
            "opens with the old password is kept.", change))

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
        finder = PushButton(FIF.SEARCH, "Find icons by name…")
        finder.clicked.connect(on_find_icons)
        root.addWidget(self._row(
            "Entries without a website", "Guess each entry's website from its name (e.g. “British Gas” → "
            "britishgas.co.uk) and get its icon. You check every guess before anything changes.", finder))
        # Password health's score; click for the full report (MainWindow connects it)
        root.addSpacing(8)
        root.addWidget(SubtitleLabel("Password health"))
        self.health_card = HealthButton()
        self.health_card.setCheckable(False)
        self.health_card.setToolTip("Open the full report: weak, reused, missing and expired passwords")
        self.health_card.setCursor(Qt.PointingHandCursor)
        root.addWidget(self.health_card)
        root.addStretch(1)
        root.addWidget(caption(f"Vault {VERSION}"), 0, Qt.AlignRight)

    def show_list_text_size(self, size):
        """Keeps the choice in step when the size is changed with Ctrl+wheel or the shortcuts."""
        self.list_text.blockSignals(True)
        self.list_text.setCurrentText(f"{size}%")
        self.list_text.blockSignals(False)
        self._preview_list_text(size)

    def _preview_list_text(self, size):
        """The sample entry row, in the same fonts the entry list uses at this size."""
        k = size / 100
        for label in (self.preview_title, self.preview_user):
            label.setFont(getFont(round(13 * k)))
        mono = QFont(MONO_FAMILY)
        mono.setPixelSize(round(14 * k))
        self.preview_pass.setFont(mono)

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
        layout.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(BodyLabel(title))
        # Wrapped to the window's width (one long line made the page wider than the window, and the
        # switches and choices went off its right edge)
        detail = caption(desc)
        detail.setWordWrap(True)
        detail.setMinimumWidth(1)
        text.addWidget(detail)
        layout.addLayout(text, 1)
        layout.addWidget(control, 0, Qt.AlignVCenter)
        return card


class UnlockDialog(MessageBoxBase):
    """Asks for the database file, master password and optional key file, then opens it.
    With Quick Unlock (`quick`, from earlier this session), an empty password means "use Touch ID /
    Windows Hello" instead."""

    def __init__(self, parent, quick=None):
        super().__init__(parent)
        self.db = None
        self.path = setting("last_file", "")
        self.keyfile = setting("last_keyfile", "")
        self.password = None  # the password that worked, for Quick Unlock next time
        self.quick = quick
        self.quick_failed = False
        self.verifier = quickunlock.get_verifier() if quick else None
        self._worker = None

        # A lock screen across the whole window (the window's own background, the padlock and name
        # above the fields), rather than a box over a darkened copy of the window
        mode, _accent, background = THEMES.get(theme_name(), THEMES["System"])
        self.setMaskColor(QColor(background or DEFAULT_BACKGROUNDS[isDarkTheme()]))
        self.widget.setGraphicsEffect(None)
        self.widget.setStyleSheet("QFrame#centerWidget { background: transparent; border: none; }")
        self.buttonGroup.setStyleSheet("QFrame#buttonGroup { background: transparent; border: none; }")
        self.viewLayout.setSpacing(10)
        badge = QLabel()
        badge.setPixmap(self._padlock(72))
        self.viewLayout.addWidget(badge, 0, Qt.AlignHCenter)
        name = TitleLabel("Vault")
        self.viewLayout.addWidget(name, 0, Qt.AlignHCenter)
        self.viewLayout.addSpacing(10)

        # Just the database's name, the password and Unlock; choosing another file, making a new one
        # or using a key file are small links underneath.
        self.file_label = caption("")
        self.file_label.setAlignment(Qt.AlignCenter)
        self.viewLayout.addWidget(self.file_label)

        self.pw = PasswordLineEdit()
        self.pw.setPlaceholderText("Master password")
        self.pw.returnPressed.connect(self.yesButton.click)
        self.pw.textChanged.connect(self._update_button)
        self.viewLayout.addWidget(self.pw)

        key_row = QHBoxLayout()  # only while a key file is chosen
        key_row.addStretch(1)
        self.key_label = caption("")
        key_row.addWidget(self.key_label)
        self.key_clear = TransparentToolButton(FIF.CLOSE)
        self.key_clear.setFixedSize(24, 24)
        self.key_clear.setIconSize(QSize(10, 10))
        self.key_clear.setToolTip("Don't use a key file")
        self.key_clear.clicked.connect(lambda: self._set_keyfile(""))
        key_row.addWidget(self.key_clear)
        key_row.addStretch(1)
        self.viewLayout.addLayout(key_row)

        self.error = CaptionLabel("")
        self.error.setTextColor("#d13438", "#ff99a4")
        self.error.setWordWrap(True)
        self.error.setAlignment(Qt.AlignCenter)
        self.error.hide()
        self.viewLayout.addWidget(self.error)

        links = QHBoxLayout()
        links.setSpacing(2)
        links.addStretch(1)
        choose = self._link("Open another…", "Open a different KeePass database file", self._choose_file)
        self.new_btn = self._link("New database…", "Create a new, empty database", self._new_database)
        key_btn = self._link("Key file…", "Unlock with a key file as well as (or instead of) the password",
                             self._choose_keyfile)
        for link in (choose, self.new_btn, key_btn):
            links.addWidget(link)
        links.addStretch(1)
        self.links = links

        self.yesButton.setText("Unlock")
        self.cancelButton.setText("Quit")
        self.cancelButton.hide()  # closing the window quits; the screen needs only Unlock
        self.vBoxLayout.addLayout(self.links)  # under the Unlock button
        self.vBoxLayout.addSpacing(12)
        self.widget.setMinimumWidth(420)
        self.widget.setMaximumWidth(420)
        self._set_path(self.path if self.path and Path(self.path).exists() else "")
        self._set_keyfile(self.keyfile if self.keyfile and Path(self.keyfile).exists() else "")
        self.pw.setFocus()

    @staticmethod
    def _link(text, tip, on_click):
        """A small, quiet text button for the lock screen's less-used choices."""
        link = HyperlinkButton(url="", text=text)
        link.setToolTip(tip)
        link.clicked.connect(on_click)
        font = link.font()
        font.setPixelSize(12)
        link.setFont(font)
        return link

    def _padlock(self, size):
        """Vault's padlock on an accent-coloured rounded square: white on the light theme's deeper accent,
        black on the dark theme's bright one."""
        ratio = self.devicePixelRatioF()
        picture = QPixmap(round(size * ratio), round(size * ratio))
        picture.fill(Qt.transparent)
        picture.setDevicePixelRatio(ratio)
        p = QPainter(picture)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(themeColor()))
        p.drawRoundedRect(QRectF(0, 0, size, size), size / 4.2, size / 4.2)
        s = round(size * 0.5)
        QIcon(AppIcon("lock").path(Theme.LIGHT if isDarkTheme() else Theme.DARK)).paint(
            p, QRect((size - s) // 2, (size - s) // 2, s, s))
        p.end()
        return picture

    def _quick_ready(self):
        return bool(self.quick and self.verifier and self.quick.matches(self.path, self.keyfile))

    def _update_button(self):
        if self._worker is None:
            quick = self._quick_ready() and not self.pw.text()
            self.yesButton.setText(f"Unlock with {self.verifier.name}" if quick else "Unlock")

    def _start_dir(self, current):
        if current:
            return str(Path(current).parent)
        return str(google_drive_folder() or Path.home())

    def _set_path(self, path):
        self.path = path
        self.file_label.setText(Path(path).name if path else "No database yet: choose one, or make a new one")
        self.file_label.setToolTip(path)
        self._update_button()

    def _set_keyfile(self, path):
        self.keyfile = path
        self.key_label.setText(f"Key file: {Path(path).name}" if path else "")
        self.key_label.setToolTip(path)
        self.key_label.setVisible(bool(path))
        self.key_clear.setVisible(bool(path))
        self._update_button()

    def _choose_file(self):
        path = ask_path(self, "Open KeePass database", self._start_dir(self.path),
                        "KeePass databases (*.kdbx *.k);;All files (*)")
        if path:
            self._set_path(path)
            self.pw.setFocus()

    def _new_database(self):
        """Creates a database, then opens it straight away."""
        dialog = NewDatabaseDialog(self.window(), self._start_dir(self.path))
        if dialog.exec() and dialog.path:
            self._set_path(dialog.path)
            self._set_keyfile("")
            self.pw.setText(dialog.password)
            dialog.password = None
            self.yesButton.click()

    def _choose_keyfile(self):
        path = ask_path(self, "Choose key file", self._start_dir(self.keyfile or self.path))
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
        if not self.pw.text() and self._quick_ready():
            self._start_quick()
            return False
        if not self.pw.text() and not self.keyfile:
            self._show_error("Enter your master password.")
            return False
        self._unlock(self.pw.text())
        return False

    def _start_quick(self):
        """Asks Touch ID / Windows Hello, then unlocks with the password kept from earlier."""
        self._show_error("")
        self.yesButton.setEnabled(False)
        self.yesButton.setText(f"Waiting for {self.verifier.name}…")
        pending = self.verifier.verify(int(self.window().winId()), "unlock your database")
        self._worker = pending  # blocks a second attempt meanwhile

        def poll():
            outcome = pending.result()
            if outcome is None:
                QTimer.singleShot(100, poll)
                return
            self._worker = None
            approved, message = outcome
            if approved:
                self._unlock(self.quick.password(), quick=True)
            else:
                self.yesButton.setEnabled(True)
                self._update_button()
                self._show_error(message)
                self.pw.setFocus()

        poll()

    def _unlock(self, password, quick=False):
        self._show_error("")
        self.yesButton.setEnabled(False)
        self.yesButton.setText("Unlocking…")
        result = {}

        def work(path=self.path, password=password, keyfile=self.keyfile):
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
        self._poll(result, password, quick)

    def _poll(self, result, password, quick):
        if self._worker.is_alive():
            QTimer.singleShot(50, lambda: self._poll(result, password, quick))
            return
        self._worker = None
        self.yesButton.setEnabled(True)
        if "db" in result:
            self.db = result["db"]
            self.password = password
            self.pw.clear()
            settings.setValue("last_file", self.path)
            settings.setValue("last_keyfile", self.keyfile)
            self.accept()
            return
        if quick and result["error"].startswith("Wrong password"):
            # The master password was changed elsewhere (e.g. in KeePassXC): forget the old one.
            self.quick, self.quick_failed = None, True
            result["error"] = "The master password has changed. Enter the new one to unlock."
        self._update_button()
        self._show_error(result["error"])
        self.pw.selectAll()
        self.pw.setFocus()


class IdleWatcher(QObject):
    """Calls `on_idle` after a period with no keyboard or mouse input anywhere in the app.
    Only while armed (unlocked) and set to a time: otherwise there's no timer and no input watching."""

    INPUT_EVENTS = {QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.Wheel}

    def __init__(self, minutes, on_idle):
        super().__init__()
        self.timer = QTimer(self, singleShot=True, timeout=on_idle)
        self.armed = self.watching = False
        self.set_minutes(minutes)

    def set_minutes(self, minutes):
        """0 = never."""
        self.minutes = minutes
        self.timer.setInterval(max(minutes, 0) * 60_000)
        self._update()

    def arm(self, armed):
        """True once unlocked, False when locked: there's nothing to lock until the database is open."""
        self.armed = armed
        self._update()

    def _update(self):
        on = self.armed and self.minutes > 0
        if on != self.watching:
            app = QApplication.instance()
            app.installEventFilter(self) if on else app.removeEventFilter(self)
            self.watching = on
        self.timer.start() if on else self.timer.stop()

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
        self.draw(p, self.rect())

    @staticmethod
    def draw(p, rect):
        p.setRenderHint(QPainter.Antialiasing)
        mode, _, background = THEMES.get(theme_name(), THEMES["System"])
        p.fillRect(rect, QColor(background or DEFAULT_BACKGROUNDS[1 if isDarkTheme() else 0]))
        size = 96
        c = rect.center()
        QIcon(str(RESOURCE_DIR / "icons" / "vault.png")).paint(p, QRect(c.x() - size // 2, c.y() - size, size, size))
        p.setPen(QColor("#ffffff" if isDarkTheme() else "#1f1f1f"))
        font = getFont(28, QFont.DemiBold)
        p.setFont(font)
        p.drawText(QRect(0, c.y() + 12, rect.width(), 44), Qt.AlignHCenter | Qt.AlignTop, "Vault")

    @classmethod
    def image(cls, size, ratio=1.0):
        """The cover as a picture, `size` in window units, `ratio` device pixels per unit."""
        img = QImage(round(size.width() * ratio), round(size.height() * ratio), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(ratio)
        p = QPainter(img)
        cls.draw(p, QRect(0, 0, size.width(), size.height()))
        p.end()
        return img


class SideButton(QAbstractButton):
    """A sidebar row below the folders (New entry, Settings): highlighted, like a folder row, while its
    page shows."""

    def __init__(self, fluent_icon, text, parent=None, checkable=True):
        super().__init__(parent)
        self.fluent_icon = fluent_icon
        self.setText(text)
        self.setCheckable(checkable)
        self.setFont(getFont(14))
        self.setFixedHeight(36)
        self.setAttribute(Qt.WA_Hover)
        self.setFocusPolicy(Qt.NoFocus)

    def event(self, e):
        if e.type() in (QEvent.HoverEnter, QEvent.HoverLeave):
            self.update()
        return super().event(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        c = 255 if isDarkTheme() else 0
        r = QRectF(self.rect()).adjusted(4, 2, -4, -2)
        if self.isChecked() or self.underMouse():
            p.setBrush(QColor(c, c, c, 15 if self.isChecked() else 9))
            p.drawRoundedRect(r, 5, 5)
        if self.isChecked():
            p.setBrush(QColor(themeColor()))
            p.drawRoundedRect(QRectF(r.x(), r.y() + r.height() * 0.27, 3, r.height() * 0.46), 1.5, 1.5)
        s = 16
        self.fluent_icon.render(p, QRect(int(r.x()) + 14, (self.height() - s) // 2, s, s))
        p.setPen(QColor(Qt.white if c else Qt.black))
        p.setFont(self.font())
        p.drawText(r.adjusted(44, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, self.text())


class HealthButton(QAbstractButton):
    """The sidebar's Password health card: a ring with the score, and how many entries need fixing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.score, self.to_fix, self.open = None, 0, False
        self.setCheckable(True)
        self.setFixedHeight(64)
        self.setAttribute(Qt.WA_Hover)
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip("Weak, reused, missing and expired passwords")

    def event(self, e):
        if e.type() in (QEvent.HoverEnter, QEvent.HoverLeave):
            self.update()
        return super().event(e)

    def set_score(self, result, open_db):
        """result: (score 0-100, entries to fix) or None while checking (or locked)."""
        self.score, self.to_fix = result if result else (None, 0)
        self.open = open_db
        self.update()

    @staticmethod
    def rating(score):
        if score >= 90:
            return "Excellent", QColor("#107c10"), QColor("#6ccb5f")
        if score >= 75:
            return "Good", QColor(themeColor()), QColor(themeColor())
        if score >= 50:
            return "Fair", QColor("#ca5010"), QColor("#f7894a")
        return "Needs work", QColor("#d13438"), QColor("#ff99a4")

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = isDarkTheme()
        c = 255 if dark else 0
        r = QRectF(self.rect()).adjusted(4.5, 1.5, -4.5, -1.5)
        p.setBrush(QColor(255, 255, 255, (16 if self.underMouse() else 10) if dark else (230 if self.underMouse() else 170)))
        p.setPen(QPen(QColor(themeColor()) if self.isChecked() else QColor(c, c, c, 24), 1.2))
        p.drawRoundedRect(r, 8, 8)

        ring = QRectF(r.x() + 12, r.center().y() - 17, 34, 34)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(c, c, c, 28), 4))
        p.drawEllipse(ring)
        if self.score is not None:
            label, light, dark_color = self.rating(self.score)
            pen = QPen(dark_color if dark else light, 4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(ring, 90 * 16, -round(360 * 16 * self.score / 100))
            font = getFont(12, QFont.DemiBold)
            p.setFont(font)
            p.setPen(QColor(Qt.white if dark else Qt.black))
            p.drawText(ring, Qt.AlignCenter, str(self.score))
            if self.to_fix:
                detail = f"{label} · {self.to_fix} to fix"
            else:
                detail = f"{label} · nothing to fix"
        else:
            detail = "Checking…" if self.open else ""
        if not self.isCheckable():  # in Settings: a chevron, as it opens the full report
            s = 14
            FIF.CHEVRON_RIGHT_MED.render(p, QRect(int(r.right()) - s - 14, int(r.center().y()) - s // 2, s, s))
        x = ring.right() + 12
        p.setPen(QColor(Qt.white if dark else Qt.black))
        p.setFont(getFont(14, QFont.DemiBold))
        p.drawText(QRectF(x, r.y() + 11, r.right() - x - 6, 20), Qt.AlignLeft | Qt.AlignVCenter, "Password health")
        p.setPen(QColor("#a3a9af" if dark else "#5c656d"))
        p.setFont(getFont(12))
        p.drawText(QRectF(x, r.y() + 32, r.right() - x - 6, 18), Qt.AlignLeft | Qt.AlignVCenter, detail)


class Sidebar(QWidget):
    """The window's left column: All entries, Favourites and the folders, then New entry. (Settings, with
    Password health in it, is a button in the title bar.)"""

    def __init__(self, window):
        super().__init__(window)
        self.main = window
        vault = window.vault
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 56, 6, 12)  # below the title bar
        layout.setSpacing(2)
        layout.addWidget(vault.tree, 1)
        layout.addSpacing(8)
        layout.addWidget(vault.new_btn)
        window.stackedWidget.currentChanged.connect(self.update_selection)
        self.setFixedWidth(250)

    def update_selection(self, *_):
        page = self.main.stackedWidget.currentWidget()
        self.main.settings_btn.setChecked(page in (self.main.settings_view, self.main.health))
        self.main.vault.folder_delegate.inactive = page is not self.main.vault
        self.main.vault.tree.viewport().update()

    def fit(self):
        """Wide enough for the longest folder name and its count (between 230 and 340 px)."""
        tree = self.main.vault.tree
        if not tree.topLevelItemCount():
            return
        margins = self.layout().contentsMargins()
        wanted = tree.sizeHintForColumn(0) + 36 + margins.left() + margins.right()
        self.setFixedWidth(max(230, min(340, wanted)))


class MainWindow(FluentWindow):
    COVER_DELAY_MS = 150  # time for the covered frame to reach the screen before minimising
    LATE_TRIMS_MS = (35_000, 65_000)  # light memory trims after minimising, once idle worker threads have exited
    _locked = True  # see the `locked` property

    def __init__(self):
        use_system_ui_font()  # before any widget asks for a font
        super().__init__()
        if sys.platform == "darwin":
            self._use_mac_window_controls()
        self.stackedWidget.setAnimationEnabled(False)  # switch pages instantly (no 0.25 s slide)
        # Clicking minimise gave it the keyboard focus, so after restoring, typing went nowhere
        # (not into the password box, search or list): the title bar's buttons never take it.
        for button in self.titleBar.findChildren(QAbstractButton):
            button.setFocusPolicy(Qt.NoFocus)
        self.privacy_cover = PrivacyCover(self)
        # Light trims once minimised (Windows): idle worker threads exit by themselves, Qt's image threads 30 s
        # after the last repaint and Windows' own about 60 s in, and each exit pages every loaded DLL back in
        # (the working set crept from 1.5 to 10 MB). One after each, then nothing; restoring cancels them.
        # Not on macOS: no such thread clean-up there.
        self.late_trim = QTimer(self, singleShot=True)
        self.late_trim.timeout.connect(self._late_trim)
        self._late_trims_left = []
        self.setWindowTitle("Vault")
        self.setWindowTitle("Vault")
        self.resize(1360, 800)
        self.locked = True
        self._copied = None
        self.quick = None  # quickunlock.Sealed: the master password, encrypted in memory, until Vault quits
        self._live_resize = False  # Windows: dragging the left edge (see nativeEvent)
        self._unlock_when_restored = False  # locked while minimised: ask for the password when reopened

        self.vault = VaultView()
        self.addSubInterface(self.vault, FIF.HOME, "Vault")
        self.navigationInterface.addItem(
            routeKey="lock", icon=AppIcon("lock"), text="Lock",
            onClick=self.lock, selectable=False, position=NavigationItemPosition.BOTTOM)
        self.health = HealthView()
        self.addSubInterface(self.health, icon("HEART", "CERTIFICATE"), "Password health")
        self.settings_view = SettingsView(on_colorize=self.vault.set_colorize, on_density=self.vault.set_density,
                                          on_fetch_missing=lambda: self.fetch_icons(missing_only=True),
                                          on_refresh_icons=lambda: self.fetch_icons(missing_only=False),
                                          on_quick_unlock=self._set_quick_unlock,
                                          on_idle_minutes=lambda minutes: self.idle.set_minutes(minutes),
                                          on_list_text=self.vault.set_list_text_size,
                                          on_find_icons=self.find_icons_by_name)
        self.addSubInterface(self.settings_view, FIF.SETTING, "Settings", NavigationItemPosition.BOTTOM)
        self.vault.listTextChanged.connect(self.settings_view.show_list_text_size)
        # The sidebar (folders, Password health, Settings) instead of the UI library's icon strip,
        # and the search box and lock button in the title bar
        self.navigationInterface.hide()
        self.sidebar = Sidebar(self)
        self.hBoxLayout.insertWidget(0, self.sidebar)
        self._setup_title_bar()
        self.health.updated.connect(self._on_health_checked)
        for keys, action in (("Ctrl+F", self.vault.focus_search), ("Ctrl+K", self.vault.focus_search),
                             ("Ctrl+N", self.vault.new_entry), ("Ctrl+Z", self.vault.undo),
                             ("F5", self.vault.check_for_changes), ("Ctrl+L", self.lock)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(lambda action=action: self._unlocked_shortcut(action))
        self.icons = IconFetcher(self)
        self.idle = IdleWatcher(idle_lock_minutes(), self._on_idle)
        # Lock with the computer (locking, sleep, switching user); see systemlock.py.
        self._system_lock_watch = systemlock.watch(int(self.winId()), lambda: QTimer.singleShot(0, self._on_system_lock))
        self._taskbar_padlock(True)  # starts locked
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

        # Full screen: Control-Command-F on macOS (like the green button), F11 on Windows.
        self._was_maximized = False
        full_screen = QShortcut(self)
        full_screen.setKeys(QKeySequence.StandardKey.FullScreen)
        full_screen.setContext(Qt.WindowShortcut)
        full_screen.activated.connect(self.toggle_full_screen)

    def _setup_title_bar(self):
        """The search box, centred in the title bar, and a lock button by the window buttons. Both
        hide while Vault is locked (the title bar stays above the unlock screen)."""
        bar = self.titleBar
        search = self.vault.search
        search.setMinimumWidth(220)
        search.setMaximumWidth(520)
        search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        i = bar.hBoxLayout.indexOf(bar.titleLabel) + 1
        bar.hBoxLayout.insertStretch(i, 1)
        bar.hBoxLayout.insertWidget(i + 1, search, 0, Qt.AlignVCenter)
        # Settings (with Password health in it): a second click goes back to the list
        self.settings_btn = TransparentToggleToolButton(FIF.SETTING)
        self.settings_btn.setToolTip("Settings and Password health")
        self.settings_btn.setFocusPolicy(Qt.NoFocus)
        self.settings_btn.clicked.connect(lambda: self.switchTo(
            self.vault if self.stackedWidget.currentWidget() in (self.settings_view, self.health)
            else self.settings_view))
        self.settings_view.health_card.clicked.connect(lambda: self.switchTo(self.health))
        self.lock_btn = TransparentToolButton(AppIcon("lock"))
        self.lock_btn.setToolTip(shortcut_text("Lock (Ctrl+L)"))
        self.lock_btn.setFocusPolicy(Qt.NoFocus)
        self.lock_btn.clicked.connect(self.lock)
        right = bar.hBoxLayout.count() - 1  # before the window buttons
        for i, button in enumerate((self.vault.reveal, self.vault.check_btn, self.settings_btn, self.lock_btn)):
            button.setFocusPolicy(Qt.NoFocus)
            bar.hBoxLayout.insertWidget(right + 2 * i, button, 0, Qt.AlignVCenter)
            bar.hBoxLayout.insertSpacing(right + 2 * i + 1, 10 if button is self.lock_btn else 2)
        if sys.platform != "darwin":
            bar.hBoxLayout.setContentsMargins(16, 0, 0, 0)
        # Searching from Password health or Settings shows the list again
        search.textChanged.connect(lambda text: text and self.vault._show_page())
        self.locked = self.locked  # hides them for now

    @property
    def locked(self):
        return self._locked

    @locked.setter
    def locked(self, value):
        self._locked = value
        if hasattr(self, "lock_btn"):  # the search box and the title bar's buttons only while unlocked
            for part in (self.vault.search, self.vault.reveal, self.vault.check_btn, self.settings_btn,
                         self.lock_btn):
                part.setVisible(not value)

    def _unlocked_shortcut(self, action):
        """Window-wide shortcuts work only while unlocked, and not behind an open dialog."""
        if not self.locked and QApplication.activeModalWidget() is None:
            action()

    def _on_health_checked(self):
        self.settings_view.health_card.set_score(self.health.score(), self.health.db is not None)
        self.vault.notes.update_chip()

    def toggle_full_screen(self):
        if self.isFullScreen():
            self.showMaximized() if self._was_maximized else self.showNormal()
        else:
            self._was_maximized = self.isMaximized()
            self.save_geometry()
            self.showFullScreen()

    def _use_mac_window_controls(self):
        """macOS: the native traffic-light buttons at the top left, like every Mac app, instead of the
        Windows-style buttons the UI library draws on the right."""
        try:
            self.setSystemTitleBarButtonVisible(True)
        except Exception:  # keep the drawn buttons rather than have none
            return
        bar = self.titleBar
        for button in (bar.minBtn, bar.maxBtn, bar.closeBtn):
            button.hide()
        bar.iconLabel.hide()  # Mac windows don't show an icon in the title bar
        # A taller title bar, like Finder's and Safari's, via an empty (invisible) toolbar: macOS then
        # places the traffic lights lower and further in by itself. Moving them by hand instead left
        # macOS's hover area (which shows ×, −, +) where they had been, so from below the symbols
        # appeared late.
        try:
            import AppKit
            import objc
            window = objc.objc_object(c_void_p=int(self.winId())).window()
            toolbar = AppKit.NSToolbar.alloc().initWithIdentifier_("VaultTitleBar")
            toolbar.setShowsBaselineSeparator_(False)
            window.setToolbar_(toolbar)
            window.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnifiedCompact)
            self._native_traffic_lights = True
        except Exception:  # fall back to placing them by hand (systemTitleBarRect)
            self._native_traffic_lights = False
        # The traffic lights take the top-left 74 px (see systemTitleBarRect) and are centred 20 px
        # down: start the title after them and centre it on their row.
        bar.hBoxLayout.setContentsMargins(92, 0, 0, 8)
        # The sidebar's Back arrow sat where the traffic lights go; Vault doesn't need page history.
        self.navigationInterface.setReturnButtonVisible(False)
        self.navigationInterface.panel.vBoxLayout.setContentsMargins(0, 34, 0, 5)

    def _updateSystemButtonRect(self):
        """macOS: the UI library moves the traffic lights on every repaint; with the toolbar (see
        _use_mac_window_controls) macOS places them itself, so leave them be."""
        if not getattr(self, "_native_traffic_lights", False):
            super()._updateSystemButtonRect()

    def systemTitleBarRect(self, size):
        """macOS: where the traffic lights go. FluentWindow puts them at the top right, like Windows'
        buttons; Mac apps with a tall title bar (Finder, Safari) have them at the top left with the close
        button 20 px in, level with the title. The library centres the minimise button in this rect;
        6 px down from the top edge, so they don't crowd it (centred 20 px down in the 48 px title bar)."""
        return QRect(0, 0 if self.isFullScreen() else 6, 94, size.height())

    # ---- hiding contents when minimised

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            # Minimised (most of the time): nothing ticks. Restored: catch up straight away.
            self.vault.notes.pause(self.isMinimized())
            if not self.locked:
                self.saver.pause(self.isMinimized())
            if self.isMinimized():
                # Unlocked, no cover: macOS says "minimised" before its animation, which would show it.
                if self.locked:
                    self.privacy_cover.show_over()
                QTimer.singleShot(1500, lambda: self.isMinimized() and trim_memory())
                if sys.platform == "win32":
                    self._late_trims_left = list(self.LATE_TRIMS_MS)
                    self.late_trim.start(self._late_trims_left[0])
            else:
                self.late_trim.stop()
                if self.privacy_cover.isVisible():
                    if getattr(self, "_unlock_when_restored", False):
                        QTimer.singleShot(self.COVER_DELAY_MS, self._uncover)  # until the unlock screen is up
                    else:
                        self.privacy_cover.hide()  # it's only needed while minimised: no flash of it on restore
            if not self.isMinimized() and getattr(self, "_unlock_when_restored", False):
                self._unlock_when_restored = False
                QTimer.singleShot(self.COVER_DELAY_MS, self._show_unlock)

    def _late_trim(self):
        """One of the light trims after minimising; then the next, if any (the delays count from minimising)."""
        if not self.isMinimized():
            return
        trim_memory(light=True)
        done = self._late_trims_left.pop(0)
        if self._late_trims_left:
            self.late_trim.start(self._late_trims_left[0] - done)

    def _uncover(self):
        if not self.isMinimized():
            self.privacy_cover.hide()

    def _taskbar_padlock(self, on):
        """While locked, the taskbar thumbnail and its hover preview (Windows) or the minimised window in
        the Dock (macOS) show the padlock screen. Otherwise, after locking while minimised, the system's
        last picture of the window (taken before it locked) would still show the passwords there."""
        if sys.platform == "win32":
            taskbarpreview.set_iconic(int(self.winId()), on)
        elif sys.platform == "darwin":
            import macdock
            macdock.set_padlock(int(self.winId()), PrivacyCover.image(self.size(), 2.0) if on else None)

    def _send_taskbar_picture(self, msg):
        hwnd = int(self.winId())
        if msg.message == taskbarpreview.WM_DWMSENDICONICTHUMBNAIL:
            max_w, max_h = taskbarpreview.thumbnail_limit(msg.lParam)
            image = PrivacyCover.image(self.size()).scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            taskbarpreview.set_thumbnail(hwnd, image)
        else:  # the full-size preview while hovering over the thumbnail
            taskbarpreview.set_live_preview(hwnd, PrivacyCover.image(self.size(), self.devicePixelRatioF()))

    def nativeEvent(self, eventType, message):
        """Windows: smooth resizing from the left or top edge. By default Windows first copies the old
        picture of the window into the resized frame, anchored to the left/top, so while dragging those
        edges the controls jump sideways until Vault redraws. Telling Windows to keep only a 1-pixel
        "valid" area makes it copy nothing, so each frame shows Vault's own redraw."""
        handled, result = super().nativeEvent(eventType, message)
        if sys.platform != "win32":
            return handled, result
        msg = MSG.from_address(int(message))
        live = getattr(self, "_live_resize", None)  # None while the window is still being created
        if msg.message == 0x0214 and msg.wParam in (1, 4, 7) and live is False:
            # WM_SIZING from the left edge or a left corner: hide the right-aligned controls (which
            # would otherwise lag a frame behind and jump) until the drag ends.
            self._set_live_resize(True)
        elif msg.message == 0x0232 and live:  # WM_EXITSIZEMOVE: drag finished
            self._set_live_resize(False)
        elif systemlock.is_lock_message(msg.message, msg.wParam) and live is not None:
            QTimer.singleShot(0, self._on_system_lock)  # Windows locked or going to sleep
        elif msg.message in (taskbarpreview.WM_DWMSENDICONICTHUMBNAIL,
                             taskbarpreview.WM_DWMSENDICONICLIVEPREVIEWBITMAP) and live is not None:
            self._send_taskbar_picture(msg)
            return True, 0
        if handled:
            if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE, while resizing/moving
                params = cast(msg.lParam, LPNCCALCSIZE_PARAMS).contents
                r = params.rgrc[0]  # the new client area (already adjusted by the library)
                params.rgrc[1] = params.rgrc[2] = RECT(r.left, r.top, r.left + 1, r.top + 1)
                return True, 0x0400  # WVR_VALIDRECTS
        return handled, result

    def _live_resize_widgets(self):
        v, bar = self.vault, self.titleBar
        return [v.search, v.sort_btn, v.reveal, v.check_btn, self.settings_btn, self.lock_btn, bar.minBtn,
                bar.maxBtn, bar.closeBtn]

    def _set_live_resize(self, on):
        self._live_resize = on
        for widget in self._live_resize_widgets():
            policy = widget.sizePolicy()
            policy.setRetainSizeWhenHidden(True)  # keep their space, so nothing else moves
            widget.setSizePolicy(policy)
            widget.setVisible(not on)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # The title bar spans the whole window (the UI library starts it after its icon strip)
        self.titleBar.move(0, 0)
        self.titleBar.resize(self.width(), self.titleBar.height())
        if hasattr(self, "privacy_cover") and self.privacy_cover.isVisible():
            self.privacy_cover.setGeometry(self.rect())
        if sys.platform == "win32" and getattr(self, "locked", False):
            taskbarpreview.invalidate(int(self.winId()))  # the thumbnail's shape follows the window's

    def save_geometry(self):
        if not self.isFullScreen():  # next time, open as it was before going full screen
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

    def find_icons_by_name(self):
        """Settings → Find icons by name: guesses websites for entries that have none (see FindIconsDialog)."""
        db = self.saver.db
        if db is None or not db.writable:
            InfoBar.info("Find site icons", "Unlock an editable database first.", orient=Qt.Horizontal,
                         isClosable=True, position=InfoBarPosition.TOP_RIGHT, duration=3000, parent=self)
            return
        entries = [e for e in db.entries if not e["in_bin"] and e["title"].strip() and not favicon.site_host(e["url"])]
        if not entries:
            InfoBar.info("Find site icons", "Every entry already has a website.", orient=Qt.Horizontal,
                         isClosable=True, position=InfoBarPosition.TOP_RIGHT, duration=3000, parent=self)
            return
        dialog = FindIconsDialog(self, entries)
        if dialog.exec() and dialog.ops:
            self.saver.submit_many(dialog.ops, "Find site icons")
            count = sum(op.kind == "set_icon" for op in dialog.ops)
            self.undo_toast(f"Added {count} site icon{'s' if count != 1 else ''}", "From Find site icons.")

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
        QApplication.clipboard().setMimeData(secret_mime_data(text))
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
        if not self.locked and idle_lock_minutes() > 0:
            self.lock()

    def _on_system_lock(self):
        """The computer was locked, put to sleep or switched to another user."""
        if not self.locked and setting("lock_with_system", True):
            self.lock()

    def lock(self):
        if self.locked and self.saver.db is None:
            self._show_unlock()
            return
        self.vault.notes.save_notes()  # notes still being typed
        self.saver.flush(self._lock_now)  # save any pending edits first

    def _lock_now(self):
        self.locked = True
        self._taskbar_padlock(True)
        self.idle.arm(False)
        self.saver.detach()
        self.vault.clear()
        QTimer.singleShot(2000, lambda: self.locked and trim_memory())  # the database is gone: give memory back
        self.health.set_db(None)
        self._clear_clipboard()
        self.setWindowTitle("Vault")
        self.switchTo(self.vault)
        if self.isMinimized():
            # Locked while minimised (e.g. after being left alone): stay minimised, and ask for the
            # password when the window is next opened (see changeEvent), covered until then.
            self._unlock_when_restored = True
            self.privacy_cover.show_over()
            return
        self._show_unlock()

    def change_master_password(self):
        db = self.saver.db
        note = lambda title, text: InfoBar.warning(title, text, orient=Qt.Horizontal, isClosable=True,
                                                   position=InfoBarPosition.TOP_RIGHT, duration=5000, parent=self)
        if self.locked or db is None:
            note("Locked", "Unlock the database first.")
            return
        if not db.writable:
            note("Read-only", f"Vault can't change the password of a KDBX {db.version} database.")
            return
        dialog = ChangeMasterDialog(self, db)
        if not dialog.exec():
            return
        password, keyfile = dialog.password, dialog.keyfile
        dialog.password = None

        def done(error):
            if error:
                InfoBar.error("Password not changed", str(error), orient=Qt.Vertical, isClosable=True,
                              position=InfoBarPosition.TOP_RIGHT, duration=-1, parent=self)
                return
            if self.quick is not None:
                self.quick = quickunlock.Sealed(db.path, keyfile, password) if self._quick_unlock_on() else None
            if Path(setting("last_file", "")) == Path(db.path):
                settings.setValue("last_keyfile", keyfile)
            InfoBar.success("Master password changed", "Use the new password from now on, on every device. "
                            "KeePassXC and your phone will ask for it next time.", orient=Qt.Vertical,
                            isClosable=True, position=InfoBarPosition.TOP_RIGHT, duration=8000, parent=self)

        self.saver.change_credentials(password, keyfile, done)

    def _set_quick_unlock(self, on):
        if not on:
            self.quick = None

    def _quick_unlock_on(self):
        return setting("quick_unlock", True) and quickunlock.get_verifier() is not None

    def _show_unlock(self):
        dialog = UnlockDialog(self, quick=self.quick if self._quick_unlock_on() else None)
        # The dialog's dark overlay covers the whole window: keep the title bar above it, so Vault can
        # still be minimised (or maximised, or closed) while it waits for the password.
        QTimer.singleShot(0, self.titleBar.raise_)
        accepted = dialog.exec() and dialog.db
        if dialog.quick_failed:
            self.quick = None
        if accepted and self._quick_unlock_on() and dialog.password is not None:
            self.quick = quickunlock.Sealed(dialog.path, dialog.keyfile, dialog.password)
        dialog.password = None
        # The dialog is the window's child, so it would otherwise outlive this unlock, still holding the
        # decrypted database: after each lock, one more copy of every password stayed in memory.
        db, dialog.db = dialog.db, None
        dialog.deleteLater()
        if accepted:
            self.vault.load(db)
            self.saver.attach(db)
            self.health.set_db(db)
            self.locked = False
            self._taskbar_padlock(False)
            self.idle.arm(True)
            QTimer.singleShot(0, self.vault.focus_search)  # ready to type what you're looking for
            # Once the first password health check (1.5 s in) has run too
            QTimer.singleShot(4000, lambda: not self.locked and release_after_work())
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
        # Save pending edits (and notes still being typed) before closing.
        if not self._closing and not self.locked:
            self.vault.notes.save_notes()
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
    use_system_ui_font()
    # On macOS this is also the Dock icon, so use the version drawn on Apple's icon grid (with its
    # margin and shadow); the edge-to-edge version looks oversized next to other Mac apps.
    app.setWindowIcon(QIcon(str(RESOURCE_DIR / "icons" / ("vault.png" if sys.platform == "darwin" else "vault_app.png"))))
    apply_theme(theme_name())
    window = MainWindow()
    apply_theme(theme_name(), window)
    window.show()
    # Load pykeepass (crypto, Argon2, XML) in the background while the password is being typed.
    threading.Thread(target=lambda: __import__("pykeepass"), daemon=True).start()
    QTimer.singleShot(0, window.lock)
    sys.exit(app.exec())
