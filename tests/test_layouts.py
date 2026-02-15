"""Tests for core/layouts.py — component layout definitions."""

from __future__ import annotations

import pytest

from core.layouts import (
    QUAD_LAYOUT,
    FLYING_WING_LAYOUT,
    VTOL_LAYOUT,
    CLASS_TO_LAYOUT,
    ComponentSlot,
    get_layout,
    get_motor_count,
)


class TestComponentSlot:
    """Test the ComponentSlot dataclass."""

    def test_slot_is_frozen(self):
        slot = ComponentSlot("motor", "motor", 4, required=True)
        with pytest.raises(AttributeError):
            slot.quantity = 5

    def test_slot_attributes(self):
        slot = ComponentSlot("servo", "servo", 2, required=True)
        assert slot.component_type == "servo"
        assert slot.key == "servo"
        assert slot.quantity == 2
        assert slot.required is True


class TestQuadLayout:
    """Verify the quad layout has the expected slots."""

    def test_motor_count_is_4(self):
        motor_slots = [s for s in QUAD_LAYOUT if s.component_type == "motor"]
        assert len(motor_slots) == 1
        assert motor_slots[0].quantity == 4

    def test_no_servo_slot(self):
        servo_slots = [s for s in QUAD_LAYOUT if s.component_type == "servo"]
        assert len(servo_slots) == 0

    def test_no_airframe_slot(self):
        airframe_slots = [s for s in QUAD_LAYOUT if s.component_type == "airframe"]
        assert len(airframe_slots) == 0

    def test_has_frame_slot(self):
        frame_slots = [s for s in QUAD_LAYOUT if s.component_type == "frame"]
        assert len(frame_slots) == 1
        assert frame_slots[0].required is True

    def test_required_components(self):
        required = {s.component_type for s in QUAD_LAYOUT if s.required}
        assert "motor" in required
        assert "esc" in required
        assert "fc" in required
        assert "frame" in required
        assert "battery" in required


class TestFlyingWingLayout:
    """Verify the flying wing layout."""

    def test_motor_count_is_1(self):
        motor_slots = [s for s in FLYING_WING_LAYOUT if s.component_type == "motor"]
        assert len(motor_slots) == 1
        assert motor_slots[0].quantity == 1

    def test_servo_count_is_2(self):
        servo_slots = [s for s in FLYING_WING_LAYOUT if s.component_type == "servo"]
        assert len(servo_slots) == 1
        assert servo_slots[0].quantity == 2
        assert servo_slots[0].required is True

    def test_has_airframe_not_frame(self):
        airframe_slots = [s for s in FLYING_WING_LAYOUT if s.component_type == "airframe"]
        frame_slots = [s for s in FLYING_WING_LAYOUT if s.component_type == "frame"]
        assert len(airframe_slots) == 1
        assert len(frame_slots) == 0


class TestVTOLLayout:
    """Verify the VTOL layout."""

    def test_motor_count_is_5(self):
        motor_slots = [s for s in VTOL_LAYOUT if s.component_type == "motor"]
        assert len(motor_slots) == 1
        assert motor_slots[0].quantity == 5

    def test_esc_count_is_2(self):
        esc_slots = [s for s in VTOL_LAYOUT if s.component_type == "esc"]
        assert len(esc_slots) == 1
        assert esc_slots[0].quantity == 2

    def test_prop_count_is_2(self):
        prop_slots = [s for s in VTOL_LAYOUT if s.component_type == "propeller"]
        assert len(prop_slots) == 1
        assert prop_slots[0].quantity == 2

    def test_has_servo_and_airframe(self):
        servo_slots = [s for s in VTOL_LAYOUT if s.component_type == "servo"]
        airframe_slots = [s for s in VTOL_LAYOUT if s.component_type == "airframe"]
        assert len(servo_slots) == 1
        assert len(airframe_slots) == 1


class TestGetLayout:
    """Test the get_layout() function."""

    def test_quad_classes_return_quad_layout(self):
        for cls in ("5inch_freestyle", "5inch_race", "3inch", "whoop", "7inch_lr"):
            layout = get_layout(cls)
            assert layout is QUAD_LAYOUT, f"{cls} should use QUAD_LAYOUT"

    def test_flying_wing_class(self):
        assert get_layout("flying_wing") is FLYING_WING_LAYOUT

    def test_vtol_class(self):
        assert get_layout("vtol") is VTOL_LAYOUT

    def test_unknown_class_defaults_to_quad(self):
        assert get_layout("unknown_xyz") is QUAD_LAYOUT


class TestGetMotorCount:
    """Test the get_motor_count() function."""

    def test_quad_motor_count(self):
        assert get_motor_count("5inch_freestyle") == 4
        assert get_motor_count("whoop") == 4

    def test_flying_wing_motor_count(self):
        assert get_motor_count("flying_wing") == 1

    def test_vtol_motor_count(self):
        assert get_motor_count("vtol") == 5

    def test_unknown_class_defaults_to_4(self):
        assert get_motor_count("some_unknown_class") == 4
