"""Font descriptors for generated documents.

A Lido `TextLayer` carries its own webfont descriptor in `props.fonts` — the editor
loads the face from that URL rather than looking it up in a catalog. So a generated
layer naming a family we have no URL for renders in a fallback face and the design
loses its typography.

Every URL here was resolved from Google Fonts' own CSS API and checked with a live
HEAD request before being hardcoded — gstatic filenames are content-hashed per
version, so a guessed URL is a coin flip, and a broken one silently drops the whole
face. `resolve()` never fails: an unknown family degrades to the closest
role-appropriate face we do have rather than emitting a dead descriptor.
"""

from __future__ import annotations

from typing import Literal

# family -> gstatic font file. Each one HEAD-checked at 200 before being added.
CATALOG: dict[str, str] = {
    "ABeeZee": "https://fonts.gstatic.com/s/abeezee/v23/esDR31xSG-6AGleN6tKukbcHCpE.ttf",
    "Akaya Telivigala": "https://fonts.gstatic.com/s/akayatelivigala/v28/lJwc-oo_iG9wXqU3rCTD395tp0uifdLdsIH0YH8.ttf",
    "Alata": "https://fonts.gstatic.com/s/alata/v12/PbytFmztEwbIofe6xKcRQEOX.ttf",
    "Allerta": "https://fonts.gstatic.com/s/allerta/v19/TwMO-IAHRlkbx940UnEdSQqO5uY.ttf",
    "Allura": "https://fonts.gstatic.com/s/allura/v23/9oRPNYsQpS4zjuAPjAIXPtrrGA.ttf",
    "Castoro": "https://fonts.gstatic.com/s/castoro/v19/1q2GY5yMCld3-O4cHYhEzOYenEU.ttf",
    "Poppins": "https://fonts.gstatic.com/s/poppins/v21/pxiEyp8kv8JHgFVrJJfedw.ttf",
    "Roboto": "https://fonts.gstatic.com/s/roboto/v49/KFOMCnqEu92Fr1ME7kSn66aGLdTylUAMQXC89YmC2DPNWuYaammTggvWl0Qn.ttf",
    "Montserrat": "https://fonts.gstatic.com/s/montserrat/v31/JTUHjIg1_i6t8kCHKm4532VJOt5-QNFgpCuM73w0aXpsog.woff2",
    "Playfair Display": "https://fonts.gstatic.com/s/playfairdisplay/v40/nuFvD-vYSZviVYUb_rj3ij__anPXJzDwcbmjWBN2PKeiunDTbtPY_Q.woff2",
    "Oswald": "https://fonts.gstatic.com/s/oswald/v57/TK3_WkUHHAIjg75cFRf3bXL8LICs1y9osUtiZTaR.woff2",
    "Merriweather": "https://fonts.gstatic.com/s/merriweather/v33/u-4D0qyriQwlOrhSvowK_l5UcA6zuSYEqOzpPe3HOZJ5eX1WtLaQwmYiScCmDxhtNOKl8yDrOSAaGV31GvU.woff2",
    "Bebas Neue": "https://fonts.gstatic.com/s/bebasneue/v16/JTUSjIg69CK48gW7PXoo9Wdhyzbi.woff2",
    "Pacifico": "https://fonts.gstatic.com/s/pacifico/v23/FwZY7-Qmy14u9lezJ-6K6MmTpA.woff2",
    "DM Sans": "https://fonts.gstatic.com/s/dmsans/v17/rP2tp2ywxg089UriI5-g4vlH9VoD8CmcqZG40F9JadbnoEwAkJxRR232VGM.woff2",
    "Raleway": "https://fonts.gstatic.com/s/raleway/v37/1Ptxg8zYS_SKggPN4iEgvnHyvveLxVs9pbCFPrEHJA.woff2",
    "Anton": "https://fonts.gstatic.com/s/anton/v27/1Ptgg87LROyAm3K8-C8QSw.woff2",
    "Dancing Script": "https://fonts.gstatic.com/s/dancingscript/v29/If2cXTr6YS-zF4S-kcSWSVi_sxjsohD9F50Ruu7B1i03Rep8ltA.woff2",
    "Space Grotesk": "https://fonts.gstatic.com/s/spacegrotesk/v22/V8mQoQDjQSkFtoMM3T6r8E7mF71Q-gOoraIAEj42VnsrPMBTTA.woff2",
    "Cormorant Garamond": "https://fonts.gstatic.com/s/cormorantgaramond/v21/co3umX5slCNuHLi8bLeY9MK7whWMhyjypVO7abI26QOD_iE9KnnOiss4.woff2",
    "Archivo Black": "https://fonts.gstatic.com/s/archivoblack/v23/HTxqL289NzCGg4MzN6KJ7eW6CYKF_i7y.woff2",
    "Caveat": "https://fonts.gstatic.com/s/caveat/v23/WnznHAc5bAfYB2QRah7pcpNvOx-pjRV6eIipYSxP.woff2",
    # Display faces with real weight on the page — the heavy condensed and slab faces a
    # poster headline is actually set in, which the original catalog had almost none of.
    "Teko": "https://fonts.gstatic.com/s/teko/v23/LYjYdG7kmE0gV69VVPPdFl06VN_wHLSy.ttf",
    "Alfa Slab One": "https://fonts.gstatic.com/s/alfaslabone/v21/6NUQ8FmMKwSEKjnm5-4v-4Jh6dU.ttf",
    "Bungee": "https://fonts.gstatic.com/s/bungee/v17/N0bU2SZBIuF2PU_ECg.ttf",
    "Fjalla One": "https://fonts.gstatic.com/s/fjallaone/v16/Yq6R-LCAWCX3-6Ky7FAFnOY.ttf",
    "Titan One": "https://fonts.gstatic.com/s/titanone/v17/mFTzWbsGxbbS_J5cQcjykw.ttf",
    "Abril Fatface": "https://fonts.gstatic.com/s/abrilfatface/v25/zOL64pLDlL1D99S8g8PtiKchm-A.ttf",
    "Righteous": "https://fonts.gstatic.com/s/righteous/v18/1cXxaUPXBpj2rGoU7C9mjw.ttf",
    "Shrikhand": "https://fonts.gstatic.com/s/shrikhand/v17/a8IbNovtLWfR7T7bMJwbBA.ttf",
    # Script faces for the one accent line above a headline.
    "Great Vibes": "https://fonts.gstatic.com/s/greatvibes/v21/RWmMoKWR9v4ksMfaWd_JN-XC.ttf",
    "Yellowtail": "https://fonts.gstatic.com/s/yellowtail/v25/OZpGg_pnoDtINPfRIlLotlw.ttf",
    "Satisfy": "https://fonts.gstatic.com/s/satisfy/v22/rP2Hp2yn6lkG50LoOZQ.ttf",
    "Sacramento": "https://fonts.gstatic.com/s/sacramento/v17/buEzpo6gcdjy0EiZMBUG0Co.ttf",
    "Permanent Marker": "https://fonts.gstatic.com/s/permanentmarker/v16/Fh4uPib9Iyv2ucM6pGQMWimMp004Hao.ttf",
    # Text faces that hold up at caption size, where the originals got thin and grey.
    "Inter": "https://fonts.gstatic.com/s/inter/v20/UcCO3FwrK3iLTeHuS_nVMrMxCp50SjIw2boKoduKmMEVuFuYMZg.ttf",
    "Work Sans": "https://fonts.gstatic.com/s/worksans/v24/QGY_z_wNahGAdqQ43RhVcIgYT2Xz5u32K5fQNig.ttf",
    "Barlow Condensed": "https://fonts.gstatic.com/s/barlowcondensed/v13/HTxwL3I-JCGChYJ8VI-L6OO_au7B46r2_3E.ttf",
    "Lato": "https://fonts.gstatic.com/s/lato/v25/S6u9w4BMUTPHh6UVew8.ttf",
    "Rubik": "https://fonts.gstatic.com/s/rubik/v31/iJWZBXyIfDnIV5PNhY1KTN7Z-Yh-4I-1UA.ttf",
    "Nunito": "https://fonts.gstatic.com/s/nunito/v32/XRXI3I6Li01BKofiOc5wtlZ2di8HDFwmRTM.ttf",
    "Josefin Sans": "https://fonts.gstatic.com/s/josefinsans/v34/Qw3PZQNVED7rKGKxtqIqX5E-AVSJrOCfjY46_ObXXME.ttf",
}

