"""The design rules that make a scratch page look designed rather than typed.

These are the invariants the quality work depends on, and each one is a failure that
actually reached a rendered page: a palette with no accent in it, an accent handed to
every line at once, a roundel stamped over the headline, a spaced-out sub-line wide
enough to wrap and drag the page off its bottom margin.
"""

from app.adapters.openai_adapters import _FLEX_TARGET_PIXELS, render_size, supports_flexible_size
from app.lido_scratch import background as bg
from app.lido_scratch import palette as pal
from app.lido_scratch.decor import Z_OVER_ALL, decorate
from app.lido_scratch.design_ai import _backfill_background_motif, _dedupe_copy
from app.lido_scratch.imagery import ensure_subject
from app.lido_scratch.layout import MARGIN, element_height, repair, visual_bottom
from app.lido_scratch.spec import DesignSpec, SpecBackground, SpecElement
from app.schema.brief import BriefCanvas, DesignBrief
from app.util.color import contrast_ratio, delta_e, relative_luminance, saturation


def _spec(elements, **kwargs) -> DesignSpec:
    kwargs.setdefault("palette", ["#12170F", "#A8E063"])
    kwargs.setdefault("background", SpecBackground(style="brush-grunge"))
    kwargs.setdefault("width", 1080)
    kwargs.setdefault("height", 1080)
    return DesignSpec(name="test", elements=elements, **kwargs)


def _text(role, text, **kwargs) -> SpecElement:
    kwargs.setdefault("x", 0.08)
    kwargs.setdefault("w", 0.84)
    return SpecElement(kind="text", role=role, text=text, **kwargs)


# --------------------------------------------------------------------------------
# palette
# --------------------------------------------------------------------------------

def test_refine_manufactures_a_ground_and_an_accent_from_a_flat_palette():
    colors = pal.refine(["#8A8A7A", "#9A9A88", "#A0A090"], "fresh salad menu")
    assert relative_luminance(colors[0]) <= pal.GROUND_MAX_LUMINANCE
    assert saturation(pal.accent_of(colors)) >= pal.ACCENT_MIN_SATURATION
    assert contrast_ratio(colors[0], pal.tint_of(colors)) >= 7.0


def test_refine_is_idempotent():
    once = pal.refine(["#12170F", "#A8E063", "#4B8A2B"], "food")
    assert pal.refine(once, "food") == once


def test_refine_keeps_a_palette_that_was_already_right():
    colors = pal.refine(["#12170F", "#A8E063", "#4B8A2B"], "food")
    assert colors[0] == "#12170F"
    assert pal.accent_of(colors) == "#A8E063"


def test_band_registers_against_its_own_ground():
    for ground in ("#12170F", "#0A0E1A", "#F5F5F0"):
        band = pal.band_of(pal.refine([ground], ""))
        assert contrast_ratio(ground, band) > 1.3


# --------------------------------------------------------------------------------
# colour assignment
# --------------------------------------------------------------------------------

def test_the_accent_goes_to_exactly_one_element():
    spec = _spec([
        _text("brand", "Fresh Fork", size="caption", y=0.06),
        _text("headline", "Food Menu", size="display", y=0.30),
        _text("subhead", "Super Delicious", size="heading", y=0.50),
        _text("tagline", "This weekend", size="caption", y=0.62),
    ])
    repair(spec)
    accent = pal.accent_of(spec.palette)
    wearing = [e for e in spec.elements if e.kind == "text" and e.color == accent]
    assert len(wearing) == 1
    assert wearing[0].role == "headline"


def test_auto_assigned_text_clears_the_small_text_contrast_bar_whatever_its_size():
    spec = _spec([_text("headline", "Food Menu", size="display", y=0.3)])
    repair(spec)
    headline = spec.elements[0]
    assert contrast_ratio(spec.background.color, headline.color) >= 4.5


# --------------------------------------------------------------------------------
# typography
# --------------------------------------------------------------------------------

def test_roles_take_their_typographic_conventions():
    spec = _spec([_text("tagline", "For this weekend only", size="caption", y=0.3)])
    repair(spec)
    tagline = spec.elements[0]
    assert tagline.tracking == "ultra"
    assert tagline.transform == "uppercase"


