"""DesignBrief — IMPLEMENTATION_PLAN §1.1. Output of the `brief.parse` job."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .doc import Base

DesignKind = Literal["story", "post", "poster", "banner", "thumbnail", "ad", "flyer"]

# §1.1: "Infer canvas size from `kind` unless stated."
KIND_DEFAULT_SIZE: dict[str, tuple[int, int, int]] = {
    # kind: (width, height, dpi)
    "story": (1080, 1920, 72),
    "post": (1080, 1350, 72),
    "square": (1080, 1080, 72),
    "poster": (2480, 3508, 300),
    "banner": (1500, 500, 72),
    "thumbnail": (1280, 720, 72),
    "ad": (1200, 628, 72),
    "flyer": (1654, 2339, 300),
}


class BriefCanvas(Base):
    width: int = Field(gt=0, le=20000)
    height: int = Field(gt=0, le=20000)


class Contact(Base):
    """How the reader is meant to act on the design.

    Separate from `Copy` because these are not written, they are *transcribed*: a phone
    number the model paraphrases is a phone number that does not ring. Everything here
    is carried verbatim from the prompt and is never rewritten downstream.
    """

    phone: str | None = None
    email: str | None = None
    website: str | None = None
    address: str | None = None
    social: str | None = Field(default=None, description="@handle or 'fb.com/...'")

    def strip_line(self, separator: str = " · ") -> str | None:
        """The whole block as one contact strip, in the order a reader scans it."""
        parts = [p for p in (self.phone, self.website, self.email, self.social,
                             self.address) if p and p.strip()]
        return separator.join(parts) if parts else None

    def has_any(self) -> bool:
        return any((self.phone, self.email, self.website, self.address, self.social))


class Copy(Base):
    headline: str | None = None
    subhead: str | None = None
    body: str | None = None
    cta: str | None = None
    caption: str | None = None
    # Promotional copy. A discount-led design is mostly these fields, and without them
    # "flat 50% off, call 98765 43210" arrives as a headline with the offer paraphrased
    # into it and the number dropped.
    offer: str | None = Field(default=None, description="the offer line, e.g. 'Flat 50% Off'")
    price: str | None = Field(default=None, description="e.g. '₹499' or 'from $29'")
    badge: str | None = Field(
        default=None, description="the few characters stamped in a seal, e.g. '50% OFF'")
    terms: str | None = Field(default=None, description="validity, *T&C apply, fine print")
    event_details: str | None = Field(
        default=None, description="date, time and venue, as one line")
    features: list[str] = Field(
        default_factory=list,
        description="short bullet lines — services, inclusions, menu items")
    # A second, shorter list. `features` is full lines ("2+ years experience"); a request
    # just as often carries a row of one- or two-word keyword chips — a tech stack, a
    # skill set, an ingredient list, a set of hashtags — that reads wrong crammed into the
    # same bullet rows and was previously merged into `features` with no way to tell the
    # two apart, so a six-line skeleton lost the requirements to make room for "Python".
    tags: list[str] = Field(
        default_factory=list,
        description="short keyword chips — technologies, skills, ingredients, amenities; "
                    "distinct from `features`, which are full bullet lines")
    # Who the design is FOR. Almost every real request names a business, and until this
    # existed there was nowhere to put it: `logo` was a layer role with no brief field
    # behind it, so a logo lockup could never be filled and no skeleton could carry one.
    brand_name: str | None = Field(
        default=None, description="the business or brand the design is for, as the user "
                                  "wrote it — set in the logo lockup, never rewritten")
    contact: Contact = Field(default_factory=Contact)

    def filled_roles(self) -> list[str]:
        """Which layer roles this copy has something to put in."""
        by_role = {
            "headline": self.headline, "subhead": self.subhead, "body": self.body,
            "cta": self.cta, "caption": self.caption, "offer": self.offer,
            "price": self.price, "badge": self.badge, "terms": self.terms,
            "logo": self.brand_name,
        }
        roles = [name for name, value in by_role.items() if value and value.strip()]
        if self.features or self.tags:
            roles.append("feature")
        if self.event_details:
            roles.append("event")
        if self.contact.has_any():
            roles.append("contact")
        return roles


class ColorDirection(Base):
    mode: Literal["brand", "from-prompt", "auto"] = "auto"
    palette: list[str] | None = None


class Typography(Base):
    vibe: Literal["geometric", "humanist", "serif-editorial", "display-bold"] = "geometric"
    family_hint: str | None = None


class LayoutHints(Base):
    subject_placement: Literal["left", "right", "center", "bottom", "full-bleed"] | None = None
    density: Literal["sparse", "balanced", "dense"] = "balanced"


class Clarification(Base):
    question: str
    options: list[str] = Field(default_factory=list)


class AssetsProvided(Base):
    logo_asset_id: str | None = None
    product_asset_ids: list[str] = Field(default_factory=list)


class DesignBrief(Base):
    kind: DesignKind
    canvas: BriefCanvas
    subject_description: str | None = Field(
        default=None, description="null => text-only / abstract design"
    )
    # Additional distinct subjects, for a range, a menu, a duo, a trio. A skeleton's
    # second and third subject slots interpolate these by index; without them every
    # cutout in a four-up grid resolves to the same prompt and the grid renders as the
    # same object printed four times.
    subjects: list[str] = Field(
        default_factory=list,
        description="further distinct subjects beyond subjectDescription, in order",
    )
    # Named `copy_text` in Python because `copy` shadows BaseModel.copy; the wire
    # name stays `copy` to match IMPLEMENTATION_PLAN §1.1 exactly.
    copy_text: Copy = Field(
        default_factory=Copy, alias="copy", serialization_alias="copy"
    )
    mood: list[str] = Field(default_factory=list)
    color_direction: ColorDirection = Field(default_factory=ColorDirection)
    typography: Typography = Field(default_factory=Typography)
    layout_hints: LayoutHints = Field(default_factory=LayoutHints)
    language: str = Field(default="en", description="BCP-47; drives font subset + shaping")
    needs_clarification: Clarification | None = None
    assets_provided: AssetsProvided | None = None

    def subject_at(self, index: int) -> str | None:
        """Subject for slot `index`, cycling once the distinct ones run out.

        Cycling rather than returning None is deliberate: a skeleton's third slot still
        has to generate something, and another angle on subject one is a showcase
        whereas an empty slot is a hole.
        """
        pool = [s for s in ([self.subject_description] + list(self.subjects)) if s]
        if not pool:
            return None
        return pool[index % len(pool)]
