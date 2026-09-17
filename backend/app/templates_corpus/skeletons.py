"""The template skeleton corpus — IMPLEMENTATION_PLAN §1.2.

§1.2 asks for 150-300 skeletons for v1 (20+ per kind, 2-4 variants each), hand-designed
and designer-reviewed at three copy lengths. This file is a **foundation corpus**, not
that target: it covers every `kind` with several distinct layout archetypes and variants
so the retrieval, composition and solving machinery is exercised across real layout
variety. Growing it to the v1 target is design work, not engineering work, and is the
single highest-leverage way to improve output quality.

Every skeleton here is checked by `validate_corpus()` for: schema validity, slots inside
the canvas, no overlap between required non-background slots, and sane autofit bounds.
"""

from __future__ import annotations

from app.schema.template import SkeletonVariant, TemplateSkeleton
from app.templates_corpus.dsl import (
    BG_EMPTY,
    BG_EMPTY_BOTTOM,
    BG_EMPTY_TOP,
    BG_TEXTURE,
    PROP_ACCENT,
    PROP_BOTANICAL,
    PROP_FOLIAGE,
    SUBJECT,
    SUBJECT_ANGLED,
    SUBJECT_DETAIL,
    SUBJECT_FRONT,
    SUBJECT_SIDE,
    con,
    image,
    ornament,
    prop,
    shadow,
    shape,
    text,
)
from app.templates_corpus.skeletons_rich import RICH_SKELETONS

# --------------------------------------------------------------------------------------
# Stories — 9:16
# --------------------------------------------------------------------------------------

STORY_HERO = TemplateSkeleton(
    id="tpl_story_hero_01",
    name="Story — product hero",
    kind="story", aspect="9:16",
    tags=["product", "bold", "high-contrast", "subject"],
    description=(
        "Full-bleed product hero for stories. Huge two-line display headline top-left, "
        "product photographed large in the lower half, pill CTA at the bottom. Best for "
        "a single physical product, confident brands and high contrast."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY_TOP,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0.5, w=1, h=0.5, scrim=True, scrim_angle=180,
              palette="primary", required=False, z=3,
              constraints=con("stretch", "bottom", priority=20, optional=True)),
        image("subject", "subject", x=0.08, y=0.44, w=0.84, h=0.36, prompt=SUBJECT,
              transparent=True, fit="contain", z=6, effects=[shadow(0.014, 0.026, 0.34)],
              constraints=con("center", "middle", lock=True, priority=95)),
        text("headline", "headline", x=0.066, y=0.10, w=0.72, h=0.22, size_n=0.077,
             weight=900, max_chars=26, transform="uppercase", line_height=0.98,
             tracking_n=-0.0022, palette="on-primary", z=10),
        text("subhead", "subhead", x=0.066, y=0.335, w=0.62, h=0.07, size_n=0.024,
             weight=400, max_chars=90, line_height=1.3, palette="on-primary",
             required=False, z=10),
        shape("cta_bg", "cta", x=0.066, y=0.865, w=0.39, h=0.056, radius_n=0.5,
              palette="accent", required=False, z=8),
        text("cta", "cta", x=0.066, y=0.865, w=0.39, h=0.056, size_n=0.023, weight=700,
             max_chars=18, align="center", valign="middle", palette="on-accent",
             required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="right", name="Subject right, copy left", patch={
            "subject": {"frameN": {"x": 0.30, "y": 0.42, "w": 0.74, "h": 0.38}},
        }),
        SkeletonVariant(id="low", name="Subject bleeds off the bottom", patch={
            "subject": {"frameN": {"x": 0.05, "y": 0.60, "w": 0.90, "h": 0.42}},
            "headline": {"frameN": {"x": 0.066, "y": 0.12, "w": 0.80, "h": 0.26}},
        }),
    ],
)

STORY_SPLIT = TemplateSkeleton(
    id="tpl_story_split_01",
    name="Story — half image, half colour",
    kind="story", aspect="9:16",
    tags=["editorial", "clean", "minimal", "subject"],
    description=(
        "Story split horizontally: photograph fills the top 55 percent, a solid colour "
        "block below carries a stacked headline, supporting paragraph and CTA. Calm and "
        "readable. Best for announcements, editorial content and longer copy."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        image("bg", "background", x=0, y=0, w=1, h=0.55, prompt=BG_EMPTY,
              constraints=con("stretch", "top", priority=90), z=1),
        text("headline", "headline", x=0.075, y=0.615, w=0.85, h=0.15, size_n=0.055,
             weight=800, max_chars=48, line_height=1.03, tracking_n=-0.0012,
             palette="on-primary", z=10),
        text("body", "body", x=0.075, y=0.785, w=0.80, h=0.10, size_n=0.020,
             weight=400, max_chars=190, line_height=1.45, palette="on-primary",
             required=False, z=10),
        shape("rule", "decoration", x=0.075, y=0.585, w=0.13, h=0.004, palette="accent",
              required=False, z=9),
        text("cta", "cta", x=0.075, y=0.915, w=0.5, h=0.035, size_n=0.021, weight=700,
             max_chars=24, transform="uppercase", tracking_n=0.0012, palette="accent",
             required=False, z=10),
    ],
    variants=[
        SkeletonVariant(id="flip", name="Image below, copy above", patch={
            "bg": {"frameN": {"x": 0, "y": 0.45, "w": 1, "h": 0.55}},
            "headline": {"frameN": {"x": 0.075, "y": 0.12, "w": 0.85, "h": 0.15}},
            "body": {"frameN": {"x": 0.075, "y": 0.29, "w": 0.80, "h": 0.10}},
            "rule": {"frameN": {"x": 0.075, "y": 0.09, "w": 0.13, "h": 0.004}},
            "cta": {"frameN": {"x": 0.075, "y": 0.40, "w": 0.5, "h": 0.035}},
        }),
    ],
)

STORY_CENTER = TemplateSkeleton(
    id="tpl_story_center_01",
    name="Story — centred subject",
    kind="story", aspect="9:16",
    tags=["premium", "minimal", "centered", "subject"],
    description=(
        "Symmetrical story. Small eyebrow label, centred headline, product floating in "
        "the middle, short supporting line and a centred CTA. Restrained and premium. "
        "Best for luxury goods, fragrance, skincare and single-item launches."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_TEXTURE,
              constraints=con("stretch", "stretch", priority=100), z=0),
        text("eyebrow", "caption", x=0.15, y=0.095, w=0.7, h=0.028, size_n=0.0145,
             weight=600, max_chars=28, align="center", transform="uppercase",
             tracking_n=0.0035, palette="accent", required=False, z=10),
        text("headline", "headline", x=0.10, y=0.135, w=0.80, h=0.145, size_n=0.052,
             weight=400, max_chars=42, align="center", line_height=1.08,
             palette="on-primary", z=10),
        image("subject", "subject", x=0.16, y=0.33, w=0.68, h=0.34, prompt=SUBJECT_FRONT,
              transparent=True, fit="contain", z=6, effects=[shadow(0.012, 0.03, 0.28)],
              constraints=con("center", "middle", lock=True, priority=95)),
        text("subhead", "subhead", x=0.16, y=0.715, w=0.68, h=0.075, size_n=0.021,
             weight=400, max_chars=120, align="center", line_height=1.45,
             palette="on-primary", required=False, z=10),
        shape("cta_bg", "cta", x=0.305, y=0.845, w=0.39, h=0.052, radius_n=0.5,
              palette="accent", required=False, z=8),
        text("cta", "cta", x=0.305, y=0.845, w=0.39, h=0.052, size_n=0.021, weight=700,
             max_chars=18, align="center", valign="middle", palette="on-accent",
             required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="tall", name="Taller subject, tighter copy", patch={
            "subject": {"frameN": {"x": 0.12, "y": 0.30, "w": 0.76, "h": 0.42}},
            "subhead": {"frameN": {"x": 0.16, "y": 0.755, "w": 0.68, "h": 0.06}},
        }),
    ],
)

STORY_TYPE = TemplateSkeleton(
    id="tpl_story_type_01",
    name="Story — type only",
    kind="story", aspect="9:16",
    tags=["text-only", "bold", "typographic", "high-contrast"],
    description=(
        "Pure typography story with no photograph: an oversized statement headline "
        "filling most of the frame over a flat or textured colour field, with a small "
        "supporting line and CTA. Best for quotes, announcements, hot takes and any "
        "brief with no physical subject."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("accent_block", "decoration", x=0.0, y=0.0, w=0.42, h=0.22,
              palette="accent", required=False, z=2,
              constraints=con("left", "top", priority=25, optional=True)),
        text("headline", "headline", x=0.075, y=0.235, w=0.85, h=0.40, size_n=0.095,
             weight=900, max_chars=60, transform="uppercase", line_height=0.94,
             tracking_n=-0.0028, palette="on-primary", z=10),
        text("subhead", "subhead", x=0.075, y=0.675, w=0.72, h=0.09, size_n=0.024,
             weight=400, max_chars=140, line_height=1.4, palette="on-primary",
             required=False, z=10),
        text("cta", "cta", x=0.075, y=0.90, w=0.6, h=0.035, size_n=0.021, weight=700,
             max_chars=26, transform="uppercase", tracking_n=0.0014, palette="accent",
             required=False, z=10),
    ],
    variants=[
        SkeletonVariant(id="centered", name="Centred", patch={
            "headline": {"text": {"align": "center"}, "frameN": {"x": 0.08, "y": 0.27,
                                                                 "w": 0.84, "h": 0.38}},
            "subhead": {"text": {"align": "center"}, "frameN": {"x": 0.12, "y": 0.68,
                                                                "w": 0.76, "h": 0.09}},
        }),
    ],
)

# --------------------------------------------------------------------------------------
# Posts — 4:5
# --------------------------------------------------------------------------------------

POST_PRODUCT = TemplateSkeleton(
    id="tpl_post_product_01",
    name="Post — product card",
    kind="post", aspect="4:5",
    tags=["product", "clean", "commerce", "subject"],
    description=(
        "Feed post built like a product card. Headline across the top, product centred "
        "and large, price or CTA strip along the bottom. Best for e-commerce drops, "
        "single SKUs and offers."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY,
              constraints=con("stretch", "stretch", priority=100), z=0),
        text("headline", "headline", x=0.075, y=0.075, w=0.72, h=0.13, size_n=0.070,
             weight=800, max_chars=32, transform="uppercase", line_height=1.0,
             tracking_n=-0.0016, palette="on-primary", z=10),
        # A colour field behind the product, so the cutout stands on something rather
        # than floating on the photograph. Optional, because on an already busy
        # background the design is better off without it.
        ornament("halo", motif="blob", x=0.150, y=0.250, w=0.700, h=0.430,
                 palette="accent", density=3, opacity=0.92, required=False, z=3),
        image("subject", "subject", x=0.13, y=0.27, w=0.74, h=0.40, prompt=SUBJECT,
              transparent=True, fit="contain", z=6, effects=[shadow(0.016, 0.032, 0.30)],
              constraints=con("center", "middle", lock=True, priority=95)),
        prop("prop", x=0.690, y=0.575, w=0.240, h=0.190, z=9, rotation=12),
        text("subhead", "subhead", x=0.075, y=0.705, w=0.60, h=0.07, size_n=0.026,
             weight=400, max_chars=100, line_height=1.4, palette="on-primary",
             required=False, z=10),
        shape("cta_bg", "cta", x=0.075, y=0.845, w=0.42, h=0.072, radius_n=0.5,
              palette="accent", required=False, z=8),
        text("cta", "cta", x=0.075, y=0.845, w=0.42, h=0.072, size_n=0.028, weight=700,
             max_chars=18, align="center", valign="middle", palette="on-accent",
             required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="offset", name="Subject offset right", patch={
            "subject": {"frameN": {"x": 0.26, "y": 0.26, "w": 0.76, "h": 0.42}},
            "headline": {"frameN": {"x": 0.075, "y": 0.07, "w": 0.60, "h": 0.15}},
        }),
    ],
)

POST_EDITORIAL = TemplateSkeleton(
    id="tpl_post_editorial_01",
    name="Post — editorial",
    kind="post", aspect="4:5",
    tags=["editorial", "minimal", "magazine", "subject"],
    description=(
        "Editorial feed post: photograph occupies the upper two thirds, a rule separates "
        "it from a serif headline and a paragraph of body copy below. Best for articles, "
        "stories, recipes and thoughtful long-form captions."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="neutral",
              constraints=con("stretch", "stretch", priority=100), z=0),
        image("bg", "background", x=0, y=0, w=1, h=0.60, prompt=BG_EMPTY,
              constraints=con("stretch", "top", priority=90), z=1),
        shape("rule", "decoration", x=0.08, y=0.645, w=0.14, h=0.0035, palette="accent",
              required=False, z=9),
        text("headline", "headline", x=0.08, y=0.675, w=0.84, h=0.135, size_n=0.052,
             weight=700, max_chars=64, line_height=1.06, palette="on-primary", z=10),
        text("body", "body", x=0.08, y=0.835, w=0.80, h=0.085, size_n=0.021,
             weight=400, max_chars=220, line_height=1.5, palette="on-primary",
             required=False, z=10),
    ],
    variants=[
        SkeletonVariant(id="full", name="Full-bleed image with overlay copy", patch={
            "bg": {"frameN": {"x": 0, "y": 0, "w": 1, "h": 1}},
            "headline": {"frameN": {"x": 0.08, "y": 0.66, "w": 0.84, "h": 0.14}},
        }),
    ],
)

POST_TYPE = TemplateSkeleton(
    id="tpl_post_type_01",
    name="Post — statement type",
    kind="post", aspect="4:5",
    tags=["text-only", "bold", "typographic"],
    description=(
        "Typographic feed post with no image. One oversized statement set tight, a thin "
        "supporting line beneath, and an accent bar. Best for quotes, stats, hot takes "
        "and any brief with no physical subject."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("bar", "decoration", x=0.08, y=0.155, w=0.10, h=0.008, palette="accent",
              required=False, z=5),
        text("headline", "headline", x=0.08, y=0.22, w=0.84, h=0.42, size_n=0.086,
             weight=900, max_chars=80, line_height=0.98, tracking_n=-0.0022,
             palette="on-primary", z=10),
        text("subhead", "subhead", x=0.08, y=0.70, w=0.70, h=0.08, size_n=0.024,
             weight=400, max_chars=130, line_height=1.45, palette="on-primary",
             required=False, z=10),
        text("caption", "caption", x=0.08, y=0.895, w=0.6, h=0.03, size_n=0.017,
             weight=600, max_chars=32, transform="uppercase", tracking_n=0.003,
             palette="accent", required=False, z=10),
    ],
    variants=[
        SkeletonVariant(id="serif", name="Serif, centred", patch={
            "headline": {"text": {"align": "center", "weight": 400, "transform": "none"},
                         "frameN": {"x": 0.10, "y": 0.25, "w": 0.80, "h": 0.40}},
            "subhead": {"text": {"align": "center"},
                        "frameN": {"x": 0.14, "y": 0.70, "w": 0.72, "h": 0.08}},
        }),
    ],
)

