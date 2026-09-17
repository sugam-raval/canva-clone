"""Regressions for the output-quality passes: colour harmony, font pairing, subject fit.

Each test here corresponds to a defect that shipped in real output, so the assertions
are about what a viewer sees, not about internal structure.
"""

from app.pipelines.part_one.brief import heuristic_brief
from app.pipelines.part_one.compose import _fonts_for, font_pairings
from app.pipelines.part_one.fit import fit_subjects
from app.schema.doc import Canvas, Constraints, DesignDoc, Frame, ImageLayer, Size
from app.util.color import (
    chroma_of,
    contrast_ratio,
    harmonious_on,
    harmony_score,
    hue_distance,
    hue_of,
    relative_luminance,
    saturation,
)

# -- colour harmony --------------------------------------------------------------------

def test_saturated_green_never_lands_on_a_warm_ground():
    """The shipped defect: a festival palette's green won on contrast ratio alone and
    was set as the headline colour over orange."""
    palette = ["#C2410C", "#FDBA74", "#16A34A", "#7F1D1D", "#FDE68A"]
    for background in ("#C2410C", "#8A2B08", "#B91C1C", "#EA580C"):
        for minimum in (3.0, 4.5):
            chosen = harmonious_on(background, palette, minimum)
            if chroma_of(chosen) >= 0.16:
                distance = hue_distance(hue_of(chosen), hue_of(background))
                assert distance <= 60 or distance >= 140, (
                    f"{chosen} on {background} sits in the discordant band")


def test_harmonious_choice_still_clears_the_contrast_threshold():
    from app.util.color import contrast_ratio

    palette = ["#0E1A33", "#F5E6C8", "#C9A227", "#7A1F2B"]
    for background in palette:
        for minimum in (3.0, 4.5, 7.0):
            chosen = harmonious_on(background, palette, minimum)
            assert contrast_ratio(background, chosen) >= minimum


def test_classic_pairings_are_not_treated_as_clashes():
    """Gold on maroon is 54 degrees apart; an over-narrow analogous window rejects it."""
    assert harmony_score("#E8C87A", "#4A0E1A") > 0.7
    assert harmony_score("#F3E3C3", "#0B1B3A") > 0.7
    # ...while a quarter-turn separation genuinely is a clash.
    assert harmony_score("#16A34A", "#C2410C") < 0.35


# -- typography ------------------------------------------------------------------------

def test_festival_prompts_route_to_ceremonial_type():
    for prompt in ("Diwali poster for a motorcycle showroom",
                   "Happy Ganesh Chaturthi greeting",
                   "Eid Mubarak social post"):
        brief = heuristic_brief(prompt)
        assert brief.typography.vibe == "serif-editorial", prompt
        assert _fonts_for(brief)[0] == "Playfair Display", prompt


def test_every_pairing_uses_a_real_supporting_face_for_body_copy():
    """A display or script face at caption size is unreadable, so no pairing may use one
    as its supporting face."""
    display_only = {"Archivo Black", "Bebas Neue", "Oswald", "Playfair Display",
                    "Anton", "Abril Fatface", "Alfa Slab One",
                    "Great Vibes", "Dancing Script", "Pacifico"}
    for vibe, pairs in font_pairings().items():
        for display, text, _script in pairs:
            assert text not in display_only, f"{vibe}: {display} + {text}"


def test_script_accents_resolve_to_a_real_face_or_degrade():
    from app.layout.fonts import get_registry
    from app.schema.composer import ComposerFont

    available = set(get_registry().families)
    for vibe, pairs in font_pairings().items():
        for display, text, script in pairs:
            assert script is None or script in available, f"{vibe}: {script}"
            font = ComposerFont(family=display, textFamily=text, scriptFamily=script)
            # Every face request must resolve to something that exists, script or not.
            for face in ("display", "text", "script", None):
                assert font.for_face(face) in available


# -- subject fit -----------------------------------------------------------------------

def _doc_with_subject(frame: Frame, natural: Size, **kwargs) -> DesignDoc:
    layer = ImageLayer(
        id="l_subject", name="Subject", role="subject", frame=frame, fit="contain",
        assetId="a1", hasAlpha=True, naturalSize=natural,
        constraints=Constraints(**({"horizontal": "center", "vertical": "middle"}
                                   | kwargs)),
    )
    return DesignDoc(id="d1", title="t", canvas=Canvas(width=1080, height=1920),
                     layers=[layer], palette=["#000000", "#FFFFFF", "#FF0000"],
                     createdAt="2026-01-01T00:00:00Z", updatedAt="2026-01-01T00:00:00Z")


def test_portrait_cutout_in_a_landscape_frame_stops_being_letterboxed():
    """The shipped defect: an upright subject in a wide frame fitted to height and
    rendered at under half the frame's width."""
    doc = _doc_with_subject(Frame(x=86, y=845, w=907, h=691), Size(w=1000, h=1500))
    before = doc.layers[0].frame
    ink_width_before = before.h * (1000 / 1500)

    fit_subjects(doc)
    after = doc.layers[0].frame

    assert abs(after.w / after.h - 1000 / 1500) < 0.01, "frame should match the content"
    assert after.w > ink_width_before * 1.15, "subject should render appreciably larger"
    assert doc.layers[0].meta.notes.get("fittedToContent") is True


def test_fit_preserves_the_allocated_area_and_the_centre():
    doc = _doc_with_subject(Frame(x=86, y=845, w=907, h=691), Size(w=1000, h=1500))
    before = doc.layers[0].frame
    centre = (before.x + before.w / 2, before.y + before.h / 2)

    fit_subjects(doc)
    after = doc.layers[0].frame

    assert abs(after.w * after.h - before.w * before.h) / (before.w * before.h) < 0.02
    assert abs((after.x + after.w / 2) - centre[0]) < 1.0


def test_fit_holds_a_pinned_edge():
    doc = _doc_with_subject(Frame(x=86, y=1100, w=907, h=691), Size(w=1000, h=1500),
                            horizontal="left", vertical="bottom")
    before = doc.layers[0].frame
    fit_subjects(doc)
    after = doc.layers[0].frame
    assert after.x == before.x
    assert abs((after.y + after.h) - (before.y + before.h)) < 1.0


def test_fit_leaves_matching_and_unknown_frames_alone():
    # Aspect already matches: nothing to do.
    doc = _doc_with_subject(Frame(x=0, y=0, w=600, h=900), Size(w=1000, h=1500))
    fit_subjects(doc)
    assert doc.layers[0].frame.w == 600

    # No asset yet, so no natural size to fit to.
    doc = _doc_with_subject(Frame(x=0, y=0, w=907, h=691), Size(w=0, h=0))
    fit_subjects(doc)
    assert doc.layers[0].frame.w == 907


# -- vertical rhythm -------------------------------------------------------------------

def _text(layer_id: str, role: str, y: float, h: float, size: float, content: str):
    from app.schema.doc import TextLayer

    return TextLayer(id=layer_id, name=layer_id, role=role,
                     frame=Frame(x=72, y=y, w=778, h=h), content=content,
                     fontFamily="Playfair Display", fontWeight=700, fontSize=size,
                     lineHeight=1.0, color="#FFFFFF")


def _stack_doc(*layers) -> DesignDoc:
    return DesignDoc(id="d", title="t", canvas=Canvas(width=1080, height=1920),
                     layers=list(layers), palette=["#000000", "#FFFFFF", "#FF0000"],
                     createdAt="2026-01-01T00:00:00Z", updatedAt="2026-01-01T00:00:00Z")


def _solve(doc):
    from app.layout.solver import SolveOpts, solve

    return solve(doc, SolveOpts(enable_snap=False, enable_optical=False))


def test_short_copy_does_not_leave_a_hole_below_it():
    """The shipped defect: a two-line headline in a box sized for four left a dead band
    between it and the subhead, because the subhead kept the skeleton's absolute y."""
    doc = _stack_doc(_text("h", "headline", 192, 422, 148, "Celebrate Diwali"),
                     _text("s", "subhead", 643, 134, 46, "Ride into the festival"))
    authored_gap = 643 - (192 + 422)

    result = _solve(doc)
    head = next(x for x in result.doc.layers if x.id == "h")
    sub = next(x for x in result.doc.layers if x.id == "s")

    rendered_gap = sub.frame.y - (head.frame.y + head.frame.h)
    assert abs(rendered_gap - authored_gap) < 2, "authored rhythm should survive packing"
    assert head.frame.y == 192, "the top of the stack must not move"


def test_packing_never_pulls_up_a_deliberately_separated_layer():
    """A CTA parked near the bottom edge is not part of the headline's stack."""
    doc = _stack_doc(_text("h", "headline", 192, 422, 148, "Celebrate Diwali"),
                     _text("s", "subhead", 643, 134, 46, "Ride into the festival"),
                     _text("cta", "cta", 1660, 108, 44, "Book a test ride"))
    result = _solve(doc)
    cta = next(x for x in result.doc.layers if x.id == "cta")
    assert cta.frame.y == 1660


def test_packing_leaves_an_already_tight_stack_alone():
    """Only slack is reclaimed; gaps are never opened."""
    doc = _stack_doc(_text("h", "headline", 192, 160, 148, "Celebrate Diwali"),
                     _text("s", "subhead", 380, 46, 46, "Ride into the festival"))
    result = _solve(doc)
    sub = next(x for x in result.doc.layers if x.id == "s")
    assert sub.frame.y <= 380


# -- ornament --------------------------------------------------------------------------

def test_every_motif_produces_parseable_geometry():
    from app.renderer.svgpath import parse_svg_path
    from app.templates_corpus.ornament import MOTIFS, render_motif

    for motif in sorted(MOTIFS):
        for size in ((800, 300), (300, 800), (600, 600), (1080, 120)):
            data = render_motif(motif, *size, seed=7, density=3)
            assert data, f"{motif} at {size} produced nothing"
            assert not parse_svg_path(data).isEmpty(), f"{motif} at {size} is empty"


