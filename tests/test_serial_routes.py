"""Tests for web/routes/serial.py — REST endpoints with mocked serial."""

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.config_store import CONFIGS_DIR
from web.app import create_app


@pytest.fixture
def client():
    """Flask test client."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def clean_test_configs():
    """Clean up test config storage."""
    slug = "_test_serial_routes"
    config_dir = CONFIGS_DIR / slug
    yield slug
    if config_dir.exists():
        shutil.rmtree(config_dir)


class TestTerminalPage:
    """GET /serial/terminal."""

    def test_terminal_renders(self, client):
        rv = client.get("/serial/terminal")
        assert rv.status_code == 200
        assert b"FC Terminal" in rv.data
        assert b"xterm" in rv.data

    def test_terminal_with_drone_param(self, client):
        rv = client.get("/serial/terminal?drone=my_drone")
        assert rv.status_code == 200
        assert b"my_drone" in rv.data


class TestPortDetection:
    """GET /serial/ports."""

    @patch("fc_serial.connection.detect_fc_ports")
    def test_list_ports(self, mock_detect, client):
        from fc_serial.models import DetectedPort

        mock_detect.return_value = [
            DetectedPort(
                device="/dev/ttyACM0",
                description="STM32 VCP",
                vid=0x0483,
                pid=0x5740,
            ),
        ]

        rv = client.get("/serial/ports")
        data = json.loads(rv.data)
        assert rv.status_code == 200
        assert len(data["ports"]) == 1
        assert data["ports"][0]["device"] == "/dev/ttyACM0"

    @patch("fc_serial.connection.detect_fc_ports")
    def test_empty_ports(self, mock_detect, client):
        mock_detect.return_value = []
        rv = client.get("/serial/ports")
        data = json.loads(rv.data)
        assert data["ports"] == []


class TestConnectionStatus:
    """GET /serial/status."""

    @patch("fc_serial.connection.get_active_port")
    def test_disconnected(self, mock_active, client):
        mock_active.return_value = None
        rv = client.get("/serial/status")
        data = json.loads(rv.data)
        assert data["connected"] is False

    @patch("fc_serial.connection.get_active_port")
    def test_connected(self, mock_active, client):
        mock_active.return_value = "/dev/ttyACM0"
        rv = client.get("/serial/status")
        data = json.loads(rv.data)
        assert data["connected"] is True
        assert data["port"] == "/dev/ttyACM0"


class TestUploadDiff:
    """POST /serial/upload-diff."""

    def test_upload_json(self, client):
        diff_text = "# Betaflight / STM32F405 (S405) 4.5.1 Nov 14 2024\nset motor_pwm_protocol = DSHOT600\n"
        rv = client.post(
            "/serial/upload-diff",
            data=json.dumps({"raw_text": diff_text}),
            content_type="application/json",
        )
        data = json.loads(rv.data)
        assert rv.status_code == 200
        assert data["firmware"] == "BTFL"
        assert data["firmware_version"] == "4.5.1"

    def test_upload_empty(self, client):
        rv = client.post(
            "/serial/upload-diff",
            data=json.dumps({"raw_text": ""}),
            content_type="application/json",
        )
        assert rv.status_code == 400


class TestSaveConfig:
    """POST /serial/save-config/<slug>."""

    def test_save_config(self, client, clean_test_configs):
        slug = clean_test_configs
        diff_text = "# Betaflight / STM32F405 (S405) 4.5.1 Nov 14 2024\nset motor_pwm_protocol = DSHOT600\n"

        rv = client.post(
            f"/serial/save-config/{slug}",
            data=json.dumps({"raw_text": diff_text}),
            content_type="application/json",
        )
        data = json.loads(rv.data)
        assert rv.status_code == 200
        assert data["saved"] is True
        assert data["firmware"] == "BTFL"

    def test_save_empty(self, client, clean_test_configs):
        slug = clean_test_configs
        rv = client.post(
            f"/serial/save-config/{slug}",
            data=json.dumps({"raw_text": ""}),
            content_type="application/json",
        )
        assert rv.status_code == 400


class TestConfigList:
    """GET /serial/configs/<slug>."""

    def test_empty_list(self, client, clean_test_configs):
        slug = clean_test_configs
        rv = client.get(f"/serial/configs/{slug}")
        assert rv.status_code == 200
        assert b"No config backups" in rv.data

    def test_list_after_save(self, client, clean_test_configs):
        slug = clean_test_configs
        diff_text = "# Betaflight / STM32F405 (S405) 4.5.1 Nov 14 2024\nset motor_pwm_protocol = DSHOT600\n"

        # Save a config first
        client.post(
            f"/serial/save-config/{slug}",
            data=json.dumps({"raw_text": diff_text}),
            content_type="application/json",
        )

        rv = client.get(f"/serial/configs/{slug}")
        assert rv.status_code == 200
        assert b"BTFL" in rv.data
        assert b"4.5.1" in rv.data