POST_SQUARE_PROMO = TemplateSkeleton(
    id="tpl_post_promo_01",
    name="Post — promo burst",
    kind="post", aspect="1:1",
    tags=["promo", "sale", "bold", "high-contrast", "subject"],
    description=(
        "Square promotional post. A large offer headline sits over a colour field with "
        "the product to one side and a bold CTA. Loud and commercial. Best for sales, "
        "discounts, launches and limited offers."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY_BOTTOM,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0, w=1, h=0.62, scrim=True, scrim_angle=0,
              palette="primary", required=False, z=3,
              constraints=con("stretch", "top", priority=20, optional=True)),
        text("eyebrow", "caption", x=0.075, y=0.085, w=0.5, h=0.045, size_n=0.028,
             weight=700, max_chars=22, transform="uppercase", tracking_n=0.004,
             palette="accent", required=False, z=10),
        text("headline", "headline", x=0.075, y=0.145, w=0.66, h=0.24, size_n=0.105,
             weight=900, max_chars=28, transform="uppercase", line_height=0.94,
             tracking_n=-0.003, palette="on-primary", z=10),
        image("subject", "subject", x=0.46, y=0.46, w=0.50, h=0.40, prompt=SUBJECT,
              transparent=True, fit="contain", z=6, effects=[shadow(0.018, 0.035, 0.32)],
              constraints=con("right", "bottom", lock=True, priority=95)),
        shape("cta_bg", "cta", x=0.075, y=0.80, w=0.36, h=0.088, radius_n=0.5,
              palette="accent", required=False, z=8),
        text("cta", "cta", x=0.075, y=0.80, w=0.36, h=0.088, size_n=0.032, weight=800,
             max_chars=16, align="center", valign="middle", transform="uppercase",
             palette="on-accent", required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="left", name="Product left", patch={
            "subject": {"frameN": {"x": 0.04, "y": 0.46, "w": 0.50, "h": 0.40}},
            "headline": {"frameN": {"x": 0.32, "y": 0.145, "w": 0.62, "h": 0.24},
                         "text": {"align": "right"}},
            "eyebrow": {"frameN": {"x": 0.44, "y": 0.085, "w": 0.5, "h": 0.045},
                        "text": {"align": "right"}},
            "cta_bg": {"frameN": {"x": 0.565, "y": 0.80, "w": 0.36, "h": 0.088}},
            "cta": {"frameN": {"x": 0.565, "y": 0.80, "w": 0.36, "h": 0.088}},
        }),
    ],
)

# --------------------------------------------------------------------------------------
# Posters — A-series portrait
# --------------------------------------------------------------------------------------

POSTER_GIG = TemplateSkeleton(
    id="tpl_poster_gig_01",
    name="Poster — gig / event",
    kind="poster", aspect="1:1.414",
    tags=["event", "bold", "typographic", "print", "subject"],
    description=(
        "Event poster with a towering display headline at the top, a central image and "
        "a block of details at the foot. Designed for print at 300dpi. Best for gigs, "
        "club nights, exhibitions and film screenings."
    ),
    gridBaseline=12,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        image("bg", "background", x=0.07, y=0.30, w=0.86, h=0.38, prompt=BG_EMPTY,
              constraints=con("center", "middle", priority=70), z=2),
        text("headline", "headline", x=0.07, y=0.065, w=0.86, h=0.205, size_n=0.095,
             weight=900, max_chars=36, transform="uppercase", line_height=0.90,
             tracking_n=-0.002, palette="on-primary", z=10),
        text("subhead", "subhead", x=0.07, y=0.715, w=0.70, h=0.055, size_n=0.030,
             weight=600, max_chars=70, line_height=1.2, palette="accent",
             required=False, z=10),
        text("body", "body", x=0.07, y=0.80, w=0.80, h=0.10, size_n=0.0175,
             weight=400, max_chars=260, line_height=1.5, palette="on-primary",
             required=False, z=10),
        text("caption", "caption", x=0.07, y=0.935, w=0.6, h=0.025, size_n=0.0125,
             weight=500, max_chars=60, transform="uppercase", tracking_n=0.002,
             palette="on-primary", required=False, z=10),
    ],
    variants=[
        SkeletonVariant(id="photo-top", name="Image on top", patch={
            "bg": {"frameN": {"x": 0, "y": 0, "w": 1, "h": 0.46}},
            "headline": {"frameN": {"x": 0.07, "y": 0.50, "w": 0.86, "h": 0.20}},
            "subhead": {"frameN": {"x": 0.07, "y": 0.725, "w": 0.70, "h": 0.055}},
        }),
    ],
)

POSTER_MINIMAL = TemplateSkeleton(
    id="tpl_poster_minimal_01",
    name="Poster — minimal",
    kind="poster", aspect="1:1.414",
    tags=["minimal", "premium", "whitespace", "print", "text-only"],
    description=(
        "Minimal print poster: enormous whitespace, a small precise type block set low "
        "on the page, a hairline rule and nothing else. No photograph. Best for gallery "
        "notices, typographic prints, luxury announcements and anything understated."
    ),
    gridBaseline=12,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="neutral",
              constraints=con("stretch", "stretch", priority=100), z=0),
        text("headline", "headline", x=0.12, y=0.60, w=0.70, h=0.115, size_n=0.050,
             weight=400, max_chars=54, line_height=1.08, palette="on-primary", z=10),
        shape("rule", "decoration", x=0.12, y=0.745, w=0.20, h=0.0022, palette="accent",
              required=False, z=9),
        text("subhead", "subhead", x=0.12, y=0.775, w=0.60, h=0.05, size_n=0.019,
             weight=400, max_chars=110, line_height=1.5, palette="on-primary",
             required=False, z=10),
        text("caption", "caption", x=0.12, y=0.885, w=0.5, h=0.022, size_n=0.0125,
             weight=600, max_chars=40, transform="uppercase", tracking_n=0.0028,
             palette="accent", required=False, z=10),
    ],
    variants=[
        SkeletonVariant(id="top", name="Type block high", patch={
            "headline": {"frameN": {"x": 0.12, "y": 0.10, "w": 0.70, "h": 0.115}},
            "rule": {"frameN": {"x": 0.12, "y": 0.245, "w": 0.20, "h": 0.0022}},
            "subhead": {"frameN": {"x": 0.12, "y": 0.275, "w": 0.60, "h": 0.05}},
        }),
    ],
)

POSTER_PHOTO = TemplateSkeleton(
    id="tpl_poster_photo_01",
    name="Poster — full-bleed photo",
    kind="poster", aspect="1:1.414",
    tags=["photographic", "cinematic", "print", "high-contrast"],
    description=(
        "Full-bleed photographic poster with a dark gradient scrim across the lower "
        "third and all copy set over it. Cinematic. Best for travel, film, landscape "
        "and any brief where the image should carry the design."
    ),
    gridBaseline=12,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY_BOTTOM,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0.42, w=1, h=0.58, scrim=True, scrim_angle=180,
              palette="primary", z=3,
              constraints=con("stretch", "bottom", priority=30)),
        text("headline", "headline", x=0.08, y=0.635, w=0.84, h=0.155, size_n=0.075,
             weight=800, max_chars=44, transform="uppercase", line_height=0.96,
             tracking_n=-0.0015, palette="on-primary", z=10),
        text("subhead", "subhead", x=0.08, y=0.815, w=0.66, h=0.055, size_n=0.022,
             weight=400, max_chars=120, line_height=1.45, palette="on-primary",
             required=False, z=10),
        text("caption", "caption", x=0.08, y=0.925, w=0.6, h=0.024, size_n=0.0125,
             weight=600, max_chars=48, transform="uppercase", tracking_n=0.0028,
             palette="accent", required=False, z=10),
    ],
    variants=[],
)

# --------------------------------------------------------------------------------------
# Banners — 3:1
# --------------------------------------------------------------------------------------

BANNER_SPLIT = TemplateSkeleton(
    id="tpl_banner_split_01",
    name="Banner — copy left, product right",
    kind="banner", aspect="3:1",
    tags=["web", "clean", "commerce", "subject"],
    description=(
        "Wide banner with copy stacked on the left and the product cut out on the right. "
        "Best for site headers, promotional strips and email hero images."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY,
              constraints=con("stretch", "stretch", priority=100), z=0),
        text("headline", "headline", x=0.045, y=0.17, w=0.44, h=0.34, size_n=0.20,
             weight=800, max_chars=34, line_height=1.0, tracking_n=-0.004,
             palette="on-primary", z=10),
        text("subhead", "subhead", x=0.045, y=0.555, w=0.40, h=0.14, size_n=0.078,
             weight=400, max_chars=76, line_height=1.35, palette="on-primary",
             required=False, z=10),
        # h must stay inside the safe area: a 3:1 canvas takes its 6.67% margin from the
        # short edge, leaving ~0.87 of the height usable.
        image("subject", "subject", x=0.60, y=0.08, w=0.36, h=0.84, prompt=SUBJECT,
              transparent=True, fit="contain", z=6, effects=[shadow(0.04, 0.09, 0.28)],
              constraints=con("right", "middle", lock=True, priority=95)),
        shape("cta_bg", "cta", x=0.045, y=0.745, w=0.19, h=0.17, radius_n=0.5,
              palette="accent", required=False, z=8),
        text("cta", "cta", x=0.045, y=0.745, w=0.19, h=0.17, size_n=0.075, weight=700,
             max_chars=16, align="center", valign="middle", palette="on-accent",
             required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="mirror", name="Product left", patch={
            "subject": {"frameN": {"x": 0.04, "y": 0.08, "w": 0.34, "h": 0.84}},
            "headline": {"frameN": {"x": 0.44, "y": 0.17, "w": 0.52, "h": 0.34}},
            "subhead": {"frameN": {"x": 0.44, "y": 0.555, "w": 0.46, "h": 0.14}},
            "cta_bg": {"frameN": {"x": 0.44, "y": 0.745, "w": 0.19, "h": 0.17}},
            "cta": {"frameN": {"x": 0.44, "y": 0.745, "w": 0.19, "h": 0.17}},
        }),
    ],
)

BANNER_CENTER = TemplateSkeleton(
    id="tpl_banner_center_01",
    name="Banner — centred statement",
    kind="banner", aspect="3:1",
    tags=["web", "text-only", "minimal", "centered"],
    description=(
        "Centred single-line banner over a flat or textured field, with an optional "
        "small line beneath. No photograph. Best for announcement bars, notices and "
        "simple promotional strips."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        text("headline", "headline", x=0.06, y=0.24, w=0.88, h=0.32, size_n=0.19,
             weight=800, max_chars=46, align="center", line_height=1.0,
             tracking_n=-0.003, palette="on-primary", z=10),
        text("subhead", "subhead", x=0.14, y=0.615, w=0.72, h=0.14, size_n=0.072,
             weight=400, max_chars=80, align="center", line_height=1.3,
             palette="on-primary", required=False, z=10),
    ],
    variants=[],
)

# --------------------------------------------------------------------------------------
# Thumbnails — 16:9
# --------------------------------------------------------------------------------------

THUMB_SPLIT = TemplateSkeleton(
    id="tpl_thumb_split_01",
    name="Thumbnail — copy left, subject right",
    kind="thumbnail", aspect="16:9",
    tags=["video", "bold", "high-contrast", "subject"],
    description=(
        "Video thumbnail with two or three enormous words on the left and the subject "
        "filling the right. Built to stay readable at 210 pixels wide. Best for YouTube "
        "and any feed where the thumbnail competes for attention."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY_TOP,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0, w=0.62, h=1, scrim=True, scrim_angle=90,
              palette="primary", required=False, z=3,
              constraints=con("left", "stretch", priority=20, optional=True)),
        text("headline", "headline", x=0.055, y=0.16, w=0.50, h=0.50, size_n=0.185,
             weight=900, max_chars=24, transform="uppercase", line_height=0.92,
             tracking_n=-0.005, palette="on-primary", z=10),
        text("subhead", "subhead", x=0.055, y=0.715, w=0.44, h=0.10, size_n=0.055,
             weight=600, max_chars=44, line_height=1.2, palette="accent",
             required=False, z=10),
        image("subject", "subject", x=0.56, y=0.05, w=0.42, h=0.90, prompt=SUBJECT,
              transparent=True, fit="contain", z=6, effects=[shadow(0.03, 0.07, 0.35)],
              constraints=con("right", "middle", lock=True, priority=95)),
    ],
    variants=[
        SkeletonVariant(id="mirror", name="Subject left", patch={
            "subject": {"frameN": {"x": 0.02, "y": 0.05, "w": 0.42, "h": 0.90}},
            "scrim": {"frameN": {"x": 0.38, "y": 0, "w": 0.62, "h": 1}},
            "headline": {"frameN": {"x": 0.45, "y": 0.16, "w": 0.50, "h": 0.50},
                         "text": {"align": "right"}},
            "subhead": {"frameN": {"x": 0.51, "y": 0.715, "w": 0.44, "h": 0.10},
                        "text": {"align": "right"}},
        }),
    ],
)

THUMB_CENTER = TemplateSkeleton(
    id="tpl_thumb_center_01",
    name="Thumbnail — centred shout",
    kind="thumbnail", aspect="16:9",
    tags=["video", "bold", "centered", "high-contrast"],
    description=(
        "Thumbnail with a single centred phrase in outlined display type over a "
        "full-bleed image. Maximum legibility at small sizes. Best for reaction videos, "
        "tutorials and listicles."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0.28, w=1, h=0.60, scrim=True, scrim_angle=180,
              palette="primary", required=False, z=3,
              constraints=con("stretch", "middle", priority=20, optional=True)),
        text("headline", "headline", x=0.07, y=0.27, w=0.86, h=0.44, size_n=0.20,
             weight=900, max_chars=30, align="center", transform="uppercase",
             line_height=0.94, tracking_n=-0.004, palette="on-primary", z=10),
        text("caption", "caption", x=0.20, y=0.78, w=0.60, h=0.09, size_n=0.055,
             weight=700, max_chars=36, align="center", transform="uppercase",
             tracking_n=0.003, palette="accent", required=False, z=10),
    ],
    variants=[],
)

# --------------------------------------------------------------------------------------
# Ads — 1.91:1
# --------------------------------------------------------------------------------------

AD_PRODUCT = TemplateSkeleton(
    id="tpl_ad_product_01",
    name="Ad — product and offer",
    kind="ad", aspect="1.91:1",
    tags=["paid", "commerce", "clean", "subject"],
    description=(
        "Paid social ad: short benefit-led headline on the left, product on the right, "
        "prominent CTA button. Sized for Facebook, Instagram and Google display. Best "
        "for direct-response campaigns with one product and one offer."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY,
              constraints=con("stretch", "stretch", priority=100), z=0),
        text("headline", "headline", x=0.055, y=0.13, w=0.46, h=0.33, size_n=0.135,
             weight=800, max_chars=40, line_height=1.0, tracking_n=-0.003,
             palette="on-primary", z=10),
        text("subhead", "subhead", x=0.055, y=0.50, w=0.42, h=0.16, size_n=0.055,
             weight=400, max_chars=90, line_height=1.35, palette="on-primary",
             required=False, z=10),
        image("subject", "subject", x=0.56, y=0.08, w=0.40, h=0.84, prompt=SUBJECT,
              transparent=True, fit="contain", z=6, effects=[shadow(0.03, 0.06, 0.30)],
              constraints=con("right", "middle", lock=True, priority=95)),
        shape("cta_bg", "cta", x=0.055, y=0.72, w=0.24, h=0.15, radius_n=0.16,
              palette="accent", required=False, z=8),
        text("cta", "cta", x=0.055, y=0.72, w=0.24, h=0.15, size_n=0.055, weight=700,
             max_chars=18, align="center", valign="middle", palette="on-accent",
             required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="centered", name="Centred offer, no product", patch={
            "subject": {"required": False},
            "headline": {"frameN": {"x": 0.10, "y": 0.17, "w": 0.80, "h": 0.34},
                         "text": {"align": "center"}},
            "subhead": {"frameN": {"x": 0.15, "y": 0.54, "w": 0.70, "h": 0.14},
                        "text": {"align": "center"}},
            "cta_bg": {"frameN": {"x": 0.38, "y": 0.72, "w": 0.24, "h": 0.15}},
            "cta": {"frameN": {"x": 0.38, "y": 0.72, "w": 0.24, "h": 0.15}},
        }),
    ],
)

