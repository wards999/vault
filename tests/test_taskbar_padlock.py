"""Windows: while Vault is locked, the taskbar thumbnail and its hover preview are the padlock screen
(Windows would otherwise keep showing its last picture of the window, from before it locked). Unlocked,
Windows shows the real window as usual."""
import ctypes
import os
import sys
import time
import helpers  # repo path; temporary folder, settings and test databases
from helpers import ok, finish, skip

if sys.platform != "win32":
    skip("Windows only")
from PySide6.QtCore import QSize, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
import vault, taskbarpreview

path = helpers.copy_db("dnd41.kdbx", "taskbar41.kdbx")
vault.settings.setValue("last_file", str(path))
vault.settings.setValue("quick_unlock", False)

calls, pictures = [], []
real_set_iconic = taskbarpreview.set_iconic
taskbarpreview.set_iconic = lambda hwnd, on: (calls.append(on), real_set_iconic(hwnd, on))[1]
real_thumb, real_live = taskbarpreview.set_thumbnail, taskbarpreview.set_live_preview
taskbarpreview.set_thumbnail = lambda hwnd, img: (pictures.append(("thumb", img.size().toTuple(), real_thumb(hwnd, img))), True)[1]
taskbarpreview.set_live_preview = lambda hwnd, img: (pictures.append(("live", img.size().toTuple(), real_live(hwnd, img))), True)[1]

w = vault.MainWindow(); w.setMicaEffectEnabled(False); w.resize(1000, 600); w.show(); QTest.qWaitForWindowExposed(w)
hwnd = int(w.winId())
send = ctypes.windll.user32.SendMessageW
send.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
ok("starts locked: padlock pictures on", calls == [True], calls)

cover = vault.PrivacyCover.image(QSize(300, 200))
ok("the padlock picture is drawn (not blank)",
   cover.size().toTuple() == (300, 200) and cover.pixelColor(150, 70) != cover.pixelColor(5, 5))

# (Windows only accepts a thumbnail within the size it really asked for; this made-up request asks small)
send(hwnd, taskbarpreview.WM_DWMSENDICONICTHUMBNAIL, 0, (100 << 16) | 80)
ok("thumbnail asked for: padlock picture sent, within the size asked for, and Windows accepted it",
   pictures and pictures[-1][0] == "thumb" and pictures[-1][1][0] <= 100 and pictures[-1][1][1] <= 80
   and pictures[-1][2], pictures)
send(hwnd, taskbarpreview.WM_DWMSENDICONICLIVEPREVIEWBITMAP, 0, 0)
ok("hover preview asked for: full-size padlock picture sent",
   pictures[-1][0] == "live" and pictures[-1][1][0] >= 1000, pictures[-1])
if not os.environ.get("CI"):  # GitHub's test machines have no desktop taskbar to preview on
    ok("…and Windows accepted it", pictures[-1][2], pictures[-1])

dialog = lambda: next((d for d in w.findChildren(vault.UnlockDialog) if d.isVisible()), None)


def steps():
    QTimer.singleShot(0, w.lock); yield dialog
    d = dialog(); d.pw.setText(helpers.PW); d.yesButton.click(); yield lambda: not w.locked
    ok("unlocked: padlock pictures off (the taskbar shows the real window)", calls[-1] is False, calls)
    w.showMinimized(); yield lambda: w.isMinimized()
    QTimer.singleShot(0, w._on_idle); yield lambda: w.locked  # the idle lock, while minimised
    ok("locked while minimised: padlock pictures back on", calls[-1] is True, calls)


def run(gen):
    """Steps driven by timers, so they keep going inside the unlock dialog's own event loop."""
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


run(steps())
app.exec()
