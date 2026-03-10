"""
core/ssh_client.py — Paramiko-based SSH client for APC NMC/NMC2/NMC3 cards.

APC hardware uses legacy SSH algorithms:
  - Host key type: ssh-rsa (not rsa-sha2-256/512)
  - Key exchange:  diffie-hellman-group14-sha1 (NMC2/NMC3)
                   diffie-hellman-group1-sha1  (NMC gen 1 — very old)

Security model — TOFU (Trust On First Use):
  - First connection: user is shown the server's key fingerprint and must
    explicitly accept it. The fingerprint is stored in the local database.
  - Subsequent connections: stored fingerprint is compared. If it matches,
    no prompt is shown. If it has CHANGED, the connection is blocked and a
    prominent warning is displayed.
  - This prevents silent MITM attacks against critical infrastructure devices.
"""

import re
import socket
import threading
import time
from typing import Callable, Optional

import paramiko


class APCSSHClient:
    CONNECT_TIMEOUT = 15
    RECV_BUFFER = 8192
    KEEPALIVE_INTERVAL = 30   # seconds between SSH keepalive packets

    def __init__(
        self,
        on_output: Optional[Callable[[str], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        on_verify_host: Optional[Callable] = None,
        on_save_host: Optional[Callable] = None,
    ):
        """
        Args:
            on_output       — callback(text: str) called from reader thread with SSH output
            on_disconnect   — callback() called when SSH session ends
            on_verify_host  — callback(ip, key_type, fingerprint, stored_fp_or_None) -> bool
                              Called from background thread; must block until user responds.
                              Return True to accept, False to reject.
            on_save_host    — callback(ip, key_type, fingerprint) called after user accepts
                              a new or changed host key so the caller can persist it.
        """
        self.on_output = on_output
        self.on_disconnect = on_disconnect
        self.on_verify_host = on_verify_host
        self.on_save_host = on_save_host

        self._client: Optional[paramiko.SSHClient] = None
        self._transport: Optional[paramiko.Transport] = None
        self._channel: Optional[paramiko.Channel] = None
        self._reader: Optional[threading.Thread] = None
        self._connected = False

        self.ip: str = ""
        self.username: str = ""

    # ── Public API ──────────────────────────────────────────────────── #

    @property
    def is_connected(self) -> bool:
        return (
            self._connected
            and self._channel is not None
            and not self._channel.closed
        )

    def connect(self, ip: str, username: str, password: str,
                stored_fingerprint: Optional[str] = None,
                port: int = 22) -> None:
        """
        Open an SSH session to an APC NMC card.

        stored_fingerprint — previously accepted host key fingerprint from the DB.
                             None means this is the first connection to this device.
        Raises ConnectionError on failure. Raises _AuthError on bad credentials
        (re-raised as ConnectionError with a clear message).
        """
        self.ip = ip
        self.username = username
        errors: list[str] = []

        # Build the TOFU policy for this connection attempt
        policy = _ToFUPolicy(
            stored_fp=stored_fingerprint,
            verify_fn=self.on_verify_host or _default_reject,
            save_fn=self.on_save_host or (lambda *_: None),
        )

        # Strategy 1 — SSHClient with rsa-sha2 variants disabled (NMC2 / NMC3)
        try:
            self._connect_via_client(ip, port, username, password, policy)
            self._start_reader()
            return
        except _AuthError:
            raise
        except Exception as e:
            errors.append(f"[strategy-1] {e}")

        # Strategy 2 — Direct Transport with explicit legacy kex (NMC gen 1)
        try:
            self._connect_via_transport(ip, port, username, password, policy)
            self._start_reader()
            return
        except _AuthError:
            raise
        except Exception as e:
            errors.append(f"[strategy-2] {e}")

        raise ConnectionError(
            f"Could not establish SSH connection to {ip}:{port}.\n"
            + "\n".join(errors)
        )

    def send(self, command: str) -> None:
        """Send a command line to the APC CLI. Thread-safe."""
        if self.is_connected:
            try:
                self._channel.send(command + "\n")
            except Exception:
                pass

    def send_raw(self, data: str) -> None:
        """Send raw characters (no newline). Thread-safe."""
        if self.is_connected:
            try:
                self._channel.send(data)
            except Exception:
                pass

    def disconnect(self) -> None:
        """Close the SSH session cleanly."""
        self._connected = False
        for obj in (self._channel, self._client, self._transport):
            if obj:
                try:
                    obj.close()
                except Exception:
                    pass
        self._channel = None
        self._client = None
        self._transport = None

    # ── Connection Strategies ────────────────────────────────────────── #

    def _connect_via_client(self, ip, port, username, password, policy) -> None:
        """Standard SSHClient approach — works for NMC2 and NMC3."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(policy)
        try:
            client.connect(
                hostname=ip,
                port=port,
                username=username,
                password=password,
                timeout=self.CONNECT_TIMEOUT,
                look_for_keys=False,
                allow_agent=False,
                # Disable rsa-sha2 variants so the card negotiates ssh-rsa
                disabled_algorithms={"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]},
            )
        except paramiko.AuthenticationException as e:
            client.close()
            raise _AuthError(f"Authentication failed for {username}@{ip}: {e}")
        except paramiko.SSHException as e:
            client.close()
            # Re-raise as plain Exception so the caller can try strategy 2,
            # UNLESS the message indicates a deliberate host-key rejection
            msg = str(e)
            if "host key" in msg.lower() or "fingerprint" in msg.lower():
                raise ConnectionError(msg)
            raise

        # Enable keepalive to detect silent session drops
        client.get_transport().set_keepalive(self.KEEPALIVE_INTERVAL)

        channel = client.invoke_shell(term="vt100", width=220, height=50)
        channel.settimeout(0.1)
        self._client = client
        self._channel = channel
        self._connected = True

    def _connect_via_transport(self, ip, port, username, password, policy) -> None:
        """
        Direct Transport with explicit legacy kex/key_types for NMC gen 1
        (AP9617/AP9618/AP9619) which may use diffie-hellman-group1-sha1.
        """
        sock = socket.create_connection((ip, port), timeout=self.CONNECT_TIMEOUT)
        transport = paramiko.Transport(sock)
        try:
            opts = transport.get_security_options()
            opts.kex = [
                "diffie-hellman-group14-sha1",
                "diffie-hellman-group-exchange-sha1",
                "diffie-hellman-group-exchange-sha256",
            ]
            opts.key_types = ["ssh-rsa"]

            # Apply TOFU policy to the raw transport
            transport._preferred_keys = opts.key_types

            try:
                transport.connect(username=username, password=password)
            except paramiko.AuthenticationException as e:
                raise _AuthError(f"Authentication failed for {username}@{ip}: {e}")

            # Manual host key check via policy
            server_key = transport.get_remote_server_key()
            if server_key:
                policy.missing_host_key(None, ip, server_key)

            # Enable keepalive
            transport.set_keepalive(self.KEEPALIVE_INTERVAL)

            channel = transport.open_session()
            channel.get_pty(term="vt100", width=220, height=50)
            channel.invoke_shell()
            channel.settimeout(0.1)

            self._transport = transport
            self._channel = channel
            self._connected = True

        except Exception:
            try:
                transport.close()
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass
            raise

    # ── Output Reader Thread ─────────────────────────────────────────── #

    def _start_reader(self) -> None:
        self._reader = threading.Thread(
            target=self._read_loop,
            name="apc-ssh-reader",
            daemon=True,
        )
        self._reader.start()

    def _read_loop(self) -> None:
        while self._connected:
            try:
                if self._channel.recv_ready():
                    data = self._channel.recv(self.RECV_BUFFER)
                    if data:
                        text = _strip_ansi(data.decode("utf-8", errors="replace"))
                        if self.on_output:
                            self.on_output(text)
                    elif self._channel.exit_status_ready():
                        break
                else:
                    time.sleep(0.05)

                if self._channel.closed:
                    break

            except socket.timeout:
                continue
            except Exception:
                break

        self._connected = False
        if self.on_disconnect:
            self.on_disconnect()


# ── TOFU Host Key Policy ──────────────────────────────────────────────── #

class _ToFUPolicy(paramiko.MissingHostKeyPolicy):
    """
    Trust On First Use host key policy.

    - If stored_fp matches the presented key → silently accept (trusted).
    - If stored_fp is None (first connect) → call verify_fn; save on accept.
    - If stored_fp differs (fingerprint changed) → call verify_fn with both
      fingerprints so the caller can warn the user; update on accept.
    - If verify_fn returns False → raise SSHException to abort the connection.
    """

    def __init__(
        self,
        stored_fp: Optional[str],
        verify_fn: Callable,
        save_fn: Callable,
    ):
        self._stored_fp = stored_fp
        self._verify = verify_fn
        self._save = save_fn

    def missing_host_key(self, client, hostname, key) -> None:
        fp = ":".join(f"{b:02x}" for b in key.get_fingerprint())

        # Already trusted — fingerprint unchanged
        if self._stored_fp is not None and self._stored_fp == fp:
            return

        # Either new host or changed fingerprint — ask user
        accepted = self._verify(hostname, key.get_name(), fp, self._stored_fp)

        if not accepted:
            if self._stored_fp is not None:
                raise paramiko.SSHException(
                    f"⚠ Host key fingerprint CHANGED for {hostname}. "
                    "Connection blocked. This may indicate a MITM attack."
                )
            raise paramiko.SSHException(
                f"Host key not accepted for {hostname}. Connection aborted."
            )

        # Persist the newly accepted fingerprint
        self._save(hostname, key.get_name(), fp)


def _default_reject(hostname, key_type, fingerprint, stored_fp) -> bool:
    """Fallback verify function when no GUI callback is provided — always rejects."""
    return False


# ── Helpers ──────────────────────────────────────────────────────────── #

class _AuthError(ConnectionError):
    """Signals bad credentials so the caller skips the second strategy."""
    pass


_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)