# --------------------------------------------------------------------------------------
# Flyers — A-series portrait
# --------------------------------------------------------------------------------------

FLYER_EVENT = TemplateSkeleton(
    id="tpl_flyer_event_01",
    name="Flyer — event",
    kind="flyer", aspect="1:1.414",
    tags=["event", "print", "informative", "subject"],
    description=(
        "Event flyer with a banner headline, a supporting image and a structured block "
        "of details — date, venue, price — at the foot. Print-ready. Best for markets, "
        "workshops, open days and community events."
    ),
    gridBaseline=12,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="neutral",
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("head_band", "decoration", x=0, y=0, w=1, h=0.22, palette="primary",
              required=False, z=2, constraints=con("stretch", "top", priority=40)),
        text("headline", "headline", x=0.08, y=0.045, w=0.84, h=0.125, size_n=0.062,
             weight=900, max_chars=40, transform="uppercase", line_height=0.98,
             palette="on-primary", z=10),
        image("bg", "background", x=0.08, y=0.26, w=0.84, h=0.34, prompt=BG_EMPTY,
              constraints=con("center", "middle", priority=70), z=3),
        text("subhead", "subhead", x=0.08, y=0.635, w=0.72, h=0.05, size_n=0.030,
             weight=700, max_chars=60, line_height=1.2, palette="accent",
             required=False, z=10),
        text("body", "body", x=0.08, y=0.71, w=0.80, h=0.12, size_n=0.0185,
             weight=400, max_chars=280, line_height=1.55, palette="on-primary",
             required=False, z=10),
        text("cta", "cta", x=0.08, y=0.885, w=0.7, h=0.035, size_n=0.022, weight=700,
             max_chars=48, transform="uppercase", tracking_n=0.002, palette="accent",
             required=False, z=10),
    ],
    variants=[],
)




# --------------------------------------------------------------------------------------
# Ornamented layouts
#
# Everything above places photography and type and nothing else, which is why its output
# reads as a picture with words on it. The layouts below carry decorative structure —
# a border, corner flourishes, a garland, a starburst, a divider under the headline —
# because that structure is most of what separates reference-quality festival and
# promotional work from a caption over a photograph. The ornament is procedural vector
# drawn from the palette (see `templates_corpus.ornament`), so it costs nothing, cannot
# clash, and cannot smuggle a glyph past the §1.4.6 gate.
# --------------------------------------------------------------------------------------

STORY_FESTIVE = TemplateSkeleton(
    id="tpl_story_festive_01",
    name="Story — framed festival greeting",
    kind="story", aspect="9:16",
    tags=["festive", "ornate", "premium", "greeting", "subject", "centered"],
    description=(
        "Ceremonial greeting card for stories. A blossom garland hangs across the top, a "
        "ruled border and corner flourishes frame the whole canvas, and a centred display "
        "serif headline sits above a small ornamental divider. The subject floats in the "
        "lower half over a dark ground. Best for Diwali, Eid, Christmas, weddings, "
        "anniversaries and any religious or cultural occasion that wants gold-on-dark "
        "ceremony rather than a photograph with a caption."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_TEXTURE,
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("frame", motif="border", x=0, y=0, w=1, h=1, palette="accent",
                 density=2, z=3),
        ornament("flourish", motif="corners", x=0, y=0, w=1, h=1, palette="accent",
                 density=3, z=4),
        ornament("garland", motif="garland", x=0, y=-0.005, w=1, h=0.085,
                 palette="accent", density=4, z=5),
        text("eyebrow", "caption", x=0.14, y=0.155, w=0.72, h=0.026, size_n=0.0135,
             weight=600, max_chars=26, align="center", transform="uppercase",
             tracking_n=0.004, palette="accent", required=False, z=10),
        text("headline", "headline", x=0.10, y=0.195, w=0.80, h=0.155, size_n=0.058,
             weight=700, max_chars=38, align="center", line_height=1.04,
             palette="on-primary", z=10),
        ornament("divider", motif="divider", x=0.32, y=0.368, w=0.36, h=0.020,
                 palette="accent", density=4, z=11),
        text("subhead", "subhead", x=0.16, y=0.405, w=0.68, h=0.062, size_n=0.020,
             weight=400, max_chars=90, align="center", line_height=1.4,
             palette="on-primary", required=False, z=10),
        image("subject", "subject", x=0.17, y=0.505, w=0.66, h=0.30, prompt=SUBJECT_FRONT,
              transparent=True, fit="contain", z=7, effects=[shadow(0.012, 0.028, 0.30)],
              constraints=con("center", "middle", lock=True, priority=95)),
        shape("cta_bg", "cta", x=0.28, y=0.862, w=0.44, h=0.052, radius_n=0.5,
              palette="accent", required=False, z=8),
        text("cta", "cta", x=0.28, y=0.862, w=0.44, h=0.052, size_n=0.021, weight=700,
             max_chars=20, align="center", valign="middle", palette="on-accent",
             required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="arched", name="Arch behind the subject", patch={
            "garland": {"frameN": {"x": 0, "y": -0.005, "w": 1, "h": 0.06}},
            "subject": {"frameN": {"x": 0.20, "y": 0.50, "w": 0.60, "h": 0.30}},
        }),
        SkeletonVariant(id="plain", name="No garland, heavier frame", patch={
            "garland": {"required": False, "opacity": 0.0},
            "headline": {"frameN": {"x": 0.10, "y": 0.165, "w": 0.80, "h": 0.175}},
        }),
    ],
)

POST_FESTIVE = TemplateSkeleton(
    id="tpl_post_festive_01",
    name="Post — garlanded greeting",
    kind="post", aspect="4:5",
    tags=["festive", "ornate", "greeting", "subject", "centered", "warm"],
    description=(
        "Portrait festival greeting. A blossom garland runs along the top edge, a "
        "scalloped band closes the bottom, and the subject sits centred between a serif "
        "headline above and a short wish below an ornamental divider. Best for Diwali, "
        "Ganesh Chaturthi, Onam, Pongal, Navratri, Eid and similar greetings, and for "
        "community or temple announcements."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_TEXTURE,
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("garland", motif="garland", x=0, y=-0.008, w=1, h=0.095,
                 palette="accent", density=5, z=5),
        ornament("skirt", motif="scallop", x=0, y=0.945, w=1, h=0.055,
                 palette="accent", density=4, z=5),
        text("eyebrow", "caption", x=0.15, y=0.135, w=0.70, h=0.024, size_n=0.0145,
             weight=600, max_chars=24, align="center", transform="uppercase",
             tracking_n=0.0042, palette="accent", required=False, z=10),
        text("headline", "headline", x=0.09, y=0.170, w=0.82, h=0.115, size_n=0.058,
             weight=700, max_chars=34, align="center", line_height=1.05,
             palette="on-primary", z=10),
        image("subject", "subject", x=0.21, y=0.330, w=0.58, h=0.360, prompt=SUBJECT_FRONT,
              transparent=True, fit="contain", z=7, effects=[shadow(0.012, 0.026, 0.26)],
              constraints=con("center", "middle", lock=True, priority=95)),
        ornament("divider", motif="divider", x=0.34, y=0.715, w=0.32, h=0.018,
                 palette="accent", density=3, z=11),
        text("subhead", "subhead", x=0.14, y=0.752, w=0.72, h=0.060, size_n=0.021,
             weight=400, max_chars=80, align="center", line_height=1.35,
             palette="on-primary", required=False, z=10),
    ],
    variants=[
        SkeletonVariant(id="tall", name="Larger subject, tighter copy", patch={
            "subject": {"frameN": {"x": 0.16, "y": 0.315, "w": 0.68, "h": 0.40}},
            "headline": {"frameN": {"x": 0.09, "y": 0.165, "w": 0.82, "h": 0.100}},
        }),
    ],
)

POST_FESTIVE_SQUARE = TemplateSkeleton(
    id="tpl_post_festive_sq_01",
    name="Square — garlanded greeting",
    kind="post", aspect="1:1",
    tags=["festive", "ornate", "greeting", "subject", "centered", "warm"],
    description=(
        "Square festival greeting. A blossom garland runs along the "
        "top edge, a scalloped band closes the bottom, and the subject sits centred "
        "between a serif headline above and a short wish below. Best for Ganesh "
        "Chaturthi, Onam, Pongal, Navratri and similar greetings, and for community "
        "or temple announcements."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_TEXTURE,
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("garland", motif="garland", x=0, y=-0.01, w=1, h=0.12,
                 palette="accent", density=5, z=5),
        ornament("skirt", motif="scallop", x=0, y=0.93, w=1, h=0.07,
                 palette="accent", density=4, z=5),
        text("eyebrow", "caption", x=0.15, y=0.145, w=0.70, h=0.030, size_n=0.018,
             weight=600, max_chars=24, align="center", transform="uppercase",
             tracking_n=0.005, palette="accent", required=False, z=10),
        text("headline", "headline", x=0.09, y=0.190, w=0.82, h=0.130, size_n=0.070,
             weight=700, max_chars=34, align="center", line_height=1.05,
             palette="on-primary", z=10),
        image("subject", "subject", x=0.22, y=0.355, w=0.56, h=0.400, prompt=SUBJECT_FRONT,
              transparent=True, fit="contain", z=7, effects=[shadow(0.014, 0.030, 0.26)],
              constraints=con("center", "middle", lock=True, priority=95)),
        ornament("divider", motif="divider", x=0.34, y=0.778, w=0.32, h=0.024,
                 palette="accent", density=3, z=11),
        text("subhead", "subhead", x=0.14, y=0.822, w=0.72, h=0.070, size_n=0.026,
             weight=400, max_chars=80, align="center", line_height=1.35,
             palette="on-primary", required=False, z=10),
    ],
    variants=[
        SkeletonVariant(id="tall", name="Larger subject, tighter copy", patch={
            "subject": {"frameN": {"x": 0.17, "y": 0.335, "w": 0.66, "h": 0.44}},
            "headline": {"frameN": {"x": 0.09, "y": 0.185, "w": 0.82, "h": 0.115}},
        }),
    ],
)

POSTER_ORNATE = TemplateSkeleton(
    id="tpl_poster_ornate_01",
    name="Poster — arched ceremonial",
    kind="poster", aspect="1:1.414",
    tags=["festive", "ornate", "premium", "event", "subject", "centered"],
    description=(
        "Formal print poster. A double ruled border and corner flourishes frame the "
        "sheet, an arch rises behind a centred subject, and a display serif headline "
        "sits under a small ornamental divider with event details beneath. Best for "
        "weddings, invitations, temple and community events, recitals and any printed "
        "announcement that should feel composed and ceremonial."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_TEXTURE,
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("frame", motif="border", x=0, y=0, w=1, h=1, palette="accent",
                 density=3, z=3),
        ornament("flourish", motif="corners", x=0, y=0, w=1, h=1, palette="accent",
                 density=4, z=4),
        ornament("arch", motif="arch", x=0.22, y=0.325, w=0.56, h=0.40,
                 palette="accent", density=2, stroke_n=0.0014, z=5),
        text("eyebrow", "caption", x=0.15, y=0.105, w=0.70, h=0.022, size_n=0.0125,
             weight=600, max_chars=28, align="center", transform="uppercase",
             tracking_n=0.0045, palette="accent", required=False, z=10),
        text("headline", "headline", x=0.10, y=0.140, w=0.80, h=0.120, size_n=0.050,
             weight=700, max_chars=40, align="center", line_height=1.06,
             palette="on-primary", z=10),
        ornament("divider", motif="divider", x=0.36, y=0.274, w=0.28, h=0.016,
                 palette="accent", density=4, z=11),
        image("subject", "subject", x=0.26, y=0.370, w=0.48, h=0.330, prompt=SUBJECT_FRONT,
              transparent=True, fit="contain", z=7, effects=[shadow(0.010, 0.024, 0.28)],
              constraints=con("center", "middle", lock=True, priority=95)),
        text("subhead", "subhead", x=0.16, y=0.752, w=0.68, h=0.058, size_n=0.019,
             weight=400, max_chars=110, align="center", line_height=1.45,
             palette="on-primary", required=False, z=10),
        text("body", "body", x=0.18, y=0.840, w=0.64, h=0.060, size_n=0.0155,
             weight=400, max_chars=140, align="center", line_height=1.5,
             palette="on-primary", required=False, z=10),
    ],
    variants=[
        SkeletonVariant(id="no-arch", name="Frame only, no arch", patch={
            "arch": {"opacity": 0.0},
            "subject": {"frameN": {"x": 0.22, "y": 0.350, "w": 0.56, "h": 0.360}},
        }),
    ],
)

POST_BURST = TemplateSkeleton(
    id="tpl_post_burst_01",
    name="Post — bunting and starburst promo",
    kind="post", aspect="4:5",
    tags=["festive", "playful", "bold", "promotional", "event", "text-heavy"],
    description=(
        "Loud celebratory announcement. A starburst radiates behind the copy, bunting "
        "hangs across the top and confetti scatters over the ground, with a heavy "
        "headline, a supporting line and a pill CTA stacked down the middle. Best for "
        "grand openings, launch days, sales, anniversaries and party invitations that "
        "want energy rather than restraint."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("burst", motif="rays", x=0, y=0, w=1, h=1, palette="accent",
                 density=4, opacity=0.11, z=2),
        ornament("bunting", motif="bunting", x=0, y=0, w=1, h=0.110,
                 palette="accent", density=4, z=5),
        ornament("confetti", motif="confetti", x=0, y=0.10, w=1, h=0.90,
                 palette="accent", density=3, opacity=0.5, z=6),
        text("eyebrow", "caption", x=0.15, y=0.195, w=0.70, h=0.026, size_n=0.0155,
             weight=700, max_chars=22, align="center", transform="uppercase",
             tracking_n=0.005, palette="accent", required=False, z=10),
        text("headline", "headline", x=0.08, y=0.245, w=0.84, h=0.185, size_n=0.082,
             weight=900, max_chars=28, align="center", transform="uppercase",
             line_height=0.96, tracking_n=-0.002, palette="on-primary", z=10),
        text("subhead", "subhead", x=0.14, y=0.460, w=0.72, h=0.070, size_n=0.022,
             weight=400, max_chars=95, align="center", line_height=1.35,
             palette="on-primary", required=False, z=10),
        shape("cta_bg", "cta", x=0.28, y=0.610, w=0.44, h=0.058, radius_n=0.5,
              palette="accent", required=False, z=8),
        text("cta", "cta", x=0.28, y=0.610, w=0.44, h=0.058, size_n=0.022, weight=700,
             max_chars=20, align="center", valign="middle", palette="on-accent",
             required=False, z=12),
        text("footer", "caption", x=0.15, y=0.880, w=0.70, h=0.026, size_n=0.0145,
             weight=500, max_chars=40, align="center", palette="on-primary",
             required=False, z=10),
    ],
    variants=[
        SkeletonVariant(id="calm", name="Starburst only, no confetti", patch={
            "confetti": {"opacity": 0.0},
            "bunting": {"opacity": 0.0},
            "headline": {"frameN": {"x": 0.08, "y": 0.215, "w": 0.84, "h": 0.215}},
        }),
    ],
)

