"""Layout engine tests — IMPLEMENTATION_PLAN §5.1.

The plan asks specifically for: text measurement against fixtures, autofit convergence
as a property test, and a collision solver that terminates and never leaves an overlap
between two priority >= 50 layers.
"""

import random

import pytest

from app.layout.measure import cache_stats, clear_cache, shape_block
from app.layout.solver import COLLISION_PRIORITY_FLOOR, SolveOpts, solve
from app.renderer.transform import world_bounds
from app.schema.doc import (
    AutoFit,
    Canvas,
    Constraints,
    DesignDoc,
    FontRef,
    Frame,
    ImageLayer,
    TextLayer,
)

WORDS = ("run", "lighter", "every", "stride", "engineered", "midsole", "energy",
         "cool", "miles", "season", "performance", "breathable")


def _doc(layers, *, w=1080, h=1920, margin=72) -> DesignDoc:
    return DesignDoc(
        id="d", canvas=Canvas(width=w, height=h, safeMargin=margin),
        fonts=[FontRef(family="Inter", weights=[400, 900])],
        palette=["#0F172A", "#FFFFFF"], layers=layers,
    )


def _text(id_, content, **kw):
    kw.setdefault("frame", Frame(x=72, y=200, w=780, h=430))
    kw.setdefault("fontFamily", "Inter")
    kw.setdefault("role", "headline")
    kw.setdefault("fontWeight", 900)
    kw.setdefault("fontSize", 148)
    kw.setdefault("lineHeight", 0.98)
    kw.setdefault("textTransform", "uppercase")
    return TextLayer(id=id_, content=content, **kw)


# -- measurement -----------------------------------------------------------------------


def test_shaping_is_deterministic_and_cached():
    clear_cache()
    kw = {"font_family": "Inter", "font_weight": 900, "font_size": 120, "max_width": 800}
    a = shape_block("Run Lighter", **kw)
    b = shape_block("Run Lighter", **kw)
    assert a is b, "identical input must hit the measurement cache (§6.5)"
    assert cache_stats()["hits"] == 1
    glyphs = a.lines[0].runs[0].glyphs
    assert [g.gid for g in glyphs] == [g.gid for g in shape_block("Run Lighter", **kw).lines[0].runs[0].glyphs]


def test_weight_changes_advance_width():
    """The instanced static faces must be genuinely different, not the same outlines."""
    light = shape_block("Hamburgefonstiv", font_family="Inter", font_weight=400, font_size=100)
    heavy = shape_block("Hamburgefonstiv", font_family="Inter", font_weight=900, font_size=100)
    assert heavy.width > light.width * 1.05


def test_uppercase_transform_is_not_baked_into_content():
    block = shape_block("run lighter", font_family="Inter", font_size=100,
                        text_transform="uppercase", max_width=1e9)
    assert block.lines[0].text == "RUN LIGHTER"


def test_wrapping_never_exceeds_max_width():
    """A line may only exceed the width if it is a single unbreakable token, and the
    block must then flag `overflowed_width` so autofit can react."""
    for width in (200, 340, 469, 500, 900):
        block = shape_block(" ".join(WORDS * 2), font_family="Inter",
                            font_weight=400, font_size=40, max_width=width)
        for line in block.lines:
            if line.advance > width + 0.5:
                assert " " not in line.text.strip(), \
                    f"line {line.text!r} overflows {width} but was breakable"
                assert block.overflowed_width


def test_explicit_newlines_are_hard_breaks():
    block = shape_block("Run\nLighter", font_family="Inter", font_size=100, max_width=1e9)
    assert [line.text for line in block.lines] == ["Run", "Lighter"]


# -- autofit ---------------------------------------------------------------------------