Vibe = Literal[
    "geometric", "humanist", "serif-editorial", "display-bold", "script",
    "impact", "corporate", "tech-modern", "luxury-serif", "casual-hand", "retro",
    "condensed-sport", "street-bold", "editorial-fat", "playful-fun",
]

#: Display face, text face and script face per vibe. The LLM picks a vibe, not a font
#: name — one choice out of fifteen it can reason about (each tied to a recognisable
#: use case) beats one out of forty it cannot. See `design_ai._system_prompt` for the
#: use-case guidance shown alongside each name.
#:
#: The third slot is what makes the reference-poster pairing possible at all: a short
#: script line set above a heavy condensed headline. Every vibe carries one, so an
#: element asking for `font='script'` always lands on a real handwritten face rather
#: than on the text face at a different size.
PAIRINGS: dict[str, tuple[str, str, str]] = {
    "geometric": ("Poppins", "Work Sans", "Satisfy"),
    "humanist": ("Work Sans", "ABeeZee", "Satisfy"),
    "serif-editorial": ("Playfair Display", "Lato", "Sacramento"),
    "display-bold": ("Titan One", "Nunito", "Yellowtail"),
    "script": ("Great Vibes", "Josefin Sans", "Great Vibes"),
    "impact": ("Anton", "Barlow Condensed", "Yellowtail"),
    "corporate": ("Raleway", "Inter", "Satisfy"),
    "tech-modern": ("Space Grotesk", "Inter", "Satisfy"),
    "luxury-serif": ("Cormorant Garamond", "Josefin Sans", "Great Vibes"),
    "casual-hand": ("Permanent Marker", "Nunito", "Caveat"),
    "retro": ("Alfa Slab One", "Work Sans", "Yellowtail"),
    "condensed-sport": ("Teko", "Barlow Condensed", "Yellowtail"),
    "street-bold": ("Bungee", "Rubik", "Permanent Marker"),
    "editorial-fat": ("Abril Fatface", "Lato", "Sacramento"),
    "playful-fun": ("Shrikhand", "Nunito", "Satisfy"),
}