def test_motifs_stay_inside_their_own_box():
    """Shape layers are not clipped to their frame, so a motif that overruns its box
    paints over the rest of the design."""
    from app.renderer.svgpath import parse_svg_path
    from app.templates_corpus.ornament import MOTIFS, render_motif

    for motif in sorted(MOTIFS):
        for w, h in ((800, 300), (300, 800), (600, 600)):
            bounds = parse_svg_path(render_motif(motif, w, h, seed=7, density=3)).getBounds()
            overflow = max(-bounds.left(), -bounds.top(),
                           bounds.right() - w, bounds.bottom() - h)
            # A garland hung edge to edge may bleed slightly; nothing may bleed far.
            assert overflow <= 0.06 * min(w, h), f"{motif} at {w}x{h} overflows by {overflow}"


def test_motifs_are_reproducible_from_their_seed():
    """INV-2: regenerating a document must reproduce it, confetti included."""
    from app.templates_corpus.ornament import render_motif

    first = render_motif("confetti", 600, 600, seed=42, density=3)
    assert first == render_motif("confetti", 600, 600, seed=42, density=3)
    assert first != render_motif("confetti", 600, 600, seed=43, density=3)


def test_the_corpus_validates():
    from app.templates_corpus.skeletons import ALL_SKELETONS
    from app.templates_corpus.validate import validate_skeleton

    issues = [i for sk in ALL_SKELETONS for i in validate_skeleton(sk)]
    assert not issues, [f"{i.template_id}/{i.slot_id}: {i.message}" for i in issues]


def test_ornamented_skeletons_carry_real_decoration():
    from app.templates_corpus.skeletons import by_id

    for template_id in ("tpl_story_festive_01", "tpl_post_festive_01",
                        "tpl_poster_ornate_01", "tpl_post_burst_01", "tpl_post_dotted_01"):
        skeleton = by_id(template_id)
        assert skeleton is not None, template_id
        motifs = [s.shape.motif for s in skeleton.slots if s.shape and s.shape.motif]
        assert len(motifs) >= 2, f"{template_id} declares only {motifs}"


# -- props, depth and bleed ------------------------------------------------------------

def test_flat_graphic_skeletons_carry_props_beside_the_subject():
    """One subject per design is what made output read as a photograph with type on it."""
    from app.templates_corpus.skeletons import by_id

    for template_id in ("tpl_post_fashion_01", "tpl_post_drop_01"):
        skeleton = by_id(template_id)
        props = [s for s in skeleton.slots if s.role == "object"]
        assert props, f"{template_id} has no props"
        for slot in props:
            assert not slot.required, f"{template_id}/{slot.slot_id} must be optional"
            assert slot.image.transparent, f"{template_id}/{slot.slot_id} must be a cutout"
            subject = next(s for s in skeleton.slots if s.role == "subject")
            assert slot.constraints.priority < subject.constraints.priority, (
                "props must yield to the subject when the budget runs out")


def test_display_type_can_sit_behind_the_subject():
    from app.templates_corpus.skeletons import by_id

    skeleton = by_id("tpl_post_drop_01")
    headline = next(s for s in skeleton.slots if s.role == "headline")
    subject = next(s for s in skeleton.slots if s.role == "subject")
    assert headline.z_index < subject.z_index, "the word should be behind the product"
    assert headline.constraints.allow_overlap and subject.constraints.allow_overlap


def test_declared_overlap_never_excuses_two_text_layers():
    """`allowOverlap` means depth, not permission to stack copy on copy."""
    from app.layout.solver import _overlap_declared
    from app.schema.doc import Constraints, Frame, ImageLayer, TextLayer

    def txt(layer_id):
        return TextLayer(id=layer_id, name=layer_id, role="headline",
                         frame=Frame(x=0, y=0, w=100, h=50), content="x",
                         constraints=Constraints(allowOverlap=True))

    image = ImageLayer(id="i", name="i", role="subject",
                       frame=Frame(x=0, y=0, w=100, h=50),
                       constraints=Constraints(allowOverlap=True))
    assert _overlap_declared(txt("a"), image) is True
    assert _overlap_declared(txt("a"), txt("b")) is False


def test_authored_bleed_survives_expansion():
    """A slot authored off-canvas is asking to bleed. Clamping it back on does not just
    lose the effect, it relocates the slot."""
    from app.pipelines.part_one.brief import heuristic_brief
    from app.pipelines.part_one.compose import expand, mechanical_compose
    from app.templates_corpus.skeletons import by_id

    skeleton = by_id("tpl_post_fashion_01")
    brief = heuristic_brief("summer fashion sale")
    brief.canvas.width, brief.canvas.height = 1080, 1350
    brief.copy_text.headline = "Fashion Sale"
    output = mechanical_compose(brief, skeleton)
    for entry in output.slots:
        entry.include = True
    doc = expand(skeleton, output, brief, doc_id="d")

    blob = next(x for x in doc.layers if x.id == "l_blob_b")
    assert blob.frame.x < 0, "the blob should still start off the left edge"
    headline = next(x for x in doc.layers if x.id == "l_headline")
    assert blob.frame.x + blob.frame.w <= headline.frame.x + 1, (
        "a relocated blob would land under the copy it was placed to avoid")


def test_outlined_text_is_judged_by_its_outline():
    """Judging the fill would recolour a keylined word and discard the treatment."""
    from app.pipelines.part_one.harmonize import _safe_everywhere

    # Navy fill on a navy ground is unreadable; the gold keyline is what carries it.
    assert not _safe_everywhere("#0F172A", "#0F172A", "#1B2438", 3.0)
    assert _safe_everywhere("#F5B700", "#0F172A", "#1B2438", 3.0)


# -- vector motifs are editable artefacts, not baked paths -----------------------------

def _showcase_doc():
    from app.pipelines.part_one.brief import heuristic_brief
    from app.pipelines.part_one.compose import expand, mechanical_compose
    from app.templates_corpus.skeletons import by_id

    skeleton = by_id("tpl_post_showcase_01")
    brief = heuristic_brief("our new skincare range")
    brief.canvas.width, brief.canvas.height = 1080, 1350
    brief.copy_text.headline = "The Range"
    output = mechanical_compose(brief, skeleton)
    for entry in output.slots:
        entry.include = True
    return expand(skeleton, output, brief, doc_id="d_showcase")


def test_ornament_records_how_it_was_built():
    """Without this the document holds a path it can recolour but never rebuild."""
    doc = _showcase_doc()
    sweep = next(x for x in doc.layers if x.id == "l_sweep")
    assert sweep.meta.ornament is not None
    assert sweep.meta.ornament.motif == "arc-band"
    assert sweep.path_data


def test_reshape_rerolls_swaps_and_moves_colour_across():
    from app.pipelines.part_one.orchestrator import reshape_layer

    doc = _showcase_doc()
    before = next(x for x in doc.layers if x.id == "l_sweep").path_data

    assert reshape_layer(doc, "l_sweep")["pathData"] != before, "re-roll changed nothing"

    reshape_layer(doc, "l_sweep", motif="wave", density=5)
    layer = next(x for x in doc.layers if x.id == "l_sweep")
    assert layer.meta.ornament.motif == "wave"
    assert layer.meta.ornament.density == 5
    assert layer.fill and layer.stroke is None, "a closed motif is filled"

    # Switching to an open contour has to carry the colour onto the stroke, or the
    # layer silently disappears.
    colour = layer.fill
    reshape_layer(doc, "l_sweep", motif="border")
    layer = next(x for x in doc.layers if x.id == "l_sweep")
    assert layer.fill is None and layer.stroke is not None
    assert layer.stroke.color == colour


def test_reshape_refuses_layers_that_are_not_motifs():
    import pytest

    from app.pipelines.part_one.orchestrator import reshape_layer

    doc = _showcase_doc()
    with pytest.raises(ValueError):
        reshape_layer(doc, "l_headline")
    with pytest.raises(ValueError):
        reshape_layer(doc, "l_sweep", motif="not-a-motif")


def test_showcase_stacks_subjects_at_distinct_depths():
    """The point of the layout is that the three cutouts interleave."""
    from app.templates_corpus.skeletons import by_id

    skeleton = by_id("tpl_post_showcase_01")
    subjects = [s for s in skeleton.slots if s.role == "subject"]
    assert len(subjects) == 3
    assert len({s.z_index for s in subjects}) == 3, "subjects must not share a depth"

    hero = next(s for s in subjects if s.required)
    companions = [s for s in subjects if not s.required]
    assert len(companions) == 2
    for companion in companions:
        assert companion.constraints.priority < hero.constraints.priority
        assert companion.constraints.optional, "a tight budget must drop these first"


# -- motif geometry --------------------------------------------------------------------

def test_every_motif_stays_inside_its_own_box():
    """Shape layers are not clipped to their frames, so ornament that escapes its box
    lands on whatever it happens to sit above. Rasterised rather than parsed, because
    arcs encode radii alongside coordinates and a naive reading of the path misjudges
    exactly the circle-based motifs most likely to overhang."""
    import numpy as np
    import skia

    from app.renderer.svgpath import parse_svg_path
    from app.templates_corpus.ornament import MOTIFS, is_stroked, render_motif

    pad = 48
    sizes = [(400, 200), (200, 400), (800, 80), (120, 120), (1080, 300)]
    offenders = []
    for motif in sorted(MOTIFS):
        for width, height in sizes:
            for density in (1, 3, 5):
                for seed in range(6):
                    data = render_motif(motif, width, height, seed=seed, density=density)
                    if not data:
                        continue
                    stroke_w = max(1.0, height * 0.02)
                    surface = skia.Surface(width + 2 * pad, height + 2 * pad)
                    canvas = surface.getCanvas()
                    canvas.clear(skia.ColorTRANSPARENT)
                    canvas.translate(pad, pad)
                    paint = skia.Paint(AntiAlias=True, Color=skia.ColorWHITE)
                    if is_stroked(motif):
                        paint.setStyle(skia.Paint.kStroke_Style)
                        paint.setStrokeWidth(stroke_w)
                    canvas.drawPath(parse_svg_path(data), paint)
                    alpha = np.array(surface.makeImageSnapshot().convert(
                        alphaType=skia.kUnpremul_AlphaType))[:, :, 3].copy()
                    # A stroke is centred on its contour, so half of it may sit outside a
                    # path that runs along the edge; antialiasing adds a pixel.
                    tol = int(stroke_w / 2 + 2) if is_stroked(motif) else 2
                    alpha[pad - tol:pad + height + tol, pad - tol:pad + width + tol] = 0
                    escaped = int((alpha > 8).sum())
                    # A scatter motif may let a corner drift past the edge; a motif
                    # placing whole elements outside is a bug.
                    if escaped > (width * height) * 0.001:
                        offenders.append(
                            f"{motif} at {width}x{height} d{density} s{seed}: {escaped}px")
    assert not offenders, "ornament outside its box: " + "; ".join(offenders[:6])


