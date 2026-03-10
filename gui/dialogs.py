"""
gui/dialogs.py — All dialog / secondary window classes.

Dialogs:
  DeviceDialog          — Add or edit a device record
  MultiInputDialog      — Generic multi-field form used for IP change etc.
  ConfirmDialog         — Simple yes/no confirmation
  ConnectDialog         — Username + password prompt before connecting
  FirmwareDialog        — Firmware update wizard with progress bar
  AuditViewerWindow     — Full-screen audit log viewer with search/filter/export
  CredentialManagerWindow — View, add, and delete stored credentials
  HostKeyDialog         — First-time SSH host key acceptance (TOFU)
  HostKeyChangedDialog  — Fingerprint-changed alert (blocks connection by default)
"""

import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable, Dict, List, Optional, Tuple

import customtkinter as ctk

import core.credentials as creds
import core.database as db
from core.firmware import FirmwareError, FirmwareUploader


# ── Shared styling constants ─────────────────────────────────────────── #
_MONO = ("Consolas", 11)
_SANS = ("Segoe UI", 11)
_SANS_SM = ("Segoe UI", 10)

# Strict IPv4 validation — four octets 0-255, dots only
_IPV4_RE = re.compile(
    r"^((25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)\.){3}"
    r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)$"
)


def is_valid_ipv4(ip: str) -> bool:
    return bool(_IPV4_RE.match(ip.strip()))


# ─────────────────────────────────────────────────────────────────────── #
#  DeviceDialog                                                           #
# ─────────────────────────────────────────────────────────────────────── #

class DeviceDialog(ctk.CTkToplevel):
    """Add or edit a device. Returns via on_save(device_dict) callback."""

    CARD_TYPES = ["NMC2", "NMC3", "NMC (gen 1)"]

    def __init__(self, master, device: Optional[Dict] = None,
                 on_save: Optional[Callable] = None):
        super().__init__(master)
        self._device = device
        self._on_save = on_save
        self._is_edit = device is not None

        self.title("Edit Device" if self._is_edit else "Add Device")
        self.geometry("420x400")
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()
        self.bind("<Return>", lambda _: self._save())

        self._build()

        if self._is_edit:
            self._populate(device)

    def _build(self):
        pad = {"padx": 20, "pady": 6}

        ctk.CTkLabel(self, text="Device Name *", font=_SANS_SM, anchor="w").pack(fill="x", **pad)
        self._name = ctk.CTkEntry(self, placeholder_text="e.g. MAIN-UPS-01")
        self._name.pack(fill="x", **pad)

        ctk.CTkLabel(self, text="IP Address *", font=_SANS_SM, anchor="w").pack(fill="x", **pad)
        self._ip = ctk.CTkEntry(self, placeholder_text="e.g. 192.168.1.100")
        self._ip.pack(fill="x", **pad)

        ctk.CTkLabel(self, text="Card Type", font=_SANS_SM, anchor="w").pack(fill="x", **pad)
        self._card_type = ctk.CTkComboBox(self, values=self.CARD_TYPES)
        self._card_type.set("NMC2")
        self._card_type.pack(fill="x", **pad)

        ctk.CTkLabel(self, text="Location", font=_SANS_SM, anchor="w").pack(fill="x", **pad)
        self._location = ctk.CTkEntry(self, placeholder_text="e.g. Server Room A")
        self._location.pack(fill="x", **pad)

        ctk.CTkLabel(self, text="Notes", font=_SANS_SM, anchor="w").pack(fill="x", **pad)
        self._notes = ctk.CTkEntry(self, placeholder_text="Optional notes")
        self._notes.pack(fill="x", **pad)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(16, 20))
        ctk.CTkButton(btn_frame, text="Cancel", width=100,
                      fg_color="transparent", border_width=1,
                      command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_frame, text="Save", width=100,
                      command=self._save).pack(side="right")

    def _populate(self, d: Dict):
        self._name.insert(0, d.get("name", ""))
        self._ip.insert(0, d.get("ip", ""))
        self._card_type.set(d.get("card_type", "NMC2"))
        self._location.insert(0, d.get("location", ""))
        self._notes.insert(0, d.get("notes", ""))

    def _save(self):
        name = self._name.get().strip().upper()
        ip = self._ip.get().strip()
        if not name or not ip:
            messagebox.showerror("Validation", "Device Name and IP are required.", parent=self)
            return
        if not is_valid_ipv4(ip):
            messagebox.showerror(
                "Invalid IP",
                f"'{ip}' is not a valid IPv4 address.\nExpected format: 192.168.1.100",
                parent=self,
            )
            return

        payload = {
            "name": name,
            "ip": ip,
            "card_type": self._card_type.get(),
            "location": self._location.get().strip(),
            "notes": self._notes.get().strip(),
        }

        if self._on_save:
            self._on_save(payload)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────── #