DEFAULT_VIBE = "geometric"

#: Mean advance width as a fraction of font size, used to estimate wrapped line count
#: without shaping. Rough by design — layout only needs to know when a line will not
#: fit, and loading real metrics here would pull in the whole font registry.
_ADVANCE_RATIO: dict[str, float] = {
    "Allura": 0.36,
    "Akaya Telivigala": 0.44,
    "Castoro": 0.50,
    "Poppins": 0.55,
    "Alata": 0.52,
    "Allerta": 0.52,
    "ABeeZee": 0.51,
    "Roboto": 0.50,
    "Montserrat": 0.56,
    "Playfair Display": 0.52,
    "Oswald": 0.44,
    "Merriweather": 0.54,
    "Bebas Neue": 0.40,
    "Pacifico": 0.50,
    "DM Sans": 0.54,
    "Raleway": 0.52,
    "Anton": 0.42,
    "Dancing Script": 0.40,
    "Space Grotesk": 0.54,
    "Cormorant Garamond": 0.46,
    "Archivo Black": 0.62,
    "Caveat": 0.40,
    "Teko": 0.36,
    "Alfa Slab One": 0.60,
    "Bungee": 0.62,
    "Fjalla One": 0.44,
    "Titan One": 0.58,
    "Abril Fatface": 0.52,
    "Righteous": 0.52,
    "Shrikhand": 0.56,
    "Great Vibes": 0.34,
    "Yellowtail": 0.42,
    "Satisfy": 0.42,
    "Sacramento": 0.32,
    "Permanent Marker": 0.48,
    "Inter": 0.53,
    "Work Sans": 0.52,
    "Barlow Condensed": 0.40,
    "Lato": 0.50,
    "Rubik": 0.54,
    "Nunito": 0.53,
    "Josefin Sans": 0.48,
}
_DEFAULT_ADVANCE = 0.52