@pytest.mark.parametrize("n_words", [1, 2, 5, 12, 25, 40, 80])
def test_autofit_always_fits_or_reports_a_violation(n_words):
    """Property: after solve(), a text layer either fits its frame or carries a
    violation. It may never silently overflow."""
    content = " ".join(random.Random(n_words).choices(WORDS, k=n_words))
    layer = _text("head", content, autoFit=AutoFit(min=24, max=168, mode="shrink"))
    result = solve(_doc([layer]))
    solved = result.doc.layers[0]
    block = result.shaped["head"]

    fits = block.height <= solved.frame.h + 1 and block.width <= solved.frame.w + 1
    overflow = [v for v in result.violations if v.code == "text-overflow"]
    assert fits or overflow, f"{n_words} words: overflowed with no violation reported"
    assert 24 <= solved.font_size <= 168


def test_autofit_shrinks_long_copy_and_leaves_short_copy_large():
    short = solve(_doc([_text("head", "Run lighter",
                              autoFit=AutoFit(min=48, max=168, mode="shrink"))]))
    long = solve(_doc([_text("head", " ".join(WORDS * 4),
                             autoFit=AutoFit(min=48, max=168, mode="shrink"))]))
    assert short.doc.layers[0].font_size > long.doc.layers[0].font_size * 1.5


def test_auto_height_grows_the_frame_instead_of_shrinking_type():
    layer = _text("head", " ".join(WORDS), autoHeight=True,
                  frame=Frame(x=72, y=200, w=780, h=100))
    result = solve(_doc([layer]))
    assert result.doc.layers[0].frame.h > 100
    assert result.doc.layers[0].font_size == 148  # unchanged


# -- collisions ------------------------------------------------------------------------


def test_collision_solver_leaves_no_overlap_between_important_layers():
    """§5.3 target: collision rate 0% for priority >= 50 pairs."""
    layers = [
        _text("head", "Run lighter than ever",
              autoFit=AutoFit(min=48, max=168, mode="shrink"),
              constraints=Constraints(priority=90)),
        ImageLayer(id="subject", role="subject", frame=Frame(x=120, y=420, w=840, h=660),
                   constraints=Constraints(priority=95, lockAspect=True)),
    ]
    result = solve(_doc(layers))
    a, b = result.doc.layers[0], result.doc.layers[1]
    assert a.constraints.priority >= COLLISION_PRIORITY_FLOOR
    overlap = world_bounds(a).intersection(world_bounds(b))
    unresolved = [v for v in result.violations if v.code == "unresolved-collision"]
    assert overlap.area <= 1.0 or unresolved


@pytest.mark.parametrize("seed", range(8))
def test_collision_solver_terminates_on_random_scenes(seed):
    rng = random.Random(seed)
    layers = [
        ImageLayer(id=f"l{i}", role="object",
                   frame=Frame(x=rng.uniform(72, 700), y=rng.uniform(72, 1500),
                               w=rng.uniform(120, 420), h=rng.uniform(120, 420)),
                   constraints=Constraints(priority=rng.choice([20, 50, 70, 90]),
                                           optional=rng.random() < 0.3))
        for i in range(7)
    ]
    result = solve(_doc(layers))  # must not hang or raise
    visible = [layer for layer in result.doc.layers if layer.visible]
    important = [layer for layer in visible
                 if layer.constraints.priority >= COLLISION_PRIORITY_FLOOR]
    unresolved = {v.layer_id for v in result.violations if v.code == "unresolved-collision"}
    for i, a in enumerate(important):
        for b in important[i + 1:]:
            if world_bounds(a).intersection(world_bounds(b)).area > 1.0:
                assert a.id in unresolved or b.id in unresolved, \
                    f"{a.id}/{b.id} overlap with no violation reported"


def test_optional_layers_are_dropped_before_important_ones_are_displaced():
    layers = [
        ImageLayer(id="hero", role="subject", frame=Frame(x=72, y=72, w=900, h=1700),
                   constraints=Constraints(priority=95)),
        ImageLayer(id="sticker", role="decoration", frame=Frame(x=200, y=300, w=300, h=300),
                   constraints=Constraints(priority=10, optional=True)),
    ]
    result = solve(_doc(layers))
    hero = next(layer for layer in result.doc.layers if layer.id == "hero")
    assert hero.frame.x == 72 and hero.frame.y == 72, "high-priority layer must not move"


# -- margins and snapping ---------------------------------------------------------------