def test_structural_motifs_are_reported_as_not_rerollable():
    """The editor greys its re-roll control for these, so the set has to be accurate."""
    from app.templates_corpus.ornament import MOTIFS, STRUCTURAL_MOTIFS, render_motif

    for motif in sorted(MOTIFS):
        shapes = {render_motif(motif, 400, 200, seed=seed, density=3)
                  for seed in range(24)}
        if motif in STRUCTURAL_MOTIFS:
            assert len(shapes) == 1, f"{motif} is listed structural but varies"
        else:
            assert len(shapes) > 1, f"{motif} never varies, so re-roll is a dead button"


# --------------------------------------------------------------------------------------
# Palette vocabulary and ordering
# --------------------------------------------------------------------------------------


def test_colour_words_resolve_to_designed_colours_not_css_keywords():
    from app.util.palette import resolve_color_word

    # The CSS keyword table answers #FFD700, a saturated primary yellow. A design that
    # takes that answer looks like a highlighter pen.
    gold = resolve_color_word("gold")
    assert gold != "#FFD700"
    assert saturation(gold) < 0.95
    assert resolve_color_word("deep blue") != "#00008B"
    assert resolve_color_word("#fff") == "#FFFFFF"
    assert resolve_color_word("not a colour at all") is None


def test_qualifiers_modify_the_base_hue_rather_than_replacing_it():
    from app.util.palette import resolve_color_word

    base = resolve_color_word("teal")
    for qualifier in ("deep teal", "pale teal", "muted teal"):
        variant = resolve_color_word(qualifier)
        assert variant != base
        assert hue_distance(hue_of(variant), hue_of(base)) < 25.0

    assert relative_luminance(resolve_color_word("deep teal")) < relative_luminance(base)
    assert relative_luminance(resolve_color_word("pale teal")) > relative_luminance(base)


def test_a_metallic_is_never_the_ground():
    """'gold and deep blue' means gold on blue, not a gold canvas."""
    from app.util.palette import order_palette, resolve_palette_words

    ordered = order_palette(resolve_palette_words(["gold", "deep blue"]),
                            moods=["elegant", "festive"])
    assert relative_luminance(ordered[0]) < 0.2, "the ground should be the deep blue"
    assert ordered[-1] == resolve_palette_words(["gold"])[0], "gold is the accent"


def test_palette_completion_keeps_the_ground_and_the_accent_at_the_ends():
    from app.util.palette import complete_palette

    completed = complete_palette(["#14264F", "#C9A227"])
    assert len(completed) >= 3
    assert completed[0] == "#14264F" and completed[-1] == "#C9A227"
    # The colour added has to be usable for body copy on that ground.
    assert contrast_ratio(completed[1], completed[0]) >= 4.5


def test_near_duplicate_palette_entries_are_dropped():
    """Five hexes are only worth having if they are five colours."""
    from app.util.palette import dedupe_palette

    deduped = dedupe_palette(["#17212F", "#1A2635", "#1A232C", "#BE9824", "#C9A227"])
    assert deduped == ["#17212F", "#C9A227"]
    # A genuinely varied palette survives untouched.
    varied = ["#0E1A33", "#F5E6C8", "#C9A227", "#7A1F2B"]
    assert dedupe_palette(varied) == varied


# --------------------------------------------------------------------------------------
# Subject inference — the omission that collapses the whole design
# --------------------------------------------------------------------------------------


def test_a_business_prompt_still_gets_a_subject():
    """A null subject hard-filters retrieval down to the type-only corner of the corpus,
    so it has to be a decision rather than an omission."""
    from app.pipelines.part_one.brief import _sanitise, heuristic_brief

    prompt = "Diwali sale post for a jewellery brand, 40% off"
    brief = _sanitise(heuristic_brief(prompt), prompt)
    assert brief.subject_description, "a jewellery sale is about jewellery"


def test_an_explicit_text_only_request_is_honoured():
    from app.pipelines.part_one.brief import _sanitise, heuristic_brief

    for prompt in ("A text-only quote card about courage",
                   "Minimal typographic poster, no photo, just text"):
        brief = _sanitise(heuristic_brief(prompt), prompt)
        assert brief.subject_description is None, prompt


def test_colour_words_in_a_brief_become_an_ordered_hex_palette():
    from app.pipelines.part_one.brief import _sanitise, heuristic_brief
    from app.schema.brief import ColorDirection

    prompt = "Elegant Diwali post in gold and deep blue"
    brief = heuristic_brief(prompt)
    brief.color_direction = ColorDirection(mode="from-prompt",
                                           palette=["gold", "deep blue"])
    brief = _sanitise(brief, prompt)

    palette = brief.color_direction.palette
    assert len(palette) >= 3
    assert all(c.startswith("#") for c in palette)
    assert relative_luminance(palette[0]) < 0.2, "deep blue is the ground"


def test_quoted_phrase_extraction_does_not_break_on_a_contraction():
    """A shared quote/apostrophe character class closes a curly-quoted phrase at the
    first apostrophe it contains: "WE'RE HIRING!" become "WE". Opening and closing marks
    have to be paired by style (straight-with-straight, curly-with-curly) instead."""
    from app.pipelines.part_one.brief import _find_quoted

    prompt = "Main headline: “WE’RE HIRING!” and CTA: “APPLY NOW”"
    assert _find_quoted(prompt) == ["WE’RE HIRING!", "APPLY NOW"]


def test_verbatim_guard_never_overwrites_an_already_correct_headline():
    """The guard exists to restore copy the model paraphrased away, not to second-guess
    copy it already transcribed correctly. A quoted phrase that belongs to a field the
    guard does not scan directly (offer, a feature, ...) must not bump a populated
    headline out of the way just because it wasn't found among the five it does check."""
    from app.pipelines.part_one.brief import _sanitise
    from app.schema.brief import (
        BriefCanvas,
        ColorDirection,
        Copy,
        DesignBrief,
        LayoutHints,
        Typography,
    )

    prompt = ('Headline "We’re hiring!" Salary "Up to ₹50 LPA". '
              'Experience "2+ Years Experience".')
    brief = DesignBrief(
        kind="post", canvas=BriefCanvas(width=1080, height=1350),
        subjectDescription="a laptop with an AI interface",
        copy=Copy(headline="We’re hiring!", subhead="AI / ML Engineer",
                  offer="Up to ₹50 LPA", features=["2+ Years Experience"]),
        mood=["modern"], colorDirection=ColorDirection(mode="auto"),
        typography=Typography(vibe="geometric"),
        layoutHints=LayoutHints(density="dense"), language="en",
    )
    sanitised = _sanitise(brief, prompt)
    assert sanitised.copy_text.headline == "We’re hiring!"


def test_composer_brief_summary_surfaces_tags_separately_from_features():
    """`_render_brief` builds the only view of the brief the composer LLM ever sees. It
    already surfaced `features`; `tags` (a tech stack, a skill set — a second, shorter
    list distinct from features) was added to the schema but never wired into this
    summary, so the model had no way to know a tag list existed and always left the
    `tag_N` slots empty even when the brief carried one."""
    from app.pipelines.part_one.compose import _render_brief
    from app.schema.brief import BriefCanvas, ColorDirection, Copy, DesignBrief, Typography

    brief = DesignBrief(
        kind="post", canvas=BriefCanvas(width=1080, height=1350),
        copy=Copy(headline="We're hiring!",
                  features=["2+ Years Experience"], tags=["Python", "LangChain"]),
        colorDirection=ColorDirection(mode="auto"), typography=Typography(),
    )
    rendered = _render_brief(brief)
    assert "Python" in rendered and "LangChain" in rendered


def test_tag_slots_pull_from_the_tags_list_not_features():
    """A `tag_N` slot and a `feature_N` slot share role `feature` — the id prefix is the
    only thing telling `copy_for_slot` which list to read from. A hiring post with both a
    requirements list and a tech stack must not have the tech stack silently re-read the
    requirements (or vice versa) just because both slots share a role."""
    from app.pipelines.part_one.compose import copy_for_slot
    from app.schema.brief import BriefCanvas, ColorDirection, Copy, DesignBrief, Typography
    from app.templates_corpus.skeletons import by_id

    brief = DesignBrief(
        kind="post", canvas=BriefCanvas(width=1080, height=1350),
        copy=Copy(features=["2+ Years Experience", "Immediate Joiner"],
                  tags=["LangChain", "Python"]),
        colorDirection=ColorDirection(mode="auto"), typography=Typography(),
    )
    skeleton = by_id("tpl_post_hiring_45_01")
    by_slot_id = {s.slot_id: s for s in skeleton.slots}
    assert copy_for_slot(by_slot_id["feature_1"], brief) == "2+ Years Experience"
    assert copy_for_slot(by_slot_id["tag_1"], brief) == "LangChain"


# --------------------------------------------------------------------------------------
# Corpus coverage — every (kind, aspect) needs both a subject and a text-only option
# --------------------------------------------------------------------------------------


