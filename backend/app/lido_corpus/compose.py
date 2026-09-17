"""Fill a Lido template's editable slots with generated copy.

Every `TextLayer` slot is fair game — these templates are scratch layout material, not
fixed branding, so a `static` label (e.g. "Contact:") is rewritten exactly like a
headline when the new design calls for it. Only layers with no text at all (background,
logo/photo frames, decorative shapes) are structural and left untouched.
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
    by_role: dict[str, str] | None = None,
    by_layer_id: dict[str, str] | None = None,
    image_by_layer_id: dict[str, str] | None = None,
) -> list[dict]:
    """Returns a fresh `[{"layers": {...}}]` document, ready to hand to the Lido editor.

    `image_by_layer_id` replaces a layer's `props.image.url` (and `.thumb`) — pass
    `"ROOT"` as a layer_id to replace the background. This is separate from
    `by_layer_id`/`by_role` (text) because a slot can need either, both, or neither.
    """
    by_role = by_role or {}
    by_layer_id = by_layer_id or {}
    image_by_layer_id = image_by_layer_id or {}
    layers_out = {
        lid: copy.deepcopy(layer.model_dump(mode="json"))
        for lid, layer in template.layers.items()
    }

    for slot in template.meta.slots:
        if not slot.editable:
            continue
        text = by_layer_id.get(slot.layer_id)
        if text is None:
            text = by_role.get(slot.role)
        if text is None:
            continue
        doc = layers_out[slot.layer_id].get("props", {}).get("doc")
        if isinstance(doc, dict):
            _set_doc_text(doc, text)

    for layer_id, url in image_by_layer_id.items():
        if layer_id in layers_out:
            _set_image_url(layers_out[layer_id], url)

    return [{"layers": layers_out}]
