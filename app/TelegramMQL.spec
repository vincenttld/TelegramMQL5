# -*- mode: python ; coding: utf-8 -*-
import os
import re
from PyInstaller.utils.hooks import collect_submodules

BASE_DIR = os.getcwd()

# === Version (lue dans constants.py, sans l importer) ===
with open(os.path.join(SPECPATH, 'constants.py'), encoding='utf-8') as f:
    _match = re.search(r'^APP_VERSION\s*=\s*"(\d+)\.(\d+)', f.read(), re.M)
if not _match:
    raise ValueError("APP_VERSION introuvable dans constants.py")
EXE_NAME = f"TelegramToMQL_v{_match.group(1)}_{_match.group(2)}"

# === PySide6 (minimum nécessaire) ===
hiddenimports = collect_submodules('PySide6')

datas = [
    (os.path.join(BASE_DIR, 'app', 'config', '*.ini'), 'config'),
    (os.path.join(BASE_DIR, 'app', 'ui', '*.ui'), 'ui'),
    (os.path.join(BASE_DIR, 'app', 'ui', 'style.css'), 'ui'),
]

a = Analysis(
    ['main.py'],
    pathex=[BASE_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=EXE_NAME,
    debug=False,
    strip=False,
    upx=True,
    console=False,
    icon=os.path.join(BASE_DIR, 'assets', 'logo_telesignal.ico'),
    onefile=True,
)