def test_every_kind_and_aspect_offers_both_a_subject_and_a_text_only_layout():
    """`template.retrieve` filters hard on (kind, aspect) and prefers one side of the
    text-only split. A hole in that grid does not degrade gracefully — the request falls
    through to a layout authored for a different canvas shape."""
    from app.templates_corpus.skeletons import ALL_SKELETONS

    families: dict[tuple[str, str], set[bool]] = {}
    for skeleton in ALL_SKELETONS:
        key = (skeleton.kind, skeleton.aspect)
        families.setdefault(key, set()).add("text-only" in skeleton.tags)

    missing = {key: kinds for key, kinds in families.items() if len(kinds) < 2}
    assert not missing, f"no text-only/subject counterpart for: {sorted(missing)}"


def test_line_ornament_is_never_authored_behind_a_subject():
    """A hairline rule behind an opaque cutout is not subtle, it is two stubs poking out
    at either end — and the subject's frame grows at runtime, so only depth holds."""
    from app.templates_corpus.skeletons import ALL_SKELETONS
    from app.templates_corpus.validate import _check_ornament_depth

    issues = [i for sk in ALL_SKELETONS for i in _check_ornament_depth(sk)]
    assert not issues, [f"{i.template_id}/{i.slot_id}: {i.message}" for i in issues]


def test_reshaping_a_subject_cannot_push_it_far_off_the_canvas():
    from app.pipelines.part_one.fit import MAX_OFFCANVAS_FRACTION

    doc = _doc_with_subject(Frame(x=140, y=400, w=1000, h=430), Size(w=1600, h=900))
    fit_subjects(doc)
    frame = doc.layers[0].frame

    assert frame.x >= -frame.w * MAX_OFFCANVAS_FRACTION - 1
    assert frame.x + frame.w <= 1080 + frame.w * MAX_OFFCANVAS_FRACTION + 1


def test_the_scrim_estimate_matches_the_scrim_that_is_drawn():
    """Harmonisation escalates to a gradient scrim and then records the contrast it
    believes it achieved. If that estimate is not the scrim actually inserted, a layer
    the renderer draws at 1.8:1 ships with a note claiming 5.8:1 — and the eval, which
    measures the render, is the only thing that notices."""
    from app.pipelines.part_one.harmonize import (
        SCRIM_OPACITY,
        _composite,
        _insert_scrim,
        weakest_scrim_opacity,
    )
    from app.schema.doc import Canvas, DesignDoc, Frame, TextLayer

    layer = TextLayer(
        id="l_headline", name="Headline", role="headline",
        frame=Frame(x=80, y=200, w=900, h=300), content="I Flew For 43",
        fontFamily="Inter", fontSize=144, fontWeight=900, color="#F0EEE9",
    )
    doc = DesignDoc(id="d1", title="t", canvas=Canvas(width=1280, height=720),
                    layers=[layer], palette=["#276CA9", "#3C85BF", "#F0EEE9"],
                    createdAt="2026-01-01T00:00:00Z", updatedAt="2026-01-01T00:00:00Z")

    behind = "#BFD4E4"
    colour, opacity = _insert_scrim(doc, 0, layer, behind)
    scrim = doc.layers[0]

    # The scrim is painted flat black or white — never the palette's ground colour, which
    # is what the old estimate assumed.
    assert {stop.color for stop in scrim.gradient.stops} == {colour}
    assert colour != doc.palette[0], "a light artwork must be darkened, not tinted"

    # The reported opacity is what the faintest line of the text sits on, not the peak.
    # Overstating it is what let a 1.8:1 layer ship with a note claiming 5.8:1.
    assert opacity == weakest_scrim_opacity()
    assert 0 < opacity < SCRIM_OPACITY
    assert max(s.opacity for s in scrim.gradient.stops) == SCRIM_OPACITY

    # And the caller's composite of that pair has to be the thing it judges against.
    effective = _composite(behind, colour, opacity)
    assert relative_luminance(effective) < relative_luminance(behind)


def test_mood_words_are_not_handed_to_an_image_model_raw():
    """A mood word names a tone to a designer and a stock genre to an image model.
    'festive' returns snowflakes and fir, which is how a Diwali greeting comes back
    decorated for Christmas."""
    from app.pipelines.part_one.compose import mood_for_image

    direction = mood_for_image(["festive", "elegant"])
    assert "festive" not in direction
    assert "ornamental" in direction and "glowing" in direction
    # An unrecognised mood is passed through rather than dropped.
    assert "energetic" in mood_for_image(["energetic"])


def test_image_prompts_never_carry_a_raw_mood_word():
    from app.pipelines.part_one.brief import heuristic_brief
    from app.pipelines.part_one.compose import build_image_prompt
    from app.templates_corpus.skeletons import ALL_SKELETONS

    brief = heuristic_brief("Diwali greeting post with a brass diya lamp")
    assert "festive" in brief.mood, "the fixture depends on this mood being detected"

    for skeleton in ALL_SKELETONS:
        for slot in skeleton.slots:
            if slot.layer_type != "image":
                continue
            prompt, _ = build_image_prompt(slot, brief, ["#14264F", "#F3E9D6", "#C9A227"])
            assert "{{" not in prompt, f"{skeleton.id}/{slot.slot_id} left a placeholder"
            assert "festive" not in prompt, f"{skeleton.id}/{slot.slot_id}"


def test_a_transparent_slot_never_asks_for_something_to_stand_on():
    """The composer writes 'arranged on a decorative surface' into a cutout prompt, the
    model obliges, and the alpha channel then traces the tray — so the 'cutout' arrives
    as a hard-edged rectangle of wood. A negative prompt cannot undo a positive
    instruction to photograph something on a surface."""
    from app.pipelines.part_one.compose import scrub_image_prompt

    scrubbed = scrub_image_prompt(
        "three brass diya lamps, arranged on a decorative surface, straight-on hero "
        "view, resting on polished marble, crisp detail", transparent=True)

    assert "surface" not in scrubbed and "marble" not in scrubbed
    assert "diya lamps" in scrubbed, "the subject clause must survive"
    assert "transparent background" in scrubbed

    # An opaque slot keeps its ground plane — a backdrop is the whole point of one.
    opaque = scrub_image_prompt("a lamp on a marble table, soft light", transparent=False)
    assert "marble table" in opaque


def test_festive_is_rewritten_but_christmas_is_left_alone():
    from app.pipelines.part_one.compose import scrub_image_prompt

    rewritten = scrub_image_prompt("subtle festive texture, abstract, flat",
                                   transparent=False)
    assert "festive" not in rewritten
    assert "ornamental" in rewritten

    # Someone who asks for Christmas wants Christmas.
    assert "Christmas" in scrub_image_prompt("a decorated Christmas tree, warm light",
                                             transparent=False)


def test_llm_written_prompts_are_scrubbed_before_they_reach_the_model():
    """`_sanitise_output` is the only enforcement point — §1.3 tells the composer both
    rules and the composer breaks both of them."""
    from app.pipelines.part_one.compose import _sanitise_output
    from app.schema.composer import ComposerOutput, ComposerSlot, SlotImagePrompt
    from app.templates_corpus.skeletons import by_id

    skeleton = by_id("tpl_post_festive_01")
    subject = next(s for s in skeleton.slots if s.slot_id == "subject")
    assert subject.image.transparent, "fixture depends on this being a cutout slot"

    output = ComposerOutput(
        templateId=skeleton.id, reason="test", palette=["#14264F", "#F3E9D6", "#C9A227"],
        font={"family": "Playfair Display", "textFamily": "Source Sans 3"},
        slots=[ComposerSlot(slotId="subject", include=True, imagePrompt=SlotImagePrompt(
            prompt="a festive diya arranged on a wooden tray, warm light",
            negativePrompt="blurry"))],
    )
    brief = heuristic_brief("Diwali greeting post with a brass diya lamp")
    cleaned = _sanitise_output(output, brief, [skeleton])

    entry = next(e for e in cleaned.slots if e.slot_id == "subject")
    assert "festive" not in entry.image_prompt.prompt
    assert "tray" not in entry.image_prompt.prompt


# --------------------------------------------------------------------------------------
# Following the request: offers, contact details, feature lists, several subjects
#
# The shipped defect these share: a prompt carrying "flat 50% off, call 98765 43210,
# facial manicure and massage" came back as a headline over one photograph. Every fact
# the user typed was parsed, and then there was nowhere to put it.
# --------------------------------------------------------------------------------------


def _dense_brief(prompt: str):
    """A brief through the same sanitising the real parser applies to LLM output."""
    from app.pipelines.part_one.brief import _sanitise

    return _sanitise(heuristic_brief(prompt), prompt)


def test_contact_details_are_transcribed_character_for_character():
    brief = _dense_brief('Salon post, call +91 98765 43210, visit glowsalon.com, '
                         'email hi@glow.in, @glowsalon')
    contact = brief.copy_text.contact

    assert contact.phone == "+91 98765 43210"
    assert contact.website == "glowsalon.com"
    assert contact.email == "hi@glow.in"
    assert contact.social == "@glowsalon"


def test_a_phone_number_nobody_gave_is_dropped():
    """A design whose number does not ring is worse than one with no number: it ships
    looking finished. The only way to tell a transcribed number from an invented one is
    whether its digits appear in the prompt."""
    from app.pipelines.part_one.brief import _restore_details
    from app.schema.brief import Contact

    prompt = "Poster for a bakery opening, warm and natural"
    brief = heuristic_brief(prompt)
    brief.copy_text.contact = Contact(phone="+1 555 0100")
    _restore_details(brief, prompt)

    assert brief.copy_text.contact.phone is None


def test_a_url_is_not_mistaken_for_a_phone_number():
    """Digits inside a domain read as a number to call unless URLs are consumed first."""
    brief = _dense_brief("Post for shop24.com, 20% off everything")
    assert brief.copy_text.contact.phone is None
    assert brief.copy_text.contact.website == "shop24.com"


