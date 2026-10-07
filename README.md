# Vault

A simple, modern password manager for KeePass databases (`.kdbx`), for Windows and Mac. It works
with the same file as KeePass and KeePassXC, for example one kept in Google Drive and used from
several computers.

## Download and run

Get the latest version from the [Releases page](https://github.com/wards999/vault/releases). There's
nothing to install.

- **Windows:** download `Vault-v…-windows.zip`, right-click it → **Extract All**, open the **Vault**
  folder and run **Vault.exe**. Put the folder anywhere you like (Documents, a USB stick…).
- **Mac:** download `Vault-v…-mac.zip`, double-click it, and drag **Vault** into Applications. The app
  isn't signed by Apple, so the first time macOS may refuse to open it. Go to **System Settings →
  Privacy & Security** and click **Open Anyway**.

Then choose your database file, type your master password and click **Unlock**.

## Features

- **A grid of entries:** site, username and password in rows, with folders alongside. Columns sort,
  and the window size, panel sizes and last folder are remembered.
- **Quick copying:** double-click a username or password to copy it and minimise Vault. The clipboard
  clears itself after a time you choose.
- **Editing:** add, edit, duplicate and delete entries; create, rename and move folders, including by
  drag and drop. **Undo** brings back deletions and other changes.
- **Password generator** for random passwords or passphrases, with a strength meter and optional
  colour-coding of letters, digits and symbols.
- **Username suggestions** from your other entries while you type (wildcards work).
- **2FA codes (TOTP)** for entries that have them.
- **Password health report:** weak, reused, expired and empty passwords, and passwords not changed in
  over a year.
- **Site icons:** downloaded from each website and saved in the database, so KeePass and KeePassXC
  show them too.
- **Themes:** light, dark and several colour themes.

## Keeping your passwords safe

- **Auto-save without surprises:** every change is saved straight away. Vault encrypts to memory,
  checks the result can be opened again, then replaces the file in one step, so a failed save can't
  damage it. It keeps up to 10 backups (at most one every 10 minutes).
- **Changes from other computers:** if the file was changed elsewhere (another PC, KeePass or
  KeePassXC), Vault merges both sets of changes and asks only when the same entry was changed in
  both places. Press **F5** to check for changes now.
- **Lock:** Vault locks after 5 minutes without use (this can be turned off), or straight away with
  **Lock**. Locking saves any pending changes first and clears copied passwords from the clipboard.
- **Quick Unlock:** after unlocking with your master password, unlock again with **Windows Hello**
  (fingerprint, face or PIN) or **Touch ID** until you quit Vault. As in KeePassXC, the master
  password is never saved: it's kept only in memory, encrypted. You can turn this off in Settings.
- **Private minimising:** the window is covered before it minimises, so taskbar previews, the Dock
  and the macOS minimise animation don't show passwords.
- **File formats:** KDBX 4 files can be edited. Older KDBX 3 files open read-only; to edit one,
  upgrade it to KDBX 4 in KeePassXC's database settings.

## Building (maintainer)

- **Windows:** `powershell -ExecutionPolicy Bypass -File build.ps1` builds the portable zip with PyInstaller.
- **Mac:** `bash build_mac.sh`, which must run on a Mac. GitHub Actions builds both on every push.
- **Release:** set `VERSION` in `vault.py`, commit, then push a tag `v<VERSION>` (for example
  `git tag v1.0.5; git push origin main v1.0.5`). GitHub Actions builds both apps and publishes the
  release, and refuses if the tag doesn't match `VERSION`.

Built with Python, PySide6, [PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
and [pykeepass](https://github.com/libkeepass/pykeepass).
