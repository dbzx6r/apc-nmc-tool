"""
core/credentials.py — Secure credential storage without third-party dependencies.

On Windows (deployed .exe): uses the Windows Data Protection API (DPAPI) via
ctypes to encrypt passwords before writing them to the SQLite settings table.
DPAPI encrypts using the current Windows user's credentials, so the data can
only be decrypted by the same user on the same machine — the same security
model used by Windows Credential Manager.

On non-Windows (dev/macOS): falls back to base64 obfuscation with a clear
warning. This is not secure and is provided only for development convenience.
"""

import base64
import sys
from typing import Optional, Tuple

from core.database import get_setting, set_setting, delete_settings_prefix


_WINDOWS = sys.platform == "win32"


# ── DPAPI helpers (Windows only) ────────────────────────────────────── #

def _dpapi_encrypt(plaintext: str) -> str:
    """Encrypt using Windows DPAPI. Returns base64-encoded ciphertext."""
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    data = plaintext.encode("utf-8")
    in_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()

    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise RuntimeError("DPAPI CryptProtectData failed.")

    enc_bytes = bytes(ctypes.string_at(out_blob.pbData, out_blob.cbData))
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    return base64.b64encode(enc_bytes).decode("ascii")


def _dpapi_decrypt(b64_ciphertext: str) -> str:
    """Decrypt DPAPI-encrypted value. Returns plaintext."""
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    data = base64.b64decode(b64_ciphertext)
    in_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()

    if not ctypes.windll.crypt32.CryptProtectData.__class__:
        pass  # type checker placeholder

    decrypt_fn = ctypes.windll.crypt32.CryptUnprotectData
    if not decrypt_fn(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise RuntimeError("DPAPI CryptUnprotectData failed.")

    plaintext = ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    return plaintext


def _encrypt(plaintext: str) -> str:
    if _WINDOWS:
        return _dpapi_encrypt(plaintext)
    raise RuntimeError(
        "Credential storage requires Windows DPAPI and can only run on Windows.\n"
        "This tool must be executed on a Windows machine.\n"
        "Do not attempt to store credentials on non-Windows systems."
    )


def _decrypt(stored: str) -> str:
    if _WINDOWS:
        return _dpapi_decrypt(stored)
    raise RuntimeError(
        "Cannot decrypt credentials: Windows DPAPI is not available on this platform."
    )


# ── Public API ───────────────────────────────────────────────────────── #

def save_credential(device_name: str, username: str, password: str) -> None:
    """Store credentials for a device (or use '__global__' for the default)."""
    set_setting(f"cred:{device_name}:user", username)
    set_setting(f"cred:{device_name}:pass", _encrypt(password))


def get_credential(device_name: str) -> Optional[Tuple[str, str]]:
    """
    Retrieve stored credentials.
    Returns (username, password) or None if not stored.
    """
    username = get_setting(f"cred:{device_name}:user")
    enc_pass = get_setting(f"cred:{device_name}:pass")

    if not username or not enc_pass:
        return None

    try:
        password = _decrypt(enc_pass)
        return username, password
    except Exception:
        return None


def delete_credential(device_name: str) -> None:
    """Remove stored credentials for a device."""
    delete_settings_prefix(f"cred:{device_name}:")


def save_global_credential(username: str, password: str) -> None:
    """Save a default credential used when a device has no specific credential."""
    save_credential("__global__", username, password)


def get_global_credential() -> Optional[Tuple[str, str]]:
    """Retrieve the default credential."""
    return get_credential("__global__")


def list_saved_devices() -> list[str]:
    """Return device names that have saved credentials."""
    from core.database import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT key FROM settings WHERE key LIKE 'cred:%:user'"
    ).fetchall()
    conn.close()
    result = []
    for (key,) in rows:
        parts = key.split(":", 2)
        if len(parts) == 3:
            result.append(parts[1])
    return result
