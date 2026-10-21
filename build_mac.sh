#!/bin/bash
# Builds the macOS version of Vault: dist/Vault-mac.zip (contains Vault.app).
# Must run on a Mac (GitHub Actions does this; see .github/workflows/build.yml).
#
# Usage:  bash build_mac.sh            (uses ./.venv if present, else python3)
set -euo pipefail
cd "$(dirname "$0")"
PYTHON=${PYTHON:-$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )}

"$PYTHON" -m pip install --quiet --upgrade pyinstaller pillow
"$PYTHON" -m pip install --quiet -r requirements.txt
# Touch ID (Quick Unlock) needs Apple's LocalAuthentication framework via pyobjc: fail early if it's missing.
"$PYTHON" -c "import quickunlock; quickunlock.TouchID(); print('Touch ID support: OK')"
# Locking with the Mac (screen lock / sleep) needs AppKit and Foundation via pyobjc.
"$PYTHON" -c "import systemlock; w = systemlock.MacWatcher(lambda: None); print('Lock-with-Mac support: OK')"

# Pillow is only used by PyInstaller here (to turn the PNG into a .icns); keep it out of the app.
# setuptools (about 0.9 MB) is only imported by cffi's code for compiling C extensions.
"$PYTHON" -m PyInstaller vault.py \
    --name Vault \
    --windowed \
    --noconfirm \
    --clean \
    --icon "$PWD/icons/vault.png" \
    --add-data "$PWD/icons:icons" \
    --add-data "$PWD/wordlists:wordlists" \
    --collect-data zxcvbn \
    --hidden-import LocalAuthentication \
    --hidden-import AppKit \
    --hidden-import Foundation \
    --exclude-module PIL \
    --exclude-module numpy \
    --exclude-module scipy \
    --exclude-module colorthief \
    --exclude-module tkinter \
    --exclude-module setuptools \
    --osx-bundle-identifier io.github.vault-keepass \
    --specpath build \
    --distpath dist \
    --workpath build

# Qt parts Vault doesn't use (~8 MB zipped), dragged in by two plugins: the PDF image format (QtPdf)
# and the on-screen keyboard for touchscreens (QtVirtualKeyboard, which needs Qt Quick and QML).
APP=dist/Vault.app/Contents
QT=$APP/Frameworks/PySide6/Qt
rm -f "$QT/plugins/imageformats/libqpdf.dylib" "$QT/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.dylib"
for fw in QtPdf QtQuick QtQml QtQmlModels QtQmlMeta QtQmlWorkerScript QtVirtualKeyboard QtVirtualKeyboardQml; do
    rm -rf "$QT/lib/$fw.framework" "$APP/Frameworks/$fw" "$APP/Resources/$fw"
done
# Nothing left may link to them, or Vault wouldn't start: stop the build instead.
still=$(find "$APP" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -u+x \) -exec otool -L {} + 2>/dev/null \
        | grep -E "^[[:space:]].*Qt(Pdf|Quick|Qml|VirtualKeyboard)" || true)
if [ -n "$still" ]; then
    echo "Removed Qt parts are still needed by:"; echo "$still"; exit 1
fi
# Removing files invalidated the app's signature: sign it again (ad hoc, as PyInstaller did).
codesign --force --deep --sign - dist/Vault.app
codesign --verify --deep --strict dist/Vault.app && echo "Signature: OK"

# ditto keeps the app bundle's symlinks and signature intact (plain zip can break them).
rm -f dist/Vault-mac.zip
ditto -c -k --sequesterRsrc --keepParent dist/Vault.app dist/Vault-mac.zip
echo "Built dist/Vault-mac.zip ($(du -h dist/Vault-mac.zip | cut -f1))"
