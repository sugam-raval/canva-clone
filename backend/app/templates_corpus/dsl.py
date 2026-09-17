"""Authoring helpers for template skeletons — IMPLEMENTATION_PLAN §1.2.

Skeletons are normalised (0..1) so one definition serves any canvas size in its aspect
family. Hand-writing the JSON invites transposed numbers, so slots are built through
these constructors and every skeleton is validated before it reaches the database.
"""

from __future__ import annotations

from app.schema.doc import Constraints
from app.schema.template import AutoFitN, FrameN, ImageSlotSpec, ShapeSlotSpec, Slot, TextSlotSpec
from app.templates_corpus.ornament import ICON_MOTIFS, MOTIFS, is_stroked

# Prompt fragments reused across skeletons.
#
# These carry COMPOSITION and nothing else: which region must stay empty, whether the
# slot is a cutout, which angle a subject is seen from. What the picture is actually OF
# comes from `art.direct` through the {{scene}}, {{texture}}, {{lighting}}, {{treatment}}
# and {{prop}} placeholders, decided per request.
#
# That split is the whole point. When these constants also described the subject matter,
# every background in the corpus was "a studio backdrop, soft directional light", so a
# barber shop, a dental clinic and a sneaker drop were photographed on the same grey
# sweep no matter what the user asked for.
#
# §1.3 still requires an image prompt to describe an EMPTY scene with room where the
# subject and headline will sit, which is why every one of these says so.
# What the background asks for is a SETTING, not an absence.
#
# These used to say "empty scene, no objects", which is what an image model was actually
# given and what it dutifully returned: a flat wall with a gradient on it. The finished
# design was then a cutout floating on a brown blur, next to reference work that puts the
# same product on a sunlit stone counter with a glass, a cloth and some leaves in it.
#
# The real requirement was never emptiness. It is that the space where the subject and
# the headline land stays calm, and that the background does not contain a second copy of
# the product — the subject arrives as its own layer. Said that way, a model returns a
# photograph with depth and materials in it, and the design gets a scene to sit in.
# `NEGATIVE_TEXT_BLOCK` handles lettering, so none of these repeat it.
BG_EMPTY = ("{{scene}}, in {{palette}} tones, {{lighting}}, styled editorial photography "
            "of the setting only — surface, backdrop and atmosphere, with the centre "
            "left calm and unobstructed for a product added separately; real materials, "
            "soft natural shadows, shallow depth of field, no product, no people")
BG_EMPTY_TOP = ("{{scene}}, in {{palette}} tones, {{lighting}}, styled editorial "
                "photography of the setting only, the upper third kept calm and "
                "unobstructed for a headline while the lower frame carries the "
                "materials and the depth; soft natural shadows, no product, no people")
BG_EMPTY_BOTTOM = ("{{scene}}, in {{palette}} tones, {{lighting}}, styled editorial "
                   "photography of the setting only, the lower half kept calm and "
                   "unobstructed for copy while the upper frame carries the materials "
                   "and the depth; soft natural shadows, no product, no people")
BG_TEXTURE = ("{{texture}}, in {{palette}}, a real material photographed close, subtle "
              "grain and tonal depth, even lighting, no focal point, no product")
SUBJECT = ("{{subjectDescription}}, three-quarter view, {{treatment}}, {{lighting}}, "
           "clean transparent background")
SUBJECT_FRONT = ("{{subjectDescription}}, straight-on hero view, {{treatment}}, "
                 "{{lighting}}, clean transparent background")
# Angle variants, for skeletons that show the same subject several times. The angle is
# compositional and stays here; without it every subject slot resolves to one prompt and
# a trio renders as three near-identical cutouts, which reads as a mistake rather than a
# showcase. The treatment is shared, so the three still look like one photoshoot.
SUBJECT_SIDE = ("{{subjectDescription}}, side profile view, {{treatment}}, {{lighting}}, "
                "clean transparent background")
SUBJECT_DETAIL = ("a close detail crop of {{subjectDescription}}, {{treatment}}, "
                  "{{lighting}}, clean transparent background")
SUBJECT_ANGLED = ("{{subjectDescription}}, three-quarter view from slightly above, "
                  "{{treatment}}, {{lighting}}, clean transparent background")
PROP = "{{prop}}, small, isolated, crisp edges, clean transparent background"
# Two props are deliberately specific: a skeleton that places a monstera leaf across a
# corner is making a compositional choice about that shape, not asking for whatever
# object the trade suggests.
PROP_FOLIAGE = ("a single large tropical monstera leaf, deep green, top-down flat view, "
                "crisp edges, clean transparent background")
