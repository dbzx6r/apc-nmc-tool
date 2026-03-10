# -*- mode: python ; coding: utf-8 -*-
#
# apc_tool.spec — PyInstaller build spec for APC NMC Field Tool
#
# Build command:  pyinstaller apc_tool.spec
# Output:         dist/APC_NMC_Tool.exe  (single-file, no console window)

import os
import customtkinter

CTK_PATH = os.path.dirname(customtkinter.__file__)

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # customtkinter ships its own theme JSON and image assets
        (CTK_PATH, "customtkinter"),
    ],
    hiddenimports=[
        "customtkinter",
        "PIL",
        "PIL._tkinter_finder",
        "tkinter",
        "tkinter.ttk",
        "paramiko",
        "paramiko.transport",
        "paramiko.auth_handler",
        "paramiko.channel",
        "paramiko.client",
        "paramiko.config",
        "paramiko.dsskey",
        "paramiko.ecdsakey",
        "paramiko.ed25519key",
        "paramiko.rsakey",
        "paramiko.sftp_client",
        "paramiko.kex_ecdh_nist",
        "paramiko.kex_gex",
        "paramiko.kex_group14",
        "paramiko.kex_group1",
        "paramiko.kex_group16",
        "paramiko.kex_curve25519",
        "cryptography",
        "cryptography.hazmat.backends",
        "cryptography.hazmat.primitives",
        "ftplib",
        "sqlite3",
        "ctypes",
        "ctypes.wintypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["keyring", "ping3"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="APC_NMC_Tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No black console window — GUI only
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # Set to "resources/icon.ico" if you have one
    # NOTE: one-file mode is achieved by the spec structure above
    # (all binaries/datas inside EXE without a separate COLLECT step).
    # Do NOT add onefile=True here — it is not a valid EXE() parameter.
)
