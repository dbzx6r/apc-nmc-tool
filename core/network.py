"""
core/network.py — Network reachability utilities.

Uses the OS ping command (no elevated privileges required) and a plain
TCP socket connect to check SSH port availability.
"""

import re
import socket
import subprocess
import sys
from typing import Optional, Tuple


def ping_host(ip: str, count: int = 1, timeout_ms: int = 1500) -> Tuple[bool, Optional[float]]:
    """
    Ping a host using the OS ping binary.
    Returns (reachable: bool, avg_latency_ms: float | None).
    """
    try:
        if sys.platform == "win32":
            cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), ip]
            total_timeout = timeout_ms / 1000 * count + 3
        else:
            # macOS / Linux
            w = max(1, timeout_ms // 1000)
            cmd = ["ping", "-c", str(count), "-W", str(w), ip]
            total_timeout = w * count + 3

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=total_timeout,
        )

        if result.returncode != 0:
            return False, None

        return True, _parse_latency(result.stdout)

    except subprocess.TimeoutExpired:
        return False, None
    except Exception:
        return False, None


def check_port(ip: str, port: int = 22, timeout: float = 3.0) -> bool:
    """Return True if the TCP port is accepting connections."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def check_reachability(ip: str) -> Tuple[bool, bool, Optional[float]]:
    """
    Full reachability check.
    Returns (ping_ok, ssh_port_open, ping_ms).
    SSH port is only checked when ping succeeds.
    """
    ping_ok, ping_ms = ping_host(ip)
    ssh_ok = check_port(ip, 22) if ping_ok else False
    return ping_ok, ssh_ok, ping_ms


def _parse_latency(output: str) -> Optional[float]:
    """Extract average round-trip time from ping output (Windows + POSIX)."""
    # Windows: "Average = 2ms"
    m = re.search(r"Average\s*=\s*([\d.]+)\s*ms", output, re.IGNORECASE)
    if m:
        return float(m.group(1))
    # macOS/Linux: "min/avg/max = x/2.3/x ms"
    m = re.search(r"min/avg/max[^=]+=\s*[\d.]+/([\d.]+)", output)
    if m:
        return float(m.group(1))
    # Linux alternate: "rtt min/avg/max/mdev = x/2.3/x/x ms"
    m = re.search(r"rtt[^=]+=\s*[\d.]+/([\d.]+)", output)
    if m:
        return float(m.group(1))
    return None