#  MultiInputDialog                                                       #
# ─────────────────────────────────────────────────────────────────────── #

class MultiInputDialog(ctk.CTkToplevel):
    """
    Generic multi-field form dialog.
    fields: list of (label, placeholder, is_password)
    Calls on_confirm({label: value, ...}) on submit.
    """

    def __init__(self, master, title: str,
                 fields: List[Tuple[str, str, bool]],
                 on_confirm: Optional[Callable] = None,
                 warning: str = ""):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()

        self._fields = fields
        self._on_confirm = on_confirm
        self._entries: Dict[str, ctk.CTkEntry] = {}

        self._build(warning)
        self.geometry(f"380x{140 + len(fields) * 68 + (40 if warning else 0)}")
        self.bind("<Return>", lambda _: self._confirm())

    def _build(self, warning: str):
        pad = {"padx": 20, "pady": 5}

        if warning:
            warn_frame = ctk.CTkFrame(self, fg_color="#5a1e1e", corner_radius=6)
            warn_frame.pack(fill="x", padx=20, pady=(16, 4))
            ctk.CTkLabel(warn_frame, text=f"⚠  {warning}",
                         font=_SANS_SM, text_color="#ff9090",
                         wraplength=320).pack(padx=10, pady=8)

        for label, placeholder, is_pw in self._fields:
            ctk.CTkLabel(self, text=label, font=_SANS_SM, anchor="w").pack(fill="x", **pad)
            entry = ctk.CTkEntry(
                self,
                placeholder_text=placeholder,
                show="●" if is_pw else "",
            )
            entry.pack(fill="x", **pad)
            self._entries[label] = entry

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(14, 20))
        ctk.CTkButton(btn_frame, text="Cancel", width=90,
                      fg_color="transparent", border_width=1,
                      command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_frame, text="Apply", width=90,
                      command=self._confirm).pack(side="right")

    def _confirm(self):
        values = {}
        for label, entry in self._entries.items():
            is_pw = any(label == f[0] and f[2] for f in self._fields)
            values[label] = entry.get() if is_pw else entry.get().strip()
        if self._on_confirm:
            self._on_confirm(values)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────── #
#  ConfirmDialog                                                          #
# ─────────────────────────────────────────────────────────────────────── #

class ConfirmDialog(ctk.CTkToplevel):
    """Simple yes/no dialog. Calls on_confirm() when confirmed."""

    def __init__(self, master, title: str, message: str,
                 confirm_label: str = "Confirm",
                 on_confirm: Optional[Callable] = None,
                 danger: bool = False):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()
        self._on_confirm = on_confirm
        self.bind("<Return>", lambda _: self._confirm())

        self.geometry("360x180")

        ctk.CTkLabel(self, text=message, font=_SANS,
                     wraplength=320).pack(padx=20, pady=(24, 12))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=20, pady=(4, 20))

        ctk.CTkButton(btn_frame, text="Cancel", width=100,
                      fg_color="transparent", border_width=1,
                      command=self.destroy).pack(side="left", padx=(0, 8))

        fg = "#d32f2f" if danger else None
        ctk.CTkButton(btn_frame, text=confirm_label, width=100,
                      fg_color=fg, command=self._confirm).pack(side="left")

    def _confirm(self):
        if self._on_confirm:
            self._on_confirm()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────── #
#  ConnectDialog                                                          #
# ─────────────────────────────────────────────────────────────────────── #