def test_an_offer_is_split_out_of_the_headline_and_stamped_into_a_badge():
    brief = _dense_brief("Sale post, flat 50% off, only Rs 2499")
    copy = brief.copy_text

    assert copy.offer == "flat 50% off"
    # A seal holds the discount, not the phrase wrapped around it.
    assert copy.badge == "50% OFF"
    assert copy.price == "only Rs 2499"


def test_a_brief_carrying_an_offer_and_a_phone_number_asks_for_a_dense_layout():
    """Density is a retrieval preference. A brief that stays 'balanced' draws a
    three-slot layout and the rest of what the user typed never reaches the canvas."""
    dense = _dense_brief("Salon post, flat 50% off, call 98765 43210")
    plain = _dense_brief('Story for a running shoe, minimal, headline "Run Lighter"')

    assert dense.layout_hints.density == "dense"
    assert plain.layout_hints.density == "balanced"


def test_the_offer_the_list_and_the_contact_strip_all_reach_the_canvas():
    from app.pipelines.part_one.compose import expand, mechanical_compose
    from app.templates_corpus.skeletons import by_id

    brief = _dense_brief('Sale post for wireless headphones, flat 50% off, only Rs 2499, '
                         'call 98765 43210, headline "Sound Unleashed" cta "Shop now"')
    brief.copy_text.features = ["30hr battery", "Active noise cancel", "2yr warranty"]

    skeleton = by_id("tpl_post_offer_dense_01")
    doc = expand(skeleton, mechanical_compose(brief, skeleton), brief, doc_id="d1")
    placed = {layer.role: layer.content for layer in doc.layers if layer.type == "text"}

    assert placed["headline"] == "Sound Unleashed"
    assert placed["offer"] == "flat 50% off"
    assert placed["price"] == "only Rs 2499"
    assert placed["badge"] == "50% OFF"
    assert placed["cta"] == "Shop now"
    assert "98765 43210" in placed["contact"]

    features = [layer.content for layer in doc.layers if layer.role == "feature"]
    assert features == ["30hr battery", "Active noise cancel", "2yr warranty"]


def test_a_truncated_phone_number_is_dropped_rather_than_shipped():
    """Shortening copy is fine. Shortening a number is not — '+91 98765 4…' is not
    abbreviated information, it is wrong information."""
    from app.pipelines.part_one.compose import _fallback_copy_for
    from app.templates_corpus.dsl import text as text_slot

    brief = _dense_brief("Post, call +91 98765 43210, visit a-very-long-domain-name.com, "
                         "email hello@a-very-long-domain-name.com")
    slot = text_slot("contact", "contact", x=0, y=0.9, w=1, h=0.05, size_n=0.02,
                     max_chars=14, required=False)

    # Too narrow for the strip and too narrow for any single line of it.
    assert _fallback_copy_for(slot, brief) is None

    wider = text_slot("contact", "contact", x=0, y=0.9, w=1, h=0.05, size_n=0.02,
                      max_chars=20, required=False)
    assert _fallback_copy_for(wider, brief) == "+91 98765 43210"


def test_several_subjects_become_several_different_cutouts():
    """A four-up grid whose slots all resolve to one prompt renders the same object four
    times, which reads as a bug rather than as a range."""
    from app.pipelines.part_one.compose import build_image_prompt
    from app.templates_corpus.skeletons import by_id

    brief = _dense_brief("Square post for a cafe menu")
    brief.subject_description = "a flat white in a ceramic cup"
    brief.subjects = ["a glazed cinnamon bun", "a cold brew in a tall glass"]

    skeleton = by_id("tpl_post_services_sq_01")
    prompts = {}
    for slot in skeleton.slots:
        if slot.role == "subject":
            prompts[slot.slot_id], _ = build_image_prompt(slot, brief, ["#111", "#eee"])

    assert "flat white" in prompts["subject"]
    assert "cinnamon bun" in prompts["subject_b"]
    assert "cold brew" in prompts["subject_c"]


def test_one_subject_across_several_slots_still_varies_the_angle():
    """Cycling back to the hero is deliberate — an empty slot is a hole, and a second
    angle on the same product is a showcase."""
    from app.pipelines.part_one.compose import build_image_prompt
    from app.templates_corpus.skeletons import by_id

    brief = _dense_brief("Square post for a ceramic mug")
    brief.subject_description = "a speckled ceramic mug"
    brief.subjects = []

    skeleton = by_id("tpl_post_services_sq_01")
    prompts = [build_image_prompt(s, brief, ["#111", "#eee"])[0]
               for s in skeleton.slots if s.role == "subject"]

    assert all("ceramic mug" in p for p in prompts)
    assert len(set(prompts)) == len(prompts), "the same prompt three times is not a trio"


def test_the_subject_survives_a_prompt_that_names_the_surface_it_sits_on():
    """Dropping the whole clause left a cutout prompt describing lighting and nothing to
    light: 'a manicure set on a marble tray' became 'side profile view, crisp detail'."""
    from app.pipelines.part_one.compose import scrub_image_prompt

    scrubbed = scrub_image_prompt("a manicure set on a marble tray, side profile view",
                                  transparent=True)
    assert "manicure set" in scrubbed
    assert "tray" not in scrubbed

    # A surface word that is the subject itself must not be cut away.
    assert "marble sculpture" in scrub_image_prompt("a marble sculpture, hero view",
                                                    transparent=True)


def test_the_same_words_are_never_set_twice_in_one_design():
    """Both composers produce this: the discount is written into the headline and then
    dutifully placed in the offer slot too, and the design says it twice."""
    from app.pipelines.part_one.compose import expand, mechanical_compose
    from app.templates_corpus.skeletons import by_id

    # No headline of its own, so the headline is derived from the offer.
    brief = _dense_brief("Square post for a salon, flat 50% off, call 98765 43210")
    skeleton = by_id("tpl_post_services_sq_01")
    doc = expand(skeleton, mechanical_compose(brief, skeleton), brief, doc_id="d1")

    contents = [" ".join(layer.content.lower().split())
                for layer in doc.layers if layer.type == "text"]
    assert len(contents) == len(set(contents)), contents
    # ...and the words survive in the more prominent slot, not the lesser one.
    assert any(layer.role == "headline" and "50%" in layer.content
               for layer in doc.layers if layer.type == "text")


def test_every_kind_with_a_dense_layout_can_also_answer_a_sparse_brief():
    """Density is a retrieval preference, so a kind offering only dense layouts would
    force one on a two-line brief."""
    from app.templates_corpus.skeletons import ALL_SKELETONS

    by_kind: dict[str, set[bool]] = {}
    for skeleton in ALL_SKELETONS:
        by_kind.setdefault(skeleton.kind, set()).add("dense" in skeleton.tags)

    only_dense = [kind for kind, flags in by_kind.items() if flags == {True}]
    assert not only_dense, only_dense


def test_a_dense_skeleton_degrades_to_the_brief_it_actually_got():
    """One skeleton has to serve both the request carrying all of it and the one carrying
    a third: the unfilled slots drop out rather than shipping as empty frames."""
    from app.pipelines.part_one.compose import expand, mechanical_compose
    from app.templates_corpus.skeletons import by_id

    brief = _dense_brief('Square post, headline "Open Today"')
    skeleton = by_id("tpl_post_services_sq_01")
    doc = expand(skeleton, mechanical_compose(brief, skeleton), brief, doc_id="d1")

    text_layers = [layer for layer in doc.layers if layer.type == "text"]
    assert [layer.content for layer in text_layers] == ["Open Today"]
    assert all(layer.content.strip() for layer in text_layers)


# --------------------------------------------------------------------------------------
# art.direct — the imagery is decided per request, not baked into the layout
#
# The shipped defect: every background slot in the corpus carried the prompt "studio
# backdrop, soft directional light", so a barber shop, a dental clinic and a sneaker drop
# were photographed on the same grey sweep, and the ornament on each was whichever motif
# the skeleton author happened to type.
# --------------------------------------------------------------------------------------


def _directed(prompt: str, request_id: str = "r1"):
    """(brief, direction) the way the orchestrator builds them."""
    from app.pipelines.part_one.art_direction import heuristic_direction, seed_from
    from app.pipelines.part_one.brief import _sanitise

    brief = _sanitise(heuristic_brief(prompt), prompt)
    return brief, heuristic_direction(brief, seed=seed_from(request_id))


def test_two_trades_through_one_skeleton_are_not_the_same_picture():
    from app.pipelines.part_one.compose import build_image_prompt
    from app.templates_corpus.skeletons import by_id

    skeleton = by_id("tpl_post_festive_01")
    background = next(s for s in skeleton.slots if s.role == "background")
    palette = ["#14264F", "#F3E9D6", "#C9A227"]

    prompts = {}
    for label, text in (("gym", "Post for a gym membership offer, bold"),
                        ("clinic", "Post for a dental clinic checkup offer"),
                        ("cafe", "Post for a coffee roastery, warm and natural")):
        brief, direction = _directed(text)
        prompts[label], _ = build_image_prompt(background, brief, palette, direction)

    assert len(set(prompts.values())) == 3, prompts
    # ...and each one is the picture its own direction asked for, not a generic sweep.
    for label, text in (("gym", "Post for a gym membership offer, bold"),
                        ("clinic", "Post for a dental clinic checkup offer"),
                        ("cafe", "Post for a coffee roastery, warm and natural")):
        _, direction = _directed(text)
        assert direction.texture in prompts[label], (label, prompts[label])
    assert "studio backdrop" not in " ".join(prompts.values())


def test_the_same_request_is_directed_the_same_way_twice():
    """INV-2. Variety across requests is the point; variety within one is a bug — the
    user regenerates a layer and the design changes underneath them."""
    from app.pipelines.part_one.art_direction import heuristic_direction, seed_from
    from app.pipelines.part_one.brief import _sanitise

    prompt = "Post for a jewellery boutique, premium gold"
    brief = _sanitise(heuristic_brief(prompt), prompt)
    seed = seed_from("request-abc")

    first = heuristic_direction(brief, seed=seed)
    second = heuristic_direction(brief, seed=seed)
    assert first.model_dump() == second.model_dump()


