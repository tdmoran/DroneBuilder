"""Tests for fleet management — core/fleet.py and CLI commands."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from core.fleet import (
    FLEET_DIR,
    load_fleet,
    load_fleet_drone,
    save_fleet_drone,
    remove_fleet_drone,
)
from core.models import Build, Component


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_fleet_dir():
    """Ensure fleet dir is clean before and after each test."""
    backup_files = []
    if FLEET_DIR.exists():
        # Preserve any existing .gitkeep
        for f in FLEET_DIR.iterdir():
            if f.name != ".gitkeep":
                backup_files.append(f)
                f.rename(f.with_suffix(f.suffix + ".bak"))

    yield

    # Clean up test files, restore backups
    if FLEET_DIR.exists():
        for f in FLEET_DIR.iterdir():
            if f.name != ".gitkeep" and not f.name.endswith(".bak"):
                f.unlink()
        for f in FLEET_DIR.glob("*.bak"):
            f.rename(f.with_suffix(""))


# ---------------------------------------------------------------------------
# Test: fleet CRUD operations
# ---------------------------------------------------------------------------

class TestFleetCRUD:
    """Test save, load, and remove fleet drones."""

    def test_save_and_load_basic_drone(self):
        data = {
            "name": "Test Quad",
            "drone_class": "5inch_freestyle",
            "status": "active",
            "motor": "motor_emax_eco2_2306_1900kv",
            "esc": "esc_speedybee_bls_50a_4in1",
            "fc": "fc_speedybee_f405_v4",
            "frame": "frame_tbs_source_one_v5",
            "propeller": "prop_gemfan_51466_hurricane",
            "battery": "battery_cnhl_ministar_1300_6s_100c",
        }
        filepath = save_fleet_drone(data, "test_quad")
        assert filepath.exists()

        fleet = load_fleet()
        assert len(fleet) >= 1
        drone = next(d for d in fleet if d.name == "Test Quad")
        assert drone.drone_class == "5inch_freestyle"
        assert drone.status == "active"

    def test_save_appends_json_extension(self):
        data = {"name": "Test", "drone_class": "whoop"}
        filepath = save_fleet_drone(data, "no_ext")
        assert filepath.suffix == ".json"

    def test_load_fleet_drone_with_db_components(self):
        data = {
            "name": "DB Components Quad",
            "drone_class": "5inch_freestyle",
            "motor": "motor_emax_eco2_2306_1900kv",
            "esc": "esc_speedybee_bls_50a_4in1",
        }
        drone = load_fleet_drone(data)
        assert drone.name == "DB Components Quad"
        assert drone.motor is not None
        assert drone.motor.manufacturer == "Emax"
        # Motor should be replicated 4x for quad class
        assert drone.motor_count == 4

    def test_load_fleet_drone_with_custom_components(self):
        data = {
            "name": "Custom Wing",
            "drone_class": "flying_wing",
            "motor": {
                "_custom": True,
                "id": "custom_test_motor",
                "component_type": "motor",
                "manufacturer": "TestMfr",
                "model": "TestMotor 2212",
                "weight_g": 56.0,
                "price_usd": 18.00,
                "specs": {"kv": 980},
            },
        }
        drone = load_fleet_drone(data)
        assert drone.name == "Custom Wing"
        assert drone.motor is not None
        assert drone.motor.manufacturer == "TestMfr"
        assert drone.motor.specs.get("kv") == 980
        # Flying wing = 1 motor
        assert drone.motor_count == 1

    def test_load_fleet_drone_with_servo_list(self):
        data = {
            "name": "Servo Test",
            "drone_class": "flying_wing",
            "servo": ["servo_emax_es08a", "servo_emax_es08a"],
        }
        drone = load_fleet_drone(data)
        assert drone.servo_count == 2

    def test_load_fleet_drone_metadata(self):
        data = {
            "name": "Full Meta",
            "drone_class": "5inch_freestyle",
            "status": "building",
            "nickname": "Zippy",
            "notes": "Still waiting for ESC",
            "tags": ["freestyle", "budget"],
            "acquired_date": "2025-12-01",
            "component_status": {"motor": "good", "esc": "ordered"},
        }
        drone = load_fleet_drone(data)
        assert drone.status == "building"
        assert drone.nickname == "Zippy"
        assert drone.notes == "Still waiting for ESC"
        assert "freestyle" in drone.tags
        assert drone.acquired_date == "2025-12-01"
        assert drone.component_status["esc"] == "ordered"

    def test_remove_fleet_drone(self):
        data = {"name": "To Remove", "drone_class": "whoop"}
        save_fleet_drone(data, "to_remove")
        assert remove_fleet_drone("to_remove") is True
        assert remove_fleet_drone("to_remove") is False  # already gone

    def test_load_fleet_empty_dir(self):
        fleet = load_fleet()
        # May or may not have test files, but should not error
        assert isinstance(fleet, list)

    def test_motor_replication_for_vtol(self):
        data = {
            "name": "VTOL Test",
            "drone_class": "vtol",
            "motor": "motor_emax_eco2_2306_1900kv",
        }
        drone = load_fleet_drone(data)
        assert drone.motor_count == 5


class TestFleetMixedComponents:
    """Test builds with a mix of DB and custom components."""

    def test_custom_airframe_with_db_servos(self):
        data = {
            "name": "Chupito",
            "drone_class": "flying_wing",
            "airframe": {
                "_custom": True,
                "id": "custom_tbs_chupito",
                "component_type": "airframe",
                "manufacturer": "TBS",
                "model": "Chupito",
                "weight_g": 180.0,
                "price_usd": 89.00,
                "specs": {"wingspan_mm": 800, "material": "epp_foam"},
            },
            "servo": ["servo_emax_es08a", "servo_emax_es08a"],
            "fc": "fc_speedybee_f405_v4",
            "battery": "battery_cnhl_ministar_1300_6s_100c",
        }
        drone = load_fleet_drone(data)
        assert drone.get_component("airframe") is not None
        assert drone.get_component("airframe").manufacturer == "TBS"
        assert drone.servo_count == 2
        assert drone.get_component("fc") is not None
        assert drone.all_up_weight_g > 0
        assert drone.total_price_usd > 0


# ---------------------------------------------------------------------------
# Test: Fleet CLI commands
# ---------------------------------------------------------------------------

class TestFleetCLI:
    """Integration tests for the fleet CLI commands."""

    def _get_runner_and_cli(self):
        from cli.main import cli
        from cli.fleet import fleet_group
        # Ensure fleet group is registered
        if "fleet" not in [c.name for c in cli.commands.values()]:
            cli.add_command(fleet_group)
        return CliRunner(), cli

    def test_fleet_add_and_list(self):
        runner, cli = self._get_runner_and_cli()

        # Add a drone
        result = runner.invoke(cli, [
            "fleet", "add",
            "--name", "CLI Test Quad",
            "--class", "5inch_freestyle",
            "--motor", "motor_emax_eco2_2306_1900kv",
            "--esc", "esc_speedybee_bls_50a_4in1",
            "--fc", "fc_speedybee_f405_v4",
            "--frame", "frame_tbs_source_one_v5",
            "--propeller", "prop_gemfan_51466_hurricane",
            "--battery", "battery_cnhl_ministar_1300_6s_100c",
        ])
        assert result.exit_code == 0, result.output
        assert "Added" in result.output

        # List
        result = runner.invoke(cli, ["fleet", "list"])
        assert result.exit_code == 0, result.output
        assert "CLI Test Quad" in result.output

    def test_fleet_show(self):
        runner, cli = self._get_runner_and_cli()

        # First add a drone
        runner.invoke(cli, [
            "fleet", "add",
            "--name", "Show Test",
            "--class", "5inch_freestyle",
            "--motor", "motor_emax_eco2_2306_1900kv",
        ])

        result = runner.invoke(cli, ["fleet", "show", "Show Test"])
        assert result.exit_code == 0, result.output
        assert "Show Test" in result.output
        assert "5inch_freestyle" in result.output

    def test_fleet_remove_with_confirm(self):
        runner, cli = self._get_runner_and_cli()

        runner.invoke(cli, [
            "fleet", "add",
            "--name", "Remove Me",
            "--class", "whoop",
        ])

        result = runner.invoke(cli, ["fleet", "remove", "Remove Me", "--confirm"])
        assert result.exit_code == 0, result.output
        assert "Removed" in result.output

    def test_fleet_validate_quad(self):
        runner, cli = self._get_runner_and_cli()

        runner.invoke(cli, [
            "fleet", "add",
            "--name", "Validate Test",
            "--class", "5inch_freestyle",
            "--motor", "motor_emax_eco2_2306_1900kv",
            "--esc", "esc_speedybee_bls_50a_4in1",
            "--fc", "fc_speedybee_f405_v4",
            "--frame", "frame_tbs_source_one_v5",
            "--propeller", "prop_gemfan_51466_hurricane",
            "--battery", "battery_cnhl_ministar_1300_6s_100c",
        ])

        result = runner.invoke(cli, ["fleet", "validate", "Validate Test"])
        assert result.exit_code == 0, result.output
        # Should contain validation output
        assert "Validate Test" in result.output or "Validation" in result.output

    def test_fleet_list_filter_by_status(self):
        runner, cli = self._get_runner_and_cli()

        runner.invoke(cli, [
            "fleet", "add",
            "--name", "Active One",
            "--class", "5inch_freestyle",
            "--status", "active",
        ])
        runner.invoke(cli, [
            "fleet", "add",
            "--name", "Building One",
            "--class", "3inch",
            "--status", "building",
        ])

        result = runner.invoke(cli, ["fleet", "list", "--status", "building"])
        assert result.exit_code == 0, result.output
        assert "Building One" in result.output

    def test_fleet_update_status(self):
        runner, cli = self._get_runner_and_cli()

        runner.invoke(cli, [
            "fleet", "add",
            "--name", "Update Test",
            "--class", "5inch_freestyle",
        ])

        result = runner.invoke(cli, [
            "fleet", "update", "Update Test",
            "--status", "retired",
        ])
        assert result.exit_code == 0, result.output
        assert "Updated" in result.output

        # Verify the update persisted
        result = runner.invoke(cli, ["fleet", "show", "Update Test"])
        assert "retired" in result.output