POST_DOTTED = TemplateSkeleton(
    id="tpl_post_dotted_01",
    name="Post — dotted graphic promo",
    kind="post", aspect="4:5",
    tags=["bold", "playful", "promotional", "subject", "high-contrast", "graphic"],
    description=(
        "Graphic promotional post with flat colour blocking. A dot grid and a run of "
        "chevrons break up a solid panel beside a large photograph, with a heavy "
        "headline, a discount line and a pill CTA. Best for food delivery, retail "
        "offers, gym and salon promotions and any discount-led campaign that wants "
        "graphic punch rather than photographic calm."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        image("bg", "background", x=0, y=0.42, w=1, h=0.58, prompt=BG_EMPTY_BOTTOM,
              constraints=con("stretch", "bottom", priority=90), z=1),
        ornament("dots", motif="dots", x=0.06, y=0.055, w=0.26, h=0.075,
                 palette="accent", density=3, opacity=0.9, z=4),
        ornament("chevrons", motif="chevrons", x=0.74, y=0.335, w=0.20, h=0.045,
                 palette="accent", density=3, opacity=0.9, z=4),
        text("headline", "headline", x=0.06, y=0.150, w=0.72, h=0.145, size_n=0.086,
             weight=900, max_chars=26, transform="uppercase", line_height=0.94,
             tracking_n=-0.0022, palette="on-primary", z=10),
        text("subhead", "subhead", x=0.06, y=0.310, w=0.62, h=0.055, size_n=0.021,
             weight=400, max_chars=80, line_height=1.35, palette="on-primary",
             required=False, z=10),
        shape("cta_bg", "cta", x=0.06, y=0.885, w=0.40, h=0.058, radius_n=0.5,
              palette="accent", required=False, z=8),
        text("cta", "cta", x=0.06, y=0.885, w=0.40, h=0.058, size_n=0.022, weight=700,
             max_chars=18, align="center", valign="middle", palette="on-accent",
             required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="flip", name="Photograph above, copy below", patch={
            "bg": {"frameN": {"x": 0, "y": 0, "w": 1, "h": 0.56}},
            "headline": {"frameN": {"x": 0.06, "y": 0.610, "w": 0.72, "h": 0.145}},
            "subhead": {"frameN": {"x": 0.06, "y": 0.770, "w": 0.62, "h": 0.055}},
            "dots": {"frameN": {"x": 0.06, "y": 0.575, "w": 0.26, "h": 0.022}},
            "chevrons": {"frameN": {"x": 0.74, "y": 0.610, "w": 0.20, "h": 0.045}},
        }),
    ],
)



# --------------------------------------------------------------------------------------
# Flat-graphic layouts
#
# The ornamented layouts above frame a photograph. These are built the other way round:
# flat colour fields, a hero cutout, several props layered in front of and behind it, and
# display type that interleaves with the subject rather than sitting politely above it.
# That interleaving is declared (`overlap=True`) so the solver reads it as depth instead
# of as a collision to pull apart.
# --------------------------------------------------------------------------------------

POST_FASHION = TemplateSkeleton(
    id="tpl_post_fashion_01",
    name="Post — colour-field fashion sale",
    kind="post", aspect="4:5",
    tags=["bold", "playful", "promotional", "subject", "graphic", "sale", "props"],
    description=(
        "Flat-graphic sale post. Two organic colour blobs bleed off opposite corners, "
        "tropical foliage layers into the top-left and over the bottom-right, and a "
        "model or product cutout stands at the left running off the bottom edge. A "
        "script accent line sits above a heavy display headline. Best for fashion, "
        "beauty, seasonal sales and any discount campaign that wants flat colour and "
        "energy rather than photographic calm."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        # The blobs sit clear of the copy column on purpose. Type straddling the edge
        # between two strong flat colours cannot be made readable by recolouring — no
        # single colour clears the threshold against both — so it would be forced into a
        # backdrop pill, and a pill behind a display headline reads as a mistake.
        ornament("blob_b", motif="blob", x=-0.34, y=-0.20, w=0.76, h=0.70,
                 palette="accent", density=4, z=1),
        ornament("blob_a", motif="blob", x=0.52, y=0.660, w=0.72, h=0.46,
                 palette="accent", density=3, z=1),
        prop("leaf_back", x=-0.08, y=-0.06, w=0.32, h=0.24, prompt=PROP_FOLIAGE, z=3,
             rotation=-18),
        image("subject", "subject", x=0.02, y=0.340, w=0.52, h=0.68, prompt=SUBJECT,
              transparent=True, fit="contain", z=6,
              effects=[shadow(0.010, 0.026, 0.22)],
              constraints=con("left", "bottom", lock=True, priority=95)),
        text("script", "caption", x=0.46, y=0.135, w=0.50, h=0.075, size_n=0.060,
             weight=400, max_chars=14, align="center", face="script",
             line_height=1.0, palette="on-primary", required=False, z=10,
             constraints=con("center", "top", priority=45, optional=True, overlap=True)),
        text("headline", "headline", x=0.44, y=0.220, w=0.54, h=0.150, size_n=0.086,
             weight=900, max_chars=18, align="center", transform="uppercase",
             line_height=0.92, tracking_n=-0.002, palette="on-primary", z=10,
             constraints=con("center", "top", priority=90, overlap=True)),
        text("subhead", "subhead", x=0.48, y=0.400, w=0.46, h=0.075, size_n=0.019,
             weight=400, max_chars=95, align="center", line_height=1.45,
             palette="on-primary", required=False, z=10,
             constraints=con("center", "top", priority=40, optional=True, overlap=True)),
        prop("leaf_front", x=0.62, y=0.740, w=0.46, h=0.32, prompt=PROP_FOLIAGE, z=12,
             rotation=14),
        prop("sprig", x=0.25, y=-0.03, w=0.15, h=0.115, prompt=PROP_BOTANICAL, z=12,
             rotation=26),
    ],
    variants=[
        SkeletonVariant(id="mirror", name="Subject right, copy left", patch={
            "subject": {"frameN": {"x": 0.46, "y": 0.340, "w": 0.52, "h": 0.68}},
            "script": {"frameN": {"x": 0.04, "y": 0.135, "w": 0.50, "h": 0.075}},
            "headline": {"frameN": {"x": 0.02, "y": 0.220, "w": 0.54, "h": 0.150}},
            "subhead": {"frameN": {"x": 0.06, "y": 0.400, "w": 0.46, "h": 0.075}},
            "blob_b": {"frameN": {"x": 0.58, "y": -0.20, "w": 0.76, "h": 0.70}},
            "blob_a": {"frameN": {"x": -0.24, "y": 0.660, "w": 0.72, "h": 0.46}},
            "leaf_front": {"frameN": {"x": -0.08, "y": 0.740, "w": 0.46, "h": 0.32}},
        }),
    ],
)

POST_DROP = TemplateSkeleton(
    id="tpl_post_drop_01",
    name="Post — striped product drop",
    kind="post", aspect="4:5",
    tags=["bold", "high-contrast", "promotional", "subject", "graphic", "product",
          "sale"],
    description=(
        "Product drop announcement on a diagonal stripe field. A huge outlined display "
        "word sits behind the product cutout so the two interlock, with a small eyebrow "
        "above, a discount seal in the top corner, a pill CTA and a contact strip along "
        "the bottom. Best for sneaker and streetwear drops, electronics launches, "
        "flash sales and any product announcement that wants graphic impact."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("stripes", motif="stripes", x=0, y=0, w=1, h=1, palette="accent",
                 density=4, opacity=0.17, z=1),
        text("eyebrow", "caption", x=0.06, y=0.140, w=0.50, h=0.048, size_n=0.040,
             weight=900, max_chars=14, transform="uppercase", tracking_n=-0.001,
             palette="on-primary", required=False, z=10),
        text("subhead", "subhead", x=0.06, y=0.202, w=0.52, h=0.044, size_n=0.035,
             weight=700, max_chars=16, transform="uppercase", tracking_n=0.002,
             palette="primary", stroke_n=0.0018, stroke_palette="on-primary",
             required=False, z=10),
        # The display word sits BEHIND the product, which is the whole composition.
        text("headline", "headline", x=0.02, y=0.330, w=0.96, h=0.150, size_n=0.122,
             weight=900, max_chars=12, align="center", transform="uppercase",
             line_height=0.90, tracking_n=-0.004, palette="on-primary", z=4,
             constraints=con("center", "middle", priority=88, overlap=True)),
        image("subject", "subject", x=0.10, y=0.310, w=0.80, h=0.250, prompt=SUBJECT,
              transparent=True, fit="contain", z=6,
              effects=[shadow(0.013, 0.028, 0.30)],
              constraints=con("center", "middle", lock=True, priority=95, overlap=True)),
        ornament("seal", motif="badge", x=0.705, y=0.048, w=0.245, h=0.196,
                 palette="accent", density=3, z=8),
        text("badge", "badge", x=0.735, y=0.108, w=0.185, h=0.078, size_n=0.030,
             weight=900, max_chars=14, align="center", valign="middle",
             transform="uppercase", line_height=0.95, palette="on-accent",
             required=False, z=12,
             constraints=con("center", "top", priority=60, optional=True, overlap=True)),
        prop("accent", x=0.03, y=0.560, w=0.20, h=0.15, prompt=PROP_ACCENT, z=7,
             rotation=-12),
        shape("cta_bg", "cta", x=0.335, y=0.700, w=0.33, h=0.052, radius_n=0.5,
              palette="accent", required=False, z=8),
        text("cta", "cta", x=0.335, y=0.700, w=0.33, h=0.052, size_n=0.020, weight=700,
             max_chars=18, align="center", valign="middle", transform="uppercase",
             tracking_n=0.002, palette="on-accent", required=False, z=12),
        shape("footer_bar", "decoration", x=0, y=0.918, w=1, h=0.082, palette="accent",
              required=False, z=7,
              constraints=con("stretch", "bottom", priority=15, optional=True)),
        text("footer", "caption", x=0.06, y=0.940, w=0.88, h=0.030, size_n=0.016,
             weight=600, max_chars=54, align="center", valign="middle",
             transform="uppercase", tracking_n=0.003, palette="on-accent",
             required=False, z=12,
             constraints=con("center", "bottom", priority=35, optional=True,
                             overlap=True)),
    ],
    variants=[
        SkeletonVariant(id="stacked", name="Word above the product", patch={
            "headline": {"frameN": {"x": 0.02, "y": 0.280, "w": 0.96, "h": 0.135}},
            "subject": {"frameN": {"x": 0.14, "y": 0.390, "w": 0.72, "h": 0.240}},
        }),
    ],
)


POST_SHOWCASE = TemplateSkeleton(
    id="tpl_post_showcase_01",
    name="Post — three-subject showcase",
    kind="post", aspect="4:5",
    tags=["bold", "modern", "promotional", "subject", "graphic", "product", "multi",
          "collection", "range"],
    description=(
        "Three cutouts of the subject at different angles, staggered in front of and "
        "behind one another over a curved colour sweep, with the display headline "
        "running behind all three. Best for a product range, a collection drop, a menu "
        "of services, a lookbook — anything where showing one item would undersell it."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("sweep", motif="arc-band", x=-0.15, y=0.420, w=1.30, h=0.24,
                 palette="accent", density=3, z=1),
        text("eyebrow", "caption", x=0.08, y=0.105, w=0.55, h=0.042, size_n=0.027,
             weight=700, max_chars=22, transform="uppercase", tracking_n=0.004,
             palette="on-primary", required=False, z=12),
        # Behind all three cutouts: the word is the backdrop they stand against.
        text("headline", "headline", x=0.05, y=0.185, w=0.90, h=0.150, size_n=0.095,
             weight=900, max_chars=20, align="center", transform="uppercase",
             line_height=0.92, tracking_n=-0.003, palette="on-primary", z=4,
             constraints=con("center", "top", priority=90, overlap=True)),
        # Depth order is deliberate: the hero is the largest and sits between its two
        # companions, so the group reads as one arrangement rather than three stickers.
        # The companions are optional and carry lower priority, so a tight budget spends
        # on the hero first and drops them rather than shipping three half-subjects.
        image("subject_b", "subject", subject_index=1, x=0.02, y=0.330, w=0.34, h=0.30,
              prompt=SUBJECT_SIDE, transparent=True, fit="contain", z=6, required=False,
              effects=[shadow(0.008, 0.018, 0.20)],
              constraints=con("left", "middle", lock=True, priority=78, optional=True,
                              overlap=True)),
        image("subject", "subject", x=0.24, y=0.250, w=0.52, h=0.42,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=8,
              effects=[shadow(0.012, 0.028, 0.26)],
              constraints=con("center", "middle", lock=True, priority=95,
                              overlap=True)),
        image("subject_c", "subject", subject_index=2, x=0.64, y=0.340, w=0.34, h=0.30,
              prompt=SUBJECT_DETAIL, transparent=True, fit="contain", z=10,
              required=False, effects=[shadow(0.008, 0.018, 0.20)],
              constraints=con("right", "middle", lock=True, priority=74, optional=True,
                              overlap=True)),
        ornament("divider", motif="divider", x=0.30, y=0.700, w=0.40, h=0.020,
                 palette="accent", density=2, z=11),
        text("subhead", "subhead", x=0.12, y=0.735, w=0.76, h=0.080, size_n=0.020,
             weight=400, max_chars=110, align="center", line_height=1.45,
             palette="on-primary", required=False, z=12),
        shape("cta_bg", "cta", x=0.330, y=0.855, w=0.34, h=0.052, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.330, y=0.855, w=0.34, h=0.052, size_n=0.020, weight=700,
             max_chars=18, align="center", valign="middle", transform="uppercase",
             tracking_n=0.002, palette="on-accent", required=False, z=13),
    ],
    variants=[
        SkeletonVariant(id="row", name="Even row, hero centre", patch={
            "subject_b": {"frameN": {"x": 0.03, "y": 0.360, "w": 0.30, "h": 0.26}},
            "subject": {"frameN": {"x": 0.335, "y": 0.300, "w": 0.33, "h": 0.34}},
            "subject_c": {"frameN": {"x": 0.67, "y": 0.360, "w": 0.30, "h": 0.26}},
        }),
    ],
)

# --------------------------------------------------------------------------------------
# Coverage fill — IMPLEMENTATION_PLAN §1.2.
#
# `template.retrieve` filters hard on (kind, aspect) and prefers a text-only or a
# subject-bearing skeleton within that. The corpus above leaves that grid full of holes:
# one text-only skeleton for a 4:5 post, none at all for a square, none for an ad or a
# thumbnail. A hole does not degrade gracefully — the request falls through to the
# relaxed-aspect fallback and comes back with a layout authored for a different canvas
# shape, which is how a request for a square sale post ends up as three lines of type on
# a flat colour.
#
# These fill the grid, and they are authored to the same brief: every one carries a full
# copy set, ornament, and — where it takes a subject — more than one of them. Two things
# make a generated design read as designed rather than as a placeholder: something in
# every band of the canvas, and more than one object in the frame.
# --------------------------------------------------------------------------------------

