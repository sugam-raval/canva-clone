"""Parallel template corpus for the Lido.js editor (https://github.com/quickhubai/lido-editor).

Independent of `app.schema` / `app.templates_corpus` (the custom DesignDoc engine). This
package speaks Lido's own JSON format directly: `[{"layers": {<layerId>: LidoLayer}}]`.

Templates are never hardcoded here. `loader.discover_templates()` globs a directory at
call time, so dropping a new `template_N.json` into it is picked up with no code change.
"""