class ConnectDialog(ctk.CTkToplevel):
    """Prompt for username + password before connecting."""

    def __init__(self, master, device_name: str, ip: str,
                 prefill_user: str = "", prefill_pass: str = "",
                 on_connect: Optional[Callable] = None):
        super().__init__(master)
        self.title(f"Connect — {device_name}")
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()
        self._on_connect = on_connect
        self.geometry("380x300")

        pad = {"padx": 20, "pady": 6}

        ctk.CTkLabel(self, text=f"Connecting to  {device_name}  ({ip})",
                     font=_SANS, wraplength=340).pack(pady=(20, 4))

        ctk.CTkLabel(self, text="Username", font=_SANS_SM, anchor="w").pack(fill="x", **pad)
        self._user = ctk.CTkEntry(self, placeholder_text="apc")
        self._user.pack(fill="x", **pad)
        if prefill_user:
            self._user.insert(0, prefill_user)

        ctk.CTkLabel(self, text="Password", font=_SANS_SM, anchor="w").pack(fill="x", **pad)
        self._pw = ctk.CTkEntry(self, show="●", placeholder_text="password")
        self._pw.pack(fill="x", **pad)
        if prefill_pass:
            self._pw.insert(0, prefill_pass)

        self._save_var = tk.BooleanVar(value=bool(prefill_user))
        ctk.CTkCheckBox(self, text="Remember credentials for this device",
                        variable=self._save_var).pack(pady=4)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=(8, 20))
        ctk.CTkButton(btn_frame, text="Cancel", width=100,
                      fg_color="transparent", border_width=1,
                      command=self.destroy).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_frame, text="Connect  ⚡", width=120,
                      command=self._do_connect).pack(side="left")

        self._pw.bind("<Return>", lambda _: self._do_connect())

    def _do_connect(self):
        username = self._user.get().strip()
        password = self._pw.get()
        if not username:
            messagebox.showerror("Missing Input", "Username is required.", parent=self)
            return
        if self._on_connect:
            self._on_connect(username, password, self._save_var.get())
        self.destroy()


# ─────────────────────────────────────────────────────────────────────── #
#  FirmwareDialog                                                         #
# ─────────────────────────────────────────────────────────────────────── #