def test_ultra_tracking_is_refused_to_display_type_and_to_long_lines():
    spec = _spec([
        _text("headline", "Food Menu", size="display", y=0.2, tracking="ultra"),
        _text("tagline", "A line far too long to space out this wide", size="caption",
              y=0.5, tracking="ultra"),
        _text("label", "Weekend only", size="caption", y=0.7, tracking="ultra"),
    ])
    repair(spec)
    by_role = {e.role: e for e in spec.elements if e.kind == "text"}
    assert by_role["headline"].tracking == "wide"
    assert by_role["tagline"].tracking == "wide"
    assert by_role["label"].tracking == "ultra"  # short enough to keep the effect


def test_an_explicit_choice_survives_the_role_defaults():
    spec = _spec([_text("cta", "Order now", size="body", y=0.3, tracking="tight")])
    repair(spec)
    assert spec.elements[0].tracking == "tight"


# --------------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------------

def test_a_page_placed_past_the_bottom_edge_is_compacted_back_inside_it():
    spec = _spec([
        _text("headline", "Special Deals", size="display", y=0.55),
        _text("subhead", "Weekend only", size="heading", y=0.75),
        _text("body", "Two for one on every burger, all weekend.", size="body", y=0.88),
        _text("phone", "+1 111 222 333", size="caption", y=0.96),
    ])
    layout = repair(spec)
    bottom = max(e.y + element_height(e, spec, layout.font_scale)
                 for e in spec.elements if e.kind == "text")
    assert bottom <= 1 - MARGIN + 1e-6


def test_the_offer_stays_stamped_on_the_photo_it_overlaps():
    spec = _spec([
        SpecElement(kind="photo", cutout=True, image_prompt="a burger",
                    x=0.15, y=0.10, w=0.70, h=0.35),
        _text("offer", "Save 50%", size="body", x=0.20, y=0.30, w=0.30),
        _text("headline", "Food Menu", size="display", y=0.60),
    ])
    repair(spec)
    offer = next(e for e in spec.elements if e.role == "offer")
    photo = next(e for e in spec.elements if e.kind == "photo")
    assert offer.y < photo.y + (photo.h or 0)  # a roundel on the hero is the design


def test_the_offer_gives_way_to_text_it_would_otherwise_cover():
    """The failure this rules out: an offer the layout could not move ends up printed
    across the call to action, and the pill is built underneath both of them."""
    spec = _spec([
        _text("offer", "Free for the first 100", size="body", x=0.10, y=0.52, w=0.40),
        _text("cta", "Book a table", size="body", x=0.10, y=0.50, w=0.40),
    ])
    layout = repair(spec)
    by_role = {e.role: e for e in spec.elements if e.kind == "text"}
    cta_bottom = by_role["cta"].y + element_height(by_role["cta"], spec,
                                                   layout.font_scale)
    assert by_role["offer"].y >= cta_bottom


# --------------------------------------------------------------------------------
# ornament
# --------------------------------------------------------------------------------

def test_the_roundel_is_skipped_when_it_would_sit_on_another_line():
    spec = _spec([
        _text("offer", "2 for 1", size="body", x=0.08, y=0.40, w=0.30),
        _text("subhead", "Weekend only", size="heading", x=0.08, y=0.44, w=0.50),
    ])
    layout = repair(spec)
    decorate(spec, layout.font_scale)
    assert "badge-ring" not in spec.decor


def test_the_roundel_is_drawn_when_it_has_room():
    spec = _spec([
        _text("offer", "Save 50%", size="body", x=0.62, y=0.12, w=0.28, align="center"),
        _text("headline", "Food Menu", size="display", x=0.08, y=0.60, w=0.84),
    ])
    layout = repair(spec)
    decorate(spec, layout.font_scale)
    assert "badge-ring" in spec.decor
    offer = next(e for e in spec.elements if e.role == "offer")
    # By z, not by "the first circle": the dot matrix is made of circles too.
    disc = next(e for e in spec.elements
                if e.kind == "shape" and e.shape == "circle" and e.z == Z_OVER_ALL)
    # The offer's box is the disc's box, so the type cannot hang off the circle.
    assert abs((offer.x + offer.w / 2) - (disc.x + disc.w / 2)) < 1e-6


