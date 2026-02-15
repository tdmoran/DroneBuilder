"""Config backup storage — save/load/list/delete FC configs per fleet drone."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fc_serial.models import FCConfig, StoredConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = PROJECT_ROOT / "fleet" / "configs"


def _drone_config_dir(drone_slug: str) -> Path:
    """Return the config storage directory for a drone, creating if needed."""
    d = CONFIGS_DIR / drone_slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_timestamp() -> str:
    """Generate a filesystem-safe timestamp: YYYYMMDDTHHMMSS."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _config_to_serializable(config: FCConfig) -> dict:
    """Convert FCConfig to a JSON-serializable dict."""
    d = asdict(config)
    # Convert set to sorted list for JSON
    d["features"] = sorted(d["features"])
    # Drop raw_text from JSON (stored separately in .txt)
    d.pop("raw_text", None)
    return d


def save_config(
    drone_slug: str,
    raw_text: str,
    parsed_config: FCConfig,
    timestamp: str | None = None,
) -> StoredConfig:
    """Save a config backup (raw .txt + parsed .json).

    Returns a StoredConfig with metadata and paths.
    """
    ts = timestamp or _make_timestamp()
    config_dir = _drone_config_dir(drone_slug)

    raw_path = config_dir / f"{drone_slug}_{ts}.txt"
    parsed_path = config_dir / f"{drone_slug}_{ts}.json"

    # Write raw diff all text (pastable for restore)
    raw_path.write_text(raw_text, encoding="utf-8")

    # Write parsed config as JSON
    data = _config_to_serializable(parsed_config)
    parsed_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return StoredConfig(
        drone_slug=drone_slug,
        timestamp=ts,
        firmware=parsed_config.firmware,
        firmware_version=parsed_config.firmware_version,
        board_name=parsed_config.board_name,
        raw_path=str(raw_path),
        parsed_path=str(parsed_path),
    )


def list_configs(drone_slug: str) -> list[StoredConfig]:
    """List all stored configs for a drone, newest first."""
    config_dir = CONFIGS_DIR / drone_slug
    if not config_dir.exists():
        return []

    configs: list[StoredConfig] = []
    # Find all .json files (each has a matching .txt)
    for json_path in sorted(config_dir.glob(f"{drone_slug}_*.json"), reverse=True):
        # Extract timestamp from filename: drone_slug_YYYYMMDDTHHMMSS.json
        stem = json_path.stem  # drone_slug_YYYYMMDDTHHMMSS
        ts = stem[len(drone_slug) + 1:]  # YYYYMMDDTHHMMSS

        txt_path = json_path.with_suffix(".txt")

        # Read parsed JSON for metadata
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        configs.append(StoredConfig(
            drone_slug=drone_slug,
            timestamp=ts,
            firmware=data.get("firmware", "UNKNOWN"),
            firmware_version=data.get("firmware_version", ""),
            board_name=data.get("board_name", ""),
            raw_path=str(txt_path),
            parsed_path=str(json_path),
        ))

    return configs


def load_config(drone_slug: str, timestamp: str) -> tuple[str, FCConfig] | None:
    """Load a specific config backup by drone slug and timestamp.

    Returns (raw_text, FCConfig) or None if not found.
    """
    config_dir = CONFIGS_DIR / drone_slug
    raw_path = config_dir / f"{drone_slug}_{timestamp}.txt"
    parsed_path = config_dir / f"{drone_slug}_{timestamp}.json"

    if not parsed_path.exists():
        return None

    # Read raw text
    raw_text = ""
    if raw_path.exists():
        raw_text = raw_path.read_text(encoding="utf-8")

    # Read parsed config
    data = json.loads(parsed_path.read_text(encoding="utf-8"))

    # Reconstruct FCConfig from dict
    from fc_serial.models import ParsedProfile, SerialPortConfig

    serial_ports = [
        SerialPortConfig(**sp) for sp in data.get("serial_ports", [])
    ]
    pid_profiles = [
        ParsedProfile(**pp) for pp in data.get("pid_profiles", [])
    ]
    rate_profiles = [
        ParsedProfile(**rp) for rp in data.get("rate_profiles", [])
    ]

    config = FCConfig(
        firmware=data.get("firmware", "UNKNOWN"),
        firmware_version=data.get("firmware_version", ""),
        board_name=data.get("board_name", ""),
        master_settings=data.get("master_settings", {}),
        features=set(data.get("features", [])),
        serial_ports=serial_ports,
        pid_profiles=pid_profiles,
        rate_profiles=rate_profiles,
        resource_mappings=data.get("resource_mappings", {}),
        aux_modes=data.get("aux_modes", []),
        raw_text=raw_text,
        parsed_at=data.get("parsed_at", ""),
    )

    return raw_text, config


def delete_config(drone_slug: str, timestamp: str) -> bool:
    """Delete a config backup. Returns True if deleted, False if not found."""
    config_dir = CONFIGS_DIR / drone_slug
    raw_path = config_dir / f"{drone_slug}_{timestamp}.txt"
    parsed_path = config_dir / f"{drone_slug}_{timestamp}.json"

    deleted = False
    if raw_path.exists():
        raw_path.unlink()
        deleted = True
    if parsed_path.exists():
        parsed_path.unlink()
        deleted = True

    return deleted