class FirmwareDialog(ctk.CTkToplevel):
    """Firmware update wizard: select .bin files, enter FTP credentials, upload."""

    def __init__(self, master, ip: str, prefill_user: str = "",
                 on_complete: Optional[Callable[[List[str]], None]] = None):
        super().__init__(master)
        self.title("Firmware Update")
        self.geometry("520x560")
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()

        self._ip = ip
        self._files: List[str] = []
        self._uploader = FirmwareUploader()
        self._on_complete = on_complete  # called with list of uploaded filenames

        self._build(prefill_user)

    def _build(self, prefill_user: str):
        pad = {"padx": 20, "pady": 5}

        # Security warning — FTP is plaintext
        sec_warn = ctk.CTkFrame(self, fg_color="#5a1e00", corner_radius=6)
        sec_warn.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(
            sec_warn,
            text=(
                "⚠  SECURITY WARNING: FTP transmits credentials and firmware\n"
                "in CLEARTEXT over the network. Ensure this laptop is connected\n"
                "directly to the device or on an isolated, trusted network segment.\n"
                "Do NOT perform firmware updates over shared or public networks."
            ),
            font=_SANS_SM, text_color="#ffaa66", justify="left", wraplength=460,
        ).pack(padx=12, pady=8)

        # Info banner
        info = ctk.CTkFrame(self, fg_color="#1a3a4a", corner_radius=6)
        info.pack(fill="x", padx=20, pady=(16, 4))
        ctk.CTkLabel(
            info,
            text=(
                "Upload firmware .bin files to the APC NMC via FTP.\n"
                "The device validates, applies firmware, and auto-reboots.\n"
                "Expected filenames:  apc_hw09_aos_*.bin  /  apc_hw09_sumx_*.bin"
            ),
            font=_SANS_SM, justify="left", wraplength=460,
        ).pack(padx=12, pady=8)

        # Credentials
        ctk.CTkLabel(self, text="FTP Credentials", font=("Segoe UI", 12, "bold"),
                     anchor="w").pack(fill="x", padx=20, pady=(12, 2))

        ctk.CTkLabel(self, text="Username", font=_SANS_SM, anchor="w").pack(fill="x", **pad)
        self._user = ctk.CTkEntry(self)
        self._user.pack(fill="x", **pad)
        if prefill_user:
            self._user.insert(0, prefill_user)

        ctk.CTkLabel(self, text="Password", font=_SANS_SM, anchor="w").pack(fill="x", **pad)
        self._pw = ctk.CTkEntry(self, show="●")
        self._pw.pack(fill="x", **pad)
        self._pw.bind("<Return>", lambda _: self._start_upload())

        # File selection
        ctk.CTkLabel(self, text="Firmware Files", font=("Segoe UI", 12, "bold"),
                     anchor="w").pack(fill="x", padx=20, pady=(12, 2))

        file_row = ctk.CTkFrame(self, fg_color="transparent")
        file_row.pack(fill="x", padx=20, pady=4)
        ctk.CTkButton(file_row, text="Browse…", width=90,
                      command=self._browse).pack(side="left")
        ctk.CTkButton(file_row, text="Clear", width=60,
                      fg_color="transparent", border_width=1,
                      command=self._clear_files).pack(side="left", padx=(8, 0))

        self._file_list = ctk.CTkTextbox(self, height=70, font=_MONO)
        self._file_list.pack(fill="x", padx=20, pady=(4, 4))
        self._file_list.configure(state="disabled")

        # Progress
        self._progress_label = ctk.CTkLabel(self, text="", font=_SANS_SM)
        self._progress_label.pack(fill="x", padx=20, pady=(8, 2))
        self._progress_bar = ctk.CTkProgressBar(self)
        self._progress_bar.set(0)
        self._progress_bar.pack(fill="x", padx=20, pady=(0, 8))

        self._status = ctk.CTkTextbox(self, height=90, font=_MONO)
        self._status.pack(fill="x", padx=20, pady=(0, 8))
        self._status.configure(state="disabled")

        # Upload button
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkButton(btn_row, text="Cancel", width=90,
                      fg_color="transparent", border_width=1,
                      command=self.destroy).pack(side="right", padx=(8, 0))
        self._upload_btn = ctk.CTkButton(btn_row, text="⬆  Upload Firmware",
                                         width=160, command=self._start_upload)
        self._upload_btn.pack(side="right")

    def _browse(self):
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Select Firmware .bin Files",
            filetypes=[("APC Firmware", "*.bin"), ("All Files", "*.*")],
        )
        if paths:
            self._files = list(paths)
            self._file_list.configure(state="normal")
            self._file_list.delete("1.0", "end")
            for p in self._files:
                self._file_list.insert("end", os.path.basename(p) + "\n")
            self._file_list.configure(state="disabled")

    def _clear_files(self):
        self._files = []
        self._file_list.configure(state="normal")
        self._file_list.delete("1.0", "end")
        self._file_list.configure(state="disabled")

    def _append_status(self, msg: str):
        self._status.configure(state="normal")
        self._status.insert("end", msg + "\n")
        self._status.see("end")
        self._status.configure(state="disabled")

    def _start_upload(self):
        username = self._user.get().strip()
        password = self._pw.get()

        if not username:
            messagebox.showerror("Missing Input", "Username is required.", parent=self)
            return
        if not self._files:
            messagebox.showerror("No Files", "Select at least one firmware .bin file.", parent=self)
            return

        self._upload_btn.configure(state="disabled", text="Uploading…")
        self._progress_bar.set(0)

        threading.Thread(
            target=self._do_upload,
            args=(username, password),
            daemon=True,
        ).start()

    def _do_upload(self, username: str, password: str):
        def on_progress(filename, pct, done, total):
            self.after(0, lambda: self._progress_label.configure(
                text=f"{filename}  —  {done // 1024} / {total // 1024} KB  ({pct:.0f}%)"
            ))
            self.after(0, lambda: self._progress_bar.set(pct / 100))

        def on_status(msg: str):
            self.after(0, lambda: self._append_status(msg))

        try:
            self._uploader.upload(
                ip=self._ip,
                username=username,
                password=password,
                firmware_files=self._files,
                on_progress=on_progress,
                on_status=on_status,
            )
            uploaded_names = [os.path.basename(f) for f in self._files]
            self.after(0, lambda: self._progress_bar.set(1.0))
            self.after(0, lambda: self._append_status("\n✅  Upload complete."))
            if self._on_complete:
                self.after(0, lambda: self._on_complete(uploaded_names))
        except (FirmwareError, Exception) as e:
            self.after(0, lambda: self._append_status(f"\n❌  Error: {e}"))
        finally:
            self.after(0, lambda: self._upload_btn.configure(
                state="normal", text="⬆  Upload Firmware"
            ))


# ─────────────────────────────────────────────────────────────────────── #
#  AuditViewerWindow                                                      #
# ─────────────────────────────────────────────────────────────────────── #