PROP_BOTANICAL = ("a small sprig of foliage, single stem, flat side view, "
                  "{{treatment}}, crisp edges, clean transparent background")
PROP_ACCENT = ("a single accent object complementing {{subjectDescription}}, "
               "{{treatment}}, small, isolated, crisp edges, clean transparent background")



# How far above its authored size a slot's type may grow when the copy turns out short.
# A skeleton's `sizeN` is authored for copy that fills the slot; real copy is often much
# shorter, and a two-word headline set at the size chosen for six words sits marooned in
# a frame built for a paragraph. The solver's autofit is still bounded by the frame, so
# raising the ceiling cannot cause an overflow — it only lets short copy claim the space
# already allocated to it.
HEADLINE_HEADROOM = 1.45
DEFAULT_HEADROOM = 1.12
# A slot whose height follows its content has no frame to stop it, only its own width,
# so it keeps the conservative ceiling.
AUTO_HEIGHT_HEADROOM = 1.15


def _headroom(role: str, auto_height: bool) -> float:
    if auto_height:
        return AUTO_HEIGHT_HEADROOM
    return HEADLINE_HEADROOM if role == "headline" else DEFAULT_HEADROOM


def con(h: str = "left", v: str = "top", *, lock: bool = False, priority: int = 50,
        optional: bool = False, overlap: bool = False) -> Constraints:
    return Constraints(horizontal=h, vertical=v, lockAspect=lock, priority=priority,
                       optional=optional, allowOverlap=overlap)


def text(slot_id: str, role: str, *, x: float, y: float, w: float, h: float,
         size_n: float, weight: int = 400, max_chars: int = 40, align: str = "left",
         valign: str = "top", transform: str = "none", line_height: float = 1.12,
         tracking_n: float = 0.0, fit_min: float | None = None,
         fit_max: float | None = None, palette: str = "on-primary",
         required: bool = True, z: int = 10, constraints: Constraints | None = None,
         auto_height: bool = False, rotation: float = 0.0,
         face: str | None = None, stroke_n: float = 0.0,
         stroke_palette: str | None = None,
         pairs_with: str | None = None) -> Slot:
    return Slot(
        slotId=slot_id, role=role, layerType="text",
        frameN=FrameN(x=x, y=y, w=w, h=h, rotation=rotation),
        required=required,
        constraints=constraints or con(priority=80 if required else 40,
                                       optional=not required),
        text=TextSlotSpec(
            maxChars=max_chars, sizeN=size_n, weight=weight, align=align,
            verticalAlign=valign, transform=transform, lineHeight=line_height,
            letterSpacingN=tracking_n,
            autoFitN=AutoFitN(min=fit_min or size_n * 0.45,
                              max=fit_max or size_n * _headroom(role, auto_height)),
            autoHeight=auto_height,
            face=face,
            strokeWidthN=stroke_n,
            strokePaletteRole=stroke_palette,
        ),
        paletteRole=palette, zIndex=z, pairsWith=pairs_with,
    )


def image(slot_id: str, role: str, *, x: float, y: float, w: float, h: float,
          prompt: str, transparent: bool = False, fit: str = "cover",
          required: bool = True, z: int = 0, constraints: Constraints | None = None,
          aspect: str | None = None, rotation: float = 0.0,
          effects: list[dict] | None = None, opacity: float = 1.0,
          subject_index: int = 0, mask: str | None = None,
          mask_radius_n: float = 0.0, pairs_with: str | None = None) -> Slot:
    return Slot(
        slotId=slot_id, role=role, layerType="image",
        frameN=FrameN(x=x, y=y, w=w, h=h, rotation=rotation),
        required=required,
        constraints=constraints or con(priority=95 if role == "subject" else 60,
                                       lock=transparent, optional=not required),
        image=ImageSlotSpec(promptTemplate=prompt, transparent=transparent,
                            aspectPreference=aspect, fit=fit,
                            subjectIndex=subject_index, mask=mask,
                            maskRadiusN=mask_radius_n),
        zIndex=z, opacity=opacity, effects=effects or [], pairsWith=pairs_with,
    )


