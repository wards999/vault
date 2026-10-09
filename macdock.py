"""macOS: while Vault is locked, a minimised Vault window shows the padlock screen in the Dock.
The Dock's picture of a minimised window is taken when it's minimised and isn't updated after, so
otherwise a window that locks while minimised would keep showing the passwords there.

set_padlock(win_id, image) when locking; set_padlock(win_id, None) when unlocked (macOS's own picture).
"""
from PySide6.QtCore import QBuffer, QByteArray, QIODevice


def set_padlock(win_id, image):
    """Best effort: never stops Vault from locking. True if macOS took it."""
    try:
        import AppKit
        import objc
        window = objc.objc_object(c_void_p=win_id).window()
        if window is None:
            return False
        if image is None:
            window.setMiniwindowImage_(None)
            return True
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        png = bytes(data)
        window.setMiniwindowImage_(AppKit.NSImage.alloc().initWithData_(AppKit.NSData.dataWithBytes_length_(png, len(png))))
        return True
    except Exception:
        return False