def test_safe_margin_pulls_stray_layers_back_inside():
    layer = ImageLayer(id="badge", role="badge", frame=Frame(x=-40, y=1880, w=200, h=200),
                       constraints=Constraints(priority=60))
    result = solve(_doc([layer]))
    bounds = world_bounds(result.doc.layers[0])
    assert bounds.x >= 72 - 8 and bounds.bottom <= 1920 - 72 + 8


def test_background_is_exempt_from_margins_and_snapping():
    bg = ImageLayer(id="bg", role="background", frame=Frame(x=0, y=0, w=1080, h=1920),
                    constraints=Constraints(horizontal="stretch", vertical="stretch",
                                            priority=100))
    result = solve(_doc([bg]))
    assert result.doc.layers[0].frame.model_dump() == bg.frame.model_dump()


def test_grid_snap_rounds_to_the_baseline():
    layer = ImageLayer(id="a", role="object", frame=Frame(x=101, y=203, w=305, h=407),
                       constraints=Constraints(priority=60))
    result = solve(_doc([layer]), SolveOpts(grid_baseline=8))
    frame = result.doc.layers[0].frame
    for value in (frame.x, frame.y, frame.w, frame.h):
        assert value % 8 == 0, f"{value} not snapped to an 8px baseline"


def test_measure_only_mode_moves_nothing():
    """Part Two and document-open both need shaping without reflow."""
    layer = ImageLayer(id="a", role="object", frame=Frame(x=-40, y=101, w=305, h=407),
                       constraints=Constraints(priority=60))
    result = solve(_doc([layer]), SolveOpts(measure_only=True))
    assert result.doc.layers[0].frame.model_dump() == layer.frame.model_dump()


def test_a_cta_label_is_never_separated_from_its_pill():
    """A label drawn on its own shape backing is one visual object.

    Without linking, the collision solver sees the overlap and helpfully pushes them
    apart, producing an empty lozenge with orphaned text beneath it.
    """
    from app.schema.doc import ShapeLayer

    pill = ShapeLayer(id="cta_bg", role="cta", shape="rect", radius=48,
                      fill="#F5B700", frame=Frame(x=72, y=1660, w=420, h=96),
                      constraints=Constraints(priority=30, optional=True))
    label = _text("cta", "Shop now", frame=Frame(x=72, y=1660, w=420, h=96),
                  role="cta", fontSize=40, verticalAlign="middle", align="center",
                  autoFit=AutoFit(min=20, max=44, mode="shrink"),
                  constraints=Constraints(priority=40, optional=True))
    blocker = ImageLayer(id="subject", role="subject",
                         frame=Frame(x=72, y=1400, w=900, h=320),
                         constraints=Constraints(priority=95))

    result = solve(_doc([blocker, pill, label]))
    solved_pill = next(layer for layer in result.doc.layers if layer.id == "cta_bg")
    solved_label = next(layer for layer in result.doc.layers if layer.id == "cta")

    assert solved_pill.visible == solved_label.visible, "pill and label must share a fate"
    if solved_label.visible:
        overlap = world_bounds(solved_pill).intersection(world_bounds(solved_label))
        smaller = min(world_bounds(solved_pill).area, world_bounds(solved_label).area)
        assert overlap.area / smaller > 0.9, (
            f"label drifted off its pill: pill={solved_pill.frame} label={solved_label.frame}"
        )


def test_linked_pair_moves_together_when_displaced():
    from app.schema.doc import ShapeLayer

    pill = ShapeLayer(id="cta_bg", role="cta", shape="rect", fill="#F5B700",
                      frame=Frame(x=200, y=300, w=400, h=100),
                      constraints=Constraints(priority=30))
    label = _text("cta", "Buy", frame=Frame(x=200, y=300, w=400, h=100), role="cta",
                  fontSize=36, align="center", verticalAlign="middle",
                  constraints=Constraints(priority=30))
    blocker = ImageLayer(id="hero", role="subject", frame=Frame(x=150, y=250, w=500, h=200),
                         constraints=Constraints(priority=95))

    result = solve(_doc([blocker, pill, label]))
    solved_pill = next(layer for layer in result.doc.layers if layer.id == "cta_bg")
    solved_label = next(layer for layer in result.doc.layers if layer.id == "cta")
    if solved_label.visible and solved_pill.visible:
        # They must receive the identical translation. A centred label takes no optical
        # shift, so the frames stay exactly aligned.
        assert abs(solved_pill.frame.x - solved_label.frame.x) < 0.5
        assert abs(solved_pill.frame.y - solved_label.frame.y) < 0.5
        assert (solved_pill.frame.y, solved_pill.frame.x) != (300, 200), "nothing moved"