def test_stacked_contact_lines_share_one_left_edge():
    spec = _spec([
        _text("headline", "Food Menu", size="display", y=0.30),
        _text("phone", "+1 111 222 333", size="micro", x=0.08, y=0.84, w=0.40),
        _text("website", "www.yourweb.com", size="micro", x=0.27, y=0.91, w=0.40),
    ])
    layout = repair(spec)
    decorate(spec, layout.font_scale)
    rows = [e for e in spec.elements if e.role in ("phone", "website")]
    assert len({round(e.x, 6) for e in rows}) == 1


def test_the_same_spec_always_compiles_to_the_same_ornament_order():
    """Layer order must not depend on string hash randomisation: two processes
    compiling one spec have to produce the same document."""
    def order():
        spec = _spec([
            _text("headline", "Food Menu", size="display", y=0.30),
            _text("cta", "Order now", size="body", y=0.60),
            _text("phone", "+1 111 222 333", size="micro", x=0.08, y=0.84, w=0.40),
            _text("website", "www.yourweb.com", size="micro", x=0.08, y=0.90, w=0.40),
        ])
        layout = repair(spec)
        decorate(spec, layout.font_scale)
        return [(e.kind, e.shape, e.z) for e in spec.elements if e.kind == "shape"]

    assert order() == order()


def test_decor_reports_only_what_it_actually_drew():
    spec = _spec([_text("headline", "Food Menu", size="display", y=0.30)],
                 decor=["cta-pill", "badge-ring", "accent-underline"])
    layout = repair(spec)
    decorate(spec, layout.font_scale)
    # There is no CTA and no offer on this page, so neither mark exists.
    assert spec.decor == ["accent-underline"]


# --------------------------------------------------------------------------------
# background
# --------------------------------------------------------------------------------

def test_every_style_in_the_menu_builds_a_prompt_or_is_the_flat_ground():
    colors = pal.refine(["#12170F", "#A8E063"], "food")
    for style in bg.RECIPES:
        prompt = bg.build_prompt(style, colors, motif="a salad", safe_zone="left")
        if style == "flat":
            assert prompt is None
            continue
        assert prompt and "#" in prompt          # the palette reached the prompt
        assert "left third" in prompt            # so did the safe zone
        assert "no text" not in prompt.lower()   # that belongs in the negative prompt
        assert "text" in bg.negative_prompt(style)


def test_a_graphic_ground_never_draws_the_subject_but_a_photograph_does():
    colors = pal.refine(["#12170F", "#A8E063"], "food")
    graphic = bg.build_prompt("brush-grunge", colors, motif="a burger")
    photo = bg.build_prompt("photo-scene", colors, motif="a diner counter")
    assert "never draw it literally" in graphic
    assert "a diner counter" in photo
    assert bg.is_photographic("photo-scene") and not bg.is_photographic("brush-grunge")


def test_only_a_photographic_ground_costs_the_page_a_scrim():
    def scrims(style):
        spec = _spec([_text("headline", "Food Menu", size="display", y=0.3)],
                     background=SpecBackground(style=style))
        repair(spec)
        return [e for e in spec.elements if e.kind == "shape" and e.behind]

    assert scrims("photo-scene")
    assert not scrims("brush-grunge")


# --------------------------------------------------------------------------------
# saying it once
# --------------------------------------------------------------------------------

def test_a_line_wholly_contained_in_another_is_dropped():
    """The real page this comes from carried the same promotion three times: a
    tagline, a subhead and an offer all saying 'the first 100 customers'."""
    spec = _spec([
        _text("headline", "Grand Opening!", size="display"),
        _text("tagline", "First 100 customers", size="body"),
        _text("subhead", "Doors open Saturday at nine", size="heading"),
        _text("offer", "Free for the first 100 customers!", size="body"),
        _text("cta", "See you there", size="body"),
    ])
    _dedupe_copy(spec)
    said = [(e.text or "").lower() for e in spec.elements if e.kind == "text"]
    assert "first 100 customers" not in said
    assert "free for the first 100 customers!" in said
    assert "doors open saturday at nine" in said


