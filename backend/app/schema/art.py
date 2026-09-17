"""ArtDirection — the visual content of a design, decided per request.

A skeleton owns *composition*: where the negative space is, which region the headline
sits over, whether a slot is a cutout. It must not also own *subject matter*, but until
this existed it did — every background slot in the corpus carried a canned prompt like
"studio backdrop, soft directional light", so a barber shop, a dental clinic and a
sneaker drop were all photographed on the same grey sweep, and the ornament on each was
whichever motif the skeleton author happened to type.

So the two are split. The skeleton keeps the compositional clauses, and everything that
describes what the image is actually *of* — the setting, the light, how the subject is
treated, which decorative motifs suit the occasion — is decided here, from the brief,
once per request.

Reproducibility (INV-2) is unaffected: the direction is recorded in the document's
provenance and every generated asset still stores the full prompt it was built from.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .doc import Base

# Constrained to the corpus's motif families so the model cannot invent a motif the
# renderer has no builder for. `None` means "keep whatever the skeleton author chose",
# which is the right answer whenever the design has no opinion.
FrameMotif = Literal["border", "corners", "arch", "frame-rule", "frame-round"]
RuleMotif = Literal["divider", "chevrons", "scallop", "zigzag"]
BandMotif = Literal["garland", "bunting"]
FieldMotif = Literal["blob", "wave", "stripes", "arc-band"]
ScatterMotif = Literal["confetti", "dots", "rays", "grid-dots"]
SealMotif = Literal["badge", "ribbon", "diamond", "tag"]
ShapeMotif = Literal["hexagon", "arch-solid", "leaf", "triangle"]

# Pictograms are deliberately absent. A tick, a handset and a pin are chosen for what
# they MEAN, by whoever authored the slot; there is no sense in which art direction
# picks "this design's icon" the way it picks this design's border.


class MotifChoice(Base):
    """Which member of each family this design's ornament is drawn from.

    One choice per family rather than one per slot: a design whose border, divider and
    corner flourishes were each picked independently looks assembled rather than
    designed. Holding the choice at family level is what keeps the decoration coherent
    across every slot that uses it.
    """

    frame: FrameMotif | None = None
    rule: RuleMotif | None = None
    band: BandMotif | None = None
    field: FieldMotif | None = None
    scatter: ScatterMotif | None = None
    seal: SealMotif | None = None
    shape: ShapeMotif | None = None

    def for_family(self, family: str | None) -> str | None:
        return getattr(self, family, None) if family else None


class ArtDirection(Base):
    scene: str = Field(
        description="what a photographic background depicts for THIS design — a place "
                    "and a surface, not a genre ('a pale marble vanity top, shallow "
                    "depth of field')"
    )
    texture: str = Field(
        description="what a flat, abstract background looks like instead of a scene "
                    "('fine brushed-brass grain, warm and even')"
    )
    lighting: str = Field(
        description="one clause naming direction, quality and colour of the light"
    )
    subject_treatment: str = Field(
        description="how the subject is rendered — materials, finish, surface quality. "
                    "NOT its angle: the layout owns that, so a trio stays a trio."
    )
    prop: str = Field(
        default="",
        description="a small secondary object that suits the design, for prop slots"
    )
    motifs: MotifChoice = Field(default_factory=MotifChoice)
    density: Literal[1, 2, 3, 4, 5] = Field(
        default=3, description="how much ornament this design carries"
    )
    reason: str = Field(default="", description="one line: why this direction fits")
