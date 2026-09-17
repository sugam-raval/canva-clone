"""SVG path data -> skia.Path.

`skia-python` exposes no SVG path parser, and the draw list carries geometry as SVG
path strings deliberately: the browser's Konva backend feeds the same string straight
into `Konva.Path`, so both renderers consume identical geometry (INV-3).

Supports the full path grammar: M L H V C S Q T A Z, absolute and relative.
"""

from __future__ import annotations

import math
import re

import skia

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")

_ARG_COUNT = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4,
              "Q": 4, "T": 2, "A": 7, "Z": 0}


class SvgPathError(ValueError):
    pass


def parse_svg_path(d: str) -> skia.Path:
    path = skia.Path()
    if not d or not d.strip():
        return path

    tokens = _TOKEN.findall(d)
    i = 0
    cmd = ""
    cur_x = cur_y = 0.0
    start_x = start_y = 0.0
    # Reflection points for the smooth variants S and T.
    last_c2: tuple[float, float] | None = None
    last_q1: tuple[float, float] | None = None

    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            cmd = token
            i += 1
            if cmd in "Zz":
                path.close()
                cur_x, cur_y = start_x, start_y
                last_c2 = last_q1 = None
                continue
        elif not cmd:
            raise SvgPathError(f"path data starts with a number, not a command: {d[:32]!r}")
        else:
            # An implicit repeat: after M the repeat is L, after m it is l.
            if cmd == "M":
                cmd = "L"
            elif cmd == "m":
                cmd = "l"

        upper = cmd.upper()
        relative = cmd.islower()
        n = _ARG_COUNT[upper]
        if i + n > len(tokens):
            raise SvgPathError(f"truncated {cmd!r} command in path data")
        args = [float(t) for t in tokens[i:i + n]]
        i += n

        if upper == "M":
            x, y = args
            if relative:
                x, y = cur_x + x, cur_y + y
            path.moveTo(x, y)
            cur_x, cur_y = start_x, start_y = x, y
            last_c2 = last_q1 = None

        elif upper == "L":
            x, y = args
            if relative:
                x, y = cur_x + x, cur_y + y
            path.lineTo(x, y)
            cur_x, cur_y = x, y
            last_c2 = last_q1 = None

        elif upper == "H":
            x = cur_x + args[0] if relative else args[0]
            path.lineTo(x, cur_y)
            cur_x = x
            last_c2 = last_q1 = None

        elif upper == "V":
            y = cur_y + args[0] if relative else args[0]
            path.lineTo(cur_x, y)
            cur_y = y
            last_c2 = last_q1 = None

        elif upper == "C":
            x1, y1, x2, y2, x, y = args
            if relative:
                x1, y1 = cur_x + x1, cur_y + y1
                x2, y2 = cur_x + x2, cur_y + y2
                x, y = cur_x + x, cur_y + y
            path.cubicTo(x1, y1, x2, y2, x, y)
            cur_x, cur_y, last_c2, last_q1 = x, y, (x2, y2), None

        elif upper == "S":
            x2, y2, x, y = args
            if relative:
                x2, y2 = cur_x + x2, cur_y + y2
                x, y = cur_x + x, cur_y + y
            if last_c2 is None:
                x1, y1 = cur_x, cur_y
            else:
                x1, y1 = 2 * cur_x - last_c2[0], 2 * cur_y - last_c2[1]
            path.cubicTo(x1, y1, x2, y2, x, y)
            cur_x, cur_y, last_c2, last_q1 = x, y, (x2, y2), None

        elif upper == "Q":
            x1, y1, x, y = args
            if relative:
                x1, y1 = cur_x + x1, cur_y + y1
                x, y = cur_x + x, cur_y + y
            path.quadTo(x1, y1, x, y)
            cur_x, cur_y, last_q1, last_c2 = x, y, (x1, y1), None

        elif upper == "T":
            x, y = args
            if relative:
                x, y = cur_x + x, cur_y + y
            if last_q1 is None:
                x1, y1 = cur_x, cur_y
            else:
                x1, y1 = 2 * cur_x - last_q1[0], 2 * cur_y - last_q1[1]
            path.quadTo(x1, y1, x, y)
            cur_x, cur_y, last_q1, last_c2 = x, y, (x1, y1), None

        elif upper == "A":
            rx, ry, rot, large_arc, sweep, x, y = args
            if relative:
                x, y = cur_x + x, cur_y + y
            if rx == 0 or ry == 0:
                path.lineTo(x, y)
            elif math.isclose(x, cur_x) and math.isclose(y, cur_y):
                pass  # zero-length arc is a no-op per the SVG spec
            else:
                path.arcTo(
                    abs(rx), abs(ry), rot,
                    skia.Path.ArcSize.kLarge_ArcSize if large_arc
                    else skia.Path.ArcSize.kSmall_ArcSize,
                    skia.PathDirection.kCW if sweep else skia.PathDirection.kCCW,
                    x, y,
                )
            cur_x, cur_y = x, y
            last_c2 = last_q1 = None

    return path
