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

# Pillow is only used by PyInstaller here (to turn the PNG into a .icns); keep it out of the app.
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
    --exclude-module PIL \
    --exclude-module numpy \
    --exclude-module scipy \
    --exclude-module colorthief \
    --exclude-module tkinter \
    --osx-bundle-identifier io.github.vault-keepass \
    --specpath build \
    --distpath dist \
    --workpath build

# ditto keeps the app bundle's symlinks and signature intact (plain zip can break them).
rm -f dist/Vault-mac.zip
ditto -c -k --sequesterRsrc --keepParent dist/Vault.app dist/Vault-mac.zip
echo "Built dist/Vault-mac.zip ($(du -h dist/Vault-mac.zip | cut -f1))"
