"""`compose.layout` equivalent for the Lido corpus — IMPLEMENTATION_PLAN §1.3, retargeted.

Same shape as the DesignDoc composer: an LLM call constrained to a small schema, with a
mechanical fallback so the pipeline never fails outright when no LLM is configured
(§1.3 "Failure handling": never fail the request at this stage). The one hard rule
carried over unchanged from `DesignBrief.Contact`: phone/address/website are
*transcribed*, never rewritten — whatever the LLM proposes for those roles is
overwritten with the brief's verbatim contact fields afterward.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.adapters.base import AdapterError
from app.adapters.registry import llm as get_llm
from app.schema.brief import DesignBrief

from .model import LidoTemplateFile, SlotInfo

_VERBATIM_ROLES = {"phone": "phone", "address": "address", "website": "website"}


class LidoSlotFill(BaseModel):
    layer_id: str
    text: str = Field(description="new copy for this slot, within max_chars")


class LidoComposerOutput(BaseModel):
    slots: list[LidoSlotFill]


def _slot_manifest(slots: list[SlotInfo]) -> list[dict]:
    return [
        {
            "layer_id": s.layer_id,
            "role": s.role,
            "current_text": s.default_text,
            "max_chars": s.max_chars,
        }
        for s in slots if s.editable
    ]


def _system_prompt() -> str:
    return (
        "You are the copy layer of a graphic design generator. You are given a design "
        "brief and a manifest of every editable text slot in the chosen template layout "
        "(role, current placeholder text, character budget). Write new copy for EVERY "
        "slot listed, replacing its current text so the whole design reads as one "
        "coherent piece for the brief — including short fixed-style labels (role "
        "'label'), which should be rewritten too if the brief's tone or subject calls "
        "for something different (e.g. a label reading 'We Are Open!' might become "
        "'Now Booking' for a different business). Rules: never exceed max_chars; never "
        "invent a layer_id that wasn't given; return exactly one entry per slot given; "
        "for roles 'phone', 'address', 'website' just copy the brief's contact info "
        "verbatim if present (it will be overwritten regardless, so don't spend effort "
        "here) — never invent a phone number or address."
    )


def _mechanical_fill(brief: DesignBrief, slots: list[SlotInfo]) -> dict[str, str]:
    """§1.3's "mechanical copy placement" fallback — direct field mapping, no LLM.

    Deliberately conservative: only fills a slot when the brief actually carries
    something for that role. A `label` slot with nothing to map to is left as
    whatever the template already had rather than guessing.
    """
    copy = brief.copy_text
    by_role = {
        "headline": copy.headline,
        "subhead": copy.subhead or copy.offer,
        "body": copy.body or copy.brand_name,
        "phone": copy.contact.phone,
        "address": copy.contact.address,
        "website": copy.contact.website,
    }
    out: dict[str, str] = {}
    for slot in slots:
        if not slot.editable:
            continue
        value = by_role.get(slot.role)
        if value:
            out[slot.layer_id] = value
    return out


def _apply_verbatim_contact(result: dict[str, str], brief: DesignBrief,
                            slots: list[SlotInfo]) -> None:
    contact = brief.copy_text.contact
    for slot in slots:
        source_field = _VERBATIM_ROLES.get(slot.role)
        if source_field is None:
            continue
        value = getattr(contact, source_field)
        if value:
            result[slot.layer_id] = value
        else:
            result.pop(slot.layer_id, None)  # no verbatim contact info -> don't invent one


async def compose_lido_content(brief: DesignBrief, template: LidoTemplateFile) -> dict[str, str]:
    """Returns `{layer_id: text}` for every editable slot the brief has something for."""
    editable = [s for s in template.meta.slots if s.editable]
    if not editable:
        return {}

    try:
        result = await get_llm().complete_json(
            system=_system_prompt(),
            user=(
                f"Brief: {brief.model_dump_json(by_alias=True, exclude_none=True)}\n"
                f"Slots: {_slot_manifest(editable)}"
            ),
            schema=LidoComposerOutput,
        )
        by_id = {fill.layer_id: fill.text for fill in result.parsed.slots
                 if fill.layer_id in {s.layer_id for s in editable}}
    except AdapterError:
        by_id = _mechanical_fill(brief, editable)

    _apply_verbatim_contact(by_id, brief, editable)
    return by_id
