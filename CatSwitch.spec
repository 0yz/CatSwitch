# -*- mode: python ; coding: utf-8 -*-
# onedir: DLLs live under dist/CatSwitch/_internal (no per-launch _MEI extract).
import os

spec_dir = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(spec_dir, 'dist', 'pyi_entry.py')],
    pathex=[spec_dir],
    binaries=[],
    datas=[(os.path.join(spec_dir, 'catswitch', 'resources'), 'catswitch/resources')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CatSwitch',
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
    version=os.path.join(spec_dir, 'dist', 'file_version_info.txt'),
    icon=[os.path.join(spec_dir, 'catswitch', 'resources', 'assets', 'app-icon.ico')],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='CatSwitch',
)