def test_the_same_prompt_asked_twice_is_directed_differently():
    prompt = "Post for a jewellery boutique, premium gold"
    scenes = {_directed(prompt, f"request-{i}")[1].scene for i in range(8)}
    assert len(scenes) > 1, "every request in a trade got the identical background"


def test_a_ceremony_keeps_its_garland():
    """Variety must not overrule the trade. Bunting on a wedding invitation is not a
    fresh take, it is wrong — so a family a domain has one answer for gets that answer
    every time, and only the families it has no opinion about wander."""
    for i in range(8):
        _, direction = _directed("Diwali greeting post with a brass diya lamp", f"r{i}")
        assert direction.motifs.band == "garland"


def test_substituting_a_motif_never_changes_whether_it_is_stroked():
    """Families are homogeneous in stroke-versus-fill on purpose: a slot authored to
    stroke an outline that comes back a filled shape floods the shape it outlined."""
    from app.templates_corpus.ornament import MOTIF_FAMILIES, STROKE_MOTIFS

    for family, members in MOTIF_FAMILIES.items():
        stroked = {m in STROKE_MOTIFS for m in members}
        assert len(stroked) == 1, (family, members)


def test_every_decorative_motif_belongs_to_exactly_one_family():
    from app.templates_corpus.ornament import ICON_MOTIFS, MOTIF_FAMILIES, MOTIFS

    seen: list[str] = [m for members in MOTIF_FAMILIES.values() for m in members]
    assert sorted(seen) == sorted(MOTIFS - ICON_MOTIFS), (
        "a decorative motif is missing or double-counted")
    assert len(seen) == len(set(seen))


def test_pictograms_belong_to_no_family():
    """Substitution within a family is safe for decoration and meaningless for a
    pictogram: a tick and a handset are two words, not two takes on one ornament. If an
    icon ever joined a family, art direction would quietly turn a checklist into a row
    of telephones."""
    from app.templates_corpus.ornament import ICON_MOTIFS, family_of

    for motif in ICON_MOTIFS:
        assert family_of(motif) is None, motif


def test_every_motif_has_a_builder_at_every_density():
    from app.templates_corpus.ornament import MOTIFS, render_motif

    for motif in MOTIFS:
        for density in (1, 3, 5):
            assert render_motif(motif, 240, 160, seed=7, density=density), (
                motif, density)


def test_ornament_the_author_varied_stays_varied():
    """A family choice applied slot by slot collapses ornament the author deliberately
    varied: a layout carrying a scalloped skirt AND a divider came back with two
    dividers."""
    from app.pipelines.part_one.compose import motif_assignment
    from app.templates_corpus.ornament import family_of
    from app.templates_corpus.skeletons import ALL_SKELETONS

    for skeleton in ALL_SKELETONS:
        authored = {s.slot_id: s.shape.motif for s in skeleton.slots
                    if s.shape is not None and s.shape.motif}
        if len(set(authored.values())) < 2:
            continue
        for i in range(4):
            _, direction = _directed("Post for a salon offer", f"r{i}")
            assigned = motif_assignment(skeleton.slots, direction)

            # Distinctness is preserved in both directions, and nothing leaves its family.
            for a, b in ((x, y) for x in authored for y in authored if x < y):
                if authored[a] != authored[b]:
                    assert assigned[a] != assigned[b], (skeleton.id, a, b, assigned)
            for slot_id, motif in assigned.items():
                assert family_of(motif) == family_of(authored[slot_id]), (
                    skeleton.id, slot_id)


def test_a_directed_prompt_leaves_no_placeholder_behind():
    from app.pipelines.part_one.compose import build_image_prompt
    from app.templates_corpus.skeletons import ALL_SKELETONS

    brief, direction = _directed("Square post for a bakery, 20% off sourdough")
    for skeleton in ALL_SKELETONS:
        for slot in skeleton.slots:
            if slot.layer_type != "image":
                continue
            prompt, _ = build_image_prompt(slot, brief, ["#F3E9D6", "#2A1A12"], direction)
            assert "{{" not in prompt, f"{skeleton.id}/{slot.slot_id}: {prompt}"
            # A dropped placeholder must not leave a hole behind it either.
            assert ", ," not in prompt and not prompt.startswith(",")
            assert "festive" not in prompt


def test_a_directed_scene_never_puts_anything_in_the_frame():
    """The subject is composited on top and the layout needs room for the headline, so a
    background that arrives with a person in it is unusable."""
    from app.pipelines.part_one.art_direction import _clean_scene

    cleaned = _clean_scene("a marble counter, a woman holding a bottle, soft daylight")
    assert "woman" not in cleaned
    assert "marble counter" in cleaned and "soft daylight" in cleaned


def test_an_invented_motif_cannot_reach_the_renderer():
    """A motif with no builder renders to an empty path, which is a slot that silently
    disappears rather than an error anyone sees. Two things stop that: the schema refuses
    it on the way in, and the assignment re-checks membership on the way out."""
    import pytest
    from pydantic import ValidationError

    from app.pipelines.part_one.compose import motif_assignment
    from app.schema.art import ArtDirection, MotifChoice
    from app.templates_corpus.skeletons import by_id

    with pytest.raises(ValidationError):
        MotifChoice.model_validate({"band": "fireworks"})

    # Built by hand, bypassing validation: the assignment must still refuse it.
    direction = ArtDirection.model_construct(
        scene="a marble top", texture="plaster grain", lighting="soft light",
        subject_treatment="dewy", prop="", density=3,
        motifs=MotifChoice.model_construct(band="fireworks", rule="divider"))

    skeleton = by_id("tpl_post_festive_01")
    assigned = motif_assignment(skeleton.slots, direction)
    assert assigned["garland"] == "garland", "an unknown motif must not be substituted in"
    assert assigned["divider"] == "divider"


def test_a_family_the_direction_has_no_view_on_keeps_the_layout_choice():
    from app.pipelines.part_one.compose import motif_assignment
    from app.schema.art import ArtDirection, MotifChoice
    from app.templates_corpus.skeletons import by_id

    direction = ArtDirection(scene="a marble top", texture="plaster grain",
                             lighting="soft light", subjectTreatment="dewy",
                             motifs=MotifChoice())
    skeleton = by_id("tpl_post_festive_01")
    authored = {s.slot_id: s.shape.motif for s in skeleton.slots
                if s.shape is not None and s.shape.motif}

    assert motif_assignment(skeleton.slots, direction) == authored


def test_without_a_direction_the_prompts_are_what_they_always_were():
    """`art.direct` is one more call that can fail, and §0.9 says a partial design beats
    an error page. With no direction the templates must still resolve to a usable prompt."""
    from app.pipelines.part_one.compose import build_image_prompt
    from app.templates_corpus.skeletons import ALL_SKELETONS

    brief = heuristic_brief("Post for a ceramic mug, minimal")
    for skeleton in ALL_SKELETONS:
        for slot in skeleton.slots:
            if slot.layer_type != "image":
                continue
            prompt, negative = build_image_prompt(slot, brief, ["#FFF", "#111"], None)
            assert "{{" not in prompt and prompt.strip()
            assert "text" in negative


# -- pictograms, masks and declared pairings -------------------------------------------
#
# The layered skeletons in `skeletons_rich` are built from units — a tick and its service
# line, a handset and its number, a keyline and its photograph — and every defect below
# is one of those units coming apart somewhere in the pipeline.


def test_a_tick_is_dropped_with_the_line_it_annotates():
    """A brief carrying four services through a six-row checklist must not ship six
    ticks, two of them pointing at empty space."""
    from app.pipelines.part_one.compose import expand, mechanical_compose
    from app.templates_corpus.skeletons import by_id

    brief = _dense_brief('Post for a yoga studio, headline "Move Better", call 98765 43210')
    brief.copy_text.features = ["Women's health", "Mental health", "Personal coach"]

    skeleton = by_id("tpl_post_checklist_sq_01")
    doc = expand(skeleton, mechanical_compose(brief, skeleton), brief, doc_id="d1")

    lines = {layer.id for layer in doc.layers if layer.role == "feature"}
    marks = {layer.id for layer in doc.layers if layer.id.endswith("_mark")
             and "feature" in layer.id}
    assert len(lines) == 3, "one row per service, no more"
    assert {mark.removesuffix("_mark") for mark in marks} == lines


def test_a_checklist_survives_the_solver_with_its_ticks_attached():
    """`_pack_text_stacks` trims each box to its ink and lifts everything below. The
    ticks are decoration, so they were left where they were and the rows came apart."""
    from app.layout.solver import SolveOpts, solve
    from app.pipelines.part_one.compose import expand, mechanical_compose
    from app.templates_corpus.skeletons import by_id

    brief = _dense_brief('Post for a clinic, headline "Care That Fits", call 98765 43210')
    brief.copy_text.features = ["Dental checks", "Whitening", "Braces", "Implants"]

    skeleton = by_id("tpl_post_checklist_sq_01")
    doc = expand(skeleton, mechanical_compose(brief, skeleton), brief, doc_id="d1")
    solved = solve(doc, SolveOpts(grid_baseline=skeleton.grid_baseline)).doc

    by_id_map = {layer.id: layer for layer in solved.layers if layer.visible}
    rows = [layer for layer in by_id_map.values() if layer.role == "feature"]
    assert rows, "the checklist reached the canvas"
    for row in rows:
        mark = by_id_map.get(f"{row.id}_mark")
        assert mark is not None, f"{row.id} lost its tick"
        # The tick sits on the row's centre line, within a hair of it.
        drift = abs((mark.frame.y + mark.frame.h / 2) - (row.frame.y + row.frame.h / 2))
        assert drift <= row.frame.h * 0.35, (row.id, drift)
        # And in front of it, not on top of the words.
        assert mark.frame.x + mark.frame.w <= row.frame.x + 1, (row.id, mark.frame.x)