def test_an_exact_repeat_keeps_the_line_that_reads_first():
    spec = _spec([
        _text("headline", "Grand Opening!", size="display"),
        _text("subhead", "Doors open Saturday", size="heading"),
        _text("body", "Cake, coffee and a free tote for everyone", size="body"),
        _text("label", "Doors open Saturday", size="caption"),
    ])
    _dedupe_copy(spec)
    roles = [e.role for e in spec.elements if e.kind == "text"]
    assert roles == ["headline", "subhead", "body"]


def test_contact_lines_are_never_deduped_against_each_other():
    spec = _spec([
        _text("headline", "Grand Opening!", size="display"),
        _text("subhead", "Doors open Saturday", size="heading"),
        _text("website", "cafe.example.com", size="caption"),
        _text("email", "hello cafe.example.com", size="caption"),
    ])
    _dedupe_copy(spec)
    assert len([e for e in spec.elements if e.kind == "text"]) == 4


def test_dedupe_never_strips_a_page_below_a_design():
    spec = _spec([
        _text("headline", "Grand Opening", size="display"),
        _text("tagline", "Grand Opening", size="body"),
        _text("subhead", "Grand Opening", size="heading"),
    ])
    _dedupe_copy(spec)
    assert len([e for e in spec.elements if e.kind == "text"]) == 3


# --------------------------------------------------------------------------------
# filling the frame
# --------------------------------------------------------------------------------

def test_a_top_heavy_page_is_spread_down_the_canvas():
    """Collision resolution only pushes elements down far enough to stop overlapping,
    so a model that stacked everything at the top got a page with a third of the
    canvas dead below it."""
    spec = _spec([
        _text("headline", "Grand Opening", size="display", y=0.08),
        _text("subhead", "Doors open Saturday at nine", size="heading", y=0.24),
        _text("cta", "Book a table", size="body", y=0.40),
    ])
    layout = repair(spec)
    bottom = max(e.y + element_height(e, spec, layout.font_scale)
                 for e in spec.elements if e.kind == "text")
    assert bottom > 0.6
    assert bottom <= 1 - MARGIN + 1e-6


def test_balancing_keeps_a_tight_group_tight():
    spec = _spec([
        _text("headline", "Grand Opening", size="display", y=0.10),
        _text("subhead", "Doors open Saturday", size="heading", y=0.22),
        _text("cta", "Book a table", size="body", y=0.60),
    ])
    layout = repair(spec)
    by_role = {e.role: e for e in spec.elements if e.kind == "text"}
    gap = by_role["subhead"].y - (
        by_role["headline"].y + element_height(by_role["headline"], spec,
                                                layout.font_scale))
    assert gap < 0.045  # the pair stays a pair; only the gap before the CTA opens up


def test_a_full_page_is_left_alone():
    spec = _spec([
        _text("headline", "Grand Opening", size="display", y=0.08),
        _text("body", "Doors open Saturday at nine, with cake for everyone who "
                      "turns up early and a free tote for the first hundred.",
              size="body", y=0.40),
        _text("phone", "+1 111 222 333", size="caption", y=0.80),
    ])
    before = [e.y for e in spec.elements]
    repair(spec)
    after = [e.y for e in spec.elements if e.kind == "text"]
    assert after[0] >= before[0]


# --------------------------------------------------------------------------------
# the call to action
# --------------------------------------------------------------------------------

def test_the_pill_is_wider_than_its_own_text():
    spec = _spec([
        _text("headline", "Food Menu", size="display", y=0.10),
        _text("cta", "Order Now", size="body", x=0.08, y=0.60, w=0.40),
    ])
    layout = repair(spec)
    decorate(spec, layout.font_scale)
    assert "cta-pill" in spec.decor
    cta = next(e for e in spec.elements if e.role == "cta")
    pill = next(e for e in spec.elements
                if e.kind == "shape" and e.shape == "rect" and e.z == Z_OVER_ALL)
    assert pill.y < cta.y
    assert pill.y + (pill.h or 0) > cta.y + element_height(cta, spec, layout.font_scale)


