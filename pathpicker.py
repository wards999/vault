"""Windows' file dialogs for Vault, in a process of their own (Vault.exe --ask-path <request>).

Windows' dialog loads every installed shell extension (Google Drive, Dropbox, OneDrive, antivirus…) into the
process that shows it, where they stay until it quits: other companies' code inside the process holding the
decrypted passwords, with threads that keep paging memory back into a minimised Vault. Shown from here, they
load into this short-lived helper instead, and go when it quits. It shows the dialog, writes the chosen path
to the result file Vault named, and exits; it never opens the database or touches Vault's settings.
"""
import ctypes
import json
import os
import sys


def main(request_json):
    request = json.loads(request_json)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QFileDialog, QWidget
    app = QApplication(sys.argv[:1])
    user32 = ctypes.windll.user32
    vault_window = request.get("owner") or 0
    # The dialog's owner: a hidden tool window (so no taskbar button), over Vault's window. Not owned by Vault's
    # itself: windows of two processes linked like that share their input, the pointer included (the shell's
    # "working" pointer flickered over Vault); Vault keeps the dialog in front instead.
    owner = QWidget(None, Qt.Tool)
    owner.winId()
    if vault_window:
        rect = (ctypes.c_long * 4)()
        if user32.GetWindowRect(ctypes.c_void_p(vault_window), rect):
            owner.move(rect[0] + (rect[2] - rect[0]) // 3, rect[1] + (rect[3] - rect[1]) // 4)  # over Vault
    caption, start, name_filter = request.get("caption", ""), request.get("start", ""), request.get("filter", "")
    mode = request.get("mode", "open")
    if mode == "folder":
        path = QFileDialog.getExistingDirectory(owner, caption, start)
    elif mode == "save":
        path = QFileDialog.getSaveFileName(owner, caption, start, name_filter)[0]
    else:
        path = QFileDialog.getOpenFileName(owner, caption, start, name_filter)[0]
    # The result, written whole (Vault carries on as soon as it appears), then back to Vault: this process is
    # still in the foreground, so it may hand it over (else Windows flashes Vault's taskbar button instead)
    partial = request["result"] + ".part"
    with open(partial, "w", encoding="utf-8") as f:
        json.dump({"path": path}, f)
    os.replace(partial, request["result"])
    if vault_window:
        user32.SetForegroundWindow(ctypes.c_void_p(vault_window))
    os._exit(0)  # no Qt clean-up: nothing here needs saving, and Vault shouldn't wait for it