def test_no_layer_outlives_the_thing_it_annotates():
    """Collision resolution drops a companion group, but decoration is not collidable
    and so was never in one: the line went and the handset stayed."""
    from app.layout.solver import SolveOpts, solve
    from app.pipelines.part_one.compose import expand, mechanical_compose
    from app.templates_corpus.skeletons import ALL_SKELETONS

    brief = _dense_brief('Post for a salon, headline "Look Sharp", flat 30% off, '
                         'call 98765 43210, visit example.com')
    brief.copy_text.features = ["Cuts", "Colour"]

    for skeleton in ALL_SKELETONS:
        doc = expand(skeleton, mechanical_compose(brief, skeleton), brief, doc_id="d1")
        solved = solve(doc, SolveOpts(grid_baseline=skeleton.grid_baseline)).doc
        live = {layer.id for layer in solved.layers if layer.visible}
        for layer in solved.layers:
            if layer.visible and layer.constraints.pairs_with:
                assert layer.constraints.pairs_with in live, (
                    f"{skeleton.id}: {layer.id} outlived "
                    f"{layer.constraints.pairs_with}")


def test_every_mask_cuts_a_shape_inside_the_frame_it_was_given():
    """A mask that escapes its frame paints over its neighbours; one that collapses to
    nothing renders the layer invisible with no error anywhere."""
    from app.renderer.core import mask_path
    from app.renderer.svgpath import parse_svg_path
    from app.schema.doc import MaskShape

    for shape in MaskShape.__args__:
        for w, h in ((300.0, 200.0), (200.0, 300.0), (240.0, 240.0)):
            layer = ImageLayer(id="i", frame=Frame(x=0, y=0, w=w, h=h), mask=shape)
            data = mask_path(layer)
            assert data, (shape, w, h)
            bounds = parse_svg_path(data).getBounds()
            assert bounds.left() >= -0.5 and bounds.top() >= -0.5, (shape, w, h)
            assert bounds.right() <= w + 0.5 and bounds.bottom() <= h + 0.5, (shape, w, h)
            # At least half the frame survives; a mask thinner than that is a mistake.
            assert bounds.width() * bounds.height() >= w * h * 0.45, (shape, w, h)


def test_a_masked_slot_reaches_the_renderer_as_a_clip_path():
    from app.renderer.core import to_draw_list
    from app.schema.doc import Canvas as DocCanvas

    doc = DesignDoc(
        id="d", canvas=DocCanvas(width=400, height=400),
        layers=[ImageLayer(id="i", assetId="a", frame=Frame(x=0, y=0, w=200, h=200),
                           naturalSize=Size(w=200, h=200), mask="circle")],
    )
    image_cmds = [c for c in to_draw_list(doc).commands if c.op == "image"]
    assert image_cmds and image_cmds[0].clip_path, "the mask never reached the draw list"


def test_a_pending_masked_asset_holds_the_same_silhouette():
    """The placeholder and the image it becomes must be the same shape, or the layer
    changes outline halfway through a progressive render."""
    from app.renderer.core import to_draw_list
    from app.schema.doc import Canvas as DocCanvas

    frame = Frame(x=0, y=0, w=200, h=200)
    pending = DesignDoc(id="d", canvas=DocCanvas(width=400, height=400),
                        layers=[ImageLayer(id="i", frame=frame, mask="arch")])
    landed = DesignDoc(id="d", canvas=DocCanvas(width=400, height=400),
                       layers=[ImageLayer(id="i", assetId="a", frame=frame,
                                          naturalSize=Size(w=200, h=200), mask="arch")])
    placeholder = next(c for c in to_draw_list(pending).commands if c.op == "placeholder")
    image = next(c for c in to_draw_list(landed).commands if c.op == "image")
    assert placeholder.clip_path == image.clip_path


def test_a_handset_and_a_globe_do_not_both_show_the_phone_number():
    """Two contact slots in one design resolved to the same field, so the website icon
    sat beside a telephone number."""
    from app.pipelines.part_one.compose import copy_for_slot
    from app.templates_corpus.dsl import text as text_slot

    brief = _dense_brief("Post for a cafe, call 98765 43210")
    brief.copy_text.contact.website = "ourcafe.example"
    brief.copy_text.contact.address = "14 Mill Lane"
    made = {
        "contact_phone": "98765 43210",
        "contact_web": "ourcafe.example",
        "contact_address": "14 Mill Lane",
    }
    for slot_id, expected in made.items():
        slot = text_slot(slot_id, "contact", x=0, y=0.9, w=0.4, h=0.05,
                         size_n=0.02, max_chars=40, required=False)
        assert copy_for_slot(slot, brief) == expected, slot_id


def test_a_named_contact_slot_falls_back_rather_than_shipping_empty():
    """A design missing its website still wants something under the globe."""
    from app.pipelines.part_one.compose import copy_for_slot
    from app.templates_corpus.dsl import text as text_slot

    brief = _dense_brief("Post for a cafe, call 98765 43210")
    slot = text_slot("contact_web", "contact", x=0, y=0.9, w=0.4, h=0.05,
                     size_n=0.02, max_chars=40, required=False)
    assert copy_for_slot(slot, brief) == "98765 43210"


def test_the_business_name_reaches_the_lockup_unchanged():
    from app.pipelines.part_one.compose import expand, mechanical_compose
    from app.templates_corpus.skeletons import by_id

    brief = _dense_brief('Post for a studio, headline "Move Better", call 98765 43210')
    brief.copy_text.brand_name = "Sunrise Yoga & Wellness"

    skeleton = by_id("tpl_post_checklist_sq_01")
    doc = expand(skeleton, mechanical_compose(brief, skeleton), brief, doc_id="d1")
    lockup = [layer for layer in doc.layers if layer.role == "logo"]
    assert lockup and lockup[0].content == "Sunrise Yoga & Wellness"


def test_every_pictogram_is_square_where_it_is_actually_drawn():
    """Normalised coordinates are not square. A tick authored 0.04 by 0.04 on a 4:5 post
    is 43 by 54 pixels, and the drawing letterboxes inside it."""
    from app.templates_corpus.ornament import ICON_MOTIFS
    from app.templates_corpus.skeletons import ALL_SKELETONS
    from app.templates_corpus.validate import aspect_ratio

    for skeleton in ALL_SKELETONS:
        ratio = aspect_ratio(skeleton.aspect)
        for slot in skeleton.slots:
            if slot.shape is None or slot.shape.motif not in ICON_MOTIFS:
                continue
            drawn = (slot.frame_n.w * ratio) / slot.frame_n.h
            assert 0.92 <= drawn <= 1.08, (skeleton.id, slot.slot_id, drawn)


# -- routing: kind, aspect, and the facts that must survive ----------------------------
#
# These are all one shipped defect. "4:5 vertical Instagram/Facebook promotional poster"
# set kind=poster from the word "poster" and a 4:5 canvas from the ratio; retrieval hard-
# filters on both, poster x 4:5 exists nowhere in the corpus, and the relaxed fallback
# returned an A4 print poster — a full-bleed photograph with three text slots. The brand
# name, the tagline, the offer and the opening date had nowhere to go, so the design
# shipped as a photo with "VISIT US TODAY" on it.


def test_a_social_aspect_is_a_post_however_the_user_said_poster():
    from app.pipelines.part_one.brief import coerce_kind_to_canvas

    assert coerce_kind_to_canvas("poster", 1080, 1350) == "post"
    assert coerce_kind_to_canvas("poster", 1080, 1080) == "post"
    assert coerce_kind_to_canvas("poster", 1080, 1920) == "story"
    assert coerce_kind_to_canvas("flyer", 1080, 1350) == "post"


def test_a_real_print_sheet_keeps_its_kind():
    """The rule must not quietly turn every poster into a post."""
    from app.pipelines.part_one.brief import coerce_kind_to_canvas

    assert coerce_kind_to_canvas("poster", 2480, 3508) == "poster"
    assert coerce_kind_to_canvas("flyer", 1654, 2339) == "flyer"
    assert coerce_kind_to_canvas("post", 1080, 1350) == "post"


def test_the_corpus_has_a_layout_for_every_kind_and_aspect_a_brief_can_ask_for():
    """A (kind, aspect) pair a brief can produce but the corpus cannot answer is how the
    fallback gets reached in the first place."""
    from app.pipelines.part_one.brief import coerce_kind_to_canvas
    from app.pipelines.part_one.retrieve import nearest_aspect
    from app.schema.brief import KIND_DEFAULT_SIZE
    from app.templates_corpus.skeletons import ALL_SKELETONS

    available = {(s.kind, s.aspect) for s in ALL_SKELETONS}
    for kind, (width, height, _dpi) in KIND_DEFAULT_SIZE.items():
        if kind == "square":     # an alias for post, not a DesignKind
            continue
        resolved = coerce_kind_to_canvas(kind, width, height)
        pair = (resolved, nearest_aspect(width, height))
        assert pair in available, f"nothing in the corpus answers {pair}"


def test_a_grand_opening_keeps_its_brand_and_its_date():
    from app.pipelines.part_one.brief import _sanitise, heuristic_brief

    prompt = ('4:5 vertical Instagram promotional poster for a motorcycle-themed '
              'restaurant called "BIKE SHED MOTO CO". Feature an appetizing gourmet '
              'burger as the main food hero. OPENING SPECIAL - FLAT 50% OFF. '
              'Opening Date: 23 September 2026.')
    brief = _sanitise(heuristic_brief(prompt), prompt)

    assert brief.kind == "post", "a 4:5 Instagram piece is a post, not a print poster"
    assert brief.copy_text.brand_name == "BIKE SHED MOTO CO"
    assert "23 September 2026" in (brief.copy_text.event_details or "")
    assert brief.copy_text.offer
    assert brief.layout_hints.density == "dense", "an offer plus a date is not sparse"
    # The subject is the thing the prompt says to feature, not the first few nouns in it.
    assert "burger" in (brief.subject_description or "").lower()


