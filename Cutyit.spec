# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Cutyit — macOS .app bundle
#
# Build:  .venv/bin/pyinstaller Cutyit.spec --clean --noconfirm
# Or via: bash scripts/build_mac.sh

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH)

# Collect everything from packages that use dynamic imports or data files
fw_datas,    fw_binaries,    fw_hiddens    = collect_all("faster_whisper")
ct_datas,    ct_binaries,    ct_hiddens    = collect_all("ctranslate2")
tok_datas,   tok_binaries,   tok_hiddens   = collect_all("tokenizers")
hf_datas,    hf_binaries,    hf_hiddens    = collect_all("huggingface_hub")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=fw_binaries + ct_binaries + tok_binaries + hf_binaries,
    datas=[
        (str(ROOT / "assets"), "assets"),
        (str(ROOT / "src"),    "src"),
        *fw_datas,
        *ct_datas,
        *tok_datas,
        *hf_datas,
    ],
    hiddenimports=[
        *fw_hiddens,
        *ct_hiddens,
        *tok_hiddens,
        *hf_hiddens,
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.QtMultimedia",
        "PyQt6.QtMultimediaWidgets",
        "PyQt6.QtSvg",
        "src.core.video_processor",
        "src.core.subtitle_generator",
        "src.ui.main_window",
        "src.ui.subtitle_editor",
        "src.ui.subtitle_overlay",
        "src.ui.subtitle_style",
        "src.ui.timeline",
        "src.ui.video_player",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "notebook"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Cutyit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Cutyit",
)

app = BUNDLE(
    coll,
    name="Cutyit.app",
    icon=str(ROOT / "assets" / "icon.icns"),
    bundle_identifier="com.lexisvar.cutyit",
    version="1.0.0",
    info_plist={
        "NSPrincipalClass": "NSApplication",
        "NSAppleScriptEnabled": False,
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
        "LSMinimumSystemVersion": "12.0",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "CFBundleName": "Cutyit",
        "CFBundleDisplayName": "Cutyit",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Video",
                "CFBundleTypeRole": "Editor",
                "LSItemContentTypes": [
                    "public.movie",
                    "public.mpeg-4",
                    "public.avi",
                ],
            }
        ],
    },
)
