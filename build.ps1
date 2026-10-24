# Builds the portable Windows version of Vault: dist\Vault-portable.zip
# Unzip anywhere and run Vault.exe; no installer or Python needed.
#
# Usage (from this folder):  powershell -ExecutionPolicy Bypass -File build.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }  # CI has no venv

# Exact versions of everything (PyInstaller included), so a build only changes when the lock file does
& $python -m pip install --quiet -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# --windowed: no console window. PIL/numpy/scipy/colorthief are optional extras of the UI
# library (and Pillow is only used by tools\make_icon.py), so keep them out of the bundle.
# setuptools (about 0.9 MB) is only imported by cffi's code for compiling C extensions.
& $python -m PyInstaller vault.py `
    --name Vault `
    --windowed `
    --noconfirm `
    --clean `
    --icon "$PSScriptRoot\icons\vault.ico" `
    --add-data "$PSScriptRoot\icons;icons" `
    --add-data "$PSScriptRoot\wordlists;wordlists" `
    --collect-data zxcvbn `
    --exclude-module PIL `
    --exclude-module numpy `
    --exclude-module scipy `
    --exclude-module colorthief `
    --exclude-module tkinter `
    --exclude-module setuptools `
    --specpath build `
    --distpath dist `
    --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Prune parts of Qt the app never uses (about 40 MB): the software-OpenGL fallback, Qt's own
# translations, and the PDF / virtual-keyboard plugins plus the Qt Quick/QML libraries they need.
$qt = "dist\Vault\_internal\PySide6"
$unused = @(
    "$qt\opengl32sw.dll", "$qt\translations",
    "$qt\plugins\imageformats\qpdf.dll", "$qt\Qt6Pdf.dll",
    "$qt\plugins\platforminputcontexts", "$qt\Qt6VirtualKeyboard*.dll",
    "$qt\Qt6Quick*.dll", "$qt\Qt6Qml*.dll", "$qt\Qt6OpenGL.dll"
)
foreach ($pattern in $unused) { Remove-Item $pattern -Recurse -Force -ErrorAction SilentlyContinue }

@"
Vault - a simple KeePass password manager
=========================================

1. Unzip this folder anywhere (Desktop, Documents, a USB stick...).
2. Double-click Vault.exe.
3. Click "Choose..." to pick your KeePass database (.kdbx), enter your master password, Unlock.

No installation or Python is needed. Your settings are saved in Vault.ini in this folder;
your master password is never saved anywhere.

Edits are saved automatically. Before saving, Vault keeps a backup of your database in the
"backups" folder here (the 10 most recent). Changes made by KeePass, KeePassXC or Vault on
another computer are picked up automatically.

The first time you run it, Windows may say "Windows protected your PC" because the app isn't
signed. Click "More info", then "Run anyway".
"@ | Set-Content -Path dist\Vault\README.txt -Encoding utf8

$zip = "dist\Vault-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path dist\Vault -DestinationPath $zip
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "Built $zip ($mb MB)"