def display_face(vibe: str) -> str:
    return PAIRINGS.get(vibe, PAIRINGS[DEFAULT_VIBE])[0]


def text_face(vibe: str) -> str:
    return PAIRINGS.get(vibe, PAIRINGS[DEFAULT_VIBE])[1]


def script_face(vibe: str) -> str:
    return PAIRINGS.get(vibe, PAIRINGS[DEFAULT_VIBE])[2]


def face_for(slot: str, vibe: str, *, display: bool) -> str:
    """The family for an element's `font` slot.

    'auto' keeps the old behaviour — large type takes the display face, small type the
    text face — so an element that expresses no preference is set exactly as before.
    """
    if slot == "display":
        return display_face(vibe)
    if slot == "text":
        return text_face(vibe)
    if slot == "script":
        return script_face(vibe)
    return display_face(vibe) if display else text_face(vibe)


def resolve(family: str | None, vibe: str, *, display: bool) -> str:
    """The catalog family to actually use. Falls back to the vibe's pairing."""
    if family and family.split(",")[0].strip() in CATALOG:
        return family.split(",")[0].strip()
    return display_face(vibe) if display else text_face(vibe)


def advance_ratio(family: str) -> float:
    return _ADVANCE_RATIO.get(family, _DEFAULT_ADVANCE)


def wrap_text(text: str, family: str, size_px: float, width_px: float,
              tracking_em: float = 0.0) -> list[str]:
    """Greedy word-wrap into physical lines that fit `width_px`.

    A Lido `TextLayer` does not reflow at render time -- its `boxSize.width` is a
    hit-testing/drag handle, not a CSS constraint, and each ProseMirror paragraph in
    `doc.content` is one physical line (see `app.lido_corpus.compose._set_doc_text`,
    which maps `lines[i]` to `content[i]` 1:1). A single long unbroken line will run
    off both edges of the canvas exactly as far as it needs to, because nothing in the
    real editor stops it. This is the one function responsible for making sure that
    never happens: every string it returns already fits `width_px`, and the caller's
    job is only to turn each returned line into its own paragraph.

    Same mean-advance-width heuristic as `layout.element_height` -- not real shaping,
    but the two must agree, or a block ends up taller on the page than layout
    reserved room for.
    """
    # Tracking widens every glyph's advance, so a line tracked out at 0.28em fits
    # roughly a third fewer characters. Ignoring it is what makes a spaced-out sub-line
    # run off the edge of the canvas while layout still believes it fits.
    advance = max(0.05, advance_ratio(family) + tracking_em)
    max_chars = max(1, int(width_px / max(1.0, size_px * advance)))
    lines: list[str] = []
    for segment in text.split(chr(10)):
        current = ""
        for word in segment.split(" "):
            candidate = f"{current} {word}".strip()
            if not current or len(candidate) <= max_chars:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""]


def descriptor(family: str) -> list[dict]:
    """The `props.fonts` value for a text layer set in `family`."""
    url = CATALOG.get(family)
    return [{"name": family, "fonts": [{"urls": [url] if url else []}]}]
