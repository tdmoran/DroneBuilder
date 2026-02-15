"""DroneBuilder CLI -- Click-based command-line interface.

Usage:
    dronebuilder list <component_type> [--category <cat>]
    dronebuilder check <id1> <id2>
    dronebuilder validate <build_json>
    dronebuilder calc <build_json>
    dronebuilder suggest --class <class> --budget <usd> [--priority key=val ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from core.loader import load_components, load_all_components_by_id, load_build
from core.models import Component, Severity
from engines.compatibility import validate_build, check_pair
from engines.performance import calculate_performance
from engines.optimizer import optimize, suggest_quick, OptimizationRequest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_TYPES = ["motor", "esc", "fc", "frame", "propeller", "battery", "vtx", "receiver", "servo", "airframe"]


def _truncate(text: str, width: int) -> str:
    """Truncate text to *width* characters, adding ellipsis if needed."""
    if len(text) <= width:
        return text
    return text[: width - 1] + "\u2026"


def _severity_style(severity: Severity, text: str) -> str:
    """Apply Click ANSI styling based on severity level."""
    if severity == Severity.CRITICAL:
        return click.style(text, fg="red", bold=True)
    if severity == Severity.WARNING:
        return click.style(text, fg="yellow")
    return click.style(text, fg="cyan")


def _load_build_file(filepath: str) -> dict:
    """Load and return a build dict from a JSON file path."""
    path = Path(filepath)
    if not path.exists():
        click.echo(click.style(f"Error: file not found: {filepath}", fg="red"))
        sys.exit(1)
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        click.echo(click.style(f"Error: invalid JSON in {filepath}: {exc}", fg="red"))
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(version="1.0.0", prog_name="dronebuilder")
def cli():
    """DroneBuilder -- FPV drone build planner and optimizer."""


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@cli.command("list")
@click.argument("component_type", type=click.Choice(VALID_TYPES, case_sensitive=False))
@click.option("--category", "-c", default=None, help="Filter by category (e.g. 5inch, 3inch, whoop).")
def list_components(component_type: str, category: str | None):
    """List all components of a given type."""
    components = load_components(component_type=component_type)
    comp_list = components.get(component_type, [])

    if category:
        comp_list = [c for c in comp_list if c.category == category]

    if not comp_list:
        click.echo(click.style(f"No {component_type} components found", fg="yellow")
                    + (f" for category '{category}'." if category else "."))
        return

    # Column widths
    id_w = max(len(c.id) for c in comp_list)
    id_w = max(id_w, 4)  # min header width
    mfr_w = max(len(c.manufacturer) for c in comp_list)
    mfr_w = max(mfr_w, 12)
    model_w = max(len(c.model) for c in comp_list)
    model_w = max(model_w, 5)
    cat_w = max(len(c.category) for c in comp_list)
    cat_w = max(cat_w, 8)

    # Cap column widths for readability
    id_w = min(id_w, 40)
    mfr_w = min(mfr_w, 20)
    model_w = min(model_w, 40)
    cat_w = min(cat_w, 18)

    # Header
    header = (
        f"{'ID':<{id_w}}  "
        f"{'Manufacturer':<{mfr_w}}  "
        f"{'Model':<{model_w}}  "
        f"{'Category':<{cat_w}}  "
        f"{'Weight(g)':>9}  "
        f"{'Price($)':>8}"
    )
    click.echo()
    click.echo(click.style(f"  {component_type.upper()} Components", bold=True)
               + (f"  [category={category}]" if category else "")
               + f"  ({len(comp_list)} found)")
    click.echo(click.style(f"  {'=' * len(header)}", dim=True))
    click.echo(f"  {click.style(header, bold=True)}")
    click.echo(click.style(f"  {'-' * len(header)}", dim=True))

    # Rows
    for c in comp_list:
        row = (
            f"  {_truncate(c.id, id_w):<{id_w}}  "
            f"{_truncate(c.manufacturer, mfr_w):<{mfr_w}}  "
            f"{_truncate(c.model, model_w):<{model_w}}  "
            f"{_truncate(c.category, cat_w):<{cat_w}}  "
            f"{c.weight_g:>9.1f}  "
            f"{c.price_usd:>8.2f}"
        )
        click.echo(row)

    click.echo(click.style(f"  {'-' * len(header)}", dim=True))
    click.echo()


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

@cli.command("check")
@click.argument("component_id_1")
@click.argument("component_id_2")
def check_components(component_id_1: str, component_id_2: str):
    """Check pairwise compatibility between two components."""
    by_id = load_all_components_by_id()

    if component_id_1 not in by_id:
        click.echo(click.style(f"Error: unknown component ID '{component_id_1}'", fg="red"))
        sys.exit(1)
    if component_id_2 not in by_id:
        click.echo(click.style(f"Error: unknown component ID '{component_id_2}'", fg="red"))
        sys.exit(1)

    comp_a = by_id[component_id_1]
    comp_b = by_id[component_id_2]

    click.echo()
    click.echo(click.style("  Compatibility Check", bold=True))
    click.echo(click.style(f"  {'=' * 56}", dim=True))
    click.echo(f"  A: {click.style(comp_a.id, fg='bright_white')}  ({comp_a.manufacturer} {comp_a.model})")
    click.echo(f"  B: {click.style(comp_b.id, fg='bright_white')}  ({comp_b.manufacturer} {comp_b.model})")
    click.echo(click.style(f"  {'-' * 56}", dim=True))

    results = check_pair(comp_a, comp_b)

    if not results:
        click.echo(click.style("  No compatibility rules apply to this pair.", fg="cyan"))
        click.echo()
        return

    pass_count = 0
    fail_count = 0

    for r in results:
        if r.details.get("skipped"):
            continue

        if r.passed:
            tag = click.style("[PASS]", fg="green", bold=True)
            pass_count += 1
        else:
            if r.severity == Severity.CRITICAL:
                tag = click.style("[FAIL]", fg="red", bold=True)
            elif r.severity == Severity.WARNING:
                tag = click.style("[WARN]", fg="yellow", bold=True)
            else:
                tag = click.style("[INFO]", fg="cyan")
            fail_count += 1

        click.echo(f"  {tag} {r.constraint_name}")
        click.echo(f"         {r.message}")

    click.echo(click.style(f"  {'-' * 56}", dim=True))

    if fail_count == 0:
        click.echo(click.style("  All checks passed.", fg="green", bold=True))
    else:
        click.echo(
            f"  Results: {click.style(str(pass_count), fg='green')} passed, "
            f"{click.style(str(fail_count), fg='red')} failed"
        )
    click.echo()


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@cli.command("validate")
@click.argument("build_json_file", type=click.Path(exists=True))
def validate_build_cmd(build_json_file: str):
    """Validate a full build from a JSON file."""
    build_data = _load_build_file(build_json_file)
    build = load_build(build_data)

    click.echo()
    report = validate_build(build)
    click.echo(report.summary())
    click.echo()


# ---------------------------------------------------------------------------
# calc
# ---------------------------------------------------------------------------

@cli.command("calc")
@click.argument("build_json_file", type=click.Path(exists=True))
def calc_performance(build_json_file: str):
    """Calculate performance metrics for a build."""
    build_data = _load_build_file(build_json_file)
    build = load_build(build_data)

    click.echo()
    try:
        perf = calculate_performance(build)
    except ValueError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))
        sys.exit(1)

    click.echo(click.style("  Build: ", bold=True) + build.name)
    click.echo(click.style(f"  {'=' * 40}", dim=True))
    click.echo(f"  All-up weight : {build.all_up_weight_g:.0f} g")
    click.echo(f"  Dry weight    : {build.dry_weight_g:.0f} g")
    click.echo(f"  Total cost    : ${build.total_price_usd:.2f}")
    click.echo()
    click.echo(perf.summary())
    click.echo()


# ---------------------------------------------------------------------------
# suggest
# ---------------------------------------------------------------------------

def _parse_priority(ctx, param, value):
    """Parse --priority key=val pairs into a dict."""
    priorities = {}
    for item in value:
        if "=" not in item:
            raise click.BadParameter(f"Expected key=value format, got '{item}'")
        key, val = item.split("=", 1)
        try:
            priorities[key.strip()] = float(val.strip())
        except ValueError:
            raise click.BadParameter(f"Invalid numeric value in '{item}'")
    return priorities


@cli.command("suggest")
@click.option("--class", "drone_class", required=True,
              help="Drone class: 5inch, 3inch, whoop.")
@click.option("--budget", required=True, type=float,
              help="Maximum budget in USD.")
@click.option("--priority", "-p", multiple=True, callback=_parse_priority, expose_value=True,
              is_eager=False,
              help="Priority weight as key=value (e.g. --priority performance=0.5). "
                   "Valid keys: performance, weight, price, durability.")
def suggest_builds(drone_class: str, budget: float, priority: dict):
    """Get optimized build suggestions for a drone class and budget."""
    click.echo()
    click.echo(click.style("  Build Optimizer", bold=True))
    click.echo(click.style(f"  {'=' * 56}", dim=True))
    click.echo(f"  Drone class : {drone_class}")
    click.echo(f"  Budget      : ${budget:.2f}")

    if priority:
        click.echo(f"  Priorities  : {priority}")
    click.echo()

    click.echo(click.style("  Searching for optimal builds...", dim=True))

    if priority:
        request = OptimizationRequest(
            drone_class=drone_class,
            budget_usd=budget,
            priorities=priority,
        )
        suggestions = optimize(request)
    else:
        suggestions = optimize(OptimizationRequest(drone_class=drone_class, budget_usd=budget))

    if not suggestions:
        click.echo(click.style(
            "\n  No valid builds found within the given budget and constraints.",
            fg="yellow",
        ))
        click.echo()
        return

    click.echo(click.style(f"\n  Found {len(suggestions)} build suggestion(s):\n", fg="green", bold=True))

    for i, s in enumerate(suggestions, 1):
        click.echo(click.style(f"  --- Suggestion #{i} ---", bold=True))
        click.echo(f"  Score : {click.style(f'{s.score:.1f}', fg='bright_white', bold=True)} / 100")
        click.echo(f"  Cost  : ${s.total_cost:.2f}")

        # Score breakdown
        breakdown_parts = []
        for key, val in sorted(s.score_breakdown.items()):
            breakdown_parts.append(f"{key}={val:.1f}")
        click.echo(f"  Breakdown : {', '.join(breakdown_parts)}")

        # Component list
        click.echo(f"  Components:")
        for comp_type in ["motor", "esc", "fc", "frame", "propeller", "battery", "vtx", "receiver"]:
            comp = s.build.get_component(comp_type)
            if comp:
                qty = ""
                if comp_type == "motor":
                    qty = " x4"
                price_str = f"${comp.price_usd:.2f}"
                if comp_type == "motor":
                    price_str = f"${comp.price_usd * 4:.2f}"
                click.echo(
                    f"    {comp_type:>10}: {comp.manufacturer} {comp.model}{qty}"
                    f"  ({price_str})"
                )

        click.echo()

    click.echo(click.style(f"  {'=' * 56}", dim=True))
    click.echo()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@cli.command("web")
@click.option("--port", "-p", default=5555, type=int, help="Port to run on (default: 5555).")
@click.option("--no-open", is_flag=True, help="Don't auto-open the browser.")
def web_server(port: int, no_open: bool):
    """Launch the DroneBuilder web UI."""
    import threading
    import webbrowser

    from web.app import create_app

    app = create_app()
    url = f"http://127.0.0.1:{port}"

    if not no_open:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()

    click.echo(f"  Starting DroneBuilder web UI at {click.style(url, bold=True)}")
    click.echo(click.style("  Press Ctrl+C to stop.\n", dim=True))
    app.run(host="127.0.0.1", port=port, debug=True)


def main():
    # Register fleet commands
    from cli.fleet import fleet_group
    cli.add_command(fleet_group)

    cli()


if __name__ == "__main__":
    main()