class AuditViewerWindow(ctk.CTkToplevel):
    """Full audit log viewer with search, filter, and CSV export."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Audit Log")
        self.geometry("900x580")
        self.grab_set()
        self._build()
        self._load()

    def _build(self):
        # Toolbar
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(toolbar, text="Search:", font=_SANS_SM).pack(side="left")
        self._search = ctk.CTkEntry(toolbar, width=220, placeholder_text="device, IP, action…")
        self._search.pack(side="left", padx=(4, 8))
        self._search.bind("<Return>", lambda _: self._load())

        ctk.CTkButton(toolbar, text="Search", width=80,
                      command=self._load).pack(side="left", padx=(0, 16))

        ctk.CTkButton(toolbar, text="Export CSV", width=100,
                      fg_color="transparent", border_width=1,
                      command=self._export).pack(side="right", padx=(8, 0))
        ctk.CTkButton(toolbar, text="Clear Log", width=90,
                      fg_color="#7a1f1f", hover_color="#a33030",
                      command=self._clear).pack(side="right")

        # Table header
        hdr = ctk.CTkFrame(self, fg_color=("#2b2b2b", "#1a1a1a"))
        hdr.pack(fill="x", padx=12)
        for text, w in [("Timestamp", 160), ("Device", 120), ("IP", 110),
                        ("User", 80), ("Action", 160), ("Details", 200), ("Result", 70)]:
            ctk.CTkLabel(hdr, text=text, font=("Segoe UI", 10, "bold"),
                         width=w, anchor="w").pack(side="left", padx=4)

        # Scrollable rows
        self._scroll = ctk.CTkScrollableFrame(self)
        self._scroll.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Status bar
        self._status_lbl = ctk.CTkLabel(self, text="", font=_SANS_SM, anchor="w")
        self._status_lbl.pack(fill="x", padx=14, pady=(0, 6))

    def _load(self):
        search = self._search.get().strip() or None
        rows = db.get_audit_log(limit=200, search=search)

        # Clear existing rows
        for w in self._scroll.winfo_children():
            w.destroy()

        result_colors = {"success": "#3fb950", "failure": "#f85149", "warning": "#d29922"}

        for i, row in enumerate(rows):
            bg = ("#1e1e1e", "#141414") if i % 2 == 0 else ("#232323", "#181818")
            r = ctk.CTkFrame(self._scroll, fg_color=bg, corner_radius=0)
            r.pack(fill="x")

            rc = result_colors.get(row.get("result", ""), "#aaaaaa")
            for text, w in [
                (row.get("timestamp", "")[:19], 160),
                (row.get("device_name", ""), 120),
                (row.get("ip", ""), 110),
                (row.get("username", ""), 80),
                (row.get("action", ""), 160),
                (row.get("details", ""), 200),
            ]:
                ctk.CTkLabel(r, text=str(text), font=_SANS_SM,
                             width=w, anchor="w").pack(side="left", padx=4)

            ctk.CTkLabel(r, text=row.get("result", ""), font=_SANS_SM,
                         width=70, text_color=rc, anchor="w").pack(side="left", padx=4)

        self._status_lbl.configure(
            text=f"{len(rows)} entries shown  (max 200 per view — use search to narrow)"
        )

    def _export(self):
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="apc_audit_log.csv",
        )
        if path:
            count = db.export_audit_csv(path)
            messagebox.showinfo("Exported", f"{count} records written to:\n{path}", parent=self)

    def _clear(self):
        if messagebox.askyesno("Clear Audit Log",
                               "Permanently delete all audit log entries?\nThis cannot be undone.",
                               parent=self):
            db.clear_audit_log()
            self._load()


# ─────────────────────────────────────────────────────────────────────── #
#  CredentialManagerWindow                                                #
# ─────────────────────────────────────────────────────────────────────── #

class CredentialManagerWindow(ctk.CTkToplevel):
    """View and manage stored credentials."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Credential Manager")
        self.geometry("480x440")
        self.resizable(False, False)
        self.grab_set()
        self._build()
        self._load()

    def _build(self):
        ctk.CTkLabel(self, text="Saved Credentials",
                     font=("Segoe UI", 13, "bold")).pack(pady=(16, 4))
        ctk.CTkLabel(
            self,
            text="Credentials are encrypted with Windows DPAPI\n"
                 "(tied to your Windows user account — cannot be read by others).",
            font=_SANS_SM, justify="center",
        ).pack(padx=20, pady=(0, 8))

        self._list = ctk.CTkScrollableFrame(self, height=160)
        self._list.pack(fill="x", padx=20, pady=(0, 12))

        # Add new credential section
        sep = ctk.CTkFrame(self, height=1, fg_color="gray50")
        sep.pack(fill="x", padx=20, pady=4)

        ctk.CTkLabel(self, text="Add / Update Credential",
                     font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", padx=20, pady=(6, 2))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=20, pady=4)

        ctk.CTkLabel(form, text="Device Name:", font=_SANS_SM, width=100, anchor="w").grid(row=0, column=0)
        self._dev_entry = ctk.CTkEntry(form, width=180)
        self._dev_entry.grid(row=0, column=1, padx=(4, 0))

        ctk.CTkLabel(form, text="Username:", font=_SANS_SM, width=100, anchor="w").grid(row=1, column=0, pady=(6, 0))
        self._user_entry = ctk.CTkEntry(form, width=180)
        self._user_entry.grid(row=1, column=1, padx=(4, 0), pady=(6, 0))

        ctk.CTkLabel(form, text="Password:", font=_SANS_SM, width=100, anchor="w").grid(row=2, column=0, pady=(6, 0))
        self._pass_entry = ctk.CTkEntry(form, show="●", width=180)
        self._pass_entry.grid(row=2, column=1, padx=(4, 0), pady=(6, 0))
        self._pass_entry.bind("<Return>", lambda _: self._save())

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(8, 16))
        ctk.CTkButton(btn_row, text="Save Credential", width=130,
                      command=self._save).pack(side="left")
        ctk.CTkButton(btn_row, text="Close", width=80,
                      fg_color="transparent", border_width=1,
                      command=self.destroy).pack(side="right")

    def _load(self):
        for w in self._list.winfo_children():
            w.destroy()

        saved = creds.list_saved_devices()
        if not saved:
            ctk.CTkLabel(self._list, text="No credentials saved yet.",
                         font=_SANS_SM, text_color="gray50").pack(pady=8)
            return

        for device_name in saved:
            row = ctk.CTkFrame(self._list, fg_color="transparent")
            row.pack(fill="x", pady=2)
            cred = creds.get_credential(device_name)
            username = cred[0] if cred else "unknown"
            display = f"{'(default)' if device_name == '__global__' else device_name}  —  {username}"
            ctk.CTkLabel(row, text=display, font=_SANS_SM, anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                row, text="Delete", width=60, height=24,
                fg_color="#7a1f1f", hover_color="#a33030",
                command=lambda n=device_name: self._delete(n),
            ).pack(side="right")

    def _save(self):
        device = self._dev_entry.get().strip().upper() or "__global__"
        user = self._user_entry.get().strip()
        pw = self._pass_entry.get()
        if not user or not pw:
            messagebox.showerror("Missing Input", "Username and password are required.", parent=self)
            return
        creds.save_credential(device, user, pw)
        self._load()
        self._dev_entry.delete(0, "end")
        self._user_entry.delete(0, "end")
        self._pass_entry.delete(0, "end")

    def _delete(self, device_name: str):
        if messagebox.askyesno("Delete Credential",
                               f"Delete saved credential for '{device_name}'?", parent=self):
            creds.delete_credential(device_name)
            self._load()


