"""Layered promotional skeletons — the second half of the §1.2 corpus.

`skeletons.py` covers the layout archetypes: a hero, a split, a grid, a type-only poster.
Those are correct and they are plain, because each one is built from the same four or
five elements — a background, a subject, a headline, a CTA — laid out differently. Put a
yoga-studio promo, a burger ad and an Independence Day greeting next to the output and
the difference is not the arrangement, it is the *count and kind* of elements: a brand
lockup, a ticked service list, a stamped discount, three photographs each cut to a
different silhouette, a phone number with a handset beside it, a website in its own pill.

So these skeletons are deliberately dense in element TYPES rather than in slots:

  * pictograms (`icon`, `checklist`, `icon_text`) — a tick per service line, a handset
    beside the number, a pin beside the address;
  * masked photography (`photo`) — arches, circles, diamonds and squircles instead of a
    page of rectangles;
  * a brand lockup (`logo_lockup`) at the top, which is what makes a design read as a
    particular business's rather than as a template with a headline in it;
  * stamped offers — a seal or a diamond carrying an eyebrow, a figure and a note, the
    three-line discount stamp every sale layout in the reference set has;
  * two-register typography — a script line against a heavy display line.

Almost every slot is optional, for the reason given above POST_OFFER_DENSE: that is what
lets one skeleton serve the request carrying all of it and the request carrying half.
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
    SUBJECT,
    SUBJECT_ANGLED,
    SUBJECT_DETAIL,
    SUBJECT_FRONT,
    SUBJECT_SIDE,
    checklist,
    chip_row,
    con,
    icon,
    icon_text,
    image,
    logo_lockup,
    ornament,
    photo,
    prop,
    shadow,
    shape,
    text,
)

SQUARE = 1.0
PORTRAIT_45 = 0.8
STORY = 9 / 16
A4 = 1 / 1.414


# --------------------------------------------------------------------------------------
# Service boards — a brand, a promise, a ticked list of what you get, and how to book.
#
# The layout a studio, clinic, salon or agency actually posts. Everything the reference
# yoga board carries has a slot here: the lockup, the three-line display headline, the
# paragraph under it, six ticked services, a stamped member discount, a large portrait
# and two supporting frames, a booking pill, a phone number and a website.
# --------------------------------------------------------------------------------------

POST_CHECKLIST_SQUARE = TemplateSkeleton(
    id="tpl_post_checklist_sq_01",
    name="Post — service checklist board",
    kind="post", aspect="1:1",
    tags=["business", "services", "list", "checklist", "dense", "text-heavy", "contact",
          "subject", "multi", "offer", "discount", "clinic", "salon", "studio", "wellness",
          "fitness", "icons", "logo", "professional"],
    description=(
        "Editorial service board for a studio or clinic. A brand lockup sits top-left "
        "above a three-line display headline and a short paragraph, six ticked service "
        "lines run down the left column, a stamped diamond carries a member discount "
        "over the gutter, a tall portrait fills the right column with two smaller framed "
        "photographs beneath it, and a booking pill, a phone number with a handset and a "
        "website pill close the design. Best for a yoga or fitness studio, a dental or "
        "wellness clinic, a salon, a coaching or consulting practice — any business "
        "whose offer is a list of services and whose design has to end in a booking."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("field", motif="grid-dots", x=0.520, y=0.742, w=0.410, h=0.070,
                 palette="accent", density=2, opacity=0.30, z=1,
                 constraints=con("right", "middle", priority=12, optional=True)),
        *logo_lockup(x=0.070, y=0.044, w=0.36, h=0.054, aspect_ratio=SQUARE,
                     motif="icon-spark", size_n=0.017, palette="on-primary",
                     mark_palette="accent", z=14),
        text("headline", "headline", x=0.070, y=0.140, w=0.40, h=0.205, size_n=0.064,
             weight=900, max_chars=34, transform="uppercase", line_height=0.96,
             tracking_n=-0.002, palette="on-primary", z=12),
        text("body", "body", x=0.070, y=0.372, w=0.330, h=0.108, size_n=0.0185,
             weight=400, max_chars=170, line_height=1.52, palette="on-primary",
             required=False, z=12),
        *checklist(x=0.070, y=0.512, w=0.350, size_n=0.0178, count=6, row_h=0.050,
                   gap=0.004, motif="icon-check-circle", aspect_ratio=SQUARE,
                   palette="on-primary", icon_palette="accent", max_chars=26, z=12),
        # The stamp. Authored to overlap the portrait's lower-left corner, which is what
        # ties the two columns together — a seal floating in the gutter reads as a sticker.
        ornament("seal", motif="diamond", x=0.406, y=0.352, w=0.212, h=0.212,
                 palette="accent", density=3, z=13,
                 constraints=con("center", "middle", priority=22, optional=True,
                                 overlap=True)),
        text("offer", "offer", x=0.436, y=0.388, w=0.152, h=0.034, size_n=0.0175,
             weight=600, max_chars=12, align="center", valign="middle",
             palette="on-accent", required=False, z=14,
             constraints=con("center", "middle", priority=24, optional=True,
                             overlap=True)),
        text("badge", "badge", x=0.424, y=0.418, w=0.176, h=0.070, size_n=0.052,
             weight=900, max_chars=8, align="center", valign="middle",
             transform="uppercase", line_height=0.94, palette="on-accent",
             required=False, z=14,
             constraints=con("center", "middle", priority=26, optional=True,
                             overlap=True)),
        text("terms", "terms", x=0.418, y=0.486, w=0.188, h=0.046, size_n=0.0125,
             weight=600, max_chars=34, align="center", valign="top", line_height=1.24,
             palette="on-accent", required=False, z=14,
             constraints=con("center", "middle", priority=16, optional=True,
                             overlap=True)),
        *photo("hero", "subject", x=0.520, y=0.040, w=0.410, h=0.448, prompt=BG_EMPTY,
               mask="rounded", mask_radius_n=0.11, required=True, z=6, priority=92),
        *photo("tile_a", "object", x=0.520, y=0.512, w=0.195, h=0.200,
               prompt=SUBJECT_ANGLED, mask="rounded", mask_radius_n=0.16,
               subject_index=1, z=6, priority=58),
        *photo("tile_b", "object", x=0.735, y=0.512, w=0.195, h=0.200,
               prompt=SUBJECT_SIDE, mask="rounded", mask_radius_n=0.16,
               subject_index=2, z=6, priority=54),
        shape("cta_bg", "cta", x=0.070, y=0.858, w=0.290, h=0.062, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.070, y=0.858, w=0.290, h=0.062, size_n=0.0205, weight=700,
             max_chars=18, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
        text("caption", "caption", x=0.448, y=0.830, w=0.200, h=0.028, size_n=0.0145,
             weight=500, max_chars=20, valign="middle", palette="on-primary",
             required=False, z=12),
        *icon_text("contact_phone", "contact", motif="icon-phone", x=0.390, y=0.862,
                   w=0.255, h=0.054, size_n=0.0235, aspect_ratio=SQUARE,
                   palette="on-primary", icon_palette="accent", weight=700,
                   max_chars=18, z=12),
        shape("contact_web_bg", "contact", x=0.665, y=0.864, w=0.265, h=0.052,
              radius_n=0.5, palette="accent", required=False, z=11,
              pairs_with="contact_web"),
        text("contact_web", "contact", x=0.677, y=0.864, w=0.241, h=0.052,
             size_n=0.0165, weight=600, max_chars=28, align="center", valign="middle",
             palette="on-accent", required=False, z=13),
    ],
    variants=[
        SkeletonVariant(id="mirror", name="Photography left, copy right", patch={
            "hero": {"frameN": {"x": 0.070, "y": 0.040, "w": 0.410, "h": 0.448}},
            "tile_a": {"frameN": {"x": 0.070, "y": 0.512, "w": 0.195, "h": 0.200}},
            "tile_b": {"frameN": {"x": 0.285, "y": 0.512, "w": 0.195, "h": 0.200}},
            "seal": {"frameN": {"x": 0.390, "y": 0.352, "w": 0.212, "h": 0.212}},
        }),
        SkeletonVariant(id="arched", name="Arched portrait, no small frames", patch={
            "hero": {"frameN": {"x": 0.520, "y": 0.040, "w": 0.410, "h": 0.672},
                     "image": {"mask": "arch"}},
            "tile_a": {"required": False, "opacity": 0.0},
            "tile_b": {"required": False, "opacity": 0.0},
        }),
        SkeletonVariant(id="quiet", name="No stamp, longer list", patch={
            "seal": {"required": False, "opacity": 0.0},
            "offer": {"required": False, "opacity": 0.0},
            "badge": {"required": False, "opacity": 0.0},
            "terms": {"required": False, "opacity": 0.0},
            "body": {"frameN": {"x": 0.070, "y": 0.372, "w": 0.410, "h": 0.108}},
        }),
    ],
)


STORY_CHECKLIST = TemplateSkeleton(
    id="tpl_story_checklist_01",
    name="Story — service checklist",
    kind="story", aspect="9:16",
    tags=["business", "services", "list", "checklist", "dense", "text-heavy", "contact",
          "subject", "offer", "clinic", "salon", "studio", "wellness", "fitness",
          "icons", "logo"],
    description=(
        "Vertical service board. A brand lockup and an arched portrait fill the top "
        "third, a display headline and a short paragraph sit beneath them, five ticked "
        "service lines run down the middle with a stamped offer beside them, and a "
        "booking pill above a contact strip carrying a handset and a globe closes the "
        "story. Best for a studio, clinic or salon promoting a set of services to a "
        "phone screen, where the list has to be scannable in a few seconds."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        *photo("hero", "subject", x=0.0, y=0.0, w=1.0, h=0.360, prompt=BG_EMPTY_BOTTOM,
               mask="arch-down", required=True, z=4, priority=92,
               keyline=False),
        shape("scrim", "overlay", x=0, y=0.150, w=1, h=0.210, scrim=True,
              scrim_angle=180, palette="primary", required=False, z=5,
              constraints=con("stretch", "top", priority=18, optional=True)),
        *logo_lockup(x=0.070, y=0.040, w=0.50, h=0.038, aspect_ratio=STORY,
                     motif="icon-spark", size_n=0.0130, palette="on-primary",
                     mark_palette="accent", z=14, over_image=True),
        text("headline", "headline", x=0.070, y=0.400, w=0.700, h=0.150, size_n=0.052,
             weight=900, max_chars=40, transform="uppercase", line_height=0.96,
             tracking_n=-0.0018, palette="on-primary", z=12),
        text("body", "body", x=0.070, y=0.566, w=0.640, h=0.072, size_n=0.0150,
             weight=400, max_chars=160, line_height=1.55, palette="on-primary",
             required=False, z=12),
        *checklist(x=0.070, y=0.662, w=0.560, size_n=0.0145, count=5, row_h=0.038,
                   gap=0.004, motif="icon-check", aspect_ratio=STORY,
                   palette="on-primary", icon_palette="accent", max_chars=30, z=12),
        ornament("seal", motif="badge", x=0.686, y=0.648, w=0.240, h=0.138,
                 palette="accent", density=3, z=13,
                 constraints=con("right", "middle", priority=22, optional=True,
                                 overlap=True)),
        text("badge", "badge", x=0.702, y=0.690, w=0.208, h=0.054, size_n=0.030,
             weight=900, max_chars=10, align="center", valign="middle",
             transform="uppercase", palette="on-accent", required=False, z=14,
             constraints=con("center", "middle", priority=24, optional=True,
                             overlap=True)),
        ornament("rule", motif="divider", x=0.070, y=0.872, w=0.240, h=0.012,
                 palette="accent", density=3, z=11),
        shape("cta_bg", "cta", x=0.070, y=0.898, w=0.400, h=0.046, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.070, y=0.898, w=0.400, h=0.046, size_n=0.0165, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
        *icon_text("contact_phone", "contact", motif="icon-phone", x=0.520, y=0.898,
                   w=0.410, h=0.046, size_n=0.0165, aspect_ratio=STORY,
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=26, z=12),
        text("terms", "terms", x=0.070, y=0.954, w=0.860, h=0.026, size_n=0.0100,
             weight=400, max_chars=80, valign="middle", palette="on-primary",
             required=False, z=12),
    ],
    variants=[
        SkeletonVariant(id="circle", name="Circular portrait, colour ground", patch={
            "hero": {"frameN": {"x": 0.190, "y": 0.048, "w": 0.620, "h": 0.310},
                     "image": {"mask": "circle"}},
            "scrim": {"required": False, "opacity": 0.0},
            "logo": {"frameN": {"x": 0.070, "y": 0.380, "w": 0.50, "h": 0.034}},
            "logo_mark": {"frameN": {"x": 0.070, "y": 0.381, "w": 0.0176, "h": 0.0313}},
            "headline": {"frameN": {"x": 0.070, "y": 0.424, "w": 0.700, "h": 0.140}},
        }),
    ],
)


# --------------------------------------------------------------------------------------
# Appetite posters — one thing, photographed enormous, shouted at.
#
# The food-and-drink register: a dark ground, a script line riding over a display word
# set as large as the canvas allows, the price called out in a flash, small props
# floating around the hero, and the two things a hungry reader needs — where you are and
# what to call — split across the bottom corners.
# --------------------------------------------------------------------------------------

POST_FLAVOUR_SQUARE = TemplateSkeleton(
    id="tpl_post_flavour_sq_01",
    name="Post — flavour hero",
    kind="post", aspect="1:1",
    tags=["food", "drink", "restaurant", "cafe", "menu", "appetite", "bold", "dark",
          "high-contrast", "price", "offer", "subject", "contact", "script", "logo",
          "promotional"],
    description=(
        "Appetite-led hero for food and drink. A brand line sits top-left, a script "
        "phrase rides over an enormous display word across the upper half, the product "
        "is photographed vast and centred with small props floating around it, a price "
        "flash sits to one side, and the address and the phone number are split across "
        "the bottom corners under their own labels. Best for a restaurant, cafe, bakery, "
        "dessert shop or drinks brand selling one dish at one price — the layout is "
        "built for a single mouth-watering photograph and very few words."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_TEXTURE,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0.0, w=1, h=1.0, scrim=True, scrim_angle=0,
              palette="primary", opacity=0.55, required=False, z=1,
              constraints=con("stretch", "stretch", priority=18, optional=True)),
        text("logo", "logo", x=0.070, y=0.046, w=0.34, h=0.040, size_n=0.0165,
             weight=700, max_chars=22, transform="uppercase", tracking_n=0.006,
             valign="middle", palette="on-primary", required=False, z=14),
        text("subhead", "subhead", x=0.130, y=0.098, w=0.740, h=0.070, size_n=0.050,
             weight=400, max_chars=24, align="center", valign="middle",
             face="script", line_height=1.02, palette="accent", required=False, z=13),
        text("headline", "headline", x=0.070, y=0.168, w=0.860, h=0.150, size_n=0.130,
             weight=900, max_chars=18, align="center", transform="uppercase",
             line_height=0.90, tracking_n=-0.004, palette="on-primary", z=12,
             constraints=con("center", "top", priority=80, overlap=True)),
        image("subject", "subject", x=0.105, y=0.296, w=0.790, h=0.434,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=8,
              effects=[shadow(0.020, 0.048, 0.42)],
              constraints=con("center", "middle", lock=True, priority=96)),
        ornament("flash", motif="badge", x=0.062, y=0.362, w=0.210, h=0.210,
                 palette="accent", density=4, z=10, pairs_with="price",
                 constraints=con("left", "middle", priority=22, optional=True,
                                 overlap=True)),
        text("caption", "caption", x=0.078, y=0.408, w=0.178, h=0.030, size_n=0.0155,
             weight=600, max_chars=14, align="center", valign="middle",
             transform="uppercase", tracking_n=0.004, palette="on-accent",
             required=False, z=12, pairs_with="price",
             constraints=con("center", "middle", priority=20, optional=True,
                             overlap=True)),
        text("price", "price", x=0.074, y=0.436, w=0.186, h=0.078, size_n=0.058,
             weight=900, max_chars=8, align="center", valign="middle",
             palette="on-accent", required=False, z=12,
             constraints=con("center", "middle", priority=26, optional=True,
                             overlap=True)),
        text("offer", "offer", x=0.100, y=0.740, w=0.800, h=0.046, size_n=0.030,
             weight=800, max_chars=24, align="center", valign="middle",
             transform="uppercase", palette="accent", required=False, z=12),
        # Floating accents. Rings and leaves rather than more photography: they cost no
        # generation budget, and a ring behind a burger is exactly the confetti the
        # reference layouts scatter around a hero.
        icon("accent_a", motif="icon-ring", x=0.760, y=0.078, size=0.072,
             aspect_ratio=SQUARE, palette="accent", z=9, pairs_with="subject",
             opacity=0.85),
        icon("accent_b", motif="icon-ring", x=0.074, y=0.212, size=0.052,
             aspect_ratio=SQUARE, palette="accent", z=9, pairs_with="subject",
             opacity=0.65),
        icon("accent_c", motif="icon-ring", x=0.866, y=0.606, size=0.060,
             aspect_ratio=SQUARE, palette="accent", z=9, pairs_with="subject",
             opacity=0.75),
        prop("garnish_a", x=0.238, y=0.286, w=0.115, h=0.100, prompt=PROP_BOTANICAL,
             z=9, rotation=-18.0, opacity=0.95),
        prop("garnish_b", x=0.672, y=0.336, w=0.110, h=0.096, prompt=PROP_ACCENT,
             z=9, rotation=14.0, opacity=0.95),
        *icon_text("event", "event", motif="icon-clock", x=0.250, y=0.794, w=0.500,
                   h=0.034, size_n=0.0150, aspect_ratio=SQUARE, align="left",
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=38, z=12),
        ornament("rule", motif="divider", x=0.380, y=0.840, w=0.240, h=0.012,
                 palette="accent", density=3, z=11),
        # Where you are on the left, what to call on the right — the split every food
        # poster in the reference set uses. Both are `contact` slots named for the field
        # they hold, so the globe cannot end up beside the phone number, and the icons
        # do the labelling: a second `caption` slot would resolve to the same brief
        # field as the price flash's and print the same words twice.
        *icon_text("contact_web", "contact", motif="icon-globe", x=0.070, y=0.884,
                   w=0.390, h=0.046, size_n=0.0175, aspect_ratio=SQUARE,
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=30, z=12),
        *icon_text("contact_phone", "contact", motif="icon-phone", x=0.585, y=0.884,
                   w=0.345, h=0.046, size_n=0.0175, aspect_ratio=SQUARE,
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=22, z=12),
    ],
    variants=[
        SkeletonVariant(id="flash-right", name="Price flash on the right", patch={
            "flash": {"frameN": {"x": 0.728, "y": 0.362, "w": 0.210, "h": 0.210}},
            "caption": {"frameN": {"x": 0.744, "y": 0.408, "w": 0.178, "h": 0.030}},
            "price": {"frameN": {"x": 0.740, "y": 0.436, "w": 0.186, "h": 0.078}},
            "offer": {"frameN": {"x": 0.736, "y": 0.516, "w": 0.194, "h": 0.034}},
            "accent_c": {"frameN": {"x": 0.074, "y": 0.606, "w": 0.060, "h": 0.060}},
        }),
        SkeletonVariant(id="stacked", name="Script above the display word", patch={
            "subhead": {"frameN": {"x": 0.130, "y": 0.080, "w": 0.740, "h": 0.064}},
            "headline": {"frameN": {"x": 0.070, "y": 0.152, "w": 0.860, "h": 0.140}},
            "subject": {"frameN": {"x": 0.105, "y": 0.310, "w": 0.790, "h": 0.420}},
        }),
    ],
)


STORY_FLAVOUR = TemplateSkeleton(
    id="tpl_story_flavour_01",
    name="Story — flavour hero",
    kind="story", aspect="9:16",
    tags=["food", "drink", "restaurant", "cafe", "menu", "appetite", "bold", "dark",
          "high-contrast", "price", "subject", "contact", "script", "logo"],
    description=(
        "Vertical appetite hero. A script line and a towering display word stack across "
        "the upper third, the dish is photographed enormous through the middle with a "
        "price flash beside it and rings floating around it, and an order pill above a "
        "single contact line closes the story. Best for a restaurant, cafe or dessert "
        "shop putting one dish and one price on a phone screen."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_TEXTURE,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0, w=1, h=1, scrim=True, scrim_angle=0,
              palette="primary", opacity=0.55, required=False, z=1,
              constraints=con("stretch", "stretch", priority=18, optional=True)),
        text("logo", "logo", x=0.070, y=0.044, w=0.44, h=0.030, size_n=0.0125,
             weight=700, max_chars=22, transform="uppercase", tracking_n=0.006,
             valign="middle", palette="on-primary", required=False, z=14),
        text("subhead", "subhead", x=0.110, y=0.108, w=0.780, h=0.058, size_n=0.040,
             weight=400, max_chars=24, align="center", valign="middle", face="script",
             palette="accent", required=False, z=13),
        text("headline", "headline", x=0.070, y=0.156, w=0.860, h=0.128, size_n=0.098,
             weight=900, max_chars=18, align="center", transform="uppercase",
             line_height=0.90, tracking_n=-0.004, palette="on-primary", z=12,
             constraints=con("center", "top", priority=80, overlap=True)),
        image("subject", "subject", x=0.075, y=0.312, w=0.850, h=0.340,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=8,
              effects=[shadow(0.016, 0.040, 0.42)],
              constraints=con("center", "middle", lock=True, priority=96)),
        ornament("flash", motif="badge", x=0.686, y=0.238, w=0.240, h=0.135,
                 palette="accent", density=4, z=10, pairs_with="price",
                 constraints=con("right", "top", priority=22, optional=True,
                                 overlap=True)),
        text("price", "price", x=0.706, y=0.278, w=0.208, h=0.056, size_n=0.036,
             weight=900, max_chars=8, align="center", valign="middle",
             palette="on-accent", required=False, z=12,
             constraints=con("center", "middle", priority=26, optional=True,
                             overlap=True)),
        icon("accent_a", motif="icon-ring", x=0.078, y=0.268, size=0.044,
             aspect_ratio=STORY, palette="accent", z=9, pairs_with="subject",
             opacity=0.70),
        icon("accent_b", motif="icon-ring", x=0.870, y=0.598, size=0.036,
             aspect_ratio=STORY, palette="accent", z=9, pairs_with="subject",
             opacity=0.70),
        prop("garnish_a", x=0.146, y=0.616, w=0.140, h=0.078, prompt=PROP_BOTANICAL,
             z=9, rotation=-16.0),
        text("offer", "offer", x=0.100, y=0.694, w=0.800, h=0.052, size_n=0.034,
             weight=800, max_chars=24, align="center", valign="middle",
             transform="uppercase", palette="accent", required=False, z=12),
        *icon_text("event", "event", motif="icon-clock", x=0.260, y=0.752, w=0.480,
                   h=0.030, size_n=0.0130, aspect_ratio=STORY, align="left",
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=38, z=12),
        text("body", "body", x=0.130, y=0.790, w=0.740, h=0.050, size_n=0.0145,
             weight=400, max_chars=130, align="center", line_height=1.50,
             palette="on-primary", required=False, z=12),
        shape("cta_bg", "cta", x=0.280, y=0.842, w=0.440, h=0.048, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.280, y=0.842, w=0.440, h=0.048, size_n=0.0170, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
        *icon_text("contact_phone", "contact", motif="icon-phone", x=0.240, y=0.906,
                   w=0.520, h=0.042, size_n=0.0155, aspect_ratio=STORY, align="left",
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=30, z=12),
    ],
    variants=[
        SkeletonVariant(id="calm", name="No flash, dish larger", patch={
            "flash": {"required": False, "opacity": 0.0},
            "price": {"required": False, "opacity": 0.0},
            "subject": {"frameN": {"x": 0.055, "y": 0.300, "w": 0.890, "h": 0.365}},
        }),
    ],
)


# --------------------------------------------------------------------------------------
# Greetings — a date, a wish, and something worth quoting.
#
# Festival and national-day posts are their own register: the photograph IS the design,
# the date is set as a graphic element rather than as a line of copy, the greeting is
# split between a heavy display line and a script one, and a short quote sits under a
# rule. Nothing is being sold, so there is no CTA — a greeting with a "BUY NOW" pill on
# it is the single most obviously machine-made thing this corpus could produce.
# --------------------------------------------------------------------------------------

POST_GREETING_SQUARE = TemplateSkeleton(
    id="tpl_post_greeting_sq_01",
    name="Post — dated greeting",
    kind="post", aspect="1:1",
    tags=["greeting", "festival", "celebration", "holiday", "national", "occasion",
          "photographic", "quote", "script", "date", "logo", "editorial"],
    description=(
        "Photographic greeting for a festival or national day. The date is set as a "
        "graphic block in the top-left, the wish runs across the top in a heavy display "
        "line with a script word riding under it, a short quote sits in a ruled block "
        "beneath a quotation mark, and the photograph fills the whole canvas with a "
        "brand line and a website in the bottom corners. Best for Independence or "
        "Republic Day, Diwali, Eid, Christmas, New Year, a founding anniversary — any "
        "post whose job is to mark a date rather than sell something."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY_TOP,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0, w=1, h=0.480, scrim=True, scrim_angle=0,
              palette="primary", required=False, z=2,
              constraints=con("stretch", "top", priority=18, optional=True)),
        text("badge", "badge", x=0.070, y=0.060, w=0.230, h=0.090, size_n=0.074,
             weight=900, max_chars=6, align="left", valign="middle",
             transform="uppercase", line_height=0.92, tracking_n=-0.003,
             palette="on-primary", required=False, z=13),
        text("event", "event", x=0.072, y=0.152, w=0.230, h=0.034, size_n=0.0225,
             weight=700, max_chars=12, transform="uppercase", tracking_n=0.006,
             valign="middle", palette="accent", required=False, z=13),
        text("headline", "headline", x=0.330, y=0.056, w=0.600, h=0.112, size_n=0.050,
             weight=800, max_chars=38, align="right", transform="uppercase",
             line_height=1.00, tracking_n=-0.001, palette="on-primary", z=13),
        text("subhead", "subhead", x=0.560, y=0.166, w=0.370, h=0.078, size_n=0.062,
             weight=400, max_chars=14, align="right", valign="middle", face="script",
             palette="accent", required=False, z=13),
        icon("quote_mark", motif="icon-quote", x=0.406, y=0.268, size=0.046,
             aspect_ratio=SQUARE, palette="accent", z=13, pairs_with="body"),
        shape("quote_rule", "decoration", x=0.392, y=0.322, w=0.004, h=0.108,
              palette="accent", required=False, z=13, pairs_with="body"),
        text("body", "body", x=0.420, y=0.322, w=0.510, h=0.108, size_n=0.0190,
             weight=500, max_chars=160, line_height=1.52, palette="on-primary",
             required=False, z=13),
        ornament("frame", motif="frame-round", x=0.028, y=0.028, w=0.944, h=0.944,
                 palette="accent", density=1, stroke_n=0.0018, z=12, opacity=0.7),
        shape("footer", "decoration", x=0, y=0.906, w=1, h=0.094, scrim=True,
              scrim_angle=180, palette="primary", required=False, z=11,
              constraints=con("stretch", "bottom", priority=16, optional=True)),
        *logo_lockup(x=0.070, y=0.928, w=0.40, h=0.044, aspect_ratio=SQUARE,
                     motif="icon-star", size_n=0.0165, palette="on-primary",
                     mark_palette="accent", z=14),
        *icon_text("contact_web", "contact", motif="icon-globe", x=0.600, y=0.928,
                   w=0.330, h=0.044, size_n=0.0155, aspect_ratio=SQUARE,
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=30, z=14),
    ],
    variants=[
        SkeletonVariant(id="centred", name="Centred wish, no quote", patch={
            "headline": {"frameN": {"x": 0.120, "y": 0.086, "w": 0.760, "h": 0.120},
                         "text": {"align": "center"}},
            "subhead": {"frameN": {"x": 0.250, "y": 0.206, "w": 0.500, "h": 0.082},
                        "text": {"align": "center"}},
            "body": {"required": False, "opacity": 0.0},
            "quote_mark": {"required": False, "opacity": 0.0},
            "quote_rule": {"required": False, "opacity": 0.0},
        }),
        SkeletonVariant(id="plain", name="No corner flourishes", patch={
            "frame": {"required": False, "opacity": 0.0},
        }),
    ],
)


STORY_GREETING = TemplateSkeleton(
    id="tpl_story_greeting_01",
    name="Story — dated greeting",
    kind="story", aspect="9:16",
    tags=["greeting", "festival", "celebration", "holiday", "national", "occasion",
          "photographic", "quote", "script", "date", "logo"],
    description=(
        "Vertical photographic greeting. A dated block and a heavy wish stack across the "
        "top over a full-bleed photograph, a script word rides beneath them, a short "
        "quote sits in a ruled block below, and a brand lockup with a website closes the "
        "foot of the story. Best for a festival, a national day or an anniversary told "
        "on a phone screen."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY_TOP,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0, w=1, h=0.520, scrim=True, scrim_angle=0,
              palette="primary", required=False, z=2,
              constraints=con("stretch", "top", priority=18, optional=True)),
        text("badge", "badge", x=0.070, y=0.058, w=0.300, h=0.068, size_n=0.056,
             weight=900, max_chars=6, valign="middle", transform="uppercase",
             line_height=0.92, tracking_n=-0.003, palette="on-primary",
             required=False, z=13),
        text("event", "event", x=0.072, y=0.128, w=0.300, h=0.028, size_n=0.0170,
             weight=700, max_chars=12, transform="uppercase", tracking_n=0.006,
             valign="middle", palette="accent", required=False, z=13),
        text("headline", "headline", x=0.070, y=0.182, w=0.800, h=0.132, size_n=0.044,
             weight=800, max_chars=42, transform="uppercase", line_height=1.00,
             palette="on-primary", z=13),
        text("subhead", "subhead", x=0.070, y=0.322, w=0.560, h=0.062, size_n=0.048,
             weight=400, max_chars=14, valign="middle", face="script",
             palette="accent", required=False, z=13),
        icon("quote_mark", motif="icon-quote", x=0.072, y=0.418, size=0.030,
             aspect_ratio=STORY, palette="accent", z=13, pairs_with="body"),
        shape("quote_rule", "decoration", x=0.070, y=0.462, w=0.003, h=0.092,
              palette="accent", required=False, z=13, pairs_with="body"),
        text("body", "body", x=0.100, y=0.462, w=0.700, h=0.092, size_n=0.0155,
             weight=500, max_chars=170, line_height=1.55, palette="on-primary",
             required=False, z=13),
        ornament("frame", motif="frame-round", x=0.034, y=0.020, w=0.932, h=0.960,
                 palette="accent", density=1, stroke_n=0.0012, z=12, opacity=0.65),
        shape("footer", "decoration", x=0, y=0.880, w=1, h=0.120, scrim=True,
              scrim_angle=180, palette="primary", required=False, z=11,
              constraints=con("stretch", "bottom", priority=16, optional=True)),
        *logo_lockup(x=0.070, y=0.912, w=0.48, h=0.036, aspect_ratio=STORY,
                     motif="icon-star", size_n=0.0130, palette="on-primary",
                     mark_palette="accent", z=14),
        *icon_text("contact_web", "contact", motif="icon-globe", x=0.570, y=0.912,
                   w=0.360, h=0.036, size_n=0.0125, aspect_ratio=STORY,
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=30, z=14),
    ],
    variants=[
        SkeletonVariant(id="centred", name="Centred wish", patch={
            "badge": {"frameN": {"x": 0.350, "y": 0.058, "w": 0.300, "h": 0.068},
                      "text": {"align": "center"}},
            "event": {"frameN": {"x": 0.350, "y": 0.128, "w": 0.300, "h": 0.028},
                      "text": {"align": "center"}},
            "headline": {"frameN": {"x": 0.100, "y": 0.182, "w": 0.800, "h": 0.132},
                         "text": {"align": "center"}},
            "subhead": {"frameN": {"x": 0.220, "y": 0.322, "w": 0.560, "h": 0.062},
                        "text": {"align": "center"}},
        }),
    ],
)


# --------------------------------------------------------------------------------------
# A gallery board — several photographs, each cut to a different silhouette.
# --------------------------------------------------------------------------------------

POST_GALLERY_SQUARE = TemplateSkeleton(
    id="tpl_post_gallery_sq_01",
    name="Post — shaped gallery",
    kind="post", aspect="1:1",
    tags=["portfolio", "gallery", "multi", "services", "showcase", "editorial", "clean",
          "subject", "list", "contact", "icons", "logo", "studio", "agency"],
    description=(
        "Shaped gallery board. A brand lockup and a display headline sit across the top, "
        "three photographs run beneath them cut to an arch, a circle and a diamond with "
        "a caption under each, a short ticked list closes the copy, and a contact strip "
        "carrying a handset and a pin runs along the foot. Best for a studio, agency, "
        "photographer, florist or interior practice showing a range of work rather than "
        "one hero product — the differing silhouettes are the design."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        ornament("band", motif="arc-band", x=-0.12, y=-0.135, w=1.24, h=0.300,
                 palette="accent", density=3, opacity=0.16, z=1,
                 constraints=con("stretch", "top", priority=12, optional=True)),
        *logo_lockup(x=0.070, y=0.052, w=0.38, h=0.042, aspect_ratio=SQUARE,
                     motif="icon-spark", size_n=0.0150, palette="on-primary",
                     mark_palette="accent", z=14),
        text("headline", "headline", x=0.070, y=0.118, w=0.640, h=0.118, size_n=0.058,
             weight=900, max_chars=32, transform="uppercase", line_height=0.98,
             tracking_n=-0.002, palette="on-primary", z=12),
        text("subhead", "subhead", x=0.070, y=0.252, w=0.560, h=0.048, size_n=0.0175,
             weight=400, max_chars=100, line_height=1.45, palette="on-primary",
             required=False, z=12),
        ornament("seal", motif="tag", x=0.740, y=0.124, w=0.190, h=0.076,
                 palette="accent", density=3, z=12,
                 constraints=con("right", "top", priority=22, optional=True,
                                 overlap=True)),
        text("offer", "offer", x=0.768, y=0.124, w=0.150, h=0.076, size_n=0.024,
             weight=800, max_chars=14, align="center", valign="middle",
             transform="uppercase", palette="on-accent", required=False, z=14,
             constraints=con("center", "middle", priority=24, optional=True,
                             overlap=True)),
        *photo("shot_a", "subject", x=0.070, y=0.334, w=0.272, h=0.286,
               prompt=SUBJECT_FRONT, mask="arch", required=True, z=6, priority=92),
        *photo("shot_b", "subject", x=0.364, y=0.334, w=0.272, h=0.286,
               prompt=SUBJECT_ANGLED, mask="circle", subject_index=1, z=6, priority=74),
        *photo("shot_c", "subject", x=0.658, y=0.334, w=0.272, h=0.286,
               prompt=SUBJECT_DETAIL, mask="diamond", subject_index=2, z=6, priority=70),
        text("feature_1", "feature", x=0.070, y=0.634, w=0.272, h=0.044, size_n=0.0165,
             weight=600, max_chars=26, align="center", valign="top", line_height=1.28,
             palette="on-primary", required=False, z=12),
        text("feature_2", "feature", x=0.364, y=0.634, w=0.272, h=0.044, size_n=0.0165,
             weight=600, max_chars=26, align="center", valign="top", line_height=1.28,
             palette="on-primary", required=False, z=12),
        text("feature_3", "feature", x=0.658, y=0.634, w=0.272, h=0.044, size_n=0.0165,
             weight=600, max_chars=26, align="center", valign="top", line_height=1.28,
             palette="on-primary", required=False, z=12),
        ornament("rule", motif="divider", x=0.380, y=0.700, w=0.240, h=0.014,
                 palette="accent", density=3, z=11),
        text("body", "body", x=0.150, y=0.732, w=0.700, h=0.066, size_n=0.0170,
             weight=400, max_chars=150, align="center", line_height=1.48,
             palette="on-primary", required=False, z=12),
        shape("cta_bg", "cta", x=0.330, y=0.816, w=0.340, h=0.056, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.330, y=0.816, w=0.340, h=0.056, size_n=0.0195, weight=700,
             max_chars=18, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
        shape("contact_bg", "contact", x=0, y=0.900, w=1, h=0.100, palette="accent",
              required=False, z=10,
              constraints=con("stretch", "bottom", priority=25, optional=True)),
        *icon_text("contact", "contact", motif="icon-phone", x=0.100, y=0.922,
                   w=0.360, h=0.052, size_n=0.0170, aspect_ratio=SQUARE,
                   palette="on-accent", icon_palette="on-accent", weight=600,
                   max_chars=24, z=13),
        *icon_text("contact_address", "contact", motif="icon-pin", x=0.530, y=0.922,
                   w=0.380, h=0.052, size_n=0.0155, aspect_ratio=SQUARE,
                   palette="on-accent", icon_palette="on-accent", weight=500,
                   max_chars=34, z=13),
    ],
    variants=[
        SkeletonVariant(id="rounded", name="Three matching rounded frames", patch={
            "shot_a": {"image": {"mask": "rounded", "maskRadiusN": 0.14}},
            "shot_b": {"image": {"mask": "rounded", "maskRadiusN": 0.14}},
            "shot_c": {"image": {"mask": "rounded", "maskRadiusN": 0.14}},
        }),
        SkeletonVariant(id="duo", name="Two larger frames", patch={
            "shot_a": {"frameN": {"x": 0.070, "y": 0.334, "w": 0.410, "h": 0.286}},
            "shot_b": {"frameN": {"x": 0.520, "y": 0.334, "w": 0.410, "h": 0.286},
                       "image": {"mask": "arch"}},
            "shot_c": {"required": False, "opacity": 0.0},
            "feature_1": {"frameN": {"x": 0.070, "y": 0.634, "w": 0.410, "h": 0.044}},
            "feature_2": {"frameN": {"x": 0.520, "y": 0.634, "w": 0.410, "h": 0.044}},
            "feature_3": {"required": False, "opacity": 0.0},
        }),
    ],
)



# --------------------------------------------------------------------------------------
# 4:5 — the shape a post is actually published in.
#
# `KIND_DEFAULT_SIZE` makes 1080x1350 the default for `kind: post`, and retrieval filters
# on aspect family before it looks at anything else, so a square board is only ever
# offered to a request that asked for a square. These are the portrait counterparts, and
# they are re-composed rather than rescaled: a two-column board whose columns are simply
# narrowed loses the thing that made it work.
# --------------------------------------------------------------------------------------

POST_CHECKLIST_45 = TemplateSkeleton(
    id="tpl_post_checklist_45_01",
    name="Post — service checklist, portrait",
    kind="post", aspect="4:5",
    tags=["business", "services", "list", "checklist", "dense", "text-heavy", "contact",
          "subject", "multi", "offer", "discount", "clinic", "salon", "studio",
          "wellness", "fitness", "icons", "logo", "professional"],
    description=(
        "Portrait service board. A brand lockup and a display headline open the design "
        "with a stamped discount beside them, a short paragraph follows, a wide "
        "photograph bands across the middle, six ticked service lines run down the left "
        "with two smaller framed photographs beside them, and a booking pill, a phone "
        "number and a website pill close the foot. Best for a studio, clinic, salon or "
        "practice publishing a list of services at the default post size."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        *logo_lockup(x=0.070, y=0.042, w=0.42, h=0.042, aspect_ratio=PORTRAIT_45,
                     motif="icon-spark", size_n=0.0140, palette="on-primary",
                     mark_palette="accent", z=14),
        text("headline", "headline", x=0.070, y=0.098, w=0.600, h=0.138, size_n=0.050,
             weight=900, max_chars=36, transform="uppercase", line_height=0.96,
             tracking_n=-0.002, palette="on-primary", z=12),
        ornament("seal", motif="diamond", x=0.706, y=0.074, w=0.224, h=0.179,
                 palette="accent", density=3, z=13,
                 constraints=con("right", "top", priority=22, optional=True,
                                 overlap=True)),
        text("offer", "offer", x=0.740, y=0.108, w=0.156, h=0.028, size_n=0.0140,
             weight=600, max_chars=12, align="center", valign="middle",
             palette="on-accent", required=False, z=14,
             constraints=con("center", "middle", priority=24, optional=True,
                             overlap=True)),
        text("badge", "badge", x=0.728, y=0.134, w=0.180, h=0.058, size_n=0.042,
             weight=900, max_chars=8, align="center", valign="middle",
             transform="uppercase", line_height=0.94, palette="on-accent",
             required=False, z=14,
             constraints=con("center", "middle", priority=26, optional=True,
                             overlap=True)),
        text("terms", "terms", x=0.722, y=0.192, w=0.192, h=0.038, size_n=0.0100,
             weight=600, max_chars=34, align="center", valign="top", line_height=1.24,
             palette="on-accent", required=False, z=14,
             constraints=con("center", "middle", priority=16, optional=True,
                             overlap=True)),
        text("body", "body", x=0.070, y=0.252, w=0.560, h=0.062, size_n=0.0155,
             weight=400, max_chars=140, line_height=1.52, palette="on-primary",
             required=False, z=12),
        *icon_text("event", "event", motif="icon-clock", x=0.070, y=0.318, w=0.520,
                   h=0.030, size_n=0.0140, aspect_ratio=PORTRAIT_45, align="left",
                   palette="accent", icon_palette="accent", weight=600,
                   max_chars=40, z=12),
        *photo("hero", "subject", x=0.070, y=0.348, w=0.860, h=0.222, prompt=BG_EMPTY,
               mask="rounded", mask_radius_n=0.08, required=True, z=6, priority=92),
        *checklist(x=0.070, y=0.590, w=0.500, size_n=0.0150, count=6, row_h=0.040,
                   gap=0.002, motif="icon-check-circle", aspect_ratio=PORTRAIT_45,
                   palette="on-primary", icon_palette="accent", max_chars=26, z=12),
        *photo("tile_a", "object", x=0.625, y=0.590, w=0.305, h=0.114,
               prompt=SUBJECT_ANGLED, mask="rounded", mask_radius_n=0.14,
               subject_index=1, z=6, priority=58),
        *photo("tile_b", "object", x=0.625, y=0.726, w=0.305, h=0.114,
               prompt=SUBJECT_SIDE, mask="rounded", mask_radius_n=0.14,
               subject_index=2, z=6, priority=54),
        shape("cta_bg", "cta", x=0.070, y=0.880, w=0.280, h=0.052, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.070, y=0.880, w=0.280, h=0.052, size_n=0.0170, weight=700,
             max_chars=18, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
        *icon_text("contact_phone", "contact", motif="icon-phone", x=0.380, y=0.880,
                   w=0.250, h=0.052, size_n=0.0185, aspect_ratio=PORTRAIT_45,
                   palette="on-primary", icon_palette="accent", weight=700,
                   max_chars=16, z=12),
        shape("contact_web_bg", "contact", x=0.655, y=0.882, w=0.275, h=0.048,
              radius_n=0.5, palette="accent", required=False, z=11,
              pairs_with="contact_web"),
        text("contact_web", "contact", x=0.667, y=0.882, w=0.251, h=0.048,
             size_n=0.0135, weight=600, max_chars=28, align="center", valign="middle",
             palette="on-accent", required=False, z=13),
    ],
    variants=[
        SkeletonVariant(id="arched", name="Arched photograph, no small frames", patch={
            "hero": {"frameN": {"x": 0.190, "y": 0.330, "w": 0.620, "h": 0.250},
                     "image": {"mask": "arch"}},
            "tile_a": {"required": False, "opacity": 0.0},
            "tile_b": {"required": False, "opacity": 0.0},
            "feature_1": {"frameN": {"x": 0.070, "y": 0.600, "w": 0.860, "h": 0.040}},
            "feature_2": {"frameN": {"x": 0.070, "y": 0.642, "w": 0.860, "h": 0.040}},
            "feature_3": {"frameN": {"x": 0.070, "y": 0.684, "w": 0.860, "h": 0.040}},
            "feature_4": {"frameN": {"x": 0.070, "y": 0.726, "w": 0.860, "h": 0.040}},
            "feature_5": {"frameN": {"x": 0.070, "y": 0.768, "w": 0.860, "h": 0.040}},
            "feature_6": {"frameN": {"x": 0.070, "y": 0.810, "w": 0.860, "h": 0.040}},
        }),
        SkeletonVariant(id="quiet", name="No stamp, wider headline", patch={
            "seal": {"required": False, "opacity": 0.0},
            "offer": {"required": False, "opacity": 0.0},
            "badge": {"required": False, "opacity": 0.0},
            "terms": {"required": False, "opacity": 0.0},
            "headline": {"frameN": {"x": 0.070, "y": 0.098, "w": 0.820, "h": 0.138}},
        }),
    ],
)


POST_FLAVOUR_45 = TemplateSkeleton(
    id="tpl_post_flavour_45_01",
    name="Post — flavour hero, portrait",
    kind="post", aspect="4:5",
    tags=["food", "drink", "restaurant", "cafe", "menu", "appetite", "bold", "dark",
          "high-contrast", "price", "offer", "subject", "contact", "script", "logo",
          "promotional"],
    description=(
        "Portrait appetite hero. A brand line opens the design, a script phrase rides "
        "over an enormous display word, the dish is photographed vast through the middle "
        "with a price flash beside it and rings floating around it, an offer line and a "
        "short paragraph follow, and an order pill sits above the website and the phone "
        "number split across the foot. Best for a restaurant, cafe, bakery or drinks "
        "brand selling one dish at one price at the default post size."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_TEXTURE,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0, w=1, h=1, scrim=True, scrim_angle=0,
              palette="primary", opacity=0.55, required=False, z=1,
              constraints=con("stretch", "stretch", priority=18, optional=True)),
        text("logo", "logo", x=0.070, y=0.040, w=0.40, h=0.034, size_n=0.0135,
             weight=700, max_chars=22, transform="uppercase", tracking_n=0.006,
             valign="middle", palette="on-primary", required=False, z=14),
        text("subhead", "subhead", x=0.130, y=0.074, w=0.740, h=0.060, size_n=0.042,
             weight=400, max_chars=24, align="center", valign="middle", face="script",
             palette="accent", required=False, z=13),
        text("headline", "headline", x=0.070, y=0.138, w=0.860, h=0.132, size_n=0.108,
             weight=900, max_chars=18, align="center", transform="uppercase",
             line_height=0.90, tracking_n=-0.004, palette="on-primary", z=12,
             constraints=con("center", "top", priority=80, overlap=True)),
        image("subject", "subject", x=0.080, y=0.290, w=0.840, h=0.330,
              prompt=SUBJECT_FRONT, transparent=True, fit="contain", z=8,
              effects=[shadow(0.016, 0.040, 0.42)],
              constraints=con("center", "middle", lock=True, priority=96)),
        ornament("flash", motif="badge", x=0.070, y=0.330, w=0.200, h=0.200,
                 palette="accent", density=4, z=10, pairs_with="price",
                 constraints=con("left", "middle", priority=22, optional=True,
                                 overlap=True)),
        text("caption", "caption", x=0.084, y=0.372, w=0.172, h=0.026, size_n=0.0125,
             weight=600, max_chars=14, align="center", valign="middle",
             transform="uppercase", tracking_n=0.004, palette="on-accent",
             required=False, z=12, pairs_with="price",
             constraints=con("center", "middle", priority=20, optional=True,
                             overlap=True)),
        text("price", "price", x=0.080, y=0.398, w=0.180, h=0.066, size_n=0.048,
             weight=900, max_chars=8, align="center", valign="middle",
             palette="on-accent", required=False, z=12,
             constraints=con("center", "middle", priority=26, optional=True,
                             overlap=True)),
        icon("accent_a", motif="icon-ring", x=0.796, y=0.078, size=0.056,
             aspect_ratio=PORTRAIT_45, palette="accent", z=9, pairs_with="subject",
             opacity=0.85),
        icon("accent_b", motif="icon-ring", x=0.836, y=0.560, size=0.046,
             aspect_ratio=PORTRAIT_45, palette="accent", z=9, pairs_with="subject",
             opacity=0.70),
        prop("garnish_a", x=0.188, y=0.554, w=0.130, h=0.086, prompt=PROP_BOTANICAL,
             z=9, rotation=-16.0),
        text("offer", "offer", x=0.100, y=0.640, w=0.800, h=0.046, size_n=0.032,
             weight=800, max_chars=24, align="center", valign="middle",
             transform="uppercase", palette="accent", required=False, z=12),
        *icon_text("event", "event", motif="icon-clock", x=0.230, y=0.692, w=0.540,
                   h=0.032, size_n=0.0145, aspect_ratio=PORTRAIT_45, align="left",
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=40, z=12),
        text("body", "body", x=0.140, y=0.734, w=0.720, h=0.050, size_n=0.0150,
             weight=400, max_chars=140, align="center", line_height=1.50,
             palette="on-primary", required=False, z=12),
        ornament("rule", motif="divider", x=0.390, y=0.790, w=0.220, h=0.014,
                 palette="accent", density=3, z=11),
        shape("cta_bg", "cta", x=0.300, y=0.806, w=0.400, h=0.052, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.300, y=0.806, w=0.400, h=0.052, size_n=0.0175, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
        *icon_text("contact_web", "contact", motif="icon-globe", x=0.070, y=0.886,
                   w=0.400, h=0.046, size_n=0.0150, aspect_ratio=PORTRAIT_45,
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=30, z=12),
        *icon_text("contact_phone", "contact", motif="icon-phone", x=0.570, y=0.886,
                   w=0.360, h=0.046, size_n=0.0150, aspect_ratio=PORTRAIT_45,
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=22, z=12),
    ],
    variants=[
        SkeletonVariant(id="flash-right", name="Price flash on the right", patch={
            "flash": {"frameN": {"x": 0.730, "y": 0.330, "w": 0.200, "h": 0.200}},
            "caption": {"frameN": {"x": 0.744, "y": 0.372, "w": 0.172, "h": 0.026}},
            "price": {"frameN": {"x": 0.740, "y": 0.398, "w": 0.180, "h": 0.066}},
            "accent_b": {"frameN": {"x": 0.084, "y": 0.560, "w": 0.0575, "h": 0.046}},
        }),
    ],
)


POST_GREETING_45 = TemplateSkeleton(
    id="tpl_post_greeting_45_01",
    name="Post — dated greeting, portrait",
    kind="post", aspect="4:5",
    tags=["greeting", "festival", "celebration", "holiday", "national", "occasion",
          "photographic", "quote", "script", "date", "logo", "editorial"],
    description=(
        "Portrait photographic greeting. The date is set as a graphic block top-left, "
        "the wish runs beside it in a heavy display line with a script word riding "
        "under, a short quote sits in a ruled block below a quotation mark, the "
        "photograph fills the canvas inside a hairline keyline, and a brand lockup with "
        "a website closes the foot. Best for a festival, national day or anniversary "
        "post at the default post size."
    ),
    gridBaseline=8,
    slots=[
        image("bg", "background", x=0, y=0, w=1, h=1, prompt=BG_EMPTY_TOP,
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("scrim", "overlay", x=0, y=0, w=1, h=0.480, scrim=True, scrim_angle=0,
              palette="primary", required=False, z=2,
              constraints=con("stretch", "top", priority=18, optional=True)),
        text("badge", "badge", x=0.070, y=0.052, w=0.250, h=0.080, size_n=0.062,
             weight=900, max_chars=6, valign="middle", transform="uppercase",
             line_height=0.92, tracking_n=-0.003, palette="on-primary",
             required=False, z=13),
        text("event", "event", x=0.072, y=0.136, w=0.250, h=0.030, size_n=0.0190,
             weight=700, max_chars=12, transform="uppercase", tracking_n=0.006,
             valign="middle", palette="accent", required=False, z=13),
        text("headline", "headline", x=0.350, y=0.050, w=0.580, h=0.108, size_n=0.042,
             weight=800, max_chars=38, align="right", transform="uppercase",
             line_height=1.00, palette="on-primary", z=13),
        text("subhead", "subhead", x=0.560, y=0.158, w=0.370, h=0.070, size_n=0.052,
             weight=400, max_chars=14, align="right", valign="middle", face="script",
             palette="accent", required=False, z=13),
        icon("quote_mark", motif="icon-quote", x=0.410, y=0.252, size=0.038,
             aspect_ratio=PORTRAIT_45, palette="accent", z=13, pairs_with="body"),
        shape("quote_rule", "decoration", x=0.396, y=0.300, w=0.004, h=0.096,
              palette="accent", required=False, z=13, pairs_with="body"),
        text("body", "body", x=0.424, y=0.300, w=0.506, h=0.096, size_n=0.0165,
             weight=500, max_chars=160, line_height=1.52, palette="on-primary",
             required=False, z=13),
        ornament("frame", motif="frame-round", x=0.028, y=0.024, w=0.944, h=0.952,
                 palette="accent", density=1, stroke_n=0.0016, z=12, opacity=0.7),
        shape("footer", "decoration", x=0, y=0.890, w=1, h=0.110, scrim=True,
              scrim_angle=180, palette="primary", required=False, z=11,
              constraints=con("stretch", "bottom", priority=16, optional=True)),
        *logo_lockup(x=0.070, y=0.918, w=0.40, h=0.040, aspect_ratio=PORTRAIT_45,
                     motif="icon-star", size_n=0.0140, palette="on-primary",
                     mark_palette="accent", z=14),
        *icon_text("contact_web", "contact", motif="icon-globe", x=0.600, y=0.918,
                   w=0.330, h=0.040, size_n=0.0130, aspect_ratio=PORTRAIT_45,
                   palette="on-primary", icon_palette="accent", weight=600,
                   max_chars=30, z=14),
    ],
    variants=[
        SkeletonVariant(id="centred", name="Centred wish, no quote", patch={
            "badge": {"frameN": {"x": 0.375, "y": 0.052, "w": 0.250, "h": 0.080},
                      "text": {"align": "center"}},
            "event": {"frameN": {"x": 0.375, "y": 0.136, "w": 0.250, "h": 0.030},
                      "text": {"align": "center"}},
            "headline": {"frameN": {"x": 0.110, "y": 0.190, "w": 0.780, "h": 0.112},
                         "text": {"align": "center"}},
            "subhead": {"frameN": {"x": 0.250, "y": 0.312, "w": 0.500, "h": 0.074},
                        "text": {"align": "center"}},
            "body": {"required": False, "opacity": 0.0},
            "quote_mark": {"required": False, "opacity": 0.0},
            "quote_rule": {"required": False, "opacity": 0.0},
        }),
    ],
)


FLYER_CHECKLIST = TemplateSkeleton(
    id="tpl_flyer_checklist_01",
    name="Flyer — service sheet with checklist",
    kind="flyer", aspect="1:1.414",
    tags=["business", "flyer", "print", "services", "list", "checklist", "dense",
          "text-heavy", "contact", "offer", "discount", "subject", "multi", "icons",
          "logo", "clinic", "salon", "studio"],
    description=(
        "A4 service sheet. A colour header band carries the brand lockup and headline "
        "with a stamped discount beside them, a wide photograph and an arched second "
        "frame sit beneath, six ticked service lines run down the page with a price and "
        "an offer under them, and a booking pill leads into a contact block carrying "
        "phone, website and address above the terms. Best for a printed handout, a "
        "leaflet, a clinic or studio price list — anything that has to answer every "
        "question on one page."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        shape("header", "decoration", x=0, y=0, w=1, h=0.175, palette="accent",
              required=False, z=1,
              constraints=con("stretch", "top", priority=25, optional=True)),
        *logo_lockup(x=0.070, y=0.036, w=0.44, h=0.030, aspect_ratio=A4,
                     motif="icon-spark", size_n=0.0115, palette="on-accent",
                     mark_palette="on-accent", z=14),
        text("headline", "headline", x=0.070, y=0.080, w=0.570, h=0.072, size_n=0.034,
             weight=900, max_chars=34, transform="uppercase", line_height=0.98,
             tracking_n=-0.002, palette="on-accent", z=12),
        ornament("seal", motif="badge", x=0.700, y=0.030, w=0.228, h=0.114,
                 palette="primary", density=3, z=13),
        text("badge", "badge", x=0.716, y=0.062, w=0.196, h=0.048, size_n=0.024,
             weight=900, max_chars=10, align="center", valign="middle",
             transform="uppercase", palette="on-primary", required=False, z=14,
             constraints=con("center", "top", priority=45, optional=True, overlap=True)),
        text("subhead", "subhead", x=0.070, y=0.196, w=0.860, h=0.046, size_n=0.0150,
             weight=400, max_chars=120, line_height=1.45, palette="on-primary",
             required=False, z=12),
        *photo("hero", "subject", x=0.070, y=0.262, w=0.520, h=0.200, prompt=BG_EMPTY,
               mask="rounded", mask_radius_n=0.07, required=True, z=6, priority=92),
        *photo("tile_a", "object", x=0.620, y=0.262, w=0.310, h=0.200,
               prompt=SUBJECT_ANGLED, mask="arch", subject_index=1, z=6, priority=58),
        ornament("rule", motif="divider", x=0.380, y=0.488, w=0.240, h=0.012,
                 palette="accent", density=3, z=11),
        *checklist(x=0.070, y=0.524, w=0.560, size_n=0.0125, count=6, row_h=0.034,
                   gap=0.002, motif="icon-check-circle", aspect_ratio=A4,
                   palette="on-primary", icon_palette="accent", max_chars=32, z=12),
        text("offer", "offer", x=0.660, y=0.534, w=0.270, h=0.048, size_n=0.026,
             weight=800, max_chars=20, align="center", valign="middle",
             transform="uppercase", palette="accent", required=False, z=12),
        text("price", "price", x=0.660, y=0.588, w=0.270, h=0.054, size_n=0.036,
             weight=900, max_chars=12, align="center", valign="middle",
             palette="on-primary", required=False, z=12),
        text("event", "event", x=0.660, y=0.650, w=0.270, h=0.044, size_n=0.0120,
             weight=600, max_chars=48, align="center", valign="middle",
             line_height=1.35, auto_height=True, palette="on-primary",
             required=False, z=12),
        shape("cta_bg", "cta", x=0.070, y=0.766, w=0.300, h=0.044, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.070, y=0.766, w=0.300, h=0.044, size_n=0.0140, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
        shape("contact_bg", "contact", x=0, y=0.844, w=1, h=0.112, palette="accent",
              required=False, z=10,
              constraints=con("stretch", "bottom", priority=42, optional=True)),
        *icon_text("contact_phone", "contact", motif="icon-phone", x=0.070, y=0.868,
                   w=0.290, h=0.042, size_n=0.0140, aspect_ratio=A4,
                   palette="on-accent", icon_palette="on-accent", weight=700,
                   max_chars=18, z=13),
        *icon_text("contact_web", "contact", motif="icon-globe", x=0.390, y=0.868,
                   w=0.290, h=0.042, size_n=0.0125, aspect_ratio=A4,
                   palette="on-accent", icon_palette="on-accent", weight=600,
                   max_chars=26, z=13),
        *icon_text("contact_address", "contact", motif="icon-pin", x=0.700, y=0.868,
                   w=0.230, h=0.042, size_n=0.0110, aspect_ratio=A4,
                   palette="on-accent", icon_palette="on-accent", weight=500,
                   max_chars=32, z=13, auto_height=True),
        # Set ON the contact bar, and it has to say so: the bar is a different role, so
        # nothing links the two, and the collision solver reads "fine print inside the
        # footer" as an overlap and lifts the line out of the band.
        text("terms", "terms", x=0.070, y=0.918, w=0.860, h=0.026, size_n=0.0090,
             weight=400, max_chars=100, align="center", valign="middle",
             palette="on-accent", required=False, z=13,
             constraints=con("center", "bottom", priority=20, optional=True,
                             overlap=True)),
    ],
    variants=[
        SkeletonVariant(id="photo-header", name="Photographic header band", patch={
            "header": {"layerType": "image", "shape": None, "role": "background",
                       "image": {"promptTemplate": BG_EMPTY_BOTTOM, "transparent": False,
                                 "fit": "cover", "subjectIndex": 0},
                       "frameN": {"x": 0, "y": 0, "w": 1, "h": 0.230}},
            "subhead": {"frameN": {"x": 0.070, "y": 0.248, "w": 0.860, "h": 0.044}},
            "hero": {"frameN": {"x": 0.070, "y": 0.306, "w": 0.520, "h": 0.170}},
            "tile_a": {"frameN": {"x": 0.620, "y": 0.306, "w": 0.310, "h": 0.170}},
        }),
    ],
)


# --------------------------------------------------------------------------------------
# Hiring / recruitment — a job opening, a salary figure, a set of requirements AND a
# separate set of keyword tags (a tech stack, a skill set).
#
# The reference case this solves: a recruitment post carries two different kinds of list
# in the same brief — full requirement lines ("2+ years experience") and short keyword
# chips ("Python", "LangChain") — and every skeleton up to this one has exactly one list
# shape, `checklist()`, which is a column of sentences with a tick in front. Cramming a
# six-item tech stack into six-sentence rows either merges the two lists into a single
# six-line cap (losing the tail of both) or renders "Python" the same size and shape as
# "2+ years experience", which reads as a mistake rather than a stack. This carries both:
# a ticked column for the requirements and a wrapping grid of pill chips for the stack,
# side by side, plus the salary as its own prominent panel — a hiring post's second most
# important word after the job title, and previously nowhere near as visually loud as the
# headline it was competing with.
# --------------------------------------------------------------------------------------

POST_HIRING_45 = TemplateSkeleton(
    id="tpl_post_hiring_45_01",
    name="Post — hiring, salary and tech stack, portrait",
    kind="post", aspect="4:5",
    tags=["hiring", "job", "career", "recruitment", "vacancy", "tech", "startup",
          "business", "dense", "text-heavy", "subject", "professional", "logo",
          "salary", "checklist", "tags"],
    description=(
        "Portrait recruitment post. A brand lockup and a short tagline open the design "
        "above a two-line display headline announcing the opening and the job title "
        "beneath it, a salary figure sits in its own prominent accent panel — the "
        "loudest thing on the canvas after the headline — a product or illustration is "
        "photographed large in the middle, a ticked column of requirements runs down "
        "the left while a wrapping grid of short keyword chips for the tech stack or "
        "skill set sits to its right, a divider leads into a pill call to action, and an "
        "optional contact line closes the foot. Best for a job opening, a recruitment "
        "campaign or any post that carries both full requirement lines and a separate "
        "row of short keywords that should not be squeezed into the same list."
    ),
    gridBaseline=8,
    slots=[
        shape("panel", "background", x=0, y=0, w=1, h=1, palette="primary",
              constraints=con("stretch", "stretch", priority=100), z=0),
        *logo_lockup(x=0.070, y=0.038, w=0.42, h=0.040, aspect_ratio=PORTRAIT_45,
                     motif="icon-spark", size_n=0.0135, palette="on-primary",
                     mark_palette="accent", z=14),
        text("caption", "caption", x=0.070, y=0.086, w=0.860, h=0.028, size_n=0.0155,
             weight=700, max_chars=42, transform="uppercase", tracking_n=0.006,
             palette="accent", required=False, z=12),
        text("headline", "headline", x=0.070, y=0.118, w=0.860, h=0.130, size_n=0.058,
             weight=900, max_chars=32, transform="uppercase", line_height=0.98,
             tracking_n=-0.002, palette="on-primary", z=12),
        text("subhead", "subhead", x=0.070, y=0.254, w=0.860, h=0.048, size_n=0.028,
             weight=700, max_chars=36, line_height=1.05, palette="accent", z=12),
        shape("price_bg", "price", x=0.070, y=0.312, w=0.860, h=0.072, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("price", "price", x=0.070, y=0.312, w=0.860, h=0.072, size_n=0.036,
             weight=800, max_chars=24, align="center", valign="middle",
             palette="on-accent", required=False, z=13),
        image("subject", "subject", x=0.150, y=0.404, w=0.700, h=0.230, prompt=SUBJECT,
              transparent=True, fit="contain", z=6,
              effects=[shadow(0.014, 0.030, 0.32)],
              constraints=con("center", "middle", lock=True, priority=95)),
        *checklist(x=0.070, y=0.660, w=0.430, size_n=0.0150, count=4, row_h=0.044,
                   gap=0.006, motif="icon-check-circle", aspect_ratio=PORTRAIT_45,
                   palette="on-primary", icon_palette="accent", max_chars=26, z=12),
        *chip_row(x=0.535, y=0.660, w=0.395, chip_h=0.052, count=6, cols=2,
                  size_n=0.0130, gap=0.014, palette="accent", text_palette="on-accent",
                  max_chars=16, z=12),
        ornament("rule", motif="divider", x=0.330, y=0.876, w=0.340, h=0.016,
                 palette="accent", density=3, z=11),
        shape("cta_bg", "cta", x=0.300, y=0.906, w=0.400, h=0.058, radius_n=0.5,
              palette="accent", required=False, z=11),
        text("cta", "cta", x=0.300, y=0.906, w=0.400, h=0.058, size_n=0.0220, weight=700,
             max_chars=20, align="center", valign="middle", transform="uppercase",
             tracking_n=0.003, palette="on-accent", required=False, z=13),
        text("contact", "contact", x=0.070, y=0.970, w=0.860, h=0.026, size_n=0.0115,
             weight=500, max_chars=90, align="center", valign="middle",
             palette="on-primary", required=False, z=13,
             constraints=con("center", "bottom", priority=20, optional=True,
                             overlap=True)),
    ],
    variants=[
        SkeletonVariant(id="quiet", name="No salary panel, wider subhead", patch={
            "price_bg": {"required": False, "opacity": 0.0},
            "price": {"required": False, "opacity": 0.0},
            "subject": {"frameN": {"x": 0.150, "y": 0.330, "w": 0.700, "h": 0.230}},
            "feature_1": {"frameN": {"x": 0.070, "y": 0.586, "w": 0.430, "h": 0.044}},
            "feature_1_mark": {"frameN": {"x": 0.070, "y": 0.591, "w": 0.0413, "h": 0.033}},
            "feature_2": {"frameN": {"x": 0.070, "y": 0.630, "w": 0.430, "h": 0.044}},
            "feature_2_mark": {"frameN": {"x": 0.070, "y": 0.635, "w": 0.0413, "h": 0.033}},
            "feature_3": {"frameN": {"x": 0.070, "y": 0.674, "w": 0.430, "h": 0.044}},
            "feature_3_mark": {"frameN": {"x": 0.070, "y": 0.679, "w": 0.0413, "h": 0.033}},
            "feature_4": {"frameN": {"x": 0.070, "y": 0.718, "w": 0.430, "h": 0.044}},
            "feature_4_mark": {"frameN": {"x": 0.070, "y": 0.723, "w": 0.0413, "h": 0.033}},
            "tag_1": {"frameN": {"x": 0.535, "y": 0.586, "w": 0.1905, "h": 0.052}},
            "tag_1_bg": {"frameN": {"x": 0.535, "y": 0.586, "w": 0.1905, "h": 0.052}},
            "tag_2": {"frameN": {"x": 0.7395, "y": 0.586, "w": 0.1905, "h": 0.052}},
            "tag_2_bg": {"frameN": {"x": 0.7395, "y": 0.586, "w": 0.1905, "h": 0.052}},
            "tag_3": {"frameN": {"x": 0.535, "y": 0.652, "w": 0.1905, "h": 0.052}},
            "tag_3_bg": {"frameN": {"x": 0.535, "y": 0.652, "w": 0.1905, "h": 0.052}},
            "tag_4": {"frameN": {"x": 0.7395, "y": 0.652, "w": 0.1905, "h": 0.052}},
            "tag_4_bg": {"frameN": {"x": 0.7395, "y": 0.652, "w": 0.1905, "h": 0.052}},
            "tag_5": {"frameN": {"x": 0.535, "y": 0.718, "w": 0.1905, "h": 0.052}},
            "tag_5_bg": {"frameN": {"x": 0.535, "y": 0.718, "w": 0.1905, "h": 0.052}},
            "tag_6": {"frameN": {"x": 0.7395, "y": 0.718, "w": 0.1905, "h": 0.052}},
            "tag_6_bg": {"frameN": {"x": 0.7395, "y": 0.718, "w": 0.1905, "h": 0.052}},
        }),
    ],
)


RICH_SKELETONS: list[TemplateSkeleton] = [
    POST_CHECKLIST_SQUARE, STORY_CHECKLIST, POST_CHECKLIST_45,
    POST_FLAVOUR_SQUARE, STORY_FLAVOUR, POST_FLAVOUR_45,
    POST_GREETING_SQUARE, STORY_GREETING, POST_GREETING_45,
    POST_GALLERY_SQUARE, FLYER_CHECKLIST, POST_HIRING_45,
]
