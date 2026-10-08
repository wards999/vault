"""Which UI font should Vault name on macOS? Runs each candidate in a fresh process and reports the
memory it costs, the font Qt actually used, and whether Qt warns that it had to scan every font
("Populating font family aliases"). Run on a Mac (see .github/workflows/mac-font-check.yml):
    python tools/mac_font_check.py
"""
import os
import subprocess
import sys
import time

CANDIDATES = {
    "library default list (Segoe UI, Microsoft YaHei, PingFang SC)": None,
    "Qt's system font name": "SYSTEM",
    ".AppleSystemUIFont": ".AppleSystemUIFont",
    "Helvetica Neue": "Helvetica Neue",
}


def child(kind, family):
    import psutil
    from PySide6.QtGui import QFontDatabase, QFontInfo
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    import qfluentwidgets
    rss = lambda: psutil.Process().memory_info().rss / 2**20
    if family == "SYSTEM":
        family = QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()
    before, t0 = rss(), time.perf_counter()
    if kind == "widgets":
        if family:
            qfluentwidgets.setFontFamilies([family])
        from qfluentwidgets import BodyLabel, PushButton, SubtitleLabel
        widgets = [BodyLabel("Body text 123"), PushButton("New entry"), SubtitleLabel("Root")]
        for w in widgets:
            w.show()
        QTest.qWait(1000)  # painted on screen (not grab(): its first use costs ~40 MB by itself)
        used = QFontInfo(widgets[0].font()).family()
    else:  # the whole Vault window
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from PySide6.QtCore import QSettings
        import vault
        vault.settings = QSettings(os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "fontcheck.ini"), QSettings.IniFormat)
        vault.use_system_ui_font = (lambda: qfluentwidgets.setFontFamilies([family])) if family else (lambda: None)
        win = vault.MainWindow()
        win.show()
        QTest.qWait(1500)
        used = QFontInfo(win.vault.search.font()).family()
    print(f"RESULT +{rss() - before:.0f} MB in {time.perf_counter() - t0:.2f} s, total {rss():.0f} MB, rendered with '{used}'"
          f" (asked for '{family or 'default list'}')", flush=True)


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    app = QApplication(sys.argv)
    print("Qt's system font name:", QFontDatabase.systemFont(QFontDatabase.GeneralFont).family())
    print("Password font Menlo installed:", "Menlo" in QFontDatabase.families())
    del app
    for kind in ("widgets", "vault"):
        print(f"\n=== {'a few UI library widgets' if kind == 'widgets' else 'the whole Vault window'}")
        for name, family in CANDIDATES.items():
            r = subprocess.run([sys.executable, __file__, "--child", kind, family or ""], capture_output=True, text=True,
                               timeout=300)
            result = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), f"FAILED: {r.stderr[-400:]}")
            scan = "  ** Qt scanned every font (font family aliases warning)" if "font family aliases" in r.stderr else ""
            print(f"{name:<62} {result}{scan}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3] or None)
    else:
        main()
