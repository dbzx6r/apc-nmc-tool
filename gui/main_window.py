"""
gui/main_window.py — Main application window.

Layout:
  ┌──────────────────────────────────────────────────────────────────┐
  │ sidebar (280px)          │  content area (fills rest)           │
  │  ├─ title                │   ├─ info bar (connection status)     │
  │  ├─ device list          │   ├─ action buttons                   │
  │  ├─ device CRUD buttons  │   ├─ terminal output (scrolling)      │
  │  └─ quick connect form   │   └─ command input row                │
  ├──────────────────────────┴──────────────────────────────────────┤
  │  status bar                                                      │
  └──────────────────────────────────────────────────────────────────┘
"""

import os
import shutil
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Dict, List, Optional

import customtkinter as ctk

import core.credentials as creds
import core.database as db
import core.network as net
from core.ssh_client import APCSSHClient
from gui.dialogs import (
    AuditViewerWindow,
    ConfirmDialog,
    ConnectDialog,
    CredentialManagerWindow,
    DeviceDialog,
    FirstRunDialog,
    FirmwareDialog,
    HostKeyChangedDialog,
    HostKeyDialog,
    MultiInputDialog,
    is_valid_ipv4,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

_MONO = ("Consolas", 11)
_SANS = ("Segoe UI", 11)
_SANS_SM = ("Segoe UI", 10)

# Terminal colour tags
_TAG_CMD = "cmd"        # sent commands  → blue
_TAG_ERR = "err"        # error text     → red
_TAG_OK  = "ok"         # success        → green
_TAG_WARN = "warn"      # warning        → orange


class APCToolApp(ctk.CTk):

    # ── Init ─────────────────────────────────────────────────────────── #

    def __init__(self):
        super().__init__()

        self.title("APC NMC Field Tool")
        self.geometry("1280x780")
        self.minsize(960, 620)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        db.initialize_db()

        self._ssh: Optional[APCSSHClient] = None
        self._current_device: Optional[Dict] = None
        self._current_user: str = ""
        self._selected_device_id: Optional[int] = None
        self._device_btns: Dict[int, ctk.CTkButton] = {}

        self._build_layout()
        self._refresh_device_list()
        self._set_connected_state(False)
        self._update_status_bar()

        # Show first-run wizard if the device list is empty
        if db.get_device_count() == 0:
            self.after(300, self._show_first_run)

    # ── Layout builders ──────────────────────────────────────────────── #

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._sidebar = ctk.CTkFrame(self, width=284, corner_radius=0)
        self._sidebar.grid(row=0, column=0, sticky="nsew")
        self._sidebar.grid_propagate(False)

        right = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self._build_sidebar()
        self._build_info_bar(right)
        self._build_actions(right)
        self._build_terminal(right)
        self._build_statusbar()

    # ── Sidebar ──────────────────────────────────────────────────────── #

    def _build_sidebar(self):
        s = self._sidebar

        # Title
        ctk.CTkLabel(
            s, text="🔌  APC NMC Field Tool",
            font=("Segoe UI", 14, "bold"),
        ).pack(pady=(20, 2), padx=12, anchor="w")
        ctk.CTkLabel(s, text="Network Management Card Programmer",
                     font=_SANS_SM, text_color="gray60").pack(padx=12, anchor="w")

        ctk.CTkFrame(s, height=1, fg_color="gray30").pack(fill="x", padx=12, pady=(12, 8))

        # Devices label + audit button
        row = ctk.CTkFrame(s, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(row, text="DEVICES", font=("Segoe UI", 10, "bold"),
                     text_color="gray60").pack(side="left")
        ctk.CTkButton(row, text="Audit Log", width=76, height=22, font=_SANS_SM,
                      fg_color="transparent", border_width=1,
                      command=self._open_audit_viewer).pack(side="right")

        # Search
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refresh_device_list())
        ctk.CTkEntry(s, textvariable=self._search_var,
                     placeholder_text="🔍  search devices…",
                     height=32).pack(fill="x", padx=12, pady=(0, 6))

        # Device list
        self._device_scroll = ctk.CTkScrollableFrame(s, height=240)
        self._device_scroll.pack(fill="x", padx=8, pady=(0, 4))

        # CRUD buttons
        crud = ctk.CTkFrame(s, fg_color="transparent")
        crud.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkButton(crud, text="＋ Add", width=68, height=28, font=_SANS_SM,
                      command=self._add_device).pack(side="left", padx=(0, 4))
        self._edit_btn = ctk.CTkButton(crud, text="✎ Edit", width=60, height=28, font=_SANS_SM,
                                       fg_color="transparent", border_width=1,
                                       command=self._edit_device, state="disabled")
        self._edit_btn.pack(side="left", padx=(0, 4))
        self._del_btn = ctk.CTkButton(crud, text="✕", width=36, height=28, font=_SANS_SM,
                                      fg_color="#7a1f1f", hover_color="#a33030",
                                      command=self._delete_device, state="disabled")
        self._del_btn.pack(side="left")

        ctk.CTkFrame(s, height=1, fg_color="gray30").pack(fill="x", padx=12, pady=(4, 10))

        # Quick connect
        ctk.CTkLabel(s, text="QUICK CONNECT", font=("Segoe UI", 10, "bold"),
                     text_color="gray60").pack(padx=12, anchor="w")

        ctk.CTkLabel(s, text="IP Address", font=_SANS_SM, anchor="w").pack(fill="x", padx=12, pady=(6, 0))
        self._quick_ip = ctk.CTkEntry(s, placeholder_text="192.168.1.100")
        self._quick_ip.pack(fill="x", padx=12, pady=(0, 4))

        ctk.CTkLabel(s, text="Username", font=_SANS_SM, anchor="w").pack(fill="x", padx=12, pady=(0, 0))
        self._quick_user = ctk.CTkEntry(s, placeholder_text="apc")
        self._quick_user.pack(fill="x", padx=12, pady=(0, 4))

        self._quick_connect_btn = ctk.CTkButton(
            s, text="⚡  Connect", height=34,
            command=self._quick_connect,
        )
        self._quick_connect_btn.pack(fill="x", padx=12, pady=(4, 0))

        ctk.CTkFrame(s, height=1, fg_color="gray30").pack(fill="x", padx=12, pady=(12, 6))

        # Bottom buttons
        ctk.CTkButton(s, text="🔑  Credential Manager", height=28, font=_SANS_SM,
                      fg_color="transparent", border_width=1,
                      command=self._open_credential_manager).pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkButton(s, text="📂  Import Database", height=28, font=_SANS_SM,
                      fg_color="transparent", border_width=1,
                      command=self._import_database).pack(fill="x", padx=12, pady=(0, 4))
        self._disconnect_btn = ctk.CTkButton(
            s, text="⏏  Disconnect", height=28, font=_SANS_SM,
            fg_color="#7a1f1f", hover_color="#a33030",
            command=self._disconnect, state="disabled",
        )
        self._disconnect_btn.pack(fill="x", padx=12, pady=(0, 14))

    # ── Info bar ─────────────────────────────────────────────────────── #

    def _build_info_bar(self, parent):
        self._info_bar = ctk.CTkFrame(parent, height=64, fg_color=("#1c2a1c", "#0d1a0d"),
                                      corner_radius=0)
        self._info_bar.grid(row=0, column=0, sticky="ew")
        self._info_bar.pack_propagate(False)

        self._info_status = ctk.CTkLabel(
            self._info_bar,
            text="⚫  No device connected — select a device from the sidebar or use Quick Connect.",
            font=_SANS, text_color="gray60",
        )
        self._info_status.pack(side="left", padx=16, pady=8)

        self._ping_lbl = ctk.CTkLabel(self._info_bar, text="", font=_SANS_SM, text_color="gray50")
        self._ping_lbl.pack(side="right", padx=16)

    # ── Action buttons ───────────────────────────────────────────────── #

    def _build_actions(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=("#1a1a2e", "#0f0f1e"), corner_radius=0)
        frame.grid(row=1, column=0, sticky="ew", pady=(1, 1))

        self._action_buttons: List[ctk.CTkButton] = []

        ACTIONS = [
            ("ℹ  System Info",     self._action_system_info),
            ("🌐  Network",        self._action_network),
            ("🔄  Change IP",      self._action_change_ip),
            ("🔑  Change Password",self._action_change_password),
            ("🔃  Reboot",         self._action_reboot),
            ("⬆  Firmware",       self._action_firmware),
            ("📝  System Name",    self._action_system_name),
            ("📌  Location",       self._action_location),
            ("👤  Contact",        self._action_contact),
            ("📋  Event Log",      self._action_event_log),
            ("📊  UPS Status",     self._action_ups_status),
            ("🔍  DNS Settings",   self._action_dns),
            ("❓  Help",           self._action_help),
            ("⌨  Manual Command",  self._action_manual),
        ]

        row_frame = None
        for i, (label, cmd) in enumerate(ACTIONS):
            if i % 7 == 0:
                row_frame = ctk.CTkFrame(frame, fg_color="transparent")
                row_frame.pack(fill="x", padx=8, pady=2)
            btn = ctk.CTkButton(
                row_frame, text=label, width=140, height=30, font=_SANS_SM,
                command=cmd,
            )
            btn.pack(side="left", padx=3, pady=2)
            self._action_buttons.append(btn)

    # ── Terminal ─────────────────────────────────────────────────────── #

    def _build_terminal(self, parent):
        term_frame = ctk.CTkFrame(parent, corner_radius=0, fg_color="transparent")
        term_frame.grid(row=2, column=0, sticky="nsew")
        term_frame.grid_rowconfigure(0, weight=1)
        term_frame.grid_columnconfigure(0, weight=1)

        # Header row
        hdr = ctk.CTkFrame(term_frame, height=30, fg_color=("#1a1a1a", "#111111"),
                           corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(hdr, text="Terminal Output", font=_SANS_SM, text_color="gray60",
                     anchor="w").pack(side="left", padx=12)
        ctk.CTkButton(hdr, text="Clear", width=60, height=22, font=_SANS_SM,
                      fg_color="transparent", border_width=1,
                      command=self._terminal_clear).pack(side="right", padx=8, pady=4)

        # Text area — inner _textbox is a standard tk.Text for tag support
        self._terminal = ctk.CTkTextbox(
            term_frame,
            font=_MONO,
            fg_color=("#0d1117", "#0d1117"),
            text_color="#e6edf3",
            corner_radius=0,
            wrap="char",
        )
        self._terminal.grid(row=1, column=0, sticky="nsew", padx=0)
        term_frame.grid_rowconfigure(1, weight=1)
        self._terminal.configure(state="disabled")

        # Configure colour tags on the underlying tk.Text
        self._terminal._textbox.tag_configure(_TAG_CMD,  foreground="#58a6ff")
        self._terminal._textbox.tag_configure(_TAG_ERR,  foreground="#f85149")
        self._terminal._textbox.tag_configure(_TAG_OK,   foreground="#3fb950")
        self._terminal._textbox.tag_configure(_TAG_WARN, foreground="#d29922")

        # Input row
        input_row = ctk.CTkFrame(term_frame, height=40, fg_color=("#181818", "#0c0c0c"),
                                 corner_radius=0)
        input_row.grid(row=2, column=0, sticky="ew")
        input_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(input_row, text="▶", font=_MONO,
                     text_color="#58a6ff").grid(row=0, column=0, sticky="w", padx=(10, 4))

        self._cmd_var = tk.StringVar()
        self._cmd_entry = ctk.CTkEntry(
            input_row, textvariable=self._cmd_var,
            placeholder_text="Enter command…",
            font=_MONO, height=32,
            border_width=0, fg_color="transparent",
        )
        self._cmd_entry.grid(row=0, column=0, sticky="ew", padx=(26, 4), pady=4)
        self._cmd_entry.bind("<Return>", lambda _: self._terminal_send())

        self._send_btn = ctk.CTkButton(
            input_row, text="Send", width=64, height=30,
            command=self._terminal_send,
        )
        self._send_btn.grid(row=0, column=1, padx=(0, 8))

    # ── Status bar ───────────────────────────────────────────────────── #

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, height=26, corner_radius=0,
                           fg_color=("#111111", "#080808"))
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")

        self._status_conn = ctk.CTkLabel(bar, text="⚫  Disconnected",
                                         font=_SANS_SM, anchor="w")
        self._status_conn.pack(side="left", padx=12)

        ctk.CTkLabel(bar, text="|", font=_SANS_SM, text_color="gray40").pack(side="left")

        self._status_audit = ctk.CTkLabel(bar, text="", font=_SANS_SM, anchor="w")
        self._status_audit.pack(side="left", padx=8)

        self._status_db = ctk.CTkLabel(bar, text=f"DB: {db.DB_PATH}",
                                       font=_SANS_SM, text_color="gray50", anchor="e")
        self._status_db.pack(side="right", padx=12)

    # ── Device list management ───────────────────────────────────────── #

    def _refresh_device_list(self):
        for w in self._device_scroll.winfo_children():
            w.destroy()
        self._device_btns.clear()

        query = self._search_var.get().strip().upper()
        devices = db.get_all_devices()

        if query:
            devices = [d for d in devices
                       if query in d["name"].upper() or query in d["ip"]]

        for d in devices:
            btn = ctk.CTkButton(
                self._device_scroll,
                text=f"  {d['name']}\n  {d['ip']}  ·  {d['card_type']}",
                anchor="w",
                height=46,
                font=_SANS_SM,
                fg_color="transparent",
                hover_color=("gray75", "gray25"),
                text_color=("gray10", "gray90"),
                command=lambda dev=d: self._select_device(dev),
            )
            btn.pack(fill="x", pady=1)
            self._device_btns[d["id"]] = btn

            btn.bind("<Double-Button-1>", lambda _, dev=d: self._start_connect(dev))
            btn.bind("<Button-3>", lambda e, dev=d: self._device_context_menu(e, dev))

        if not devices:
            ctk.CTkLabel(
                self._device_scroll,
                text="No devices found.\nClick  ＋ Add  to add one.",
                font=_SANS_SM, text_color="gray50",
            ).pack(pady=16)

        self._update_status_bar()

    def _select_device(self, device: Dict):
        self._selected_device_id = device["id"]
        for did, btn in self._device_btns.items():
            btn.configure(fg_color=(
                ("gray75", "gray30") if did == device["id"] else "transparent"
            ))
        self._edit_btn.configure(state="normal")
        self._del_btn.configure(state="normal")

    def _device_context_menu(self, event, device: Dict):
        self._select_device(device)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="⚡  Connect", command=lambda: self._start_connect(device))
        menu.add_command(label="✎  Edit",    command=self._edit_device)
        menu.add_command(label="📡  Ping",   command=lambda: self._ping_device(device))
        menu.add_separator()
        menu.add_command(label="📋  Copy IP", command=lambda: self._copy_to_clipboard(device["ip"]))
        menu.add_separator()
        menu.add_command(label="✕  Delete",  command=self._delete_device)
        menu.tk_popup(event.x_root, event.y_root)

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    # ── Device CRUD ──────────────────────────────────────────────────── #

    def _add_device(self):
        DeviceDialog(self, on_save=self._save_new_device)

    def _save_new_device(self, data: Dict):
        try:
            db.add_device(**{k: data[k] for k in ("name", "ip", "card_type", "notes", "location")})
            self._refresh_device_list()
        except Exception as e:
            messagebox.showerror("Save Error", str(e), parent=self)

    def _edit_device(self):
        if not self._selected_device_id:
            return
        device = db.get_device_by_id(self._selected_device_id)
        if device:
            DeviceDialog(self, device=device, on_save=lambda d: self._save_edit(d, device["id"]))

    def _save_edit(self, data: Dict, device_id: int):
        try:
            db.update_device(device_id, **{k: data[k] for k in ("name", "ip", "card_type", "notes", "location")})
            self._refresh_device_list()
        except Exception as e:
            messagebox.showerror("Save Error", str(e), parent=self)

    def _delete_device(self):
        if not self._selected_device_id:
            return
        device = db.get_device_by_id(self._selected_device_id)
        if not device:
            return
        ConfirmDialog(
            self,
            title="Delete Device",
            message=f"Delete  {device['name']}  ({device['ip']})?\nThis cannot be undone.",
            confirm_label="Delete",
            danger=True,
            on_confirm=lambda: self._do_delete(device["id"]),
        )

    def _do_delete(self, device_id: int):
        db.delete_device(device_id)
        self._selected_device_id = None
        self._edit_btn.configure(state="disabled")
        self._del_btn.configure(state="disabled")
        self._refresh_device_list()

    # ── Connection flow ──────────────────────────────────────────────── #

    def _start_connect(self, device: Dict):
        if self._ssh and self._ssh.is_connected:
            messagebox.showwarning("Already Connected",
                                   "Disconnect from the current device first.", parent=self)
            return

        # Pre-fill credentials if saved
        saved = creds.get_credential(device["name"]) or creds.get_global_credential()
        prefill_user, prefill_pass = ("", "")
        if saved:
            prefill_user, prefill_pass = saved

        ConnectDialog(
            self,
            device_name=device["name"],
            ip=device["ip"],
            prefill_user=prefill_user,
            prefill_pass=prefill_pass,
            on_connect=lambda u, p, save: self._do_connect(device, u, p, save),
        )

    def _quick_connect(self):
        ip = self._quick_ip.get().strip()
        user = self._quick_user.get().strip() or "apc"
        if not ip:
            messagebox.showerror("Missing Input", "Enter an IP address.", parent=self)
            return
        if not is_valid_ipv4(ip):
            messagebox.showerror(
                "Invalid IP",
                f"'{ip}' is not a valid IPv4 address.\nExpected format: 192.168.1.100",
                parent=self,
            )
            return
        pseudo_device = {"id": None, "name": ip, "ip": ip, "card_type": "NMC2",
                         "notes": "", "location": ""}
        ConnectDialog(
            self, device_name=ip, ip=ip,
            prefill_user=user,
            on_connect=lambda u, p, save: self._do_connect(pseudo_device, u, p, save),
        )

    def _do_connect(self, device: Dict, username: str, password: str, save_creds: bool):
        if save_creds and device.get("name"):
            creds.save_credential(device["name"], username, password)

        self._current_device = device
        self._current_user = username

        # Reachability check in background
        self._terminal_write(
            f"\n[  Checking reachability of {device['ip']}…  ]\n", tag=_TAG_WARN
        )

        threading.Thread(
            target=self._connect_thread,
            args=(device, username, password),
            daemon=True,
        ).start()

    def _connect_thread(self, device: Dict, username: str, password: str):
        ip = device["ip"]

        # Ping check
        ping_ok, ssh_ok, ping_ms = net.check_reachability(ip)
        if not ping_ok:
            self.after(0, lambda: self._terminal_write(
                f"[  ⚠  {ip} is not responding to ping.  Attempting SSH anyway…  ]\n",
                tag=_TAG_WARN,
            ))
        else:
            ms_str = f"{ping_ms:.0f} ms" if ping_ms else "< 1 ms"
            self.after(0, lambda: self._terminal_write(
                f"[  ✓ Ping OK  ({ms_str})  SSH port {'open' if ssh_ok else 'closed'}  ]\n",
                tag=_TAG_OK,
            ))

        # SSH connect
        self.after(0, lambda: self._terminal_write(
            f"[  Connecting to {username}@{ip}…  ]\n", tag=_TAG_WARN
        ))

        client = APCSSHClient(
            on_output=lambda t: self.after(0, lambda text=t: self._terminal_write(text)),
            on_disconnect=lambda: self.after(0, self._on_disconnected),
            on_verify_host=self._verify_host_key,
            on_save_host=self._save_host_key,
        )

        # Look up stored fingerprint for this device
        stored_rec = db.get_host_key(ip)
        stored_fp = stored_rec["fingerprint"] if stored_rec else None

        try:
            client.connect(ip, username, password, stored_fingerprint=stored_fp)
        except ConnectionError as e:
            err_msg = str(e)
            self.after(0, lambda: self._terminal_write(
                f"[  ❌  Connection failed: {err_msg}  ]\n", tag=_TAG_ERR
            ))
            db.log_audit(
                device["name"], ip, username,
                "SSH Connect Failed", err_msg, result="failure"
            )
            # H-5: reset shared state on the main thread, not the background thread
            def _reset():
                self._current_device = None
                self._current_user = ""
                self._update_status_bar()
            self.after(0, _reset)
            return

        self._ssh = client
        if device.get("id"):
            db.update_last_connected(device["id"])

        db.log_audit(device["name"], ip, username, "SSH Connect", result="success")

        # Auto-detect card type from 'about' command output
        self._detect_card_type(client, device, username)

        self.after(0, lambda: self._set_connected_state(True))
        self.after(0, lambda ms=ping_ms: self._update_info_bar(ms))

    def _detect_card_type(self, client: APCSSHClient, device: Dict, username: str) -> None:
        """
        Called from _connect_thread after successful login.
        Sends 'about', parses Hardware Rev to determine NMC generation,
        updates the DB and _current_device in-place, refreshes the info bar.
        """
        import re as _re

        # Wait briefly for the login banner to clear before sending a command
        import time as _time
        _time.sleep(2.5)

        output = client.send_and_capture("about", timeout=6.0)

        # Map Hardware Rev number to card type string
        # HW02 = NMC gen 1, HW09 = NMC2, HW21 = NMC3 (others mapped by generation)
        _HW_MAP = {
            "02": "NMC (gen 1)",
            "09": "NMC2",
            "21": "NMC3",
        }

        detected: Optional[str] = None

        m = _re.search(r"[Hh]ardware\s+[Rr]ev\s*[:\s]+HW(\d+)", output)
        if m:
            hw_num = m.group(1).lstrip("0") or "0"
            # Try exact two-digit match first, then fall back to generation hint
            hw_padded = m.group(1).zfill(2)
            if hw_padded in _HW_MAP:
                detected = _HW_MAP[hw_padded]
            elif client.card_generation == 1:
                detected = "NMC (gen 1)"
            else:
                detected = "NMC2"
        elif client.card_generation == 1:
            detected = "NMC (gen 1)"

        if not detected:
            return

        # Update in-memory device dict so info bar reflects it immediately
        device["card_type"] = detected

        # Persist to DB if device has a real ID
        if device.get("id"):
            db.update_card_type(device["id"], detected)
            db.log_audit(
                device["name"], device["ip"], username,
                "Card Type Detected", f"type={detected}", result="success"
            )
            # Refresh sidebar list so the stored type is shown
            self.after(0, self._load_devices)

        # Refresh info bar to show detected type
        self.after(0, self._update_info_bar)

    def _disconnect(self):
        if self._ssh:
            self._ssh.disconnect()
        self._on_disconnected()

    def _on_disconnected(self):
        if self._current_device:
            db.log_audit(
                self._current_device.get("name", ""),
                self._current_device.get("ip", ""),
                self._current_user,
                "SSH Disconnect",
                result="success",
            )
        self._ssh = None
        self._current_device = None
        self._current_user = ""
        self._set_connected_state(False)
        self._terminal_write("\n[  Disconnected.  ]\n", tag=_TAG_WARN)
        self._update_status_bar()

    # ── Connected/disconnected state ─────────────────────────────────── #

    def _set_connected_state(self, connected: bool):
        state = "normal" if connected else "disabled"
        for btn in self._action_buttons:
            btn.configure(state=state)
        self._send_btn.configure(state=state)
        self._cmd_entry.configure(state=state)
        self._disconnect_btn.configure(state=state)

        if not connected:
            self._info_status.configure(
                text="⚫  No device connected — select a device or use Quick Connect.",
                text_color="gray60",
            )
            self._ping_lbl.configure(text="")
            self._status_conn.configure(text="⚫  Disconnected")
        self._update_status_bar()

    def _update_info_bar(self, ping_ms: Optional[float] = None):
        if not self._current_device:
            return
        d = self._current_device
        ms = f"{ping_ms:.0f} ms" if ping_ms is not None else "—"
        self._info_status.configure(
            text=f"🟢  CONNECTED  │  {d['name']}  │  {d['ip']}  │  {d['card_type']}",
            text_color="#3fb950",
        )
        self._ping_lbl.configure(text=f"Ping: {ms}", text_color="#3fb950")
        self._status_conn.configure(
            text=f"🟢  {d['name']}  ({d['ip']})  │  {self._current_user}"
        )

    def _update_status_bar(self):
        count = db.get_audit_count()
        self._status_audit.configure(text=f"Audit: {count} events")

    # ── TOFU host key verification ───────────────────────────────────── #

    def _verify_host_key(self, ip: str, key_type: str, fingerprint: str,
                          stored_fp: Optional[str]) -> bool:
        """
        Called from the SSH background thread when a host key must be verified.
        Schedules a dialog on the main thread and blocks until the user responds.
        Returns True to accept, False to reject.
        """
        event = threading.Event()
        result = [False]

        def _show():
            if stored_fp is None:
                HostKeyDialog(
                    self, ip=ip, key_type=key_type, fingerprint=fingerprint,
                    on_accept=lambda: [result.__setitem__(0, True), event.set()],
                    on_reject=lambda: event.set(),
                )
            else:
                HostKeyChangedDialog(
                    self, ip=ip, key_type=key_type,
                    new_fingerprint=fingerprint, stored_fingerprint=stored_fp,
                    on_accept=lambda: [result.__setitem__(0, True), event.set()],
                    on_reject=lambda: event.set(),
                )

        self.after(0, _show)
        event.wait(timeout=120)   # 2-minute timeout; treats as rejection
        return result[0]

    def _save_host_key(self, ip: str, key_type: str, fingerprint: str) -> None:
        """Persist an accepted host key fingerprint to the database."""
        db.save_host_key(ip, key_type, fingerprint, accepted_by=self._current_user)
        db.log_audit(
            self._current_device.get("name", ip) if self._current_device else ip,
            ip, self._current_user,
            "Host Key Accepted",
            f"type={key_type} fp={fingerprint}",
        )
        self.after(0, self._update_status_bar)  # C-2: schedule on main thread

    # ── Ping device (sidebar context menu) ──────────────────────────── #

    def _ping_device(self, device: Dict):
        self._terminal_write(f"\n[  Pinging {device['ip']}…  ]\n", tag=_TAG_WARN)

        def _run():
            ok, ms = net.ping_host(device["ip"])
            if ok:
                ms_str = f"{ms:.0f} ms" if ms else "< 1 ms"
                self.after(0, lambda: self._terminal_write(
                    f"[  ✓ {device['ip']} is reachable  ({ms_str})  ]\n", tag=_TAG_OK
                ))
            else:
                self.after(0, lambda: self._terminal_write(
                    f"[  ✕ {device['ip']} did not respond to ping  ]\n", tag=_TAG_ERR
                ))

        threading.Thread(target=_run, daemon=True).start()

    # ── Terminal helpers ─────────────────────────────────────────────── #

    def _terminal_write(self, text: str, tag: Optional[str] = None):
        """Append text to terminal. Must be called on main thread."""
        self._terminal.configure(state="normal")
        if tag:
            self._terminal._textbox.insert("end", text, tag)
        else:
            self._terminal._textbox.insert("end", text)
        self._terminal._textbox.see("end")
        self._terminal.configure(state="disabled")

    def _terminal_clear(self):
        self._terminal.configure(state="normal")
        self._terminal._textbox.delete("1.0", "end")
        self._terminal.configure(state="disabled")

    def _terminal_send(self):
        cmd = self._cmd_var.get().strip()
        if not cmd or not self._ssh:
            return
        self._terminal_write(f"\napc> {cmd}\n", tag=_TAG_CMD)
        self._ssh.send(cmd)
        self._cmd_var.set("")

    # ── Action handlers ──────────────────────────────────────────────── #

    def _send_cmd(self, cmd: str, log_action: str = "", log_details: str = ""):
        """Send a CLI command and optionally audit-log it."""
        if not self._ssh:
            return
        self._terminal_write(f"\napc> {cmd}\n", tag=_TAG_CMD)
        self._ssh.send(cmd)
        if log_action and self._current_device:
            d = self._current_device
            db.log_audit(d.get("name", ""), d.get("ip", ""),
                         self._current_user, log_action, log_details)
            self._update_status_bar()

    def _action_system_info(self):
        self._send_cmd("about", "System Info")

    def _action_network(self):
        self._send_cmd("tcpip", "Network Info")

    def _action_change_ip(self):
        MultiInputDialog(
            self,
            title="Change IP Address",
            fields=[
                ("New IP Address", "e.g. 192.168.1.200", False),
                ("Subnet Mask",    "e.g. 255.255.255.0", False),
                ("Default Gateway","e.g. 192.168.1.1",   False),
            ],
            warning="Changing the IP will disconnect this session immediately.",
            on_confirm=self._apply_ip_change,
        )

    def _apply_ip_change(self, vals: Dict):
        ip   = vals.get("New IP Address", "").strip()
        mask = vals.get("Subnet Mask", "").strip()
        gw   = vals.get("Default Gateway", "").strip()
        if not ip or not mask or not gw:
            messagebox.showerror("Missing Input", "All three fields are required.")
            return
        if not is_valid_ipv4(ip):
            messagebox.showerror("Invalid IP",
                                 f"'{ip}' is not a valid IPv4 address.")
            return
        if not is_valid_ipv4(mask):
            messagebox.showerror("Invalid Subnet Mask",
                                 f"'{mask}' is not a valid IPv4 subnet mask.")
            return
        if not is_valid_ipv4(gw):
            messagebox.showerror("Invalid Gateway",
                                 f"'{gw}' is not a valid IPv4 address.")
            return
        self._send_cmd(f"tcpip -i {ip} -s {mask} -g {gw}",
                       "Change IP", f"New IP={ip} Mask={mask} GW={gw}")

    def _action_change_password(self):
        MultiInputDialog(
            self,
            title="Change Password",
            fields=[
                ("Username to Modify", "e.g. apc",        False),
                ("New Password",       "new password",     True),
                ("Confirm Password",   "re-enter password",True),
            ],
            on_confirm=self._apply_password_change,
        )

    def _apply_password_change(self, vals: Dict):
        user = vals.get("Username to Modify", "").strip()
        pw1  = vals.get("New Password", "")
        pw2  = vals.get("Confirm Password", "")
        if not user or not pw1:
            messagebox.showerror("Missing Input", "Username and password are required.")
            return
        if pw1 != pw2:
            messagebox.showerror("Mismatch", "Passwords do not match.")
            return
        # Echo a redacted version to the terminal — never show the actual password
        self._terminal_write(f"\napc> user -n {user} -pw ******\n", tag=_TAG_CMD)
        if self._ssh:
            self._ssh.send(f"user -n {user} -pw {pw1}")
        db.log_audit(
            self._current_device.get("name", "") if self._current_device else "",
            self._current_device.get("ip", "") if self._current_device else "",
            self._current_user,
            "Change Password", f"user={user}",
        )
        self._update_status_bar()

    def _action_reboot(self):
        ConfirmDialog(
            self,
            title="Reboot Card",
            message="Reboot the NMC card?\nThe device will be unreachable for ~60 seconds.",
            confirm_label="Reboot",
            danger=True,
            on_confirm=self._do_reboot,
        )

    def _do_reboot(self):
        """Send reboot command; schedule YES confirmation via after() — no sleep on main thread."""
        self._terminal_write("\napc> reboot\n", tag=_TAG_CMD)
        self._ssh.send("reboot")
        # Schedule confirmation after 1 s to let the device display its prompt
        self.after(1000, self._send_reboot_confirm)

    def _send_reboot_confirm(self):
        if self._ssh and self._ssh.is_connected:
            self._ssh.send("YES")
            if self._current_device:
                db.log_audit(
                    self._current_device.get("name", ""),
                    self._current_device.get("ip", ""),
                    self._current_user,
                    "Reboot",
                    "Card reboot confirmed",
                )
            self._update_status_bar()

    def _action_firmware(self):
        if not self._current_device:
            return
        device = self._current_device
        FirmwareDialog(
            self,
            ip=device["ip"],
            prefill_user=self._current_user,
            on_complete=lambda files: [
                db.log_audit(
                    device.get("name", ""),
                    device.get("ip", ""),
                    self._current_user,
                    "Firmware Update",
                    f"Files: {', '.join(files)}",
                ),
                self.after(0, self._update_status_bar),
            ],
        )
        self._update_status_bar()

    def _action_system_name(self):
        dlg = ctk.CTkInputDialog(text="Enter new system name:", title="Set System Name")
        name = dlg.get_input()
        if name and name.strip():
            self._send_cmd(f'system -n "{name.strip()}"',
                           "Set System Name", f"name={name.strip()}")

    def _action_location(self):
        dlg = ctk.CTkInputDialog(text="Enter new system location:", title="Set Location")
        loc = dlg.get_input()
        if loc and loc.strip():
            self._send_cmd(f'system -l "{loc.strip()}"',
                           "Set Location", f"location={loc.strip()}")

    def _action_contact(self):
        dlg = ctk.CTkInputDialog(text="Enter system contact:", title="Set Contact")
        contact = dlg.get_input()
        if contact and contact.strip():
            self._send_cmd(f'system -c "{contact.strip()}"',
                           "Set Contact", f"contact={contact.strip()}")

    def _action_event_log(self):
        self._send_cmd("eventlog", "View Event Log")

    def _action_ups_status(self):
        self._send_cmd("ups", "UPS Status")

    def _action_dns(self):
        self._send_cmd("dns", "DNS Settings")

    def _action_help(self):
        self._send_cmd("help")

    def _action_manual(self):
        dlg = ctk.CTkInputDialog(text="Enter raw CLI command:", title="Manual Command")
        cmd = dlg.get_input()
        if cmd and cmd.strip():
            self._send_cmd(cmd.strip(), "Manual Command", cmd.strip())

    # ── First-run wizard ─────────────────────────────────────────────── #

    def _show_first_run(self):
        FirstRunDialog(
            self,
            on_import=self._do_import_database,
            on_add_device=self._add_device,
            on_skip=lambda: None,
        )

    # ── Import database ──────────────────────────────────────────────── #

    def _import_database(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            parent=self,
            title="Import APC Devices Database",
            filetypes=[("SQLite Database", "*.db"), ("All Files", "*.*")],
        )
        if path:
            self._do_import_database(path)

    def _do_import_database(self, src_path: str):
        dest = db.DB_PATH
        # NEW-1: use samefile to handle case/symlink differences on Windows
        try:
            same = os.path.exists(dest) and os.path.samefile(src_path, dest)
        except (OSError, ValueError):
            same = False
        if same:
            messagebox.showinfo("Same File",
                                "That is already the active database.", parent=self)
            return

        # NEW-2: verify the selected file is a valid SQLite database
        import sqlite3 as _sqlite3
        try:
            with _sqlite3.connect(src_path, timeout=5) as probe:
                probe.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        except Exception:
            messagebox.showerror(
                "Invalid File",
                "The selected file does not appear to be a valid SQLite database.\n"
                "Please select the correct apc_devices.db file.",
                parent=self,
            )
            return

        if os.path.exists(dest):
            overwrite = messagebox.askyesno(
                "Overwrite Database",
                f"This will REPLACE the current database at:\n{dest}\n\n"
                "All existing devices and audit log entries will be lost.\n\n"
                "Are you sure?",
                parent=self,
            )
            if not overwrite:
                return
        try:
            shutil.copy2(src_path, dest)
            db.initialize_db()   # ensure schema is up to date
            self._refresh_device_list()
            count = db.get_device_count()
            messagebox.showinfo(
                "Import Successful",
                f"Database imported successfully.\n{count} device(s) loaded.",
                parent=self,
            )
        except Exception as e:
            messagebox.showerror("Import Failed", str(e), parent=self)

    # ── Menu / tool buttons ──────────────────────────────────────────── #

    def _open_audit_viewer(self):
        AuditViewerWindow(self)

    def _open_credential_manager(self):
        CredentialManagerWindow(self)

    # ── Cleanup ──────────────────────────────────────────────────────── #

    def _on_close(self):
        if self._ssh:
            self._ssh.disconnect()
        self.destroy()
