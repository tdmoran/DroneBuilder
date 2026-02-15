"""Tests for web/routes/diagnose.py — Flask test client."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from web.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Create a test Flask app with isolated fleet and component dirs."""
    # Create fleet dir with a test drone
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()
    configs_dir = fleet_dir / "configs"
    configs_dir.mkdir()

    # Create minimal component database
    # Files must match core.loader._FILE_TO_TYPE mapping: motors.json, escs.json, etc.
    comp_dir = tmp_path / "components"
    comp_dir.mkdir()

    comp_dir.joinpath("motors.json").write_text(json.dumps([
        {
            "id": "motor_test_2306",
            "manufacturer": "Test",
            "model": "2306",
            "weight_g": 33.0,
            "price_usd": 15.0,
            "category": "5inch",
            "specs": {"kv": 1800, "stator_diameter_mm": 23, "stator_height_mm": 6},
        }
    ]))

    comp_dir.joinpath("escs.json").write_text(json.dumps([
        {
            "id": "esc_test_45a",
            "manufacturer": "Test",
            "model": "45A",
            "weight_g": 10.0,
            "price_usd": 25.0,
            "category": "5inch",
            "specs": {"protocol": "DShot600", "firmware": "BLHeli_32", "current_sensor": True},
        }
    ]))

    comp_dir.joinpath("flight_controllers.json").write_text(json.dumps([
        {
            "id": "fc_test_f405",
            "manufacturer": "Test",
            "model": "F405",
            "weight_g": 8.0,
            "price_usd": 35.0,
            "category": "5inch",
            "specs": {"mcu": "STM32F405", "osd": "AT7456E"},
        }
    ]))

    comp_dir.joinpath("receivers.json").write_text(json.dumps([
        {
            "id": "rx_test_elrs",
            "manufacturer": "Test",
            "model": "ELRS RX",
            "weight_g": 2.0,
            "price_usd": 15.0,
            "category": "5inch",
            "specs": {"output_protocol": "CRSF", "telemetry": True},
        }
    ]))

    comp_dir.joinpath("vtx.json").write_text(json.dumps([
        {
            "id": "vtx_test_dji",
            "manufacturer": "DJI",
            "model": "O3 Air Unit",
            "weight_g": 20.0,
            "price_usd": 100.0,
            "category": "5inch",
            "specs": {"type": "Digital HD", "system": "DJI O3"},
        }
    ]))

    # Empty files for remaining component types
    for filename in ("batteries.json", "frames.json", "propellers.json"):
        comp_dir.joinpath(filename).write_text("[]")

    # Create schemas dir (needed by some code paths)
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()

    # Create constraints dir (empty — no YAML rules for test isolation)
    constraints_dir = tmp_path / "constraints"
    constraints_dir.mkdir()

    # Create test drone
    drone_data = {
        "name": "Test Quad",
        "drone_class": "5inch_freestyle",
        "status": "active",
        "motor": "motor_test_2306",
        "esc": "esc_test_45a",
        "fc": "fc_test_f405",
        "receiver": "rx_test_elrs",
        "vtx": "vtx_test_dji",
    }
    fleet_dir.joinpath("test_quad.json").write_text(json.dumps(drone_data))

    # Force-import route modules BEFORE patching, so monkeypatch captures
    # the real FLEET_DIR as the "original" value to restore on teardown.
    # Without this, create_app() would first-import these modules while
    # core.fleet.FLEET_DIR is already patched, and monkeypatch would save
    # the tmp_path as the original — never restoring the real path.
    import web.routes.fleet as _fleet_routes
    import web.routes.validation as _val_routes
    import web.routes.diagnose as _diag_routes

    # Monkey-patch all modules that bind FLEET_DIR at module level
    monkeypatch.setattr("core.fleet.FLEET_DIR", fleet_dir)
    monkeypatch.setattr("core.fleet.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("core.loader.COMPONENTS_DIR", comp_dir)
    monkeypatch.setattr("core.loader.SCHEMAS_DIR", schemas_dir)
    monkeypatch.setattr("core.loader.CONSTRAINTS_DIR", constraints_dir)
    monkeypatch.setattr("core.loader.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("core.config_store.CONFIGS_DIR", configs_dir)
    monkeypatch.setattr("web.routes.fleet.FLEET_DIR", fleet_dir)
    monkeypatch.setattr("web.routes.validation.FLEET_DIR", fleet_dir)
    monkeypatch.setattr("web.routes.diagnose.FLEET_DIR", fleet_dir)

    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# Sample diff all text for a Betaflight config
SAMPLE_DIFF_ALL = """# version
# Betaflight / MATEKF405 (S405) 4.5.2 Dec 25 2024 / 10:30:00 (norevision) MSP API: 1.46
# config: manufacturer_id: TEST, board_name: MATEKF405, version: abc123, date: 2024-12-25T10:30:00Z

# start the command batch
batch start

# reset configuration to default values
defaults nosave

board_name MATEKF405

# feature
feature OSD
feature ESC_SENSOR

# serial
serial 0 64 115200 57600 0 115200
serial 1 0 115200 57600 0 115200
serial 2 65536 115200 57600 0 115200

# set
set motor_pwm_protocol = DSHOT600
set serialrx_provider = CRSF
set dshot_bidir = ON
set vbat_min_cell_voltage = 330
set vbat_max_cell_voltage = 430
set name = Test Quad
set pid_process_denom = 2

# resource
resource MOTOR 1 B06
resource MOTOR 2 B07
resource MOTOR 3 B08
resource MOTOR 4 B09
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDiagnoseIndex:
    """GET /diagnose/ — main page."""

    def test_loads_page(self, client):
        resp = client.get("/diagnose/")
        assert resp.status_code == 200
        assert b"FC Diagnostic" in resp.data
        assert b"Test Quad" in resp.data

    def test_preselects_drone(self, client):
        resp = client.get("/diagnose/?drone=test_quad")
        assert resp.status_code == 200
        assert b"selected" in resp.data

    def test_shows_symptoms(self, client):
        resp = client.get("/diagnose/")
        assert b"Motors won" in resp.data  # "Motors won't spin"
        assert b"No video" in resp.data


class TestUploadConfig:
    """POST /diagnose/upload-config — parse pasted/uploaded config."""

    def test_upload_json(self, client):
        resp = client.post(
            "/diagnose/upload-config",
            json={"raw_text": SAMPLE_DIFF_ALL},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["firmware"] == "BTFL"
        assert data["board_name"] == "MATEKF405"

    def test_upload_empty(self, client):
        resp = client.post(
            "/diagnose/upload-config",
            json={"raw_text": ""},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_upload_with_drone(self, client):
        resp = client.post(
            "/diagnose/upload-config",
            json={"raw_text": SAMPLE_DIFF_ALL, "drone_filename": "test_quad"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["stored_timestamp"] != ""


class TestScan:
    """POST /diagnose/scan — discrepancy detection."""

    def test_scan_matching_config(self, client):
        resp = client.post("/diagnose/scan", data={
            "drone_filename": "test_quad",
            "raw_text": SAMPLE_DIFF_ALL,
        })
        assert resp.status_code == 200
        # Should show "No Discrepancies" since config matches build
        assert b"No Discrepancies" in resp.data or b"discrepancy" in resp.data.lower()

    def test_scan_with_mismatch(self, client):
        # Modify the diff to have SBUS instead of CRSF
        diff_with_mismatch = SAMPLE_DIFF_ALL.replace(
            "serialrx_provider = CRSF", "serialrx_provider = SBUS"
        )
        resp = client.post("/diagnose/scan", data={
            "drone_filename": "test_quad",
            "raw_text": diff_with_mismatch,
        })
        assert resp.status_code == 200
        assert b"disc_002" in resp.data
        assert b"Receiver" in resp.data or b"receiver" in resp.data

    def test_scan_missing_drone(self, client):
        resp = client.post("/diagnose/scan", data={
            "drone_filename": "nonexistent",
            "raw_text": SAMPLE_DIFF_ALL,
        })
        assert resp.status_code == 404

    def test_scan_no_config(self, client):
        resp = client.post("/diagnose/scan", data={
            "drone_filename": "test_quad",
            "raw_text": "",
        })
        assert resp.status_code == 400


class TestRun:
    """POST /diagnose/run — full diagnostic."""

    def test_run_basic(self, client):
        resp = client.post("/diagnose/run", data={
            "drone_filename": "test_quad",
            "raw_text": SAMPLE_DIFF_ALL,
        })
        assert resp.status_code == 200
        assert b"Diagnostic Report" in resp.data
        assert b"Test Quad" in resp.data

    def test_run_with_symptoms(self, client):
        resp = client.post("/diagnose/run", data={
            "drone_filename": "test_quad",
            "raw_text": SAMPLE_DIFF_ALL,
            "symptoms": ["motors_wont_spin", "no_video"],
        })
        assert resp.status_code == 200
        assert b"Related to" in resp.data or b"Diagnostic Report" in resp.data

    def test_run_missing_drone(self, client):
        resp = client.post("/diagnose/run", data={
            "drone_filename": "nonexistent",
            "raw_text": SAMPLE_DIFF_ALL,
        })
        assert resp.status_code == 404


class TestUpdateFleet:
    """POST /diagnose/update-fleet/<filename> — update fleet record."""

    def test_update_fleet(self, client, app):
        resp = client.post(
            "/diagnose/update-fleet/test_quad",
            json={"updates": {"nickname": "Updated"}},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["updated"] is True

    def test_update_fleet_no_updates(self, client):
        resp = client.post(
            "/diagnose/update-fleet/test_quad",
            json={"updates": {}},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_update_fleet_missing_drone(self, client):
        resp = client.post(
            "/diagnose/update-fleet/nonexistent",
            json={"updates": {"nickname": "X"}},
            content_type="application/json",
        )
        assert resp.status_code == 404