def shape(slot_id: str, role: str, *, x: float, y: float, w: float, h: float,
          kind: str = "rect", radius_n: float = 0.0, palette: str = "accent",
          required: bool = True, z: int = 5, constraints: Constraints | None = None,
          scrim: bool = False, scrim_angle: float = 90.0, opacity: float = 1.0,
          rotation: float = 0.0, effects: list[dict] | None = None,
          pairs_with: str | None = None) -> Slot:
    return Slot(
        slotId=slot_id, role=role, layerType="shape",
        frameN=FrameN(x=x, y=y, w=w, h=h, rotation=rotation),
        required=required,
        constraints=constraints or con(priority=55 if required else 30,
                                       optional=not required),
        shape=ShapeSlotSpec(shape=kind, radiusN=radius_n, fillFromPalette=True,
                            gradientScrim=scrim, gradientAngle=scrim_angle),
        paletteRole=palette, zIndex=z, opacity=opacity, effects=effects or [],
        pairsWith=pairs_with,
    )


def prop(slot_id: str, *, x: float, y: float, w: float, h: float,
         prompt: str | None = None, z: int = 5, rotation: float = 0.0,
         opacity: float = 1.0, effects: list[dict] | None = None,
         subject_index: int = 0, mask: str | None = None,
         fit: str = "contain", transparent: bool = True) -> Slot:
    """A secondary cutout beside the hero subject — a leaf, a sprig, an accent object.

    Props are what stop a design reading as one photograph with type on it, and they are
    always optional: they carry a low constraint priority so the subject is generated
    first and, when the request budget runs out, the props are the layers that go.

    Give `z` above the subject's to layer the prop in front of it and below to tuck it
    behind. Either way the overlap is the composition, so the slot declares it and the
    solver stops trying to separate the two.
    """
    return Slot(
        slotId=slot_id, role="object", layerType="image",
        frameN=FrameN(x=x, y=y, w=w, h=h, rotation=rotation),
        required=False,
        constraints=con("center", "middle", lock=True, priority=35, optional=True,
                        overlap=True),
        image=ImageSlotSpec(promptTemplate=prompt or PROP, transparent=transparent,
                            fit=fit, subjectIndex=subject_index, mask=mask),
        zIndex=z, opacity=opacity, effects=effects or [],
    )


def ornament(slot_id: str, *, motif: str, x: float, y: float, w: float, h: float,
             palette: str = "accent", density: int = 3, stroke_n: float = 0.0,
             opacity: float = 1.0, required: bool = False, z: int = 4,
             rotation: float = 0.0, constraints: Constraints | None = None,
             pairs_with: str | None = None) -> Slot:
    """A decorative slot: a procedural vector motif, coloured from the palette.

    Ornament is always optional. It is the first thing that should go when the solver is
    under pressure, and a design missing its garland is still a design — one whose CTA
    has been shoved off the canvas to make room for a garland is not.
    """
    if motif not in MOTIFS:
        raise ValueError(f"unknown motif {motif!r}; known: {sorted(MOTIFS)}")
    return Slot(
        slotId=slot_id, role="decoration", layerType="shape",
        frameN=FrameN(x=x, y=y, w=w, h=h, rotation=rotation),
        required=required,
        constraints=constraints or con("stretch" if w >= 0.999 else "center",
                                       "top", priority=15, optional=True),
        shape=ShapeSlotSpec(shape="path", fillFromPalette=True, motif=motif,
                            strokeWidthN=stroke_n or (0.0018 if is_stroked(motif) else 0.0),
                            density=density),
        paletteRole=palette, zIndex=z, opacity=opacity, pairsWith=pairs_with,
    )


def shadow(dy: float = 0.02, blur: float = 0.05, opacity: float = 0.32) -> dict:
    """Effect values are normalised to canvas height and denormalised by `expand()`."""
    return {"kind": "shadow", "dx": 0.0, "dy": dy, "blur": blur,
            "color": "#000000", "opacity": opacity}


# --------------------------------------------------------------------------------------
# Composite constructors
#
# The single-slot constructors above describe one element. Real promotional layouts are
# built from repeating *units* — a tick and the service line beside it, a handset and the
# number beside it, a photograph and the keyline around it — and hand-writing each unit
# slot by slot is where a six-row checklist picks up the one row whose icon sits two
# pixels low. These build the whole unit, wired together, so the rows cannot drift.
# --------------------------------------------------------------------------------------


