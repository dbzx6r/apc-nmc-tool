<div align="center">

# 🔌 APC NMC Field Tool

**A production-grade Windows GUI for programming APC Network Management Cards**

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-blue?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![SSH](https://img.shields.io/badge/SSH-Paramiko%204.0-green?logo=openssh&logoColor=white)](https://www.paramiko.org/)
[![GUI](https://img.shields.io/badge/GUI-customtkinter%205.2-purple)](https://github.com/TomSchimansky/CustomTkinter)
[![Air‑Gapped](https://img.shields.io/badge/Install-Air--Gapped%20Ready-orange)](./vendor/)

<br/>

> A field technician tool for configuring, managing, and auditing APC NMC / NMC2 / NMC3  
> network management cards — built for critical infrastructure environments.

</div>

---

## ✨ Features

| | Feature | Details |
|---|---|---|
| 🔐 | **TOFU Host Key Verification** | First connect shows SHA256 fingerprint for operator approval. Changed fingerprints block the connection with a red warning — MITM protection. |
| 🖥️ | **Embedded Terminal** | Live SSH output streamed to a colour-coded terminal. Send ad-hoc commands directly. |
| 🗄️ | **Device Database** | SQLite device registry with name, IP, card type, location, and notes. Add / edit / delete from the GUI. |
| 🔑 | **Credential Vault** | Passwords encrypted with Windows DPAPI — tied to your Windows user account, same model as Windows Credential Manager. |
| 📋 | **Audit Log** | Every connection, command, IP change, reboot, and firmware update is logged with timestamp, username, and result. Searchable, filterable, CSV-exportable. |
| ⬆️ | **Firmware Update** | FTP firmware upload wizard with a real-time progress bar. Supports all NMC generations. |
| ⚡ | **Quick Connect** | Connect directly by IP without adding a device to the database first. |
| 📡 | **Pre-connect Ping** | Reachability check (ping + TCP port 22) before every SSH attempt. |
| 🔒 | **Air-Gapped Install** | All Python dependencies are bundled in `vendor/` — no internet required on the target machine. |

---

## 🖥️ Supported Hardware

| Generation | Model Series | Card Type |
|---|---|---|
| NMC (Gen 1) | AP9617, AP9618, AP9619 | `NMC (gen 1)` |
| NMC2 (Gen 2) | AP9630, AP9631, AP9635 | `NMC2` |
| NMC3 (Gen 3) | AP9640, AP9641 | `NMC3` |

> Legacy Gen 1 cards use `diffie-hellman-group1-sha1` key exchange. The tool handles this automatically with a dual-strategy connection fallback.

---

## 🚀 Quick Start

> **Requirements:** Windows 10/11 · Python 3.11 or newer ([python.org](https://www.python.org/downloads/)) · Git (optional)

### Step 1 — Get the code

```bat
git clone https://github.com/dbzx6r/apc-nmc-tool.git
cd apc-nmc-tool
```

Or download and extract the ZIP from GitHub.

### Step 2 — Run setup (one time only)

Double-click **`setup.bat`** or right-click → *Run as administrator*.

```
✔ Checks Python is installed
✔ Creates an isolated virtual environment (.venv)
✔ Installs all dependencies from vendor\ (no internet needed)
✔ Creates an "APC NMC Tool" shortcut on your Desktop
```

### Step 3 — Launch

Double-click the **APC NMC Tool** shortcut on your Desktop.

> From then on, that's the only step.

---

## 📦 Air-Gapped / Offline Installation

All required Python packages are pre-downloaded in the `vendor/` folder as Windows `.whl` files. `setup.bat` installs them with `--no-index --find-links vendor\` — **no internet access is needed on the target machine at any point.**

| Package | Version | Purpose |
|---|---|---|
| `paramiko` | 4.0.0 | SSH client |
| `customtkinter` | 5.2.2 | Modern GUI framework |
| `cryptography` | 46.0.5 | SSH cryptographic primitives |
| `bcrypt` | 5.0.0 | Key derivation (paramiko dep) |
| `pynacl` | 1.6.2 | Ed25519 support (paramiko dep) |

---

## 🔒 Security Model

### SSH — Trust On First Use (TOFU)

On every first connection to a device, the operator is shown the server's **SHA256 fingerprint** and must explicitly accept it. The fingerprint is saved to the local database.

On subsequent connections, the stored fingerprint is compared against the presented one:

- ✅ **Match** → connect silently
- ⚠️ **Mismatch** → connection is **blocked** with a prominent red warning dialog requiring explicit operator override

This prevents silent MITM attacks against critical infrastructure devices.

### Credentials — Windows DPAPI

Saved passwords are encrypted using the **Windows Data Protection API (DPAPI)** before being written to the SQLite database. DPAPI encrypts using your Windows user credentials, meaning the data can only be decrypted by the same user on the same machine — identical to the security model used by Windows Credential Manager.

### Audit Log

Every action is logged:

```
timestamp           | device     | ip            | user | action           | result
2026-03-10 14:22:01 | MAIN-UPS-1 | 192.168.1.100 | apc  | SSH Connect      | success
2026-03-10 14:22:45 | MAIN-UPS-1 | 192.168.1.100 | apc  | Change IP        | success
2026-03-10 14:23:10 | MAIN-UPS-1 | 192.168.1.100 | apc  | SSH Disconnect   | success
```

The log viewer supports search, filter by device, and full CSV export.

---

## 🗂️ Project Structure

```
apc-nmc-tool/
│
├── main.py                  # Entry point
│
├── core/
│   ├── ssh_client.py        # Paramiko SSH — TOFU policy, dual-strategy connect
│   ├── database.py          # SQLite layer — devices, audit log, host keys
│   ├── credentials.py       # Windows DPAPI credential vault
│   ├── firmware.py          # FTP firmware upload
│   └── network.py           # Ping + TCP port check
│
├── gui/
│   ├── main_window.py       # Main application window
│   └── dialogs.py           # All dialogs: device CRUD, connect, firmware,
│                            #   audit viewer, credential manager, TOFU prompts
│
├── vendor/                  # Pre-downloaded Windows wheels (air-gapped install)
│
├── setup.bat                # ← Run once: creates venv, installs deps, desktop shortcut
├── launch.bat               # ← Run every time (or use the desktop shortcut)
├── build.bat                # Compile to APC_NMC_Tool.exe via PyInstaller
├── apc_tool.spec            # PyInstaller build spec
└── requirements.txt         # Pinned runtime dependencies
```

---

## 🔨 Building the `.exe`

To distribute a single standalone executable (no Python required on target):

```bat
.venv\Scripts\activate
build.bat
```

Output: `dist\APC_NMC_Tool.exe`

The `.exe` is a single-file Windows binary. Copy it anywhere — no Python, no venv, no dependencies needed. The database (`apc_devices.db`) is created next to the `.exe` on first run.

> **Tip:** Drop an `icon.ico` in the project root before building to embed a custom icon.

---

## ⌨️ Available Actions (when connected)

| Action | APC CLI Command |
|---|---|
| System Info | `about` |
| Network Settings | `tcpip` |
| Change IP / Subnet / Gateway | `tcpip -i … -s … -g …` |
| Change Password | `user -n … -pw …` |
| Reboot Card | `reboot` → `YES` |
| Firmware Update | FTP upload wizard |
| Set System Name | `system -n …` |
| Set Location | `system -l …` |
| Set Contact | `system -c …` |
| View Event Log | `eventlog` |
| UPS Status | `ups` |
| DNS Settings | `dns` |
| Manual Command | raw CLI input |