POST_SALE = TemplateSkeleton(
    id="tpl_post_sale_01",
    name="Post — retail sale with price badge",
    kind="post", aspect="4:5",
    tags=["promotional", "sale", "retail", "subject", "bold", "offer", "discount",
          "shop", "product", "multi"],
    description=(
        "Portrait retail sale layout. A starburst sits behind the hero product, a round "
        "price badge punches into the upper right, a small companion object tucks in "
        "beside the hero, and the offer runs as headline, terms and a pill call to "
        "action down the lower third. Best for a discount, a clearance, a seasonal "
        "offer or a flash sale on a physical product."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("burst", motif="rays", x=-0.10, y=0.150, w=1.20, h=0.60,
                 palette="accent", density=4, opacity=0.22, z=1),
        text("eyebrow", "caption", x=0.08, y=0.070, w=0.52, h=0.034, size_n=0.022,
             weight=700, max_chars=24, transform="uppercase", tracking_n=0.005,
             palette="accent", required=False, z=12),
        text("headline", "headline", x=0.07, y=0.110, w=0.62, h=0.150, size_n=0.098,
             weight=900, max_chars=18, transform="uppercase", line_height=0.92,
             tracking_n=-0.004, palette="on-primary", z=12),
        ornament("badge", motif="badge", x=0.700, y=0.075, w=0.250, h=0.200,
                 palette="accent", density=3, z=13),
        text("badge_label", "caption", x=0.715, y=0.140, w=0.220, h=0.070,
             size_n=0.040, weight=900, max_chars=10, align="center", valign="middle",
             transform="uppercase", palette="on-accent", required=False, z=14,
             constraints=con("center", "top", priority=45, optional=True, overlap=True)),
        image("subject", "subject", x=0.140, y=0.300, w=0.620, h=0.400,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=8,
              effects=[shadow(0.014, 0.030, 0.28)],
              constraints=con("center", "middle", lock=True, priority=95, overlap=True)),
        prop("companion", x=0.640, y=0.430, w=0.300, h=0.240, prompt=SUBJECT_SIDE,
             subject_index=1, z=9,
             rotation=-6.0, effects=[shadow(0.008, 0.020, 0.22)]),
        ornament("rule", motif="divider", x=0.310, y=0.715, w=0.380, h=0.018,
                 palette="accent", density=3, z=11),
        text("subhead", "subhead", x=0.110, y=0.750, w=0.780, h=0.075, size_n=0.024,
             weight=400, max_chars=110, align="center", line_height=1.40,
             palette="on-primary", required=False, z=12),
        shape("cta_bg", "cta", x=0.300, y=0.865, w=0.400, h=0.060, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.300, y=0.865, w=0.400, h=0.060, size_n=0.023, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
    ],
    variants=[
        SkeletonVariant(id="calm", name="No starburst, product larger", patch={
            "burst": {"required": False, "frameN": {"x": 0, "y": 0, "w": 0.001,
                                                    "h": 0.001}},
            "subject": {"frameN": {"x": 0.120, "y": 0.290, "w": 0.700, "h": 0.420}},
        }),
        SkeletonVariant(id="left", name="Copy left, product right", patch={
            "headline": {"frameN": {"x": 0.07, "y": 0.300, "w": 0.46, "h": 0.190}},
            "eyebrow": {"frameN": {"x": 0.07, "y": 0.255, "w": 0.46, "h": 0.034}},
            "subject": {"frameN": {"x": 0.480, "y": 0.250, "w": 0.500, "h": 0.480}},
            "companion": {"frameN": {"x": 0.070, "y": 0.520, "w": 0.260, "h": 0.200}},
        }),
    ],
)


POST_GRID = TemplateSkeleton(
    id="tpl_post_grid_01",
    name="Post — four-up collection grid",
    kind="post", aspect="4:5",
    tags=["subject", "multi", "collection", "range", "grid", "catalogue", "menu",
          "lookbook", "modern", "product"],
    description=(
        "Four cutouts of the subject on a two-by-two grid of tinted cells, under a "
        "display headline and over a caption and call to action. Best for a product "
        "range, a menu, a set of services, a team, a lookbook or a catalogue page — "
        "anywhere the design has to show four related things at equal weight."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        text("eyebrow", "caption", x=0.08, y=0.065, w=0.60, h=0.032, size_n=0.021,
             weight=700, max_chars=26, transform="uppercase", tracking_n=0.005,
             palette="accent", required=False, z=12),
        text("headline", "headline", x=0.07, y=0.102, w=0.86, h=0.120, size_n=0.072,
             weight=900, max_chars=26, transform="uppercase", line_height=0.95,
             tracking_n=-0.003, palette="on-primary", z=12),
        # The cells are the grid. They are shapes rather than part of the background so
        # each cutout has a field of its own to sit on and the four read as a set.
        shape("cell_a", "decoration", x=0.070, y=0.265, w=0.410, h=0.255, radius_n=0.04,
              palette="accent", opacity=0.16, required=False, z=2),
        shape("cell_b", "decoration", x=0.520, y=0.265, w=0.410, h=0.255, radius_n=0.04,
              palette="accent", opacity=0.16, required=False, z=2),
        shape("cell_c", "decoration", x=0.070, y=0.540, w=0.410, h=0.255, radius_n=0.04,
              palette="accent", opacity=0.16, required=False, z=2),
        shape("cell_d", "decoration", x=0.520, y=0.540, w=0.410, h=0.255, radius_n=0.04,
              palette="accent", opacity=0.16, required=False, z=2),
        image("subject", "subject", x=0.100, y=0.285, w=0.350, h=0.215,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=6,
              effects=[shadow(0.006, 0.016, 0.22)],
              constraints=con("center", "middle", lock=True, priority=95, overlap=True)),
        image("subject_b", "subject", subject_index=1, x=0.550, y=0.285, w=0.350, h=0.215,
              prompt=SUBJECT_SIDE, transparent=True, fit="contain", z=6, required=False,
              effects=[shadow(0.006, 0.016, 0.22)],
              constraints=con("center", "middle", lock=True, priority=80, optional=True,
                              overlap=True)),
        image("subject_c", "subject", subject_index=2, x=0.100, y=0.560, w=0.350, h=0.215,
              prompt=SUBJECT_DETAIL, transparent=True, fit="contain", z=6, required=False,
              effects=[shadow(0.006, 0.016, 0.22)],
              constraints=con("center", "middle", lock=True, priority=76, optional=True,
                              overlap=True)),
        image("subject_d", "subject", subject_index=3, x=0.550, y=0.560, w=0.350, h=0.215,
              prompt=SUBJECT, transparent=True, fit="contain", z=6, required=False,
              effects=[shadow(0.006, 0.016, 0.22)],
              constraints=con("center", "middle", lock=True, priority=72, optional=True,
                              overlap=True)),
        ornament("rule", motif="divider", x=0.330, y=0.822, w=0.340, h=0.016,
                 palette="accent", density=2, z=11),
        text("subhead", "subhead", x=0.110, y=0.852, w=0.780, h=0.058, size_n=0.021,
             weight=400, max_chars=100, align="center", line_height=1.38,
             palette="on-primary", required=False, z=12),
        text("cta", "cta", x=0.250, y=0.925, w=0.500, h=0.040, size_n=0.020, weight=700,
             max_chars=22, align="center", valign="middle", transform="uppercase",
             tracking_n=0.004, palette="accent", required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="trio", name="Three across, one wide cell", patch={
            "cell_a": {"frameN": {"x": 0.070, "y": 0.290, "w": 0.270, "h": 0.300}},
            "cell_b": {"frameN": {"x": 0.365, "y": 0.290, "w": 0.270, "h": 0.300}},
            "cell_c": {"frameN": {"x": 0.660, "y": 0.290, "w": 0.270, "h": 0.300}},
            "cell_d": {"frameN": {"x": 0.070, "y": 0.615, "w": 0.860, "h": 0.170}},
            "subject": {"frameN": {"x": 0.090, "y": 0.310, "w": 0.230, "h": 0.260}},
            "subject_b": {"frameN": {"x": 0.385, "y": 0.310, "w": 0.230, "h": 0.260}},
            "subject_c": {"frameN": {"x": 0.680, "y": 0.310, "w": 0.230, "h": 0.260}},
            "subject_d": {"frameN": {"x": 0.330, "y": 0.630, "w": 0.340, "h": 0.140}},
        }),
    ],
)


POST_DUO = TemplateSkeleton(
    id="tpl_post_duo_01",
    name="Post — two-subject pairing",
    kind="post", aspect="4:5",
    tags=["subject", "multi", "pair", "comparison", "duo", "modern", "editorial",
          "product", "before-after"],
    description=(
        "Two cutouts of comparable weight facing one another over a wide colour band, "
        "with the headline split above them and the detail set below. Best for a "
        "pairing, a comparison, a before and after, a bundle of two, a collaboration "
        "or any design whose point is the relationship between two things."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("band", motif="arc-band", x=-0.20, y=0.360, w=1.40, h=0.280,
                 palette="accent", density=3, opacity=0.85, z=1),
        text("eyebrow", "caption", x=0.10, y=0.080, w=0.80, h=0.032, size_n=0.021,
             weight=700, max_chars=28, align="center", transform="uppercase",
             tracking_n=0.006, palette="accent", required=False, z=12),
        text("headline", "headline", x=0.07, y=0.118, w=0.86, h=0.140, size_n=0.080,
             weight=900, max_chars=28, align="center", transform="uppercase",
             line_height=0.94, tracking_n=-0.003, palette="on-primary", z=12),
        image("subject", "subject", x=0.055, y=0.300, w=0.440, h=0.360,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=8,
              effects=[shadow(0.012, 0.026, 0.26)],
              constraints=con("center", "middle", lock=True, priority=95, overlap=True)),
        image("subject_b", "subject", subject_index=1, x=0.505, y=0.300, w=0.440, h=0.360,
              prompt=SUBJECT_SIDE, transparent=True, fit="contain", z=8, required=False,
              effects=[shadow(0.012, 0.026, 0.26)],
              constraints=con("center", "middle", lock=True, priority=88, optional=True,
                              overlap=True)),
        ornament("rule", motif="divider", x=0.330, y=0.690, w=0.340, h=0.018,
                 palette="accent", density=3, z=11),
        text("subhead", "subhead", x=0.120, y=0.725, w=0.760, h=0.085, size_n=0.023,
             weight=400, max_chars=120, align="center", line_height=1.42,
             palette="on-primary", required=False, z=12),
        text("body", "body", x=0.150, y=0.828, w=0.700, h=0.060, size_n=0.017,
             weight=400, max_chars=160, align="center", line_height=1.50,
             palette="on-primary", required=False, auto_height=True, z=12),
        shape("cta_bg", "cta", x=0.320, y=0.905, w=0.360, h=0.055, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.320, y=0.905, w=0.360, h=0.055, size_n=0.021, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
    ],
    variants=[
        SkeletonVariant(id="stagger", name="Staggered, left subject lower", patch={
            "subject": {"frameN": {"x": 0.040, "y": 0.340, "w": 0.470, "h": 0.360}},
            "subject_b": {"frameN": {"x": 0.500, "y": 0.270, "w": 0.470, "h": 0.360}},
        }),
    ],
)


POST_FESTIVE_MULTI = TemplateSkeleton(
    id="tpl_post_festive_multi_01",
    name="Post — festive spread with three lamps",
    kind="post", aspect="4:5",
    tags=["festive", "ornate", "greeting", "subject", "multi", "warm", "celebration",
          "diwali", "wedding", "invitation"],
    description=(
        "Portrait festival layout carrying a full spread rather than a single object: a "
        "blossom garland along the top, a bordered field, three cutouts staggered across "
        "the middle with the tallest at the centre, an ornamental divider, and the wish "
        "and details set beneath over a scalloped skirt. Best for Diwali, Navratri, "
        "Eid, Christmas, a wedding invitation or a sale announced on a festival."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_TEXTURE,
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("frame", motif="border", x=0, y=0, w=1, h=1, palette="accent",
                 density=2, stroke_n=0.0016, opacity=0.75, z=2,
                 constraints=con("stretch", "stretch", priority=12, optional=True)),
        ornament("garland", motif="garland", x=0, y=-0.006, w=1, h=0.085,
                 palette="accent", density=5, z=5),
        ornament("skirt", motif="scallop", x=0, y=0.950, w=1, h=0.050,
                 palette="accent", density=4, z=5),
        text("eyebrow", "caption", x=0.15, y=0.108, w=0.70, h=0.024, size_n=0.0145,
             weight=600, max_chars=24, align="center", transform="uppercase",
             tracking_n=0.0045, palette="accent", required=False, z=12),
        text("headline", "headline", x=0.09, y=0.142, w=0.82, h=0.110, size_n=0.058,
             weight=700, max_chars=34, align="center", line_height=1.05,
             palette="on-primary", z=12),
        ornament("halo", motif="rays", x=0.150, y=0.290, w=0.700, h=0.360,
                 palette="accent", density=3, opacity=0.20, z=3),
        image("subject_b", "subject", subject_index=1, x=0.055, y=0.400, w=0.280, h=0.230,
              prompt=SUBJECT_SIDE, transparent=True, fit="contain", z=7, required=False,
              effects=[shadow(0.008, 0.020, 0.22)],
              constraints=con("left", "middle", lock=True, priority=78, optional=True,
                              overlap=True)),
        image("subject", "subject", x=0.305, y=0.300, w=0.390, h=0.330,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=9,
              effects=[shadow(0.012, 0.028, 0.28)],
              constraints=con("center", "middle", lock=True, priority=95, overlap=True)),
        image("subject_c", "subject", subject_index=2, x=0.665, y=0.400, w=0.280, h=0.230,
              prompt=SUBJECT_DETAIL, transparent=True, fit="contain", z=7, required=False,
              effects=[shadow(0.008, 0.020, 0.22)],
              constraints=con("right", "middle", lock=True, priority=74, optional=True,
                              overlap=True)),
        ornament("divider", motif="divider", x=0.340, y=0.672, w=0.320, h=0.018,
                 palette="accent", density=3, z=11),
        text("subhead", "subhead", x=0.130, y=0.708, w=0.740, h=0.070, size_n=0.023,
             weight=400, max_chars=90, align="center", line_height=1.40,
             palette="on-primary", required=False, z=12),
        text("body", "body", x=0.160, y=0.795, w=0.680, h=0.060, size_n=0.0165,
             weight=400, max_chars=150, align="center", line_height=1.55,
             palette="on-primary", required=False, auto_height=True, z=12),
        text("cta", "cta", x=0.250, y=0.880, w=0.500, h=0.040, size_n=0.019, weight=600,
             max_chars=26, align="center", valign="middle", transform="uppercase",
             tracking_n=0.005, palette="accent", required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="single", name="One lamp, larger", patch={
            "subject": {"frameN": {"x": 0.250, "y": 0.290, "w": 0.500, "h": 0.360}},
            "subject_b": {"required": False,
                          "frameN": {"x": 0.030, "y": 0.440, "w": 0.001, "h": 0.001}},
            "subject_c": {"required": False,
                          "frameN": {"x": 0.960, "y": 0.440, "w": 0.001, "h": 0.001}},
        }),
    ],
)


POST_PRODUCT_SQUARE = TemplateSkeleton(
    id="tpl_post_product_sq_01",
    name="Square — product card with companions",
    kind="post", aspect="1:1",
    tags=["subject", "product", "promotional", "multi", "modern", "shop", "offer",
          "clean"],
    description=(
        "Square product card. A soft blob sits behind the hero cutout, a smaller "
        "companion object tucks in at the lower right, and the copy runs as eyebrow, "
        "headline, detail line and a pill call to action beneath a short rule. Best for "
        "a single product, a new arrival, a feature announcement or a shop listing."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("halo", motif="blob", x=0.140, y=0.140, w=0.720, h=0.480,
                 palette="accent", density=3, opacity=0.28, z=1),
        text("eyebrow", "caption", x=0.09, y=0.070, w=0.60, h=0.034, size_n=0.024,
             weight=700, max_chars=24, transform="uppercase", tracking_n=0.005,
             palette="accent", required=False, z=12),
        image("subject", "subject", x=0.180, y=0.160, w=0.640, h=0.420,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=8,
              effects=[shadow(0.014, 0.032, 0.28)],
              constraints=con("center", "middle", lock=True, priority=95, overlap=True)),
        prop("companion", x=0.660, y=0.400, w=0.280, h=0.220, prompt=SUBJECT_SIDE, z=9,
             rotation=-8.0, effects=[shadow(0.008, 0.020, 0.22)]),
        text("headline", "headline", x=0.08, y=0.620, w=0.84, h=0.120, size_n=0.082,
             weight=900, max_chars=24, align="center", transform="uppercase",
             line_height=0.94, tracking_n=-0.003, palette="on-primary", z=12),
        ornament("rule", motif="divider", x=0.360, y=0.762, w=0.280, h=0.018,
                 palette="accent", density=3, z=11),
        text("subhead", "subhead", x=0.120, y=0.795, w=0.760, h=0.070, size_n=0.026,
             weight=400, max_chars=100, align="center", line_height=1.40,
             palette="on-primary", required=False, z=12),
        shape("cta_bg", "cta", x=0.320, y=0.888, w=0.360, h=0.062, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.320, y=0.888, w=0.360, h=0.062, size_n=0.026, weight=700,
             max_chars=18, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
    ],
    variants=[
        SkeletonVariant(id="quiet", name="No blob, no companion", patch={
            "halo": {"required": False,
                     "frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "companion": {"frameN": {"x": 0.96, "y": 0.96, "w": 0.001, "h": 0.001}},
            "subject": {"frameN": {"x": 0.160, "y": 0.150, "w": 0.680, "h": 0.440}},
        }),
    ],
)


# --- Text-only. One per (kind, aspect) that had none. ---------------------------------
#
# Type-only is the hardest case to make look designed, because there is no photograph to
# carry the composition — everything has to come from the type itself and from procedural
# ornament, which is free. So these lean on ornament harder than the subject-bearing
# skeletons do: a rule, a frame, a field of dots, a scallop closing the bottom edge.

POST_QUOTE = TemplateSkeleton(
    id="tpl_post_quote_01",
    name="Post — framed quotation",
    kind="post", aspect="4:5",
    tags=["text-only", "quote", "editorial", "minimal", "typographic", "statement",
          "announcement"],
    description=(
        "Portrait typographic card inside a fine ruled border, with a small mark above "
        "the quotation, the quotation set large and centred, an attribution rule beneath "
        "and a caption closing the frame. Best for a quotation, a statement, a "
        "testimonial, an announcement or any design that is carried by its words."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("frame", motif="frame-rule", x=0.055, y=0.045, w=0.890, h=0.910,
                 palette="accent", density=2, stroke_n=0.0014, opacity=0.8, z=2,
                 constraints=con("center", "top", priority=12, optional=True)),
        ornament("corners", motif="corners", x=0.040, y=0.032, w=0.920, h=0.936,
                 palette="accent", density=2, stroke_n=0.0022, z=3,
                 constraints=con("center", "top", priority=12, optional=True)),
        text("eyebrow", "caption", x=0.18, y=0.140, w=0.64, h=0.030, size_n=0.018,
             weight=600, max_chars=26, align="center", transform="uppercase",
             tracking_n=0.006, palette="accent", required=False, z=12),
        ornament("mark", motif="divider", x=0.430, y=0.196, w=0.140, h=0.020,
                 palette="accent", density=2, z=11),
        text("headline", "headline", x=0.125, y=0.265, w=0.750, h=0.320, size_n=0.062,
             weight=700, max_chars=120, align="center", valign="middle",
             line_height=1.24, palette="on-primary", auto_height=True, z=12),
        ornament("rule", motif="divider", x=0.400, y=0.630, w=0.200, h=0.016,
                 palette="accent", density=2, z=11),
        text("subhead", "subhead", x=0.150, y=0.668, w=0.700, h=0.070, size_n=0.024,
             weight=400, max_chars=90, align="center", line_height=1.42,
             palette="on-primary", required=False, z=12),
        text("body", "body", x=0.175, y=0.760, w=0.650, h=0.075, size_n=0.017,
             weight=400, max_chars=180, align="center", line_height=1.55,
             palette="on-primary", required=False, auto_height=True, z=12),
        text("caption", "caption", x=0.200, y=0.872, w=0.600, h=0.038, size_n=0.018,
             weight=600, max_chars=34, align="center", valign="middle",
             transform="uppercase", tracking_n=0.006, palette="accent",
             required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="plain", name="No border, type only", patch={
            "frame": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "corners": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "headline": {"frameN": {"x": 0.09, "y": 0.250, "w": 0.82, "h": 0.340},
                         "text": {"sizeN": 0.072}},
        }),
        SkeletonVariant(id="left", name="Ranged left", patch={
            "eyebrow": {"frameN": {"x": 0.11, "y": 0.140, "w": 0.60, "h": 0.030},
                        "text": {"align": "left"}},
            "mark": {"frameN": {"x": 0.110, "y": 0.196, "w": 0.140, "h": 0.020}},
            "headline": {"frameN": {"x": 0.105, "y": 0.265, "w": 0.790, "h": 0.320},
                         "text": {"align": "left"}},
            "rule": {"frameN": {"x": 0.110, "y": 0.630, "w": 0.200, "h": 0.016}},
            "subhead": {"frameN": {"x": 0.110, "y": 0.668, "w": 0.700, "h": 0.070},
                        "text": {"align": "left"}},
            "body": {"frameN": {"x": 0.110, "y": 0.760, "w": 0.650, "h": 0.075},
                     "text": {"align": "left"}},
            "caption": {"frameN": {"x": 0.110, "y": 0.872, "w": 0.600, "h": 0.038},
                        "text": {"align": "left"}},
        }),
    ],
)


POST_TYPE_SQUARE = TemplateSkeleton(
    id="tpl_post_type_sq_01",
    name="Square — statement type",
    kind="post", aspect="1:1",
    tags=["text-only", "typographic", "statement", "bold", "announcement", "quote",
          "minimal"],
    description=(
        "Square typographic statement. A field of dots anchors the upper left, the "
        "statement is set very large across the middle, and a rule, a detail line and a "
        "call to action close the lower third above a scalloped edge. Best for an "
        "announcement, a quotation, an opening hours card, a hiring notice or any "
        "message with no product to show."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("dots", motif="dots", x=0.080, y=0.080, w=0.300, h=0.085,
                 palette="accent", density=4, z=3),
        ornament("skirt", motif="scallop", x=0, y=0.945, w=1, h=0.055,
                 palette="accent", density=4, z=3),
        text("eyebrow", "caption", x=0.08, y=0.205, w=0.62, h=0.036, size_n=0.024,
             weight=700, max_chars=26, transform="uppercase", tracking_n=0.006,
             palette="accent", required=False, z=12),
        text("headline", "headline", x=0.075, y=0.255, w=0.860, h=0.330, size_n=0.115,
             weight=900, max_chars=42, transform="uppercase", line_height=0.94,
             tracking_n=-0.004, palette="on-primary", auto_height=True, z=12),
        ornament("rule", motif="divider", x=0.080, y=0.618, w=0.300, h=0.018,
                 palette="accent", density=3, z=11),
        text("subhead", "subhead", x=0.080, y=0.660, w=0.720, h=0.090, size_n=0.030,
             weight=400, max_chars=110, line_height=1.38, palette="on-primary",
             required=False, z=12),
        text("body", "body", x=0.080, y=0.770, w=0.660, h=0.070, size_n=0.020,
             weight=400, max_chars=190, line_height=1.55, palette="on-primary",
             required=False, auto_height=True, z=12),
        shape("cta_bg", "cta", x=0.080, y=0.860, w=0.380, h=0.062, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.080, y=0.860, w=0.380, h=0.062, size_n=0.025, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
    ],
    variants=[
        SkeletonVariant(id="centered", name="Centred", patch={
            "dots": {"frameN": {"x": 0.350, "y": 0.085, "w": 0.300, "h": 0.085}},
            "eyebrow": {"frameN": {"x": 0.15, "y": 0.205, "w": 0.70, "h": 0.036},
                        "text": {"align": "center"}},
            "headline": {"frameN": {"x": 0.075, "y": 0.255, "w": 0.860, "h": 0.330},
                         "text": {"align": "center"}},
            "rule": {"frameN": {"x": 0.350, "y": 0.618, "w": 0.300, "h": 0.018}},
            "subhead": {"frameN": {"x": 0.140, "y": 0.660, "w": 0.720, "h": 0.090},
                        "text": {"align": "center"}},
            "body": {"frameN": {"x": 0.170, "y": 0.770, "w": 0.660, "h": 0.070},
                     "text": {"align": "center"}},
            "cta_bg": {"frameN": {"x": 0.310, "y": 0.860, "w": 0.380, "h": 0.062}},
            "cta": {"frameN": {"x": 0.310, "y": 0.860, "w": 0.380, "h": 0.062}},
        }),
    ],
)


AD_TYPE = TemplateSkeleton(
    id="tpl_ad_type_01",
    name="Ad — offer, no product",
    kind="ad", aspect="1.91:1",
    tags=["text-only", "typographic", "promotional", "offer", "landscape", "campaign"],
    description=(
        "Landscape advertising unit with no photograph. A chevron flash marks the right "
        "edge, the offer is set large and ranged left, and a detail line and a pill call "
        "to action sit beneath a short rule. Best for a discount code, an event date, a "
        "service offer or any campaign unit that is carried by the offer itself."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("flash", motif="chevrons", x=0.760, y=0.180, w=0.190, h=0.640,
                 palette="accent", density=4, opacity=0.85, z=3),
        text("eyebrow", "caption", x=0.055, y=0.120, w=0.45, h=0.070, size_n=0.048,
             weight=700, max_chars=24, transform="uppercase", tracking_n=0.006,
             palette="accent", required=False, z=12),
        text("headline", "headline", x=0.050, y=0.215, w=0.660, h=0.260, size_n=0.190,
             weight=900, max_chars=26, transform="uppercase", line_height=0.92,
             tracking_n=-0.004, palette="on-primary", z=12),
        ornament("rule", motif="divider", x=0.055, y=0.510, w=0.240, h=0.036,
                 palette="accent", density=3, z=11),
        text("subhead", "subhead", x=0.055, y=0.575, w=0.640, h=0.140, size_n=0.058,
             weight=400, max_chars=100, line_height=1.35, palette="on-primary",
             required=False, z=12),
        shape("cta_bg", "cta", x=0.055, y=0.760, w=0.330, h=0.130, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.055, y=0.760, w=0.330, h=0.130, size_n=0.055, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.004, palette="on-accent", required=False, z=13),
    ],
    variants=[
        SkeletonVariant(id="centered", name="Centred, no flash", patch={
            "flash": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "eyebrow": {"frameN": {"x": 0.20, "y": 0.120, "w": 0.60, "h": 0.070},
                        "text": {"align": "center"}},
            "headline": {"frameN": {"x": 0.10, "y": 0.215, "w": 0.80, "h": 0.260},
                         "text": {"align": "center"}},
            "rule": {"frameN": {"x": 0.380, "y": 0.510, "w": 0.240, "h": 0.036}},
            "subhead": {"frameN": {"x": 0.18, "y": 0.575, "w": 0.64, "h": 0.140},
                        "text": {"align": "center"}},
            "cta_bg": {"frameN": {"x": 0.335, "y": 0.760, "w": 0.330, "h": 0.130}},
            "cta": {"frameN": {"x": 0.335, "y": 0.760, "w": 0.330, "h": 0.130}},
        }),
    ],
)


THUMB_TYPE = TemplateSkeleton(
    id="tpl_thumb_type_01",
    name="Thumbnail — type-only shout",
    kind="thumbnail", aspect="16:9",
    tags=["text-only", "typographic", "bold", "video", "youtube", "loud", "statement"],
    description=(
        "Landscape video thumbnail with no photograph, built to survive being shrunk to "
        "a strip. Diagonal stripes sit behind, the headline is set enormous with a "
        "contrasting outline, and an eyebrow and a short kicker frame it above and "
        "below. Best for a video title, an episode number, a topic card or a chapter "
        "marker."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("stripes", motif="stripes", x=0, y=0, w=1, h=1, palette="accent",
                 density=3, opacity=0.20, z=1,
                 constraints=con("stretch", "stretch", priority=12, optional=True)),
        text("eyebrow", "caption", x=0.070, y=0.105, w=0.500, h=0.090, size_n=0.060,
             weight=700, max_chars=22, transform="uppercase", tracking_n=0.006,
             palette="accent", required=False, z=12),
        text("headline", "headline", x=0.060, y=0.230, w=0.880, h=0.420, size_n=0.250,
             weight=900, max_chars=24, transform="uppercase", line_height=0.90,
             tracking_n=-0.006, palette="on-primary", stroke_n=0.006,
             stroke_palette="accent", z=12),
        ornament("rule", motif="divider", x=0.070, y=0.700, w=0.300, h=0.048,
                 palette="accent", density=3, z=11),
        text("subhead", "subhead", x=0.070, y=0.780, w=0.700, h=0.130, size_n=0.072,
             weight=700, max_chars=46, line_height=1.20, palette="on-primary",
             required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="centered", name="Centred, no stripes", patch={
            "stripes": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "eyebrow": {"frameN": {"x": 0.25, "y": 0.105, "w": 0.50, "h": 0.090},
                        "text": {"align": "center"}},
            "headline": {"frameN": {"x": 0.060, "y": 0.230, "w": 0.880, "h": 0.420},
                         "text": {"align": "center"}},
            "rule": {"frameN": {"x": 0.350, "y": 0.700, "w": 0.300, "h": 0.048}},
            "subhead": {"frameN": {"x": 0.150, "y": 0.780, "w": 0.700, "h": 0.130},
                        "text": {"align": "center"}},
        }),
    ],
)


FLYER_TYPE = TemplateSkeleton(
    id="tpl_flyer_type_01",
    name="Flyer — type-only notice",
    kind="flyer", aspect="1:1.414",
    tags=["text-only", "typographic", "event", "notice", "print", "announcement",
          "listing"],
    description=(
        "Portrait A-series notice carried entirely by type. A ruled border holds the "
        "page, the title is set large under an eyebrow, and the details run as a "
        "subhead, a long body paragraph and a footer line, separated by rules. Best for "
        "an event notice, a class timetable, a menu, a hiring notice or any handout "
        "whose job is to be read rather than looked at."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("frame", motif="frame-rule", x=0.060, y=0.042, w=0.880, h=0.916,
                 palette="accent", density=2, stroke_n=0.0012, opacity=0.8, z=2,
                 constraints=con("center", "top", priority=12, optional=True)),
        text("eyebrow", "caption", x=0.140, y=0.110, w=0.720, h=0.026, size_n=0.016,
             weight=600, max_chars=30, align="center", transform="uppercase",
             tracking_n=0.007, palette="accent", required=False, z=12),
        text("headline", "headline", x=0.100, y=0.152, w=0.800, h=0.150, size_n=0.072,
             weight=700, max_chars=40, align="center", line_height=1.02,
             tracking_n=-0.002, palette="on-primary", z=12),
        ornament("rule", motif="divider", x=0.400, y=0.322, w=0.200, h=0.014,
                 palette="accent", density=2, z=11),
        text("subhead", "subhead", x=0.130, y=0.358, w=0.740, h=0.070, size_n=0.026,
             weight=400, max_chars=100, align="center", line_height=1.38,
             palette="on-primary", required=False, z=12),
        text("body", "body", x=0.150, y=0.460, w=0.700, h=0.240, size_n=0.0165,
             weight=400, max_chars=520, align="center", line_height=1.62,
             palette="on-primary", required=False, auto_height=True, z=12),
        ornament("rule_b", motif="divider", x=0.400, y=0.752, w=0.200, h=0.014,
                 palette="accent", density=2, z=11),
        text("caption", "caption", x=0.150, y=0.790, w=0.700, h=0.060, size_n=0.019,
             weight=600, max_chars=90, align="center", line_height=1.45,
             palette="accent", required=False, z=12),
        text("cta", "cta", x=0.200, y=0.878, w=0.600, h=0.040, size_n=0.018, weight=700,
             max_chars=40, align="center", valign="middle", transform="uppercase",
             tracking_n=0.006, palette="on-primary", required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="left", name="Ranged left, no border", patch={
            "frame": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "eyebrow": {"frameN": {"x": 0.100, "y": 0.110, "w": 0.720, "h": 0.026},
                        "text": {"align": "left"}},
            "headline": {"frameN": {"x": 0.100, "y": 0.152, "w": 0.800, "h": 0.150},
                         "text": {"align": "left"}},
            "rule": {"frameN": {"x": 0.100, "y": 0.322, "w": 0.200, "h": 0.014}},
            "subhead": {"frameN": {"x": 0.100, "y": 0.358, "w": 0.740, "h": 0.070},
                        "text": {"align": "left"}},
            "body": {"frameN": {"x": 0.100, "y": 0.460, "w": 0.700, "h": 0.240},
                     "text": {"align": "left"}},
            "rule_b": {"frameN": {"x": 0.100, "y": 0.752, "w": 0.200, "h": 0.014}},
            "caption": {"frameN": {"x": 0.100, "y": 0.790, "w": 0.700, "h": 0.060},
                        "text": {"align": "left"}},
            "cta": {"frameN": {"x": 0.100, "y": 0.878, "w": 0.600, "h": 0.040},
                    "text": {"align": "left"}},
        }),
    ],
)


STORY_SHOWCASE = TemplateSkeleton(
    id="tpl_story_showcase_01",
    name="Story — stacked three-up",
    kind="story", aspect="9:16",
    tags=["subject", "multi", "collection", "range", "vertical", "modern", "product",
          "promotional"],
    description=(
        "Vertical story showing three cutouts stacked down the canvas over alternating "
        "tinted bands, with the headline at the top, a short line of detail between the "
        "second and third, and a call to action closing the bottom. Best for a product "
        "range, a three-step process, a menu or a set of offers in a single scroll."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("band_a", motif="arc-band", x=-0.25, y=0.235, w=1.50, h=0.150,
                 palette="accent", density=3, opacity=0.22, z=1),
        ornament("band_b", motif="arc-band", x=-0.25, y=0.545, w=1.50, h=0.150,
                 palette="accent", density=3, opacity=0.22, z=1),
        text("eyebrow", "caption", x=0.10, y=0.070, w=0.80, h=0.022, size_n=0.016,
             weight=700, max_chars=26, align="center", transform="uppercase",
             tracking_n=0.006, palette="accent", required=False, z=12),
        text("headline", "headline", x=0.08, y=0.098, w=0.84, h=0.090, size_n=0.048,
             weight=900, max_chars=28, align="center", transform="uppercase",
             line_height=0.96, tracking_n=-0.003, palette="on-primary", z=12),
        image("subject", "subject", x=0.170, y=0.205, w=0.660, h=0.200,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=8,
              effects=[shadow(0.008, 0.018, 0.26)],
              constraints=con("center", "middle", lock=True, priority=95, overlap=True)),
        image("subject_b", "subject", subject_index=1, x=0.170, y=0.435, w=0.660, h=0.200,
              prompt=SUBJECT_SIDE, transparent=True, fit="contain", z=8, required=False,
              effects=[shadow(0.008, 0.018, 0.26)],
              constraints=con("center", "middle", lock=True, priority=82, optional=True,
                              overlap=True)),
        text("subhead", "subhead", x=0.120, y=0.658, w=0.760, h=0.050, size_n=0.019,
             weight=400, max_chars=90, align="center", line_height=1.40,
             palette="on-primary", required=False, z=12),
        image("subject_c", "subject", subject_index=2, x=0.170, y=0.715, w=0.660, h=0.190,
              prompt=SUBJECT_DETAIL, transparent=True, fit="contain", z=8, required=False,
              effects=[shadow(0.008, 0.018, 0.26)],
              constraints=con("center", "middle", lock=True, priority=78, optional=True,
                              overlap=True)),
        shape("cta_bg", "cta", x=0.290, y=0.920, w=0.420, h=0.045, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.290, y=0.920, w=0.420, h=0.045, size_n=0.018, weight=700,
             max_chars=22, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
    ],
    variants=[
        SkeletonVariant(id="hero", name="Hero large, two small beneath", patch={
            "subject": {"frameN": {"x": 0.110, "y": 0.195, "w": 0.780, "h": 0.300}},
            "subject_b": {"frameN": {"x": 0.090, "y": 0.530, "w": 0.380, "h": 0.190}},
            "subject_c": {"frameN": {"x": 0.530, "y": 0.530, "w": 0.380, "h": 0.190}},
            "subhead": {"frameN": {"x": 0.120, "y": 0.760, "w": 0.760, "h": 0.090}},
        }),
    ],
)


STORY_TYPE_ORNATE = TemplateSkeleton(
    id="tpl_story_type_ornate_01",
    name="Story — ornamented type card",
    kind="story", aspect="9:16",
    tags=["text-only", "typographic", "festive", "greeting", "ornate", "vertical",
          "statement", "announcement"],
    description=(
        "Vertical type-only card dressed with procedural ornament: a garland along the "
        "top, a ruled border, a divider under the title and a scalloped band closing the "
        "bottom. The message is set centred and large through the middle third. Best for "
        "a festival greeting with no photograph, a quotation, an announcement or a "
        "thank-you card."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("frame", motif="border", x=0, y=0, w=1, h=1, palette="accent",
                 density=2, stroke_n=0.0012, opacity=0.7, z=2,
                 constraints=con("stretch", "stretch", priority=12, optional=True)),
        ornament("garland", motif="garland", x=0, y=-0.004, w=1, h=0.058,
                 palette="accent", density=5, z=5),
        ornament("skirt", motif="scallop", x=0, y=0.962, w=1, h=0.038,
                 palette="accent", density=4, z=5),
        text("eyebrow", "caption", x=0.15, y=0.155, w=0.70, h=0.020, size_n=0.0125,
             weight=600, max_chars=26, align="center", transform="uppercase",
             tracking_n=0.006, palette="accent", required=False, z=12),
        text("headline", "headline", x=0.10, y=0.220, w=0.80, h=0.200, size_n=0.058,
             weight=700, max_chars=60, align="center", valign="middle",
             line_height=1.12, palette="on-primary", auto_height=True, z=12),
        ornament("divider", motif="divider", x=0.360, y=0.455, w=0.280, h=0.016,
                 palette="accent", density=3, z=11),
        text("subhead", "subhead", x=0.130, y=0.500, w=0.740, h=0.090, size_n=0.023,
             weight=400, max_chars=110, align="center", line_height=1.42,
             palette="on-primary", required=False, z=12),
        text("body", "body", x=0.160, y=0.625, w=0.680, h=0.110, size_n=0.016,
             weight=400, max_chars=280, align="center", line_height=1.60,
             palette="on-primary", required=False, auto_height=True, z=12),
        ornament("rule_b", motif="divider", x=0.400, y=0.775, w=0.200, h=0.014,
                 palette="accent", density=2, z=11),
        text("caption", "caption", x=0.150, y=0.815, w=0.700, h=0.040, size_n=0.016,
             weight=600, max_chars=50, align="center", transform="uppercase",
             tracking_n=0.006, palette="accent", required=False, z=12),
        text("cta", "cta", x=0.200, y=0.885, w=0.600, h=0.036, size_n=0.016, weight=700,
             max_chars=30, align="center", valign="middle", transform="uppercase",
             tracking_n=0.005, palette="on-primary", required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="plain", name="No garland or border", patch={
            "frame": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "garland": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "skirt": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "headline": {"text": {"sizeN": 0.066}},
        }),
    ],
)


BANNER_TYPE_SPLIT = TemplateSkeleton(
    id="tpl_banner_type_split_01",
    name="Banner — ruled type strip",
    kind="banner", aspect="3:1",
    tags=["text-only", "typographic", "header", "web", "cover", "announcement",
          "minimal"],
    description=(
        "Wide strip carried by type alone, divided by a vertical rule: the title sits "
        "left with an eyebrow above it, the detail line and call to action sit right. A "
        "field of dots closes the far edge. Best for a site header, an email banner, a "
        "profile cover or an announcement bar."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("dots", motif="dots", x=0.845, y=0.250, w=0.120, h=0.500,
                 palette="accent", density=4, opacity=0.55, z=3),
        text("eyebrow", "caption", x=0.045, y=0.185, w=0.34, h=0.110, size_n=0.078,
             weight=700, max_chars=24, transform="uppercase", tracking_n=0.006,
             palette="accent", required=False, z=12),
        text("headline", "headline", x=0.040, y=0.330, w=0.420, h=0.340, size_n=0.290,
             weight=900, max_chars=26, transform="uppercase", line_height=0.94,
             tracking_n=-0.005, palette="on-primary", z=12),
        shape("rule", "decoration", x=0.492, y=0.180, w=0.004, h=0.640, palette="accent",
              required=False, z=4),
        text("subhead", "subhead", x=0.535, y=0.250, w=0.290, h=0.240, size_n=0.105,
             weight=400, max_chars=90, line_height=1.30, palette="on-primary",
             required=False, z=12),
        shape("cta_bg", "cta", x=0.535, y=0.560, w=0.245, h=0.190, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.535, y=0.560, w=0.245, h=0.190, size_n=0.092, weight=700,
             max_chars=18, align="center", valign="middle", transform="uppercase",
             tracking_n=0.004, palette="on-accent", required=False, z=13),
    ],
    variants=[
        SkeletonVariant(id="centered", name="Centred, no split", patch={
            "rule": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "dots": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "eyebrow": {"frameN": {"x": 0.20, "y": 0.135, "w": 0.60, "h": 0.110},
                        "text": {"align": "center"}},
            "headline": {"frameN": {"x": 0.10, "y": 0.275, "w": 0.80, "h": 0.340},
                         "text": {"align": "center"}},
            "subhead": {"frameN": {"x": 0.20, "y": 0.660, "w": 0.60, "h": 0.180},
                        "text": {"align": "center"}},
            "cta_bg": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
            "cta": {"frameN": {"x": 0.5, "y": 0.5, "w": 0.001, "h": 0.001}},
        }),
    ],
)


# --------------------------------------------------------------------------------------
# Information-dense layouts
#
# Everything above is built for a design with one thing to say. A large share of real
# requests are not that: a salon promo carries an offer, a price, four services, a phone
# number and an opening date, and a three-slot layout answers it by throwing most of that
# away. Retrieval has no way to prefer a fuller layout if the corpus contains none, so
# these exist to be that option — every band of the canvas occupied, and a slot for each
# kind of fact a business actually puts on a poster.
#
# Almost every slot here is optional. That is what lets one skeleton serve both the
# request that carries all of it and the one that carries half: the unfilled slots drop
# out and the solver closes the gaps, rather than the design shipping with holes.
# --------------------------------------------------------------------------------------

POST_OFFER_DENSE = TemplateSkeleton(
    id="tpl_post_offer_dense_01",
    name="Post — full offer sheet",
    kind="post", aspect="4:5",
    tags=["promotional", "offer", "discount", "sale", "dense", "text-heavy", "business",
          "contact", "subject", "services", "bold"],
    description=(
        "Information-dense promotional post. An eyebrow and a two-line display headline "
        "sit top-left with a stamped discount seal punched into the top-right corner, "
        "the offer and price run as one band beneath them, the product is photographed "
        "centre, three short feature lines sit in a row below it, and a pill call to "
        "action leads into a full-width contact strip carrying phone, website and "
        "address with the terms beneath. Best for a sale, a service package, a clinic or "
        "salon promotion — any request that arrives with a discount, a list and a phone "
        "number and needs all three on the canvas."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY_BOTTOM,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0.52, w=1, h=0.48, scrim=True, scrim_angle=180,
              palette="primary", required=False, z=2,
              constraints=con("stretch", "bottom", priority=20, optional=True)),
        text("eyebrow", "caption", x=0.055, y=0.045, w=0.55, h=0.032, size_n=0.020,
             weight=700, max_chars=26, transform="uppercase", tracking_n=0.005,
             palette="accent", required=False, z=12),
        text("headline", "headline", x=0.055, y=0.085, w=0.63, h=0.125, size_n=0.072,
             weight=900, max_chars=28, transform="uppercase", line_height=0.94,
             tracking_n=-0.003, palette="on-primary", z=12),
        ornament("seal", motif="badge", x=0.705, y=0.040, w=0.245, h=0.195,
                 palette="accent", density=3, z=13),
        text("badge", "badge", x=0.720, y=0.100, w=0.215, h=0.078, size_n=0.034,
             weight=900, max_chars=12, align="center", valign="middle",
             transform="uppercase", palette="on-accent", required=False, z=14,
             constraints=con("center", "top", priority=45, optional=True, overlap=True)),
        text("offer", "offer", x=0.055, y=0.220, w=0.52, h=0.072, size_n=0.046,
             weight=800, max_chars=26, transform="uppercase", line_height=1.02,
             palette="accent", required=False, z=12),
        text("price", "price", x=0.600, y=0.226, w=0.345, h=0.062, size_n=0.040,
             weight=800, max_chars=16, align="right", valign="middle",
             palette="on-primary", required=False, z=12),
        image("subject", "subject", x=0.290, y=0.305, w=0.420, h=0.265,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=8,
              effects=[shadow(0.012, 0.026, 0.28)],
              constraints=con("center", "middle", lock=True, priority=95)),
        prop("companion", x=0.045, y=0.360, w=0.230, h=0.185, prompt=SUBJECT_SIDE,
             subject_index=1, z=7, rotation=-5.0,
             effects=[shadow(0.008, 0.018, 0.20)]),
        prop("companion_b", x=0.730, y=0.360, w=0.230, h=0.185, prompt=SUBJECT_DETAIL,
             subject_index=2, z=7, rotation=5.0,
             effects=[shadow(0.008, 0.018, 0.20)]),
        text("feature_1", "feature", x=0.055, y=0.592, w=0.275, h=0.058, size_n=0.019,
             weight=600, max_chars=34, align="center", valign="middle",
             line_height=1.30, palette="on-primary", required=False, z=12),
        text("feature_2", "feature", x=0.362, y=0.592, w=0.275, h=0.058, size_n=0.019,
             weight=600, max_chars=34, align="center", valign="middle",
             line_height=1.30, palette="on-primary", required=False, z=12),
        text("feature_3", "feature", x=0.670, y=0.592, w=0.275, h=0.058, size_n=0.019,
             weight=600, max_chars=34, align="center", valign="middle",
             line_height=1.30, palette="on-primary", required=False, z=12),
        ornament("rule", motif="divider", x=0.330, y=0.664, w=0.340, h=0.018,
                 palette="accent", density=3, z=11),
        text("subhead", "subhead", x=0.110, y=0.694, w=0.780, h=0.062, size_n=0.021,
             weight=400, max_chars=105, align="center", line_height=1.40,
             palette="on-primary", required=False, z=12),
        shape("cta_bg", "cta", x=0.300, y=0.774, w=0.400, h=0.058, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.300, y=0.774, w=0.400, h=0.058, size_n=0.022, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
        shape("contact_bg", "contact", x=0, y=0.845, w=1, h=0.098, palette="accent",
              required=False, z=10,
              constraints=con("stretch", "bottom", priority=25, optional=True)),
        text("contact", "contact", x=0.080, y=0.855, w=0.840, h=0.046, size_n=0.019,
             weight=600, max_chars=72, align="center", valign="middle",
             palette="on-accent", required=False, z=13),
        text("terms", "terms", x=0.100, y=0.903, w=0.800, h=0.030, size_n=0.013,
             weight=400, max_chars=80, align="center", valign="middle",
             palette="on-accent", required=False, z=13,
             constraints=con("center", "bottom", priority=20, optional=True,
                             overlap=True)),
    ],
    variants=[
        SkeletonVariant(id="panel", name="Flat colour ground, no photograph", patch={
            "bg": {"layerType": "shape", "image": None,
                   "shape": {"shape": "rect", "radiusN": 0, "fillFromPalette": True,
                             "gradientScrim": False, "gradientAngle": 90,
                             "motif": None, "strokeWidthN": 0, "density": 3},
                   "paletteRole": "primary"},
            "scrim": {"required": False, "opacity": 0.0},
        }),
        SkeletonVariant(id="stacked", name="Offer stacked under the headline", patch={
            "headline": {"frameN": {"x": 0.055, "y": 0.075, "w": 0.63, "h": 0.110}},
            "offer": {"frameN": {"x": 0.055, "y": 0.196, "w": 0.62, "h": 0.070},
                      "text": {"align": "left"}},
            "price": {"frameN": {"x": 0.055, "y": 0.272, "w": 0.40, "h": 0.048},
                      "text": {"align": "left"}},
        }),
    ],
)


POST_SERVICES_SQUARE = TemplateSkeleton(
    id="tpl_post_services_sq_01",
    name="Post — services menu with contact",
    kind="post", aspect="1:1",
    tags=["business", "services", "menu", "dense", "text-heavy", "contact", "subject",
          "multi", "list", "offer", "clinic", "salon"],
    description=(
        "Square services board. A headline and subhead sit over a colour header band, "
        "three different subjects are photographed in a row beneath it with a short "
        "feature line under each, and a price line, a pill call to action and a contact "
        "strip carrying phone and website close the design. Best for a salon, a clinic, "
        "a studio, a restaurant menu or any business showing several offerings at once "
        "rather than one hero product."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("header", "decoration", x=0, y=0, w=1, h=0.255, palette="accent",
              required=False, z=1,
              constraints=con("stretch", "top", priority=25, optional=True)),
        text("eyebrow", "caption", x=0.080, y=0.048, w=0.840, h=0.034, size_n=0.021,
             weight=700, max_chars=28, align="center", transform="uppercase",
             tracking_n=0.006, palette="on-accent", required=False, z=12),
        text("headline", "headline", x=0.070, y=0.092, w=0.860, h=0.092, size_n=0.062,
             weight=900, max_chars=26, align="center", transform="uppercase",
             line_height=0.96, tracking_n=-0.002, palette="on-accent", z=12),
        text("subhead", "subhead", x=0.130, y=0.196, w=0.740, h=0.044, size_n=0.019,
             weight=400, max_chars=80, align="center", line_height=1.35,
             palette="on-accent", required=False, z=12),
        image("subject", "subject", x=0.055, y=0.300, w=0.270, h=0.230,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=8,
              effects=[shadow(0.010, 0.022, 0.24)],
              constraints=con("left", "middle", lock=True, priority=95)),
        image("subject_b", "subject", subject_index=1, x=0.365, y=0.300, w=0.270,
              h=0.230, prompt=SUBJECT_ANGLED, transparent=True, fit="contain", z=8,
              required=False, effects=[shadow(0.010, 0.022, 0.24)],
              constraints=con("center", "middle", lock=True, priority=80,
                              optional=True)),
        image("subject_c", "subject", subject_index=2, x=0.675, y=0.300, w=0.270,
              h=0.230, prompt=SUBJECT_SIDE, transparent=True, fit="contain", z=8,
              required=False, effects=[shadow(0.010, 0.022, 0.24)],
              constraints=con("right", "middle", lock=True, priority=76, optional=True)),
        text("feature_1", "feature", x=0.048, y=0.548, w=0.284, h=0.056, size_n=0.018,
             weight=600, max_chars=30, align="center", valign="top", line_height=1.30,
             palette="on-primary", required=False, z=12),
        text("feature_2", "feature", x=0.358, y=0.548, w=0.284, h=0.056, size_n=0.018,
             weight=600, max_chars=30, align="center", valign="top", line_height=1.30,
             palette="on-primary", required=False, z=12),
        text("feature_3", "feature", x=0.668, y=0.548, w=0.284, h=0.056, size_n=0.018,
             weight=600, max_chars=30, align="center", valign="top", line_height=1.30,
             palette="on-primary", required=False, z=12),
        ornament("rule", motif="divider", x=0.340, y=0.622, w=0.320, h=0.018,
                 palette="accent", density=3, z=11),
        text("offer", "offer", x=0.100, y=0.654, w=0.800, h=0.062, size_n=0.038,
             weight=800, max_chars=28, align="center", valign="middle",
             transform="uppercase", palette="accent", required=False, z=12),
        text("price", "price", x=0.200, y=0.726, w=0.600, h=0.048, size_n=0.030,
             weight=700, max_chars=20, align="center", valign="middle",
             palette="on-primary", required=False, z=12),
        shape("cta_bg", "cta", x=0.310, y=0.766, w=0.380, h=0.058, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.310, y=0.766, w=0.380, h=0.058, size_n=0.021, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
        shape("contact_bg", "contact", x=0, y=0.842, w=1, h=0.091, palette="accent",
              required=False, z=10,
              constraints=con("stretch", "bottom", priority=25, optional=True)),
        text("contact", "contact", x=0.080, y=0.852, w=0.840, h=0.042, size_n=0.018,
             weight=600, max_chars=70, align="center", valign="middle",
             palette="on-accent", required=False, z=13),
        text("terms", "terms", x=0.120, y=0.896, w=0.760, h=0.028, size_n=0.012,
             weight=400, max_chars=72, align="center", valign="middle",
             palette="on-accent", required=False, z=13,
             constraints=con("center", "bottom", priority=20, optional=True,
                             overlap=True)),
    ],
    variants=[
        SkeletonVariant(id="duo", name="Two subjects, larger", patch={
            "subject": {"frameN": {"x": 0.075, "y": 0.295, "w": 0.390, "h": 0.245}},
            "subject_b": {"frameN": {"x": 0.535, "y": 0.295, "w": 0.390, "h": 0.245}},
            "subject_c": {"required": False, "opacity": 0.0},
            "feature_1": {"frameN": {"x": 0.070, "y": 0.552, "w": 0.400, "h": 0.056}},
            "feature_2": {"frameN": {"x": 0.530, "y": 0.552, "w": 0.400, "h": 0.056}},
            "feature_3": {"required": False, "opacity": 0.0},
        }),
    ],
)


FLYER_BUSINESS = TemplateSkeleton(
    id="tpl_flyer_business_01",
    name="Flyer — business offer sheet",
    kind="flyer", aspect="1:1.414",
    tags=["business", "flyer", "dense", "text-heavy", "contact", "offer", "discount",
          "services", "subject", "multi", "list", "print"],
    description=(
        "A4 business flyer carrying a full page of information. A colour header band "
        "holds the eyebrow and headline, a discount seal sits beside them, the subject "
        "is photographed large in the upper half with a second item tucked beside it, "
        "four feature lines run down the middle as a list, and an offer, a price, a call "
        "to action, a dated event line and a full contact block close the page above the "
        "terms. Best for a handout, a leaflet, a clinic or workshop announcement, a "
        "service menu — anything printed that has to answer every question at once."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("header", "decoration", x=0, y=0, w=1, h=0.185, palette="accent",
              required=False, z=1,
              constraints=con("stretch", "top", priority=25, optional=True)),
        text("eyebrow", "caption", x=0.070, y=0.036, w=0.560, h=0.026, size_n=0.0150,
             weight=700, max_chars=30, transform="uppercase", tracking_n=0.005,
             palette="on-accent", required=False, z=12),
        text("headline", "headline", x=0.070, y=0.070, w=0.560, h=0.086, size_n=0.042,
             weight=900, max_chars=32, transform="uppercase", line_height=0.98,
             tracking_n=-0.002, palette="on-accent", z=12),
        ornament("seal", motif="badge", x=0.690, y=0.028, w=0.240, h=0.130,
                 palette="primary", density=3, z=13),
        text("badge", "badge", x=0.705, y=0.068, w=0.210, h=0.052, size_n=0.024,
             weight=900, max_chars=12, align="center", valign="middle",
             transform="uppercase", palette="on-primary", required=False, z=14,
             constraints=con("center", "top", priority=45, optional=True, overlap=True)),
        text("subhead", "subhead", x=0.070, y=0.205, w=0.860, h=0.052, size_n=0.0175,
             weight=400, max_chars=110, line_height=1.40, palette="on-primary",
             required=False, z=12),
        image("subject", "subject", x=0.090, y=0.285, w=0.520, h=0.230,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=8,
              effects=[shadow(0.008, 0.020, 0.26)],
              constraints=con("left", "middle", lock=True, priority=95)),
        image("subject_b", "subject", subject_index=1, x=0.640, y=0.310, w=0.280,
              h=0.185, prompt=SUBJECT_ANGLED, transparent=True, fit="contain", z=8,
              required=False, effects=[shadow(0.006, 0.016, 0.20)],
              constraints=con("right", "middle", lock=True, priority=78, optional=True)),
        ornament("rule", motif="divider", x=0.340, y=0.535, w=0.320, h=0.014,
                 palette="accent", density=3, z=11),
        text("feature_1", "feature", x=0.120, y=0.566, w=0.760, h=0.040, size_n=0.0165,
             weight=600, max_chars=44, valign="middle", palette="on-primary",
             required=False, z=12),
        text("feature_2", "feature", x=0.120, y=0.612, w=0.760, h=0.040, size_n=0.0165,
             weight=600, max_chars=44, valign="middle", palette="on-primary",
             required=False, z=12),
        text("feature_3", "feature", x=0.120, y=0.658, w=0.760, h=0.040, size_n=0.0165,
             weight=600, max_chars=44, valign="middle", palette="on-primary",
             required=False, z=12),
        text("feature_4", "feature", x=0.120, y=0.704, w=0.760, h=0.040, size_n=0.0165,
             weight=600, max_chars=44, valign="middle", palette="on-primary",
             required=False, z=12),
        text("offer", "offer", x=0.070, y=0.762, w=0.520, h=0.052, size_n=0.032,
             weight=800, max_chars=26, transform="uppercase", valign="middle",
             palette="accent", required=False, z=12),
        text("price", "price", x=0.620, y=0.762, w=0.310, h=0.052, size_n=0.028,
             weight=800, max_chars=16, align="right", valign="middle",
             palette="on-primary", required=False, z=12),
        text("event", "event", x=0.070, y=0.824, w=0.860, h=0.034, size_n=0.0160,
             weight=600, max_chars=62, valign="middle", palette="on-primary",
             required=False, z=12),
        shape("cta_bg", "cta", x=0.070, y=0.872, w=0.330, h=0.046, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.070, y=0.872, w=0.330, h=0.046, size_n=0.0175, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
        text("contact", "contact", x=0.430, y=0.866, w=0.500, h=0.058, size_n=0.0155,
             weight=600, max_chars=90, align="right", valign="middle", line_height=1.35,
             auto_height=True, palette="on-primary", required=False, z=12),
        text("terms", "terms", x=0.070, y=0.924, w=0.860, h=0.026, size_n=0.0110,
             weight=400, max_chars=100, valign="middle", palette="on-primary",
             required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="photo", name="Photographic header", patch={
            "header": {"layerType": "image", "shape": None, "role": "background",
                       "image": {"promptTemplate": BG_EMPTY_BOTTOM,
                                 "transparent": False, "fit": "cover",
                                 "subjectIndex": 0},
                       "frameN": {"x": 0, "y": 0, "w": 1, "h": 0.260}},
            "subhead": {"frameN": {"x": 0.070, "y": 0.278, "w": 0.860, "h": 0.048}},
            "subject": {"frameN": {"x": 0.090, "y": 0.340, "w": 0.520, "h": 0.185}},
            "subject_b": {"frameN": {"x": 0.640, "y": 0.355, "w": 0.280, "h": 0.155}},
        }),
    ],
)


ALL_SKELETONS: list[TemplateSkeleton] = [
    STORY_HERO, STORY_SPLIT, STORY_CENTER, STORY_TYPE,
    POST_PRODUCT, POST_EDITORIAL, POST_TYPE, POST_SQUARE_PROMO,
    POSTER_GIG, POSTER_MINIMAL, POSTER_PHOTO,
    BANNER_SPLIT, BANNER_CENTER,
    THUMB_SPLIT, THUMB_CENTER,
    AD_PRODUCT,
    FLYER_EVENT,
    STORY_FESTIVE, POST_FESTIVE, POST_FESTIVE_SQUARE, POSTER_ORNATE,
    POST_BURST, POST_DOTTED, POST_FASHION, POST_DROP, POST_SHOWCASE,
    # Coverage fill — see the block comment above POST_SALE.
    POST_SALE, POST_GRID, POST_DUO, POST_FESTIVE_MULTI, POST_PRODUCT_SQUARE,
    POST_QUOTE, POST_TYPE_SQUARE, AD_TYPE, THUMB_TYPE, FLYER_TYPE,
    STORY_SHOWCASE, STORY_TYPE_ORNATE, BANNER_TYPE_SPLIT,
    # Information-dense — see the block comment above POST_OFFER_DENSE.
    POST_OFFER_DENSE, POST_SERVICES_SQUARE, FLYER_BUSINESS,
    # Layered promotional work — see the module docstring of `skeletons_rich`.
    *RICH_SKELETONS,
]


def by_id(template_id: str) -> TemplateSkeleton | None:
    return next((s for s in ALL_SKELETONS if s.id == template_id), None)
