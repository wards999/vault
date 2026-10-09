"""Windows: while Vault is locked, the taskbar thumbnail, and the full-size preview shown while hovering
over it, are pictures Vault supplies (its padlock screen). Otherwise a window that locks while minimised
keeps showing Windows' last picture of it, taken before it locked, with the passwords.

set_iconic(hwnd, True) when locking (False when unlocked: the real window is fine then). While on,
Windows asks for the pictures with WM_DWMSENDICONICTHUMBNAIL and WM_DWMSENDICONICLIVEPREVIEWBITMAP,
answered with set_thumbnail / set_live_preview.
"""
import ctypes
import sys
from ctypes import wintypes as wt

from PySide6.QtGui import QImage

WM_DWMSENDICONICTHUMBNAIL = 0x0323
WM_DWMSENDICONICLIVEPREVIEWBITMAP = 0x0326
_DWMWA_FORCE_ICONIC_REPRESENTATION = 7
_DWMWA_HAS_ICONIC_BITMAP = 10

if sys.platform == "win32":
    _dwm, _gdi = ctypes.windll.dwmapi, ctypes.windll.gdi32
    _dwm.DwmSetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    _dwm.DwmSetIconicThumbnail.argtypes = [wt.HWND, ctypes.c_void_p, wt.DWORD]
    _dwm.DwmSetIconicLivePreviewBitmap.argtypes = [wt.HWND, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD]
    _dwm.DwmInvalidateIconicBitmaps.argtypes = [wt.HWND]
    for f in (_dwm.DwmSetWindowAttribute, _dwm.DwmSetIconicThumbnail, _dwm.DwmSetIconicLivePreviewBitmap,
              _dwm.DwmInvalidateIconicBitmaps):
        f.restype = ctypes.c_long  # HRESULT: 0 = OK
    _gdi.CreateDIBSection.restype = ctypes.c_void_p
    _gdi.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p),
                                      wt.HANDLE, wt.DWORD]
    _gdi.DeleteObject.argtypes = [ctypes.c_void_p]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def set_iconic(hwnd, on):
    """On: Windows asks Vault for the pictures (and drops any it kept). Off: it shows the window itself.
    True if Windows accepted it."""
    value = wt.BOOL(on)
    ok = all(_dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0
             for attr in (_DWMWA_FORCE_ICONIC_REPRESENTATION, _DWMWA_HAS_ICONIC_BITMAP))
    if on:
        invalidate(hwnd)
    return ok


def invalidate(hwnd):
    """The window changed size: Windows asks for new pictures next time it needs them."""
    _dwm.DwmInvalidateIconicBitmaps(hwnd)


def thumbnail_limit(lparam):
    """The largest thumbnail Windows accepts, from WM_DWMSENDICONICTHUMBNAIL's lParam: (width, height)."""
    return (lparam >> 16) & 0xFFFF, lparam & 0xFFFF


def _with_bitmap(image, call):
    """Calls call(hbitmap) with a 32-bit top-down bitmap of the image; True if Windows accepted it."""
    image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)  # = Windows' BGRA in memory
    w, h = image.width(), image.height()
    header = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32)  # negative: top-down
    bits = ctypes.c_void_p()
    hbitmap = _gdi.CreateDIBSection(None, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    if not hbitmap:
        return False
    try:
        ctypes.memmove(bits, bytes(image.constBits())[:w * h * 4], w * h * 4)
        return call(hbitmap) == 0
    finally:
        _gdi.DeleteObject(hbitmap)


def set_thumbnail(hwnd, image):
    return _with_bitmap(image, lambda b: _dwm.DwmSetIconicThumbnail(hwnd, b, 0))


def set_live_preview(hwnd, image):
    return _with_bitmap(image, lambda b: _dwm.DwmSetIconicLivePreviewBitmap(hwnd, b, None, 0))