def test_auto_height_text_still_has_to_fit_its_column():
    """Releasing the height does not release the width. A headline too wide for its
    column overflows however tall its frame is allowed to grow, so auto-height layers
    autofit downward on width."""
    from app.layout.solver import SolveOpts, solve
    from app.schema.doc import AutoFit, Canvas, DesignDoc, Frame, TextLayer

    layer = TextLayer(
        id="l_headline", name="Headline", role="headline",
        frame=Frame(x=80, y=200, w=400, h=200),
        content="Sustainability report for the financial year",
        fontFamily="Inter", fontSize=120, fontWeight=700, color="#111111",
        autoHeight=True, autoFit=AutoFit(min=24, max=140),
    )
    doc = DesignDoc(id="d1", title="t", canvas=Canvas(width=1080, height=1080),
                    layers=[layer], palette=["#FFFFFF", "#888888", "#111111"],
                    createdAt="2026-01-01T00:00:00Z", updatedAt="2026-01-01T00:00:00Z")

    result = solve(doc, SolveOpts())
    fitted = result.doc.layers[0]

    assert fitted.font_size < 120, "the headline should have shrunk to fit its column"
    assert fitted.font_size >= 24
    assert not [v for v in result.violations if v.code == "text-overflow"]


def test_shaping_empty_text_does_not_kill_the_solver():
    """uharfbuzz returns None rather than an empty sequence for a buffer with nothing in
    it, so the whole layout pass died on text with no glyphs. A run of spaces reaches
    this every time: it tokenizes to one whitespace token whose stripped form is "",
    which is how a contact strip with a spaced separator took the solver down."""
    from app.layout.fonts import get_registry
    from app.layout.measure import shape_line

    face = get_registry().face("Inter", 400, "normal")

    assert shape_line("", face, 32.0, 0.0, "en").advance == 0.0
    # Spaces are not ink but they do advance the pen.
    assert shape_line("   ", face, 32.0, 0.0, "en").advance > 0.0


def test_a_dense_document_solves_without_violations():
    """The information-dense skeletons carry two to three times the text layers of the
    rest of the corpus, which is exactly the condition the margin and collision passes
    are most likely to fail to satisfy."""
    from app.layout.solver import solve
    from app.pipelines.part_one.brief import _sanitise, heuristic_brief
    from app.pipelines.part_one.compose import expand, mechanical_compose
    from app.templates_corpus.skeletons import by_id

    prompt = ('Sale post for wireless headphones, flat 50% off, only Rs 2499, '
              'call 98765 43210, visit sound.co, headline "Sound Unleashed" cta "Shop now"')
    brief = _sanitise(heuristic_brief(prompt), prompt)
    brief.copy_text.features = ["30hr battery life", "Active noise cancelling",
                                "2 year warranty"]

    for template_id in ("tpl_post_offer_dense_01", "tpl_post_services_sq_01",
                        "tpl_flyer_business_01"):
        skeleton = by_id(template_id)
        doc = expand(skeleton, mechanical_compose(brief, skeleton), brief, doc_id="d1")
        result = solve(doc)

        assert not result.violations, (template_id, result.violations)
        for layer in doc.layers:
            assert layer.frame.x >= -1 and layer.frame.y >= -1, (template_id, layer.id)
            assert layer.frame.x + layer.frame.w <= doc.canvas.width + 1
            assert layer.frame.y + layer.frame.h <= doc.canvas.height + 1
