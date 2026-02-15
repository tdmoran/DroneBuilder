"""Component browsing routes."""

from __future__ import annotations

from flask import Blueprint, render_template, request, abort

from core.loader import load_components, load_all_components_by_id

components_bp = Blueprint("components", __name__)

# Human-friendly labels for component types
TYPE_LABELS = {
    "motor": "Motors",
    "esc": "ESCs",
    "fc": "Flight Controllers",
    "frame": "Frames",
    "propeller": "Propellers",
    "battery": "Batteries",
    "vtx": "Video Transmitters",
    "receiver": "Receivers",
    "servo": "Servos",
    "airframe": "Airframes",
}


@components_bp.route("/")
def browse():
    """Component type selector cards with counts."""
    all_components = load_components()
    type_data = []
    for ctype, comps in sorted(all_components.items()):
        type_data.append({
            "type": ctype,
            "label": TYPE_LABELS.get(ctype, ctype.title()),
            "count": len(comps),
        })
    return render_template("components/browse.html", types=type_data)


@components_bp.route("/<component_type>")
def component_list(component_type: str):
    """Filtered and sorted component table."""
    all_components = load_components(component_type)
    if component_type not in all_components:
        abort(404)

    comps = all_components[component_type]
    label = TYPE_LABELS.get(component_type, component_type.title())

    # Gather available categories for filtering
    categories = sorted({c.category for c in comps if c.category})

    # Filter by category
    category = request.args.get("category", "")
    if category:
        comps = [c for c in comps if c.category == category]

    # Sort
    sort_key = request.args.get("sort", "model")
    reverse = request.args.get("order", "asc") == "desc"

    if sort_key == "weight":
        comps.sort(key=lambda c: c.weight_g, reverse=reverse)
    elif sort_key == "price":
        comps.sort(key=lambda c: c.price_usd, reverse=reverse)
    elif sort_key == "manufacturer":
        comps.sort(key=lambda c: c.manufacturer.lower(), reverse=reverse)
    else:
        comps.sort(key=lambda c: c.model.lower(), reverse=reverse)

    return render_template(
        "components/list.html",
        components=comps,
        component_type=component_type,
        label=label,
        categories=categories,
        current_category=category,
        current_sort=sort_key,
        current_order="desc" if reverse else "asc",
    )


@components_bp.route("/<component_type>/<component_id>")
def component_detail(component_type: str, component_id: str):
    """Full spec detail page for a single component."""
    by_id = load_all_components_by_id()
    comp = by_id.get(component_id)
    if not comp or comp.component_type != component_type:
        abort(404)

    label = TYPE_LABELS.get(component_type, component_type.title())
    return render_template(
        "components/detail.html",
        component=comp,
        component_type=component_type,
        label=label,
    )