def test_a_fact_that_will_not_fit_is_dropped_rather_than_mangled():
    """"BIKE SHED M…" is not a business and "FLAT 50…" is not an offer. Both ship a
    design that looks finished and says something untrue."""
    from app.pipelines.part_one.compose import fit_to_slot
    from app.templates_corpus.dsl import text as text_slot

    def slot(role, limit):
        return text_slot("s", role, x=0, y=0.9, w=1, h=0.05, size_n=0.02,
                         max_chars=limit, required=False)

    assert fit_to_slot("BIKE SHED MOTO CO", slot("logo", 12)) is None
    assert fit_to_slot("FLAT 50% OFF", slot("price", 8)) is None
    assert fit_to_slot("Opening Date: 23 September 2026", slot("event", 14)) is None
    assert fit_to_slot("+91 98765 43210", slot("contact", 10)) is None
    # Prose may be shortened — but never mid-word.
    shortened = fit_to_slot("BIKE SHED MOTO CO", slot("headline", 12))
    assert shortened and shortened.endswith("…") and "M…" not in shortened


def test_a_script_line_is_never_set_in_capitals():
    """Script capitals are unjoined swashes: "RIDE IN. DINE OUT." rendered as
    "R IDE IN. D INE OUT." with holes punched through it."""
    from app.layout.measure import shape_block
    from app.pipelines.part_one.compose import normalise_case
    from app.templates_corpus.dsl import text as text_slot

    slot = text_slot("subhead", "subhead", x=0, y=0.1, w=0.7, h=0.06, size_n=0.04,
                     max_chars=24, face="script", required=False)
    fixed = normalise_case("RIDE IN. DINE OUT.", slot)
    assert fixed == "Ride In. Dine Out."

    # And it is narrower, so it stops overrunning the box it was authored for.
    def width(text):
        block = shape_block(text, font_family="Dancing Script", font_weight=400,
                            font_style="normal", font_size=60, max_width=4000)
        return max(line.advance for line in block.lines)

    assert width(fixed) < width("RIDE IN. DINE OUT.") * 0.9


def test_every_script_slot_in_the_corpus_gets_title_case_copy():
    from app.pipelines.part_one.compose import normalise_case
    from app.templates_corpus.skeletons import ALL_SKELETONS

    script_slots = [s for sk in ALL_SKELETONS for s in sk.slots
                    if s.text is not None and s.text.face == "script"]
    assert script_slots, "the corpus is meant to carry script accents"
    for slot in script_slots:
        assert not normalise_case("SUMMER SALE", slot).isupper(), slot.slot_id


# -- a tall cutout must not take the layout apart --------------------------------------
#
# The shipped defect, in one picture: a copper bottle on a product card. The cutout is
# tall, the subject frame is wide, `fit_subjects` grew it to two thirds of the canvas,
# and collision resolution then evicted the headline to the bottom of the design, left
# the CTA label without its pill and stranded the colour halo — three times wider than
# the product it was backing — as an unexplained blob.


def _product_doc(natural: Size, template_id: str = "tpl_post_product_01"):
    from app.pipelines.part_one.brief import _sanitise, heuristic_brief
    from app.pipelines.part_one.compose import expand, mechanical_compose
    from app.templates_corpus.skeletons import by_id

    prompt = ('4:5 post for a premium copper water bottle. '
              'Headline "PURE WATER. TIMELESS WELLNESS." cta "Shop Now".')
    brief = _sanitise(heuristic_brief(prompt), prompt)
    skeleton = by_id(template_id)
    doc = expand(skeleton, mechanical_compose(brief, skeleton), brief, doc_id="d1")
    for layer in doc.layers:
        if layer.type == "image":
            layer.asset_id = "a"
            layer.natural_size = natural if layer.role == "subject" else Size(w=1200, h=1500)
    return doc, skeleton


def test_a_tall_product_does_not_push_the_headline_off_the_top_of_the_design():
    from app.layout.solver import SolveOpts, solve
    from app.pipelines.part_one.fit import fit_subjects

    doc, skeleton = _product_doc(Size(w=700, h=2000))
    fit_subjects(doc)
    solved = solve(doc, SolveOpts(grid_baseline=skeleton.grid_baseline)).doc

    headline = next(l for l in solved.layers if l.role == "headline" and l.visible)
    subject = next(l for l in solved.layers if l.role == "subject" and l.visible)
    assert headline.frame.y < subject.frame.y, "the headline is authored above the product"
    assert headline.frame.y < doc.canvas.height * 0.25, "and near the top of the canvas"


def test_a_refitted_subject_stays_inside_the_band_the_layout_gave_it():
    from app.pipelines.part_one.fit import fit_subjects, free_band

    doc, _ = _product_doc(Size(w=700, h=2000))
    subject = next(l for l in doc.layers if l.role == "subject")
    top, bottom = free_band(doc, subject)
    fit_subjects(doc)

    assert subject.frame.y >= top - 1
    assert subject.frame.y + subject.frame.h <= bottom + 1


def test_a_wide_cutout_can_still_claim_the_width_it_needs():
    """The band constrains height, not width — the pass must still do its original job."""
    from app.pipelines.part_one.fit import fit_subjects

    doc, _ = _product_doc(Size(w=2000, h=700))
    subject = next(l for l in doc.layers if l.role == "subject")
    before = subject.frame.w
    fit_subjects(doc)
    assert subject.frame.w > before, "a wide cutout should spread out"


def test_the_field_behind_a_product_follows_it_when_the_product_is_refitted():
    """A halo three times wider than the thing it backs reads as a stray shape."""
    from app.pipelines.part_one.fit import fit_subjects

    doc, _ = _product_doc(Size(w=700, h=2000))
    halo = next(l for l in doc.layers if l.id == "l_halo")
    fit_subjects(doc)
    subject = next(l for l in doc.layers if l.role == "subject")

    assert halo.meta.notes.get("followedSubject") == subject.id
    assert halo.frame.w < subject.frame.w * 3, "the backing dwarfs the product"
    # And it is still behind it, not beside it.
    assert abs((halo.frame.x + halo.frame.w / 2)
               - (subject.frame.x + subject.frame.w / 2)) < subject.frame.w


def test_no_template_loses_its_headline_to_a_tall_cutout():
    from app.layout.solver import SolveOpts, solve
    from app.pipelines.part_one.fit import fit_subjects
    from app.templates_corpus.skeletons import ALL_SKELETONS

    for skeleton in ALL_SKELETONS:
        head = next((s for s in skeleton.slots if s.role == "headline"), None)
        subj = next((s for s in skeleton.slots if s.role == "subject"), None)
        if head is None or subj is None:
            continue
        # Only where the two are stacked; a side-by-side layout has no such ordering.
        shared = (min(head.frame_n.x + head.frame_n.w, subj.frame_n.x + subj.frame_n.w)
                  - max(head.frame_n.x, subj.frame_n.x))
        if shared <= 0.25 or head.frame_n.y >= subj.frame_n.y:
            continue

        doc, _ = _product_doc(Size(w=700, h=2000), template_id=skeleton.id)
        fit_subjects(doc)
        solved = solve(doc, SolveOpts(grid_baseline=skeleton.grid_baseline)).doc
        headline = next((l for l in solved.layers if l.role == "headline" and l.visible),
                        None)
        subject = next((l for l in solved.layers if l.role == "subject" and l.visible),
                       None)
        if headline is None or subject is None:
            continue
        assert headline.frame.y < subject.frame.y + subject.frame.h, skeleton.id


# -- legibility escalation: a scrim, not a row of chips --------------------------------


def test_prose_takes_a_scrim_and_a_label_takes_a_pill():
    from app.pipelines.part_one.harmonize import _prefers_scrim
    from app.schema.doc import TextLayer

    def layer(role, size):
        return TextLayer(id="t", role=role, frame=Frame(x=0, y=0, w=400, h=80),
                         content="x", font_size=size)

    for role in ("headline", "subhead", "body", "offer"):
        assert _prefers_scrim(layer(role, 24)), role
    for role in ("cta", "badge", "price", "caption", "contact"):
        assert not _prefers_scrim(layer(role, 24)), role
    # Display type takes a scrim whatever its role: a pill behind it reads as a label.
    assert _prefers_scrim(layer("caption", 96))


def test_a_copy_block_does_not_ship_as_a_stack_of_chips():
    """Each line used to earn its own backdrop, so a headline and the subhead under it
    came back as two brown rectangles of different widths."""
    from app.pipelines.part_one.harmonize import _covering_scrim
    from app.renderer.transform import Rect
    from app.schema.doc import GradientStop, LinearGradient, ShapeLayer, TextLayer

    scrim = ShapeLayer(id="s", role="overlay", frame=Frame(x=0, y=0, w=1080, h=600),
                       gradient=LinearGradient(angle=180, stops=[
                           GradientStop(offset=0.0, color="#000000", opacity=0.0),
                           GradientStop(offset=0.5, color="#000000", opacity=0.45),
                           GradientStop(offset=1.0, color="#000000", opacity=0.0)]))
    scrim.meta.notes["insertedBy"] = "harmonize.scrim"
    subhead = TextLayer(id="t", role="subhead", frame=Frame(x=80, y=300, w=600, h=90),
                        content="Premium Copper Water Bottle", font_size=26)
    doc = DesignDoc(id="d", canvas=Canvas(width=1080, height=1350), layers=[scrim, subhead])

    covering = _covering_scrim(doc, subhead, Rect(80, 300, 600, 90))
    assert covering is not None, "the scrim above already covers this line"
    assert covering[0] == "#000000" and 0 < covering[1] <= 0.45


def test_a_background_prompt_asks_for_a_setting_not_an_absence():
    """"empty scene, no objects" is what an image model was given, and a flat wall with a
    gradient on it is what it returned."""
    from app.templates_corpus import dsl

    grounds = [dsl.BG_EMPTY, dsl.BG_EMPTY_TOP, dsl.BG_EMPTY_BOTTOM, dsl.BG_TEXTURE]
    for prompt in grounds:
        assert "no objects" not in prompt, prompt
        assert "empty scene" not in prompt, prompt
        # But the subject must still be kept out of it, or the design ships two.
        assert "no product" in prompt, prompt