# ─────────────────────────────────────────────────────────────────────── #
#  FirstRunDialog                                                          #
# ─────────────────────────────────────────────────────────────────────── #

class FirstRunDialog(ctk.CTkToplevel):
    """
    Shown on first launch when the device database is empty.
    Gives the operator three choices:
      1. Import an existing apc_devices.db file
      2. Add devices now (opens AddDevice dialog after close)
      3. Start empty / skip
    """

    def __init__(self, master,
                 on_import: Callable[[str], None],
                 on_add_device: Callable[[], None],
                 on_skip: Callable[[], None]):
        super().__init__(master)
        self.title("Welcome — APC NMC Field Tool")
        self.geometry("520x400")
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()
        self.protocol("WM_DELETE_WINDOW", self._skip)

        self._on_import = on_import
        self._on_add = on_add_device
        self._on_skip = on_skip

        self._build()

    def _build(self):
        # Header
        ctk.CTkLabel(
            self, text="🔌  Welcome to APC NMC Field Tool",
            font=("Segoe UI", 15, "bold"),
        ).pack(pady=(28, 4))
        ctk.CTkLabel(
            self,
            text="No devices found in the database.\nChoose how you'd like to get started:",
            font=_SANS_SM, text_color="gray60", justify="center",
        ).pack(pady=(0, 24))

        # Option 1 — Import
        opt1 = ctk.CTkFrame(self, fg_color=("#1a2a1a", "#0d1a0d"), corner_radius=8)
        opt1.pack(fill="x", padx=28, pady=(0, 10))
        inner1 = ctk.CTkFrame(opt1, fg_color="transparent")
        inner1.pack(fill="x", padx=16, pady=12)
        ctk.CTkLabel(
            inner1, text="📂  Import an existing database",
            font=("Segoe UI", 11, "bold"), anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            inner1,
            text="Already have an apc_devices.db from another machine? Import it here.",
            font=_SANS_SM, text_color="gray60", anchor="w", wraplength=400,
        ).pack(anchor="w", pady=(2, 8))
        ctk.CTkButton(
            inner1, text="Browse for .db file…", width=160,
            command=self._browse_import,
        ).pack(anchor="w")

        # Option 2 — Add device
        opt2 = ctk.CTkFrame(self, fg_color=("#1a1a2a", "#0d0d1a"), corner_radius=8)
        opt2.pack(fill="x", padx=28, pady=(0, 10))
        inner2 = ctk.CTkFrame(opt2, fg_color="transparent")
        inner2.pack(fill="x", padx=16, pady=12)
        ctk.CTkLabel(
            inner2, text="➕  Add devices now",
            font=("Segoe UI", 11, "bold"), anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            inner2,
            text="Start building your device list. You can add more devices at any time.",
            font=_SANS_SM, text_color="gray60", anchor="w", wraplength=400,
        ).pack(anchor="w", pady=(2, 8))
        ctk.CTkButton(
            inner2, text="Add first device…", width=160,
            command=self._add_device,
        ).pack(anchor="w")

        # Skip
        ctk.CTkButton(
            self, text="Skip — start with empty database",
            fg_color="transparent", border_width=1,
            font=_SANS_SM, width=220,
            command=self._skip,
        ).pack(pady=(4, 24))

    def _browse_import(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Select APC Devices Database",
            filetypes=[("SQLite Database", "*.db"), ("All Files", "*.*")],
        )
        if path:
            self.grab_release()
            self.destroy()
            self._on_import(path)

    def _add_device(self):
        self.grab_release()
        self.destroy()
        self._on_add()

    def _skip(self):
        self.grab_release()
        self.destroy()
        self._on_skip()


