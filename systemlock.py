"""Tells Vault when the computer is locked or goes to sleep, so it can lock at the same moment.

Windows: the window registers for session notifications and then receives WM_WTSSESSION_CHANGE
(WTS_SESSION_LOCK: Windows+L, the lock screen, switching user) and WM_POWERBROADCAST
(PBT_APMSUSPEND: sleep/hibernate) in its nativeEvent; see is_lock_message().

macOS: MacWatcher listens for the screen locking (Control-Command-Q, the screen saver or display
sleep asking for the password), the Mac going to sleep, and switching user.
"""
import sys

WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK = 0x02B1, 0x7
WM_POWERBROADCAST, PBT_APMSUSPEND = 0x0218, 0x4


def register_windows(hwnd):
    """Asks Windows to send this window lock/unlock notifications for the current session."""
    import ctypes
    try:
        wtsapi32 = ctypes.windll.wtsapi32
        wtsapi32.WTSRegisterSessionNotification.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        return bool(wtsapi32.WTSRegisterSessionNotification(hwnd, 0))  # NOTIFY_FOR_THIS_SESSION
    except Exception:
        return False


def is_lock_message(message, wparam):
    return ((message == WM_WTSSESSION_CHANGE and wparam == WTS_SESSION_LOCK)
            or (message == WM_POWERBROADCAST and wparam == PBT_APMSUSPEND))


_observer_class = None

MAC_NOTIFICATIONS = {
    "distributed": ["com.apple.screenIsLocked"],
    "workspace": ["NSWorkspaceWillSleepNotification", "NSWorkspaceSessionDidResignActiveNotification"],
}


class MacWatcher:
    """Calls `callback` (on the main thread) when the Mac locks its screen, sleeps or switches user."""

    def __init__(self, callback):
        global _observer_class
        from AppKit import NSWorkspace
        from Foundation import NSDistributedNotificationCenter, NSObject
        if _observer_class is None:  # an Objective-C class can only be defined once per process
            class VaultLockObserver(NSObject):
                def systemLocked_(self, notification):
                    if self.callback:
                        self.callback()
            _observer_class = VaultLockObserver
        self.observer = _observer_class.alloc().init()
        self.observer.callback = callback
        distributed = NSDistributedNotificationCenter.defaultCenter()
        for name in MAC_NOTIFICATIONS["distributed"]:
            distributed.addObserver_selector_name_object_(self.observer, "systemLocked:", name, None)
        workspace = NSWorkspace.sharedWorkspace().notificationCenter()
        for name in MAC_NOTIFICATIONS["workspace"]:
            workspace.addObserver_selector_name_object_(self.observer, "systemLocked:", name, None)


def watch(window_handle, callback):
    """Starts watching on this system; returns an object to keep alive (or None on Windows/others)."""
    if sys.platform == "win32":
        register_windows(window_handle)
        return None
    if sys.platform == "darwin":
        try:
            return MacWatcher(callback)
        except Exception:
            return None
    return None
