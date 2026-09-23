"""Fill a Lido template's editable slots with generated copy and images.

Every unlocked `TextLayer` slot is fair game — a `static` label (e.g. "Get Yours!") is
rewritten exactly like a headline when the new design calls for it. Layers with no text
(background, frames, shapes) only change through `image_by_layer_id`, and anything the
template's metadata marks `locked` is never touched.
"""

from __future__ import annotations

import copy

from .model import LidoTemplateFile


def _set_doc_text(doc: dict, text: str) -> None:
    content = doc.get("content", [])
    if not content:
        return
    lines = text.split("\n")
    for i, para in enumerate(content):
        nodes = para.get("content", [])
        if not nodes:
            continue
        line = lines[i] if i < len(lines) else ""
        nodes[0]["text"] = line
        for extra in nodes[1:]:
            extra["text"] = ""
    if len(lines) > len(content) and content:
        last_nodes = content[-1].get("content", [])
        if last_nodes:
            last_nodes[0]["text"] = " ".join(lines[len(content) - 1:])


def _set_image_url(layer: dict, url: str) -> None:
    image = layer.get("props", {}).get("image")
    if isinstance(image, dict):
        image["url"] = url
        image["thumb"] = url


def fill_template(
    template: LidoTemplateFile,
    by_layer_id: dict[str, str] | None = None,
    image_by_layer_id: dict[str, str] | None = None,
) -> list[dict]:
    """Returns a fresh `[{"layers": {...}}]` document, ready to hand to the Lido editor.

    `image_by_layer_id` replaces a layer's `props.image.url` (and `.thumb`) — pass
    `"ROOT"` as a layer_id to replace the background. Slots marked `locked` in the
    template's metadata (e.g. the logo) are never written, whatever is passed in.
    """
    by_layer_id = by_layer_id or {}
    image_by_layer_id = image_by_layer_id or {}
    locked = {slot.layer_id for slot in template.meta.slots if slot.locked}
    layers_out = {
        lid: copy.deepcopy(layer.model_dump(mode="json"))
        for lid, layer in template.layers.items()
    }

    for slot in template.meta.slots:
        if not slot.editable or slot.locked:
            continue
        text = by_layer_id.get(slot.layer_id)
        if text is None:
            continue
        doc = layers_out[slot.layer_id].get("props", {}).get("doc")
        if isinstance(doc, dict):
            _set_doc_text(doc, text)

    for layer_id, url in image_by_layer_id.items():
        if layer_id in layers_out and layer_id not in locked:
            _set_image_url(layers_out[layer_id], url)

    return [{"layers": layers_out}]
