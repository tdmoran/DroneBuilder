"""Tests for the DroneBuilder web UI — Flask test client."""

from __future__ import annotations

import json

import pytest

from core.fleet import FLEET_DIR, save_fleet_drone, remove_fleet_drone
from web.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clean_fleet_dir():
    """Ensure fleet dir is clean before and after each test."""
    backup_files = []
    if FLEET_DIR.exists():
        for f in FLEET_DIR.iterdir():
            if f.name != ".gitkeep":
                backup_files.append(f)
                f.rename(f.with_suffix(f.suffix + ".bak"))

    yield

    if FLEET_DIR.exists():
        for f in FLEET_DIR.iterdir():
            if f.name != ".gitkeep" and not f.name.endswith(".bak"):
                f.unlink()
        for f in FLEET_DIR.glob("*.bak"):
            f.rename(f.with_suffix(""))


def _add_test_drone(name="Test Quad", drone_class="5inch_freestyle", filename="test_quad"):
    """Helper to add a test drone directly via core."""
    data = {
        "name": name,
        "drone_class": drone_class,
        "status": "active",
        "motor": "motor_emax_eco2_2306_1900kv",
        "esc": "esc_speedybee_bls_50a_4in1",
        "fc": "fc_speedybee_f405_v4",
        "frame": "frame_tbs_source_one_v5",
        "propeller": "prop_gemfan_51466_hurricane",
        "battery": "battery_cnhl_ministar_1300_6s_100c",
    }
    save_fleet_drone(data, filename)
    return data


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_index_loads(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Dashboard" in resp.data

    def test_index_shows_component_counts(self, client):
        resp = client.get("/")
        assert b"Components" in resp.data
        # Should have at least motor type cards
        assert b"motor" in resp.data.lower()

    def test_index_shows_fleet_count(self, client):
        _add_test_drone()
        resp = client.get("/")
        assert b"1" in resp.data  # at least one drone


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

class TestComponents:
    def test_browse_page(self, client):
        resp = client.get("/components/")
        assert resp.status_code == 200
        assert b"Components" in resp.data
        assert b"Motors" in resp.data

    def test_motor_list(self, client):
        resp = client.get("/components/motor")
        assert resp.status_code == 200
        assert b"Emax" in resp.data or b"T-Motor" in resp.data

    def test_motor_list_filter_by_category(self, client):
        resp = client.get("/components/motor?category=5inch")
        assert resp.status_code == 200

    def test_motor_list_sort_by_weight(self, client):
        resp = client.get("/components/motor?sort=weight")
        assert resp.status_code == 200

    def test_component_detail(self, client):
        resp = client.get("/components/motor/motor_emax_eco2_2306_1900kv")
        assert resp.status_code == 200
        assert b"Emax" in resp.data
        assert b"Eco II 2306 1900KV" in resp.data

    def test_invalid_type_404(self, client):
        resp = client.get("/components/unicorn")
        assert resp.status_code == 404

    def test_invalid_component_id_404(self, client):
        resp = client.get("/components/motor/motor_nonexistent_9999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Fleet — list and detail (read-only)
# ---------------------------------------------------------------------------

class TestFleetReadOnly:
    def test_fleet_list_empty(self, client):
        resp = client.get("/fleet/")
        assert resp.status_code == 200
        assert b"Fleet" in resp.data

    def test_fleet_list_with_drone(self, client):
        _add_test_drone()
        resp = client.get("/fleet/")
        assert resp.status_code == 200
        assert b"Test Quad" in resp.data

    def test_fleet_list_filter_by_status(self, client):
        _add_test_drone()
        resp = client.get("/fleet/?status=active")
        assert resp.status_code == 200
        assert b"Test Quad" in resp.data

    def test_fleet_list_filter_no_match(self, client):
        _add_test_drone()
        resp = client.get("/fleet/?status=retired")
        assert resp.status_code == 200
        assert b"Test Quad" not in resp.data

    def test_fleet_detail(self, client):
        _add_test_drone()
        resp = client.get("/fleet/test_quad")
        assert resp.status_code == 200
        assert b"Test Quad" in resp.data
        assert b"5inch_freestyle" in resp.data

    def test_fleet_detail_shows_components(self, client):
        _add_test_drone()
        resp = client.get("/fleet/test_quad")
        assert b"Emax" in resp.data
        assert b"Validate Build" in resp.data

    def test_fleet_detail_404(self, client):
        resp = client.get("/fleet/nonexistent_drone")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Fleet — add
# ---------------------------------------------------------------------------

class TestFleetAdd:
    def test_new_form_loads(self, client):
        resp = client.get("/fleet/new")
        assert resp.status_code == 200
        assert b"Add Drone" in resp.data

    def test_add_drone(self, client):
        resp = client.post("/fleet/new", data={
            "name": "Web Test Quad",
            "drone_class": "5inch_freestyle",
            "status": "active",
            "comp_motor": "motor_emax_eco2_2306_1900kv",
            "comp_esc": "esc_speedybee_bls_50a_4in1",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Web Test Quad" in resp.data

        # Verify file was created
        assert (FLEET_DIR / "web_test_quad.json").exists()

    def test_add_drone_empty_name_redirects(self, client):
        resp = client.post("/fleet/new", data={
            "name": "",
            "drone_class": "5inch_freestyle",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"required" in resp.data.lower() or b"Add Drone" in resp.data


# ---------------------------------------------------------------------------
# Fleet — edit
# ---------------------------------------------------------------------------

class TestFleetEdit:
    def test_edit_form_loads(self, client):
        _add_test_drone()
        resp = client.get("/fleet/test_quad/edit")
        assert resp.status_code == 200
        assert b"Test Quad" in resp.data
        assert b"Edit" in resp.data

    def test_edit_drone(self, client):
        _add_test_drone()
        resp = client.post("/fleet/test_quad/edit", data={
            "name": "Updated Quad",
            "drone_class": "5inch_freestyle",
            "status": "building",
            "nickname": "Speedy",
            "notes": "Waiting for parts",
            "comp_motor": "motor_emax_eco2_2306_1900kv",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Updated Quad" in resp.data

        # Verify changes persisted
        with open(FLEET_DIR / "test_quad.json") as f:
            data = json.load(f)
        assert data["status"] == "building"
        assert data["nickname"] == "Speedy"

    def test_edit_nonexistent_404(self, client):
        resp = client.get("/fleet/nonexistent/edit")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Fleet — delete
# ---------------------------------------------------------------------------

class TestFleetDelete:
    def test_delete_drone(self, client):
        _add_test_drone()
        assert (FLEET_DIR / "test_quad.json").exists()

        resp = client.post("/fleet/test_quad/delete", follow_redirects=True)
        assert resp.status_code == 200
        assert not (FLEET_DIR / "test_quad.json").exists()

    def test_delete_nonexistent_404(self, client):
        resp = client.post("/fleet/nonexistent/delete")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_validate_drone(self, client):
        _add_test_drone()
        resp = client.get("/validate/test_quad")
        assert resp.status_code == 200
        # Should return validation partial HTML
        assert b"critical" in resp.data.lower() or b"passed" in resp.data.lower()

    def test_validate_nonexistent_404(self, client):
        resp = client.get("/validate/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# htmx partials
# ---------------------------------------------------------------------------

class TestHtmxPartials:
    def test_layout_slots_quad(self, client):
        resp = client.get("/fleet/layout-slots?drone_class=5inch_freestyle")
        assert resp.status_code == 200
        assert b"motor" in resp.data.lower()
        assert b"frame" in resp.data.lower()
        # Quads should not have airframe
        assert b"airframe" not in resp.data.lower()

    def test_layout_slots_wing(self, client):
        resp = client.get("/fleet/layout-slots?drone_class=flying_wing")
        assert resp.status_code == 200
        assert b"servo" in resp.data.lower()
        assert b"airframe" in resp.data.lower()