def test_no_pill_is_ever_drawn_across_another_line():
    """The rendered failure: an offer, a CTA and a sub-line the model placed within a
    hair of each other came back as three sentences printed across one button."""
    spec = _spec([
        _text("headline", "Grand Opening!", size="display", y=0.10),
        _text("tagline", "Doors open at nine", size="body", y=0.49),
        _text("cta", "Book a table", size="body", x=0.08, y=0.50, w=0.40),
        _text("offer", "Half price", size="body", x=0.10, y=0.51, w=0.30),
    ])
    layout = repair(spec)
    decorate(spec, layout.font_scale)

    cta = next(e for e in spec.elements if e.role == "cta")
    others = [e for e in spec.elements
              if e.kind == "text" and e is not cta and (e.text or "").strip()]
    pills = [e for e in spec.elements
             if e.kind == "shape" and e.z == Z_OVER_ALL]
    for pill in pills:
        for other in others:
            height = element_height(other, spec, layout.font_scale)
            overlaps = (pill.x < other.x + other.w
                        and other.x < pill.x + pill.w
                        and pill.y < other.y + height
                        and other.y < pill.y + (pill.h or 0))
            assert not overlaps, f"{pill.shape} drawn over the {other.role} line"


# --------------------------------------------------------------------------------
# render size
# --------------------------------------------------------------------------------

def test_a_flexible_model_renders_at_the_canvas_aspect_ratio():
    for width, height in ((1080, 1080), (1080, 1350), (1500, 500)):
        render_w, render_h = render_size("gpt-image-2", width, height)
        assert render_w % 16 == 0 and render_h % 16 == 0
        # Within a few percent of the canvas ratio, so `fit_to_canvas` only rescales
        # and never crops away the safe zone the background prompt just asked for.
        assert abs((render_w / render_h) / (width / height) - 1) < 0.04


def test_a_fixed_size_model_still_gets_a_supported_size():
    assert not supports_flexible_size("gpt-image-1")
    assert render_size("gpt-image-1", 1080, 1350) in (
        (1024, 1024), (1024, 1536), (1536, 1024))


def test_every_flexible_render_meets_the_providers_pixel_budget():
    """The API refuses a request below a minimum pixel *budget* — 768x768 is rejected
    where 960x704 is accepted — so an edge-based clamp is not enough."""
    for width, height in ((1080, 1080), (1080, 1350), (1500, 500), (709, 337),
                          (400, 400), (3000, 300), (300, 3000)):
        render_w, render_h = render_size("gpt-image-2", width, height)
        assert render_w % 16 == 0 and render_h % 16 == 0
        assert render_w * render_h >= _FLEX_TARGET_PIXELS * 0.97
        # "The maximum supported aspect ratio is 3:1" — past it the request is
        # refused, and the provider's own fallback comes back square.
        assert max(render_w / render_h, render_h / render_w) <= 3.0 + 1e-9


# --------------------------------------------------------------------------------
# a ground that belongs to the brief
# --------------------------------------------------------------------------------

def _brief(subject: str) -> DesignBrief:
    return DesignBrief(kind="poster", canvas=BriefCanvas(width=1080, height=1350),
                       subject_description=subject)


def test_a_motif_restating_the_style_is_replaced_by_the_subject():
    spec = _spec([_text("headline", "Grand Opening!", size="display")])
    spec.background = SpecBackground(style="brush-grunge",
                                     motif="a warm abstract brush texture")
    _backfill_background_motif(spec, _brief("the opening of a neighbourhood restaurant"))
    assert spec.background.motif == "the opening of a neighbourhood restaurant"


def test_a_real_motif_is_left_alone():
    spec = _spec([_text("headline", "Food Menu", size="display")])
    spec.background = SpecBackground(style="brush-grunge", motif="a loaded cheeseburger")
    _backfill_background_motif(spec, _brief("a burger restaurant"))
    assert spec.background.motif == "a loaded cheeseburger"


def test_an_empty_motif_takes_the_briefs_subject():
    spec = _spec([_text("headline", "Food Menu", size="display")])
    spec.background = SpecBackground(style="halftone-pop")
    _backfill_background_motif(spec, _brief("a burger restaurant"))
    assert spec.background.motif == "a burger restaurant"


# --------------------------------------------------------------------------------
# the accent belongs to one element
# --------------------------------------------------------------------------------

