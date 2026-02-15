"""Tests for core/config_store.py — save/load/list/delete config backups."""

import json
import shutil
from pathlib import Path

import pytest

from core.config_store import (
    CONFIGS_DIR,
    delete_config,
    list_configs,
    load_config,
    save_config,
)
from fc_serial.config_parser import parse_diff_all


SAMPLE_DIFF = """\
# Betaflight / STM32F405 (S405) 4.5.1 Nov 14 2024 / 10:00:00

feature OSD

serial 0 64 115200 57600 0 115200

set motor_pwm_protocol = DSHOT600
set serialrx_provider = CRSF
"""


@pytest.fixture
def clean_test_drone():
    """Create and clean up a test drone config directory."""
    slug = "_test_config_store_drone"
    config_dir = CONFIGS_DIR / slug
    yield slug
    if config_dir.exists():
        shutil.rmtree(config_dir)


class TestConfigStore:
    """Roundtrip save/load/list/delete."""

    def test_save_and_load(self, clean_test_drone):
        slug = clean_test_drone
        config = parse_diff_all(SAMPLE_DIFF)

        stored = save_config(slug, SAMPLE_DIFF, config, timestamp="20240115T120000")

        assert stored.drone_slug == slug
        assert stored.timestamp == "20240115T120000"
        assert stored.firmware == "BTFL"
        assert stored.firmware_version == "4.5.1"

        # Load back
        result = load_config(slug, "20240115T120000")
        assert result is not None
        raw_text, loaded_config = result
        assert raw_text == SAMPLE_DIFF
        assert loaded_config.firmware == "BTFL"
        assert loaded_config.firmware_version == "4.5.1"
        assert "OSD" in loaded_config.features
        assert loaded_config.master_settings["motor_pwm_protocol"] == "DSHOT600"
        assert len(loaded_config.serial_ports) == 1

    def test_list_configs_newest_first(self, clean_test_drone):
        slug = clean_test_drone
        config = parse_diff_all(SAMPLE_DIFF)

        save_config(slug, SAMPLE_DIFF, config, timestamp="20240101T100000")
        save_config(slug, SAMPLE_DIFF, config, timestamp="20240115T120000")
        save_config(slug, SAMPLE_DIFF, config, timestamp="20240110T080000")

        configs = list_configs(slug)
        assert len(configs) == 3
        # Newest first (alphabetical descending)
        assert configs[0].timestamp == "20240115T120000"
        assert configs[1].timestamp == "20240110T080000"
        assert configs[2].timestamp == "20240101T100000"

    def test_list_configs_empty(self, clean_test_drone):
        configs = list_configs("nonexistent_drone_xyz")
        assert configs == []

    def test_delete_config(self, clean_test_drone):
        slug = clean_test_drone
        config = parse_diff_all(SAMPLE_DIFF)

        save_config(slug, SAMPLE_DIFF, config, timestamp="20240115T120000")

        assert delete_config(slug, "20240115T120000") is True
        assert load_config(slug, "20240115T120000") is None
        assert delete_config(slug, "20240115T120000") is False

    def test_save_creates_files(self, clean_test_drone):
        slug = clean_test_drone
        config = parse_diff_all(SAMPLE_DIFF)

        stored = save_config(slug, SAMPLE_DIFF, config, timestamp="20240115T120000")

        assert Path(stored.raw_path).exists()
        assert Path(stored.parsed_path).exists()

        # Raw text is pastable
        assert Path(stored.raw_path).read_text() == SAMPLE_DIFF

        # JSON is valid
        parsed_data = json.loads(Path(stored.parsed_path).read_text())
        assert parsed_data["firmware"] == "BTFL"

    def test_load_nonexistent(self, clean_test_drone):
        result = load_config(clean_test_drone, "99990101T000000")
        assert result is None

    def test_stored_config_metadata(self, clean_test_drone):
        slug = clean_test_drone
        config = parse_diff_all(SAMPLE_DIFF)

        stored = save_config(slug, SAMPLE_DIFF, config, timestamp="20240115T120000")

        configs = list_configs(slug)
        assert len(configs) == 1
        assert configs[0].firmware == "BTFL"
        assert configs[0].firmware_version == "4.5.1"
        assert configs[0].board_name == "STM32F405"