# ─────────────────────────────────────────────────────────────────────── #
#  HostKeyDialog — TOFU first-time accept                                 #
# ─────────────────────────────────────────────────────────────────────── #

class HostKeyDialog(ctk.CTkToplevel):
    """
    Shown on first connection to a device.
    The operator must explicitly review and accept the SSH host key fingerprint.
    Calls on_accept() or on_reject() and destroys itself.
    """

    def __init__(self, master, ip: str, key_type: str, fingerprint: str,
                 on_accept, on_reject):
        super().__init__(master)
        self.title("Verify SSH Host Key")
        self.geometry("500x320")
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()
        self.protocol("WM_DELETE_WINDOW", self._reject)

        self._on_accept = on_accept
        self._on_reject = on_reject

        ctk.CTkLabel(self, text="🔑  New SSH Host Key", font=("Segoe UI", 14, "bold")).pack(pady=(20, 4))
        ctk.CTkLabel(
            self,
            text=(
                f"This is the first connection to  {ip}.\n"
                "Verify the fingerprint below with the device label or the APC\n"
                "management console before accepting."
            ),
            font=_SANS_SM, justify="center", wraplength=450,
        ).pack(padx=20, pady=(0, 10))

        fp_frame = ctk.CTkFrame(self, fg_color="#0d1117", corner_radius=6)
        fp_frame.pack(fill="x", padx=24, pady=4)
        ctk.CTkLabel(fp_frame, text="Host:", font=_SANS_SM, width=80, anchor="w").grid(row=0, column=0, padx=10, pady=4)
        ctk.CTkLabel(fp_frame, text=ip, font=_MONO, anchor="w").grid(row=0, column=1, sticky="w", pady=4)
        ctk.CTkLabel(fp_frame, text="Key type:", font=_SANS_SM, width=80, anchor="w").grid(row=1, column=0, padx=10)
        ctk.CTkLabel(fp_frame, text=key_type, font=_MONO, anchor="w").grid(row=1, column=1, sticky="w")
        ctk.CTkLabel(fp_frame, text="SHA256:", font=_SANS_SM, width=80, anchor="w").grid(row=2, column=0, padx=10, pady=4)
        ctk.CTkLabel(fp_frame, text=fingerprint, font=_MONO, text_color="#58a6ff",
                     wraplength=350, anchor="w").grid(row=2, column=1, sticky="w", pady=4)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(16, 20))
        ctk.CTkButton(btn_row, text="✕  Reject (Safe)", width=130,
                      fg_color="#7a1f1f", hover_color="#a33030",
                      command=self._reject).pack(side="left", padx=(0, 12))
        ctk.CTkButton(btn_row, text="✓  Accept & Trust", width=130,
                      command=self._accept).pack(side="left")

    def _accept(self):
        self.grab_release()
        self.destroy()
        self._on_accept()

    def _reject(self):
        self.grab_release()
        self.destroy()
        self._on_reject()


