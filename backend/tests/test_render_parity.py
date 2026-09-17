"""Render parity — IMPLEMENTATION_PLAN §0.11, §5.2, INV-3.

§5.2 compares a browser render against a server render with SSIM and fails below 0.995.
Under ADR 0001 the two renderers consume the *same* draw list — the browser does not
build one of its own — so the meaningful checks here are:

  1. the draw list is deterministic and stable for a given document;
  2. the geometry it carries survives a JSON round-trip byte-for-byte, since that is the
     wire the browser receives;
  3. the server render of that draw list is itself deterministic;
  4. text is described by resolved glyph ids and positions, so a browser that redraws
     them cannot re-shape and drift (the classic INV-3 failure, Appendix A.5).

The browser half — Playwright rendering the same draw list and comparing with SSIM —
belongs in CI where a browser is available; `render_ssim` below is the comparison the
harness uses, and is exercised here against server renders.
"""

import io
import json

import numpy as np
import pytest

from app.renderer.core import to_draw_list
from app.renderer.skia_backend import render_png, render_surface, surface_to_numpy
from app.schema.doc import (
    AutoFit,
    Canvas,
    Constraints,
    DesignDoc,
    FontRef,
    Frame,
    GradientStop,
    GroupLayer,
    ImageLayer,
    LinearGradient,
    ShadowEffect,
    ShapeLayer,
    TextLayer,
)
from app.schema.draw import DrawList

