"""Fleet management CLI commands for DroneBuilder."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import click

from core.fleet import FLEET_DIR, load_fleet, load_fleet_drone, save_fleet_drone, remove_fleet_drone, name_to_filename
from core.loader import load_all_components_by_id
from core.models import Severity
from engines.compatibility import validate_build


def _name_to_filename(name: str) -> str:
    """Convert a drone name to a safe filename slug."""
    return name_to_filename(name)


def _find_drone_by_name(name: str):
    """Find a fleet drone by name (case-insensitive). Returns (Build, data_dict) or exits."""
    fleet = load_fleet()
    name_lower = name.lower()
    for drone in fleet:
        if drone.name.lower() == name_lower:
            # Re-read the raw JSON for the data dict
            if drone.source_file:
                with open(drone.source_file) as f:
                    data = json.load(f)
                return drone, data
    click.echo(click.style(f"Error: no fleet drone named '{name}'", fg="red"))
    sys.exit(1)


# ---------------------------------------------------------------------------
# Fleet command group
# ---------------------------------------------------------------------------

@click.group("fleet")
def fleet_group():
    """Manage your personal drone fleet."""


# ---------------------------------------------------------------------------
# fleet list
# ---------------------------------------------------------------------------

@fleet_group.command("list")
@click.option("--status", "-s", default=None, help="Filter by status (active, building, retired, etc.).")
@click.option("--class", "drone_class", default=None, help="Filter by drone class.")
def fleet_list(status: str | None, drone_class: str | None):
    """List all drones in your fleet."""
    fleet = load_fleet()

    if status:
        fleet = [d for d in fleet if d.status == status]
    if drone_class:
        fleet = [d for d in fleet if d.drone_class == drone_class]

    if not fleet:
        click.echo(click.style("  No fleet drones found.", fg="yellow"))
        return

    click.echo()
    click.echo(click.style(f"  Fleet ({len(fleet)} drone{'s' if len(fleet) != 1 else ''})", bold=True))

    # Compute column widths
    name_w = max(len(d.name) for d in fleet)
    name_w = min(max(name_w, 4), 30)
    class_w = max(len(d.drone_class) for d in fleet)
    class_w = min(max(class_w, 5), 20)
    status_w = max(len(d.status) for d in fleet)
    status_w = min(max(status_w, 6), 12)

    header = (
        f"{'Name':<{name_w}}  "
        f"{'Class':<{class_w}}  "
        f"{'Status':<{status_w}}  "
        f"{'Nickname':<15}  "
        f"{'Weight(g)':>9}  "
        f"{'Price($)':>8}"
    )
    click.echo(click.style(f"  {'=' * len(header)}", dim=True))
    click.echo(f"  {click.style(header, bold=True)}")
    click.echo(click.style(f"  {'-' * len(header)}", dim=True))

    for d in fleet:
        status_str = d.status
        if status_str == "active":
            status_styled = click.style(f"{status_str:<{status_w}}", fg="green")
        elif status_str == "building":
            status_styled = click.style(f"{status_str:<{status_w}}", fg="yellow")
        elif status_str in ("retired", "crashed", "sold"):
            status_styled = click.style(f"{status_str:<{status_w}}", fg="red")
        else:
            status_styled = f"{status_str:<{status_w}}"

        nick = d.nickname[:15] if d.nickname else ""
        auw = d.all_up_weight_g
        price = d.total_price_usd

        row = (
            f"  {d.name:<{name_w}}  "
            f"{d.drone_class:<{class_w}}  "
            f"{status_styled}  "
            f"{nick:<15}  "
            f"{auw:>9.0f}  "
            f"{price:>8.2f}"
        )
        click.echo(row)

    click.echo(click.style(f"  {'-' * len(header)}", dim=True))
    click.echo()


# ---------------------------------------------------------------------------
# fleet show
# ---------------------------------------------------------------------------

@fleet_group.command("show")
@click.argument("name")
def fleet_show(name: str):
    """Show detailed info for a fleet drone."""
    drone, data = _find_drone_by_name(name)

    click.echo()
    click.echo(click.style(f"  {drone.name}", bold=True)
               + (f"  ({drone.nickname})" if drone.nickname else ""))
    click.echo(click.style(f"  {'=' * 50}", dim=True))
    click.echo(f"  Class    : {drone.drone_class}")
    click.echo(f"  Status   : {drone.status}")
    if drone.acquired_date:
        click.echo(f"  Acquired : {drone.acquired_date}")
    if drone.notes:
        click.echo(f"  Notes    : {drone.notes}")
    if drone.tags:
        click.echo(f"  Tags     : {', '.join(drone.tags)}")

    click.echo()
    click.echo(click.style("  Components:", bold=True))
    click.echo(click.style(f"  {'-' * 50}", dim=True))

    comp_order = ["motor", "esc", "fc", "frame", "airframe", "propeller", "battery",
                  "servo", "vtx", "receiver"]

    for comp_type in comp_order:
        comp = drone.components.get(comp_type)
        if comp is None:
            continue

        comp_status = drone.component_status.get(comp_type, "")
        status_suffix = f"  [{comp_status}]" if comp_status else ""

        if isinstance(comp, list):
            qty = len(comp)
            first = comp[0]
            label = f"{comp_type} x{qty}"
            click.echo(
                f"    {label:>14}: {first.manufacturer} {first.model}"
                f"  (${first.price_usd:.2f} ea){status_suffix}"
            )
        else:
            click.echo(
                f"    {comp_type:>14}: {comp.manufacturer} {comp.model}"
                f"  (${comp.price_usd:.2f}){status_suffix}"
            )

    click.echo(click.style(f"  {'-' * 50}", dim=True))
    click.echo(f"  All-up weight : {drone.all_up_weight_g:.0f} g")
    click.echo(f"  Total cost    : ${drone.total_price_usd:.2f}")
    click.echo()


# ---------------------------------------------------------------------------
# fleet add
# ---------------------------------------------------------------------------

@fleet_group.command("add")
@click.option("--name", required=True, help="Name for the drone.")
@click.option("--class", "drone_class", required=True, help="Drone class (5inch_freestyle, flying_wing, vtol, etc.).")
@click.option("--motor", "motor_id", default=None, help="Motor component ID.")
@click.option("--esc", "esc_id", default=None, help="ESC component ID.")
@click.option("--fc", "fc_id", default=None, help="Flight controller component ID.")
@click.option("--frame", "frame_id", default=None, help="Frame component ID (quad classes).")
@click.option("--airframe", "airframe_id", default=None, help="Airframe component ID (wing/vtol classes).")
@click.option("--propeller", "propeller_id", default=None, help="Propeller component ID.")
@click.option("--battery", "battery_id", default=None, help="Battery component ID.")
@click.option("--vtx", "vtx_id", default=None, help="VTX component ID.")
@click.option("--receiver", "receiver_id", default=None, help="Receiver component ID.")
@click.option("--servo", "servo_ids", multiple=True, help="Servo component ID (repeat for multiple).")
@click.option("--status", default="active", help="Initial status (default: active).")
@click.option("--nickname", default="", help="Optional nickname.")
@click.option("--from-build", "from_build", type=click.Path(exists=True), default=None,
              help="Import component IDs from an existing build JSON file.")
def fleet_add(name, drone_class, motor_id, esc_id, fc_id, frame_id, airframe_id,
              propeller_id, battery_id, vtx_id, receiver_id, servo_ids,
              status, nickname, from_build):
    """Add a new drone to your fleet."""
    drone_data: dict = {
        "name": name,
        "drone_class": drone_class,
        "status": status,
    }
    if nickname:
        drone_data["nickname"] = nickname

    # Import from an existing build file if provided
    if from_build:
        with open(from_build) as f:
            build_data = json.load(f)
        for key in ("motor", "esc", "fc", "frame", "propeller", "battery", "vtx", "receiver"):
            if key in build_data and key not in drone_data:
                drone_data[key] = build_data[key]

    # CLI options override imported values
    if motor_id:
        drone_data["motor"] = motor_id
    if esc_id:
        drone_data["esc"] = esc_id
    if fc_id:
        drone_data["fc"] = fc_id
    if frame_id:
        drone_data["frame"] = frame_id
    if airframe_id:
        drone_data["airframe"] = airframe_id
    if propeller_id:
        drone_data["propeller"] = propeller_id
    if battery_id:
        drone_data["battery"] = battery_id
    if vtx_id:
        drone_data["vtx"] = vtx_id
    if receiver_id:
        drone_data["receiver"] = receiver_id
    if servo_ids:
        drone_data["servo"] = list(servo_ids)

    filename = _name_to_filename(name)
    filepath = save_fleet_drone(drone_data, filename)

    click.echo(click.style(f"  Added '{name}' to fleet.", fg="green", bold=True))
    click.echo(f"  Saved to: {filepath}")


# ---------------------------------------------------------------------------
# fleet update
# ---------------------------------------------------------------------------

@fleet_group.command("update")
@click.argument("name")
@click.option("--status", default=None, help="Update status.")
@click.option("--nickname", default=None, help="Update nickname.")
@click.option("--set-component", "set_components", multiple=True,
              help="Set a component: TYPE=ID (e.g., --set-component motor=motor_emax_eco2_2306_1900kv).")
@click.option("--set-component-status", "set_comp_status", multiple=True,
              help="Set component status: TYPE=STATUS (e.g., --set-component-status esc=needs_replacement).")
def fleet_update(name, status, nickname, set_components, set_comp_status):
    """Update a fleet drone's metadata or components."""
    drone, data = _find_drone_by_name(name)

    if status:
        data["status"] = status
    if nickname is not None:
        data["nickname"] = nickname

    for item in set_components:
        if "=" not in item:
            click.echo(click.style(f"Error: expected TYPE=ID format, got '{item}'", fg="red"))
            sys.exit(1)
        comp_type, comp_id = item.split("=", 1)
        data[comp_type.strip()] = comp_id.strip()

    if set_comp_status:
        comp_status = data.get("component_status", {})
        for item in set_comp_status:
            if "=" not in item:
                click.echo(click.style(f"Error: expected TYPE=STATUS format, got '{item}'", fg="red"))
                sys.exit(1)
            comp_type, comp_stat = item.split("=", 1)
            comp_status[comp_type.strip()] = comp_stat.strip()
        data["component_status"] = comp_status

    # Save back to the same file
    filename = Path(drone.source_file).stem if drone.source_file else _name_to_filename(name)
    save_fleet_drone(data, filename)

    click.echo(click.style(f"  Updated '{name}'.", fg="green", bold=True))


# ---------------------------------------------------------------------------
# fleet remove
# ---------------------------------------------------------------------------

@fleet_group.command("remove")
@click.argument("name")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
def fleet_remove(name, confirm):
    """Remove a drone from your fleet."""
    drone, data = _find_drone_by_name(name)

    if not confirm:
        click.confirm(f"  Remove '{drone.name}' from fleet?", abort=True)

    if drone.source_file:
        filename = Path(drone.source_file).stem
    else:
        filename = _name_to_filename(name)

    removed = remove_fleet_drone(filename)
    if removed:
        click.echo(click.style(f"  Removed '{drone.name}' from fleet.", fg="green", bold=True))
    else:
        click.echo(click.style(f"  Could not find file for '{drone.name}'.", fg="red"))


# ---------------------------------------------------------------------------
# fleet validate
# ---------------------------------------------------------------------------

@fleet_group.command("validate")
@click.argument("name")
def fleet_validate(name):
    """Run compatibility checks on a fleet drone."""
    drone, data = _find_drone_by_name(name)

    click.echo()
    report = validate_build(drone)
    click.echo(report.summary())
    click.echo()