# ─────────────────────────────────────────────────────────────────────── #
#  HostKeyChangedDialog — fingerprint mismatch / possible MITM            #
# ─────────────────────────────────────────────────────────────────────── #

class HostKeyChangedDialog(ctk.CTkToplevel):
    """
    Shown when a device presents a DIFFERENT host key fingerprint than the
    one previously stored. Default action is to BLOCK the connection.
    The operator must explicitly override after physically verifying the device.
    """

    def __init__(self, master, ip: str, key_type: str,
                 new_fingerprint: str, stored_fingerprint: str,
                 on_accept, on_reject):
        super().__init__(master)
        self.title("⚠  HOST KEY MISMATCH — Possible MITM Attack")
        self.geometry("540x420")
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()
        self.protocol("WM_DELETE_WINDOW", self._reject)

        self._on_accept = on_accept
        self._on_reject = on_reject

        # Red alert banner
        alert = ctk.CTkFrame(self, fg_color="#7a0000", corner_radius=0)
        alert.pack(fill="x")
        ctk.CTkLabel(
            alert,
            text="⚠  WARNING: SSH HOST KEY HAS CHANGED  ⚠",
            font=("Segoe UI", 13, "bold"), text_color="#ff9090",
        ).pack(pady=12)

        ctk.CTkLabel(
            self,
            text=(
                f"The SSH host key fingerprint for  {ip}  no longer matches\n"
                "the value stored in the database from the previous connection.\n\n"
                "This MAY indicate:\n"
                "  • The NMC card was replaced or re-imaged (legitimate)\n"
                "  • A man-in-the-middle (MITM) attack (serious security threat)\n\n"
                "DO NOT accept unless you have physically verified the device."
            ),
            font=_SANS_SM, justify="left", wraplength=490,
        ).pack(padx=20, pady=(12, 6))

        fp_frame = ctk.CTkFrame(self, fg_color="#0d1117", corner_radius=6)
        fp_frame.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(fp_frame, text="Stored (trusted):", font=_SANS_SM, width=140, anchor="w").grid(row=0, column=0, padx=10, pady=4)
        ctk.CTkLabel(fp_frame, text=stored_fingerprint, font=_MONO,
                     text_color="#3fb950", wraplength=320, anchor="w").grid(row=0, column=1, sticky="w", pady=4)
        ctk.CTkLabel(fp_frame, text="Presented (new):", font=_SANS_SM, width=140, anchor="w").grid(row=1, column=0, padx=10, pady=4)
        ctk.CTkLabel(fp_frame, text=new_fingerprint, font=_MONO,
                     text_color="#f85149", wraplength=320, anchor="w").grid(row=1, column=1, sticky="w", pady=4)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(16, 20))
        ctk.CTkButton(btn_row, text="🔒  Block Connection (Safe)", width=180,
                      fg_color="#7a1f1f", hover_color="#a33030",
                      command=self._reject).pack(side="left", padx=(0, 12))
        ctk.CTkButton(btn_row, text="Override & Trust New Key", width=180,
                      fg_color="#3a3a00", hover_color="#5a5a00",
                      command=self._accept).pack(side="left")

    def _accept(self):
        self.grab_release()
        self.destroy()
        self._on_accept()

    def _reject(self):
        self.grab_release()
        self.destroy()
        self._on_reject()