SSIM_THRESHOLD = 0.995


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Global SSIM on luminance. Sufficient for the golden-image gate in §5.2."""
    if a.shape != b.shape:
        return 0.0
    x = a[:, :, :3].astype(np.float64).mean(axis=2)
    y = b[:, :, :3].astype(np.float64).mean(axis=2)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mx, my = x.mean(), y.mean()
    vx, vy = x.var(), y.var()
    cov = ((x - mx) * (y - my)).mean()
    return float(
        ((2 * mx * my + c1) * (2 * cov + c2)) / ((mx**2 + my**2 + c1) * (vx + vy + c2))
    )


def fixture_doc() -> DesignDoc:
    """Covers what §5.2 requires fixtures to cover: rotation, groups, blend modes,
    effects, alpha edges, autofit at both bounds, and every layer type."""
    return DesignDoc(
        id="fixture_1",
        title="Parity fixture",
        canvas=Canvas(width=800, height=1000, background="#0F172A", safeMargin=48),
        palette=["#0F172A", "#F5B700", "#FFFFFF", "#94A3B8"],
        fonts=[FontRef(family="Inter", weights=[400, 700, 900]),
               FontRef(family="Playfair Display", weights=[400, 700])],
        layers=[
            ShapeLayer(id="bg", role="background", shape="rect", fill="#0F172A",
                       frame=Frame(x=0, y=0, w=800, h=1000),
                       constraints=Constraints(horizontal="stretch", vertical="stretch",
                                               priority=100)),
            ShapeLayer(id="scrim", role="overlay", shape="rect",
                       frame=Frame(x=0, y=500, w=800, h=500),
                       gradient=LinearGradient(angle=180, stops=[
                           GradientStop(offset=0, color="#000000", opacity=0.0),
                           GradientStop(offset=1, color="#000000", opacity=0.8)]),
                       constraints=Constraints(priority=20)),
            ShapeLayer(id="rotated", role="decoration", shape="rect", fill="#F5B700",
                       radius=12, frame=Frame(x=520, y=120, w=180, h=180, rotation=17),
                       blendMode="screen", opacity=0.8,
                       effects=[ShadowEffect(dx=4, dy=10, blur=24, opacity=0.5)],
                       constraints=Constraints(priority=30)),
            ShapeLayer(id="ellipse", role="decoration", shape="ellipse", fill="#94A3B8",
                       frame=Frame(x=80, y=620, w=220, h=140), opacity=0.65,
                       blendMode="multiply", constraints=Constraints(priority=25)),
            GroupLayer(id="group", role="decoration",
                       frame=Frame(x=100, y=780, w=320, h=120, rotation=-8),
                       constraints=Constraints(priority=25), children=[
                           ShapeLayer(id="chip", role="badge", shape="rect", radius=999,
                                      fill="#FFFFFF",
                                      frame=Frame(x=0, y=0, w=200, h=56),
                                      constraints=Constraints(priority=25)),
                           TextLayer(id="chip_text", role="badge", content="Grouped",
                                     fontFamily="Inter", fontWeight=700, fontSize=24,
                                     color="#0F172A", align="center",
                                     verticalAlign="middle",
                                     frame=Frame(x=0, y=0, w=200, h=56),
                                     constraints=Constraints(priority=25)),
                       ]),
            TextLayer(id="headline", role="headline", content="Parity\nCheck",
                      fontFamily="Inter", fontWeight=900, fontSize=96, lineHeight=0.95,
                      letterSpacing=-3, textTransform="uppercase", color="#FFFFFF",
                      autoFit=AutoFit(min=48, max=120, mode="shrink"),
                      frame=Frame(x=48, y=96, w=440, h=240),
                      constraints=Constraints(priority=90)),
            TextLayer(id="serif", role="body",
                      content="Mixed families, tracking and leading must shape identically "
                              "on both renderers.",
                      fontFamily="Playfair Display", fontWeight=400, fontSize=22,
                      lineHeight=1.45, color="#94A3B8",
                      frame=Frame(x=48, y=380, w=420, h=140),
                      constraints=Constraints(priority=40)),
            ImageLayer(id="pending", role="subject", frame=Frame(x=480, y=640, w=260, h=260),
                       placeholderColor="#1E293B",
                       constraints=Constraints(priority=60)),
        ],
    )


@pytest.fixture(scope="module")
def doc() -> DesignDoc:
    return fixture_doc()


def test_draw_list_is_deterministic(doc):
    a = to_draw_list(doc, scale=1.0).model_dump(by_alias=True, exclude_none=True)
    b = to_draw_list(doc, scale=1.0).model_dump(by_alias=True, exclude_none=True)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_draw_list_survives_the_json_wire_unchanged(doc):
    """This is the wire the browser receives; any loss here is drift by definition."""
    original = to_draw_list(doc, scale=1.0)
    wire = original.model_dump_json(by_alias=True, exclude_none=True)
    restored = DrawList.model_validate_json(wire)
    assert restored.model_dump(by_alias=True) == original.model_dump(by_alias=True)


def test_text_is_carried_as_resolved_glyphs_not_strings(doc):
    """INV-3's classic failure is the browser re-shaping text (Appendix A.5). The draw
    list must therefore carry glyph ids and positions, not just a string."""
    commands = to_draw_list(doc, scale=1.0).commands
    runs = [run for cmd in commands if cmd.op == "textRun" for run in cmd.runs]
    assert runs, "fixture has text layers but the draw list carries no runs"
    for run in runs:
        assert run.font_key, "a run must name the exact face it was shaped with"
        assert run.glyphs, "a run must carry positioned glyphs"
        for glyph in run.glyphs:
            assert glyph.gid >= 0
            assert np.isfinite(glyph.x) and np.isfinite(glyph.y)
    # Positions must be strictly advancing within a left-to-right run.
    ltr = [run for run in runs if run.direction == "ltr" and len(run.glyphs) > 2]
    for run in ltr:
        xs = [glyph.x for glyph in run.glyphs]
        assert xs == sorted(xs), "glyph advances are out of order"


def test_server_render_is_deterministic(doc):
    draw_list = to_draw_list(doc, scale=1.0)
    first = surface_to_numpy(render_surface(draw_list))
    second = surface_to_numpy(render_surface(draw_list))
    assert ssim(first, second) >= 0.9999
    assert np.array_equal(first, second), "identical input produced different pixels"


def test_scale_preserves_composition(doc):
    """A 2x render must be the same design, not a different layout."""
    small = surface_to_numpy(render_surface(to_draw_list(doc, scale=0.5)))
    large = surface_to_numpy(render_surface(to_draw_list(doc, scale=1.0)))
    assert large.shape[0] == small.shape[0] * 2
    assert large.shape[1] == small.shape[1] * 2

    # Box-average the large render down; nearest-neighbour sampling would throw away
    # antialiasing and fail on aliasing rather than on any real layout difference.
    h, w = small.shape[0], small.shape[1]
    reduced = (large[: h * 2, : w * 2]
               .reshape(h, 2, w, 2, large.shape[2])
               .mean(axis=(1, 3))
               .astype(large.dtype))
    assert ssim(reduced, small) >= 0.97


def test_ssim_detects_a_real_difference(doc):
    """Guards the gate itself: a metric that never fails is not a gate."""
    base = surface_to_numpy(render_surface(to_draw_list(doc, scale=0.5)))

    moved = doc.model_copy(deep=True)
    headline = next(layer for layer in moved.layers if layer.id == "headline")
    headline.frame.x += 60
    shifted = surface_to_numpy(render_surface(to_draw_list(moved, scale=0.5)))

    assert ssim(base, shifted) < SSIM_THRESHOLD, "SSIM failed to notice a 60px shift"


def test_every_layer_type_reaches_the_renderer(doc):
    ops = {cmd.op for cmd in to_draw_list(doc, scale=1.0).commands}
    assert {"clear", "saveTransform", "restore", "path", "textRun", "placeholder"} <= ops


def test_surface_pixels_are_rgba_not_bgra():
    """Skia rasterises BGRA on this platform.

    Harmonisation (§1.5) reads these pixels as RGB to extract the palette, measure
    contrast and match colour, so a channel swap here produces confidently wrong colour
    decisions rather than an obvious failure.
    """
    for hex_color, expected in (
        ("#FF0000", [255, 0, 0]), ("#00FF00", [0, 255, 0]), ("#0000FF", [0, 0, 255]),
        ("#0F172A", [15, 23, 42]), ("#F5B700", [245, 183, 0]),
    ):
        probe = DesignDoc(id="probe", canvas=Canvas(width=8, height=8, background=hex_color),
                          fonts=[], layers=[])
        pixels = surface_to_numpy(render_surface(to_draw_list(probe, scale=1.0)))
        assert pixels[0, 0, :3].tolist() == expected, f"{hex_color} decoded as channel-swapped"


def test_png_export_is_byte_stable(doc):
    draw_list = to_draw_list(doc, scale=0.5)
    assert render_png(draw_list) == render_png(draw_list)


def test_a_wide_gradient_actually_fades_across_its_own_shape():
    """The ramp must span the box along the gradient's direction, not along its longest
    edge. Sized by max(width, height), a 1080x272 scrim covers only the middle quarter of
    the ramp: every stop lands near the midpoint and the fade renders as a flat band with
    two hard edges — which is worse than no scrim at all."""
    import numpy as np
    from PIL import Image

    from app.renderer.skia_backend import render_png
    from app.schema.draw import DrawList, PathCmd

    band = PathCmd(
        d="M 0 200 L 800 200 L 800 400 L 0 400 Z",
        fill=None,
        gradient={"kind": "linear", "angle": 180, "stops": [
            {"offset": 0.0, "color": "#000000", "opacity": 0.0},
            {"offset": 0.5, "color": "#000000", "opacity": 1.0},
            {"offset": 1.0, "color": "#000000", "opacity": 0.0},
        ]},
    )
    page = PathCmd(d="M 0 0 L 800 0 L 800 600 L 0 600 Z", fill="#FFFFFF")
    draw_list = DrawList(width=800, height=600, commands=[page, band])
    pixels = np.asarray(Image.open(io.BytesIO(render_png(draw_list))).convert("L"),
                        dtype=float)

    column = pixels[:, 400]
    top_edge, middle, bottom_edge = column[205], column[300], column[395]

    # Dark in the middle, and fading back to the white page at both edges of the band.
    assert middle < 40, f"the gradient's peak should be near-opaque, got {middle}"
    assert top_edge > 180, f"the top of the band should be nearly clear, got {top_edge}"
    assert bottom_edge > 180, f"the bottom should be nearly clear, got {bottom_edge}"