def icon(slot_id: str, *, motif: str, x: float, y: float, size: float,
         aspect_ratio: float = 1.0, palette: str = "accent", z: int = 12,
         stroke_n: float = 0.0, pairs_with: str | None = None,
         required: bool = False, opacity: float = 1.0, rotation: float = 0.0) -> Slot:
    """A pictogram, square by construction.

    Icons are authored square because every glyph in `ICON_MOTIFS` is drawn in a unit
    square and centred in its box: a non-square slot would letterbox the drawing and put
    a tick somewhere other than where the author placed it.

    `size` is normalised to canvas HEIGHT, and `aspect_ratio` (the canvas's width over
    its height) converts it for the x axis. Normalised coordinates are not square: a slot
    0.04 wide and 0.04 tall on a 1080x1350 post is 43 by 54 pixels, and a tick drawn in
    it is a tick standing on its toes.
    """
    if motif not in ICON_MOTIFS:
        raise ValueError(f"{motif!r} is not a pictogram; known: {sorted(ICON_MOTIFS)}")
    return Slot(
        slotId=slot_id, role="decoration", layerType="shape",
        frameN=FrameN(x=x, y=y, w=size / max(aspect_ratio, 1e-6), h=size,
                      rotation=rotation),
        required=required,
        constraints=con("left", "middle", lock=True, priority=20,
                        optional=not required, overlap=True),
        shape=ShapeSlotSpec(shape="path", fillFromPalette=True, motif=motif,
                            strokeWidthN=stroke_n or (size * 0.10 if is_stroked(motif)
                                                      else 0.0),
                            density=3),
        paletteRole=palette, zIndex=z, opacity=opacity, pairsWith=pairs_with,
    )


def checklist(*, x: float, y: float, w: float, size_n: float, count: int,
              row_h: float, gap: float = 0.0, motif: str = "icon-check-circle",
              icon_size: float | None = None, indent: float | None = None,
              palette: str = "on-primary", icon_palette: str = "accent",
              weight: int = 500, max_chars: int = 34, z: int = 12,
              role: str = "feature", prefix: str = "feature",
              aspect_ratio: float = 1.0) -> list[Slot]:
    """A ticked list: `count` rows of pictogram plus copy, as 2 x count slots.

    Each row's icon declares `pairsWith` its own line, so a brief carrying four services
    renders four ticks rather than six — two of them pointing at empty space. That is the
    whole reason this is a constructor and not six hand-written pairs.

    `aspect_ratio` is the canvas's width/height. Icons are square in PIXELS, so a slot's
    normalised width and height differ by exactly that factor; passing it wrong gives a
    row of ovals, so it is required to be stated rather than guessed.
    """
    if count < 1:
        raise ValueError("a checklist needs at least one row")
    mark = icon_size if icon_size is not None else row_h * 0.78
    mark_w = mark / aspect_ratio
    text_x = x + (indent if indent is not None else mark_w * 1.75)
    slots: list[Slot] = []
    for index in range(count):
        line_id = f"{prefix}_{index + 1}"
        top = y + index * (row_h + gap)
        slots.append(text(
            line_id, role, x=text_x, y=top, w=max(0.02, x + w - text_x), h=row_h,
            size_n=size_n, weight=weight, max_chars=max_chars, valign="middle",
            line_height=1.24, palette=palette, required=False, z=z,
        ))
        slots.append(icon(
            f"{line_id}_mark", motif=motif, x=x, y=top + (row_h - mark) / 2,
            size=mark, aspect_ratio=aspect_ratio, palette=icon_palette,
            z=z, pairs_with=line_id,
        ))
    return slots


def chip_row(*, x: float, y: float, w: float, chip_h: float, count: int, cols: int,
            size_n: float, gap: float = 0.014, palette: str = "accent",
            text_palette: str = "on-accent", weight: int = 700, max_chars: int = 16,
            role: str = "feature", prefix: str = "tag", z: int = 12,
            radius_n: float = 0.5) -> list[Slot]:
    """A wrapping grid of small filled pill chips — a tech stack, a skill set, an
    ingredient list, hashtags. `checklist()` is a column of full sentences with a tick in
    front; this is short keywords side by side, which is how a stack or a skill set is
    actually read. Each chip is a pill shape and its label, paired the same way a
    checklist ties an icon to its line, so a brief with five tags renders five chips
    rather than `count` of them with the last row empty.

    `cols` wraps the count into rows of even width; a stack of six at three columns is
    two rows of three, not six chips each a sixth of the design's width.
    """
    if count < 1:
        raise ValueError("a chip row needs at least one chip")
    chip_w = (w - gap * (cols - 1)) / cols
    slots: list[Slot] = []
    for index in range(count):
        col, row = index % cols, index // cols
        cx = x + col * (chip_w + gap)
        cy = y + row * (chip_h + gap)
        chip_id = f"{prefix}_{index + 1}"
        slots.append(shape(
            f"{chip_id}_bg", "decoration", x=cx, y=cy, w=chip_w, h=chip_h,
            radius_n=radius_n, palette=palette, required=False, z=z - 1,
            pairs_with=chip_id,
        ))
        slots.append(text(
            chip_id, role, x=cx, y=cy, w=chip_w, h=chip_h, size_n=size_n,
            weight=weight, max_chars=max_chars, align="center", valign="middle",
            palette=text_palette, required=False, z=z,
        ))
    return slots


