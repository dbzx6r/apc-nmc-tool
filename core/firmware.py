"""
core/firmware.py — APC NMC firmware update via FTP.

APC NMC/NMC2/NMC3 cards run an FTP server on port 21.
Firmware is distributed as .bin files uploaded to the FTP root.
The card validates the filename, applies the firmware, and auto-reboots.

Expected firmware filenames (APC conventions):
  NMC  (gen 1):  apc_hw02_aos_*.bin
  NMC2 (gen 2):  apc_hw09_aos_*.bin   apc_hw09_sumx_*.bin (or app-specific)
  NMC3 (gen 3):  apc_hw21_aos_*.bin   apc_hw21_sumx_*.bin

The tool does not enforce filename validation — it uploads what you select
and warns if the filename doesn't match a known APC pattern.
"""

import ftplib
import os
import re
from typing import Callable, List, Optional


# Filenames that match known APC NMC firmware naming conventions
_FIRMWARE_PATTERN = re.compile(
    r"^apc_hw\d+_(aos|sumx|app|pxgx|rpdu|smart)[_-]",
    re.IGNORECASE,
)


class FirmwareError(Exception):
    pass


class FirmwareUploader:
    FTP_PORT = 21
    BLOCK_SIZE = 8192
    CONNECT_TIMEOUT = 30
    TRANSFER_TIMEOUT = 300  # 5-minute cap on the full transfer

    def upload(
        self,
        ip: str,
        username: str,
        password: str,
        firmware_files: List[str],
        on_progress: Optional[Callable[[str, float, int, int], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        port: int = 21,
    ) -> None:
        """
        Upload one or more firmware .bin files to the APC NMC via FTP.

        Args:
            ip            — Device IP address
            username      — FTP username (same as SSH credentials)
            password      — FTP password
            firmware_files — List of local .bin file paths
            on_progress   — callback(filename, pct, bytes_done, total_bytes)
            on_status     — callback(message_str)

        Raises FirmwareError on failure.
        """
        if not firmware_files:
            raise ValueError("No firmware files provided.")

        for path in firmware_files:
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Firmware file not found: {path}")
            name = os.path.basename(path)
            if not _FIRMWARE_PATTERN.match(name):
                if on_status:
                    on_status(
                        f"⚠  Warning: '{name}' does not match the expected APC firmware "
                        "filename pattern (apc_hwXX_*). Proceeding anyway."
                    )

        ftp = ftplib.FTP()
        try:
            if on_status:
                on_status(f"Connecting to FTP server on {ip}:{port}...")

            ftp.connect(ip, port, timeout=self.CONNECT_TIMEOUT)
            ftp.login(username, password)
            # storbinary() calls TYPE I internally; set_pasv ensures passive mode
            ftp.set_pasv(True)

            if on_status:
                on_status("FTP connection established. Starting transfer...")

            for fw_path in firmware_files:
                self._upload_file(ftp, fw_path, on_progress, on_status)

            if on_status:
                on_status(
                    "✓ All firmware files uploaded successfully.\n"
                    "The device is now validating and applying the firmware.\n"
                    "It will reboot automatically — this normally takes 2–5 minutes.\n"
                    "Do not power off the device during this process."
                )

        except ftplib.error_perm as e:
            raise FirmwareError(
                f"FTP permission error: {e}\n"
                "Verify that FTP is enabled on the device and credentials are correct."
            )
        except ftplib.error_temp as e:
            raise FirmwareError(f"FTP temporary error: {e}")
        except ConnectionRefusedError:
            raise FirmwareError(
                f"FTP connection refused on {ip}:{port}.\n"
                "Ensure FTP is enabled in the device network settings."
            )
        except OSError as e:
            raise FirmwareError(f"Network/IO error during FTP: {e}")
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

    def _upload_file(
        self,
        ftp: ftplib.FTP,
        fw_path: str,
        on_progress: Optional[Callable],
        on_status: Optional[Callable],
    ) -> None:
        filename = os.path.basename(fw_path)
        total = os.path.getsize(fw_path)
        uploaded = [0]

        if on_status:
            on_status(f"Uploading {filename}  ({total / 1024:.1f} KB)...")

        def _track(data: bytes) -> None:
            uploaded[0] += len(data)
            if on_progress:
                pct = min(100.0, uploaded[0] / total * 100.0)
                on_progress(filename, pct, uploaded[0], total)

        with open(fw_path, "rb") as f:
            # Set a transfer-level timeout so a stalled upload doesn't hang forever
            ftp.sock.settimeout(self.TRANSFER_TIMEOUT)
            ftp.storbinary(
                f"STOR {filename}",
                f,
                blocksize=self.BLOCK_SIZE,
                callback=_track,
            )

        if on_status:
            on_status(f"✓ {filename} transferred ({total / 1024:.1f} KB).")
