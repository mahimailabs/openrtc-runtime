"""Regenerate the README badges: `uvx --with fonttools --with brotli python assets/badges/make_badges.py`.

Run `npm ci --prefix web/docs` first for the Space Grotesk font. Labels are drawn as paths, so the
badges look the same wherever GitHub serves them, and each follows the viewer's light or dark scheme.
"""

from __future__ import annotations

from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parents[2]
FONT = (
    ROOT
    / "web/docs/node_modules/@fontsource-variable/space-grotesk/files/space-grotesk-latin-wght-normal.woff2"
)
OUT = Path(__file__).resolve().parent

SIZE = 13.0  # label font size, px
HEIGHT = 30
PAD_X = 12
ICON = 16
GAP = 8

# Icons on a 16x16 grid, in the accent (.a) and muted (.m) roles only.
ICONS = {
    "pypi": '<path class="a" d="M8 1.4L14 4.7V11.3L8 14.6L2 11.3V4.7Z"/>'
    '<path class="k" d="M2 4.7L8 8L14 4.7M8 8V14.6" stroke-width="1" fill="none"/>',
    "python": '<path class="a" d="M7.9 1.4C5.4 1.4 5.5 2.5 5.5 2.5L5.5 4.2H8.1V4.7H4.2C4.2 4.7 2.5 4.5 2.5 7C2.5 9.6 4 9.5 4 9.5H5V7.8C5 6.5 6.1 6.3 6.1 6.3H9.3C9.3 6.3 10.5 6.3 10.5 5.1V2.6C10.5 2.6 10.6 1.4 7.9 1.4ZM6 2.3C6.3 2.3 6.5 2.5 6.5 2.8C6.5 3.1 6.3 3.3 6 3.3C5.7 3.3 5.5 3.1 5.5 2.8C5.5 2.5 5.7 2.3 6 2.3Z"/>'
    '<path class="m" d="M8.1 14.6C10.6 14.6 10.5 13.5 10.5 13.5L10.5 11.8H7.9V11.3H11.8C11.8 11.3 13.5 11.5 13.5 9C13.5 6.4 12 6.5 12 6.5H11V8.2C11 9.5 9.9 9.7 9.9 9.7H6.7C6.7 9.7 5.5 9.7 5.5 10.9V13.4C5.5 13.4 5.4 14.6 8.1 14.6ZM10 13.7C9.7 13.7 9.5 13.5 9.5 13.2C9.5 12.9 9.7 12.7 10 12.7C10.3 12.7 10.5 12.9 10.5 13.2C10.5 13.5 10.3 13.7 10 13.7Z"/>',
    "livekit": '<rect class="m" x="1" y="6" width="2.2" height="4" rx="1.1"/>'
    '<rect class="m" x="4.4" y="3.5" width="2.2" height="9" rx="1.1"/>'
    '<rect class="a" x="7.8" y="1.4" width="2.2" height="13.2" rx="1.1"/>'
    '<rect class="m" x="11.2" y="4.5" width="2.2" height="7" rx="1.1"/>',
    "license": '<circle class="s" cx="8" cy="8" r="6.2" fill="none" stroke-width="1.5"/>'
    '<path class="s" d="M5.3 8.1L7.1 9.9L10.8 6.1" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
}
BADGES = {
    "pypi": "PyPI",
    "python": "Python 3.11+",
    "livekit": "LiveKit Agents",
    "license": "MIT License",
}

# DESIGN.md roles: surface, line, ink, signal, muted; light-* for light schemes.
STYLE = (
    ".bg{fill:#141414;stroke:#262626}.t{fill:#fafafa}.a{fill:#cba6f7}.m{fill:#a3a3a3}"
    ".k{stroke:#141414}.s{stroke:#cba6f7}"
    "@media (prefers-color-scheme:light){.bg{fill:#f3f3f4;stroke:#e3e3e6}.t{fill:#0a0a0a}"
    ".a{fill:#6f3fb0}.m{fill:#55555c}.k{stroke:#f3f3f4}.s{stroke:#6f3fb0}}"
)


def label_path(font: TTFont, text: str) -> tuple[str, float]:
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    scale = SIZE / font["head"].unitsPerEm
    pen = SVGPathPen(glyphs)
    x = 0.0
    for ch in text:
        name = cmap[ord(ch)]
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x, 0)))
        x += glyphs[name].width * scale
    return pen.getCommands(), x


def main() -> None:
    font = instantiateVariableFont(TTFont(FONT), {"wght": 500})
    ascent = font["OS/2"].sCapHeight * SIZE / font["head"].unitsPerEm
    for key, text in BADGES.items():
        d, width = label_path(font, text)
        w = round(PAD_X + ICON + GAP + width + PAD_X)
        baseline = (HEIGHT + ascent) / 2
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{HEIGHT}" viewBox="0 0 {w} {HEIGHT}">'
            f"<style>{STYLE}</style>"
            f'<rect class="bg" x="0.5" y="0.5" width="{w - 1}" height="{HEIGHT - 1}" rx="7"/>'
            f'<g transform="translate({PAD_X},{(HEIGHT - ICON) / 2})">{ICONS[key]}</g>'
            f'<path class="t" transform="translate({PAD_X + ICON + GAP},{baseline:.2f})" d="{d}"/>'
            "</svg>\n"
        )
        (OUT / f"{key}.svg").write_text(svg)
        print(key, w)


if __name__ == "__main__":
    main()