def icon_text(slot_id: str, role: str, *, motif: str, x: float, y: float, w: float,
              h: float, size_n: float, aspect_ratio: float = 1.0,
              icon_size: float | None = None, palette: str = "on-primary",
              icon_palette: str = "accent", weight: int = 600, max_chars: int = 40,
              align: str = "left", z: int = 12, auto_height: bool = False,
              line_height: float = 1.3) -> list[Slot]:
    """One line of copy with a pictogram in front of it — "call us on", an address, a
    website. Same pairing as `checklist`: no number, no handset."""
    mark = icon_size if icon_size is not None else h * 0.72
    mark_w = mark / aspect_ratio
    return [
        text(slot_id, role, x=x + mark_w * 1.5, y=y, w=max(0.02, w - mark_w * 1.5), h=h,
             size_n=size_n, weight=weight, max_chars=max_chars, align=align,
             valign="middle", line_height=line_height, auto_height=auto_height,
             palette=palette, required=False, z=z),
        icon(f"{slot_id}_mark", motif=motif, x=x, y=y + (h - mark) / 2, size=mark,
             aspect_ratio=aspect_ratio, palette=icon_palette, z=z,
             pairs_with=slot_id),
    ]


def photo(slot_id: str, role: str, *, x: float, y: float, w: float, h: float,
          prompt: str, mask: str, fit: str = "cover", required: bool = False,
          z: int = 6, priority: int = 70, rotation: float = 0.0,
          effects: list[dict] | None = None, subject_index: int = 0,
          keyline: bool = False, keyline_palette: str = "accent",
          mask_radius_n: float = 0.0) -> list[Slot]:
    """A photograph cut to a silhouette, optionally inside a hairline keyline.

    Returns one or two slots. The keyline is a separate ornament rather than a stroke on
    the image because only shapes carry strokes — and keeping it separate is what lets it
    take the accent colour while the photograph stays untouched.
    """
    slots = [image(slot_id, role, x=x, y=y, w=w, h=h, prompt=prompt, fit=fit,
                   required=required, z=z, rotation=rotation, effects=effects,
                   subject_index=subject_index, mask=mask,
                   mask_radius_n=mask_radius_n,
                   constraints=con("center", "middle", lock=True, priority=priority,
                                   optional=not required))]
    if keyline:
        slots.append(ornament(f"{slot_id}_keyline", motif="frame-round", x=x, y=y,
                              w=w, h=h, palette=keyline_palette, density=1,
                              z=z + 1, rotation=rotation, pairs_with=slot_id,
                              constraints=con("center", "middle", priority=18,
                                              optional=True, overlap=True)))
    return slots


def logo_lockup(*, x: float, y: float, w: float, h: float, aspect_ratio: float = 1.0,
                motif: str = "icon-spark", size_n: float = 0.018,
                palette: str = "on-primary", mark_palette: str = "accent",
                z: int = 14, max_chars: int = 24,
                over_image: bool = False) -> list[Slot]:
    """A brand mark and the brand name beside it, top-left of the design.

    Every reference layout carries one and the corpus had no way to place it: `logo` was
    a role with no slot anywhere. A generated design that names the business at the top
    reads as that business's design rather than as a stock template with a headline.
    """
    mark = h * 0.92
    mark_w = mark / aspect_ratio
    return [
        text("logo", "logo", x=x + mark_w * 1.35, y=y, w=max(0.02, w - mark_w * 1.35),
             h=h, size_n=size_n, weight=700, max_chars=max_chars, valign="middle",
             transform="uppercase", tracking_n=0.004, line_height=1.16,
             palette=palette, required=False, z=z,
             # A lockup laid over a photograph is depth, not a collision. Without this
             # the solver dutifully lifts the name off the picture and parks it in the
             # copy below, a third of the way down the design.
             constraints=con("left", "top", priority=40, optional=True,
                             overlap=over_image)),
        icon("logo_mark", motif=motif, x=x, y=y + (h - mark) / 2, size=mark,
             aspect_ratio=aspect_ratio, palette=mark_palette, z=z,
             pairs_with="logo"),
    ]
