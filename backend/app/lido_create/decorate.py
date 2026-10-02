"""Contact icons, placed by code once the designer has built a design that passes its
checks: a small clean icon from the icon library (doodles.py) beside each website /
phone / email / address line — sized to the text, in the text's own colour, the text
nudged over to make room.

Nothing here may make a design worse: every icon is re-checked and dropped if it adds a
problem the design didn't have.
"""

from __future__ import annotations

from app.lido_create.check import text_extent, validate
from app.lido_create.doodles import info_icon, stroke_width
from app.lido_create.kit import Design, Element, Variant, line_count

ICON_GAP = 0.4  # gap between an icon and its text, as a share of the icon size


def _keep_if_ok(design: Design, v: Variant, trial: Design, plan, baseline: int) -> bool:
    return len(validate(trial, v, creative=True, plan=plan)) <= baseline


# --------------------------------------------------------------------------------------
# Contact icons
# --------------------------------------------------------------------------------------


def add_contact_icons(design: Design, v: Variant, plan=None) -> tuple[Design, list[str]]:
    """A clean icon left of every contact line that has one in the library. Returns the
    design and which text types got an icon."""
    baseline = len(validate(design, v, creative=True, plan=plan))
    added: list[str] = []
    for kind in ("website", "phone", "email", "address"):
        icon = info_icon(kind)
        index = next((i for i, e in enumerate(design.elements)
                      if e.kind == "text" and e.text_type == kind), None)
        if icon is None or index is None:
            continue
        trial = _with_icon(design, v, index, icon.name)
        if trial is not None and _keep_if_ok(design, v, trial, plan, baseline):
            design = trial
            added.append(kind)
    return design, added


def _with_icon(design: Design, v: Variant, index: int, name: str) -> Design | None:
    els = [e.model_copy() for e in design.elements]
    text = els[index]
    lh = (text.size or 24) * (text.line_height or 1.3)
    size = round(min(44.0, max(22.0, (text.size or 24) * 1.1)), 1)
    gap = round(size * ICON_GAP, 1)
    if (text.align or "left") == "left":
        # make room: the text moves right by the icon and its gap
        text.x, text.w = text.x + size + gap, text.w - size - gap
        lines, wide = line_count(v.fonts, text)
        if wide or (text.max_lines and len(lines) > text.max_lines) or text.w < 80:
            return None
        text.h = round(len(lines) * lh, 2)
        x = text.x - size - gap
    else:
        x = text_extent(text, v)[0] - size - gap
    y = text.y + (lh - size) / 2
    if x < 30:
        return None
    icon = Element(kind="draw", doodle=name, x=round(x, 2), y=round(y, 2), w=size, h=size,
                   color=text.color or "ink", stroke_width=stroke_width(size))
    els.insert(index + 1, icon)
    return design.model_copy(update={"elements": els})