def test_a_second_line_written_in_the_accent_is_recoloured():
    """The accent is also the colour the background is painted with, so a second line
    set in it passes every contrast check and still vanishes into the brush stroke."""
    accent = pal.accent_of(["#3F2B20", "#E69F6D", "#8A5B3E"])
    spec = _spec([
        _text("headline", "Grand Opening!", size="display", y=0.10),
        _text("offer", "Free for the first 100", size="body", y=0.40, color=accent),
    ], palette=["#3F2B20", "#E69F6D", "#8A5B3E"])
    repair(spec)
    offer = next(e for e in spec.elements if e.role == "offer")
    wearers = [e for e in spec.elements
               if e.kind == "text" and e.color
               and delta_e(e.color, pal.accent_of(spec.palette)) < 12.0]
    assert offer.color != pal.accent_of(spec.palette)
    assert len(wearers) <= 1


def test_the_contact_band_keeps_its_icon_chips():
    spec = _spec([
        _text("headline", "Grand Opening!", size="display", y=0.10),
        _text("phone", "+1 555 0110", size="caption", x=0.055, y=0.86, w=0.40),
        _text("website", "coppertable.example", size="caption", x=0.055, y=0.92, w=0.40),
    ])
    layout = repair(spec)
    decorate(spec, layout.font_scale)
    assert "contact-bar" in spec.decor
    chips = [e for e in spec.elements
             if e.kind == "shape" and e.shape == "circle" and e.z == Z_OVER_ALL]
    assert len(chips) == 2
    assert all(chip.x > 0 for chip in chips)


# --------------------------------------------------------------------------------
# imagery yields to copy that would otherwise fall off the page
# --------------------------------------------------------------------------------

def test_a_tall_photo_gives_back_room_rather_than_pushing_copy_off_the_canvas():
    """A real run put a 0.6-tall photo above eight text elements and the last three
    landed past y=1.0 — off the bottom of the canvas entirely."""
    spec = _spec([
        SpecElement(kind="photo", image_prompt="a restaurant interior",
                    x=0.0, y=0.055, w=1.0, h=0.60),
        _text("headline", "Grand Opening!", size="display", y=0.67),
        _text("subhead", "Experience fine dining at its best.", size="heading", y=0.80),
        _text("offer", "Free for the first 100 customers", size="body", y=0.90),
        _text("cta", "Reserve a table", size="body", y=0.94),
        _text("brand", "The Copper Table", size="heading", y=0.97),
        _text("phone", "+1 555 0110", size="caption", y=0.99),
    ], height=1350)
    layout = repair(spec)
    photo = next(e for e in spec.elements if e.kind == "photo")
    assert photo.h < 0.60
    bottom = max(e.y + element_height(e, spec, layout.font_scale)
                 for e in spec.elements if e.kind == "text")
    assert bottom <= 1 - MARGIN + 1e-6


def test_a_page_that_fits_never_shrinks_its_photo():
    spec = _spec([
        SpecElement(kind="photo", image_prompt="a burger", x=0.0, y=0.05, w=1.0, h=0.45),
        _text("headline", "Food Menu", size="display", y=0.55),
    ])
    repair(spec)
    assert next(e for e in spec.elements if e.kind == "photo").h == 0.45


# --------------------------------------------------------------------------------
# the design shows its subject
# --------------------------------------------------------------------------------

def test_a_type_only_page_gets_the_briefs_subject():
    spec = _spec([
        _text("headline", "Grand Opening!", size="display", y=0.08),
        _text("phone", "+1 555 0110", size="caption", y=0.88),
    ])
    assert ensure_subject(spec, _brief("a cozy restaurant interior"))
    layout = repair(spec)
    photo = next(e for e in spec.elements if e.kind == "photo")
    assert photo.cutout
    assert "cozy restaurant interior" in (photo.image_prompt or "")
    # And the page it landed in still fits.
    bottom = max(e.y + element_height(e, spec, layout.font_scale)
                 for e in spec.elements if e.kind == "text")
    assert bottom <= 1 - MARGIN + 1e-6


