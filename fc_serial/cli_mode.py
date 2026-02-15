"""CLI mode helpers — enter/exit CLI, send commands, capture diff all."""

from __future__ import annotations

import time

from fc_serial.connection import FCConnection


def enter_cli_mode(conn: FCConnection, timeout: float = 3.0) -> str:
    """Send '#' to enter CLI mode. Returns initial prompt text."""
    conn.write(b"#\r\n")
    return _read_until_prompt(conn, timeout)


def send_command(conn: FCConnection, command: str, timeout: float = 5.0) -> str:
    """Send a CLI command and read response until next prompt."""
    conn.write(f"{command}\r\n".encode("utf-8"))
    return _read_until_prompt(conn, timeout)


def get_diff_all(conn: FCConnection, timeout: float = 15.0) -> str:
    """Send 'diff all' and capture the full output.

    This can take several seconds on FCs with many settings.
    """
    conn.write(b"diff all\r\n")
    return _read_until_prompt(conn, timeout)


def exit_cli_mode(conn: FCConnection) -> None:
    """Send 'exit' to leave CLI mode and reboot the FC."""
    conn.write(b"exit\r\n")
    # Don't wait for response — FC will reboot


def _read_until_prompt(conn: FCConnection, timeout: float) -> str:
    """Read serial data until we see the '# ' prompt or timeout."""
    buffer = b""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        chunk = conn.read(1024)
        if chunk:
            buffer += chunk
            # Look for prompt at end of output
            text = buffer.decode("utf-8", errors="replace")
            if text.rstrip().endswith("# ") or text.rstrip().endswith("#"):
                return text
        else:
            time.sleep(0.05)

    # Return whatever we got before timeout
    return buffer.decode("utf-8", errors="replace")