def test_the_subject_sits_below_the_headline_and_above_the_rest():
    spec = _spec([
        _text("headline", "Grand Opening!", size="display", y=0.08),
        _text("cta", "Reserve a table", size="body", y=0.50),
        _text("phone", "+1 555 0110", size="caption", y=0.88),
    ])
    ensure_subject(spec, _brief("a cozy restaurant interior"))
    repair(spec)
    photo = next(e for e in spec.elements if e.kind == "photo")
    by_role = {e.role: e for e in spec.elements if e.kind == "text"}
    assert by_role["headline"].y < photo.y
    assert by_role["cta"].y > photo.y


def test_a_page_that_already_shows_something_is_left_alone():
    spec = _spec([
        SpecElement(kind="photo", image_prompt="a burger", x=0.1, y=0.1, w=0.8, h=0.4),
        _text("headline", "Food Menu", size="display", y=0.60),
    ])
    assert not ensure_subject(spec, _brief("a burger"))
    assert len([e for e in spec.elements if e.kind == "photo"]) == 1


def test_no_subject_is_invented_when_the_brief_names_none():
    spec = _spec([_text("headline", "Grand Opening!", size="display", y=0.08)])
    assert not ensure_subject(spec, DesignBrief(
        kind="poster", canvas=BriefCanvas(width=1080, height=1350)))
    assert not [e for e in spec.elements if e.kind == "photo"]


def test_a_long_offer_gives_way_to_the_hero_image_it_will_never_stamp():
    """The exemption that lets a roundel sit on the hero is for offers that get a
    roundel. A long one gets none, and then it is just type across the subject's face."""
    spec = _spec([
        _text("headline", "Grand Opening!", size="display", y=0.06),
        _text("offer", "Free for the first 100 customers", size="body",
              x=0.10, y=0.30, w=0.60),
        SpecElement(kind="photo", cutout=True, image_prompt="a waiter",
                    x=0.30, y=0.28, w=0.50, h=0.30),
    ], height=1350)
    repair(spec)
    offer = next(e for e in spec.elements if e.role == "offer")
    photo = next(e for e in spec.elements if e.kind == "photo")
    assert offer.y >= photo.y + (photo.h or 0)


def test_a_short_offer_still_stamps_the_hero_image():
    spec = _spec([
        _text("headline", "Food Menu", size="display", y=0.06),
        _text("offer", "Save 50%", size="body", x=0.20, y=0.30, w=0.25),
        SpecElement(kind="photo", cutout=True, image_prompt="a burger",
                    x=0.15, y=0.28, w=0.60, h=0.30),
    ], height=1350)
    repair(spec)
    offer = next(e for e in spec.elements if e.role == "offer")
    photo = next(e for e in spec.elements if e.kind == "photo")
    assert offer.y < photo.y + (photo.h or 0)


# --------------------------------------------------------------------------------
# marks drawn against the type
# --------------------------------------------------------------------------------

def test_display_type_reports_more_ink_than_layout_box():
    """Display type is set at 0.94 leading, so its layout box ends above its own
    descenders. A rule hung off that box is drawn through the headline."""
    spec = _spec([_text("headline", "Grand Opening!", size="display", y=0.10)])
    headline = spec.elements[0]
    box_bottom = headline.y + element_height(headline, spec, 1.0)
    assert visual_bottom(headline, spec, 1.0) > box_bottom


def test_the_accent_rule_clears_the_headline_it_underlines():
    spec = _spec([
        _text("headline", "Grand Opening!", size="display", y=0.10),
        _text("cta", "Reserve a table", size="body", y=0.70),
    ], decor=["accent-underline"])
    layout = repair(spec)
    decorate(spec, layout.font_scale)
    assert "accent-underline" in spec.decor
    headline = next(e for e in spec.elements if e.role == "headline")
    rule = next(e for e in spec.elements
                if e.kind == "shape" and e.shape == "rect" and e.z == 2)
    assert rule.y >= visual_bottom(headline, spec, layout.font_scale)


def test_the_safe_zone_keeps_the_accent_out_of_the_type_area():
    prompt = bg.build_prompt("brush-grunge", ["#2E1D0B", "#F2C27E", "#A66E46"],
                             motif="a restaurant opening", safe_zone="top")
    assert "no accent colour at all may enter that area" in prompt
