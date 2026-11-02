"""Turn the deck logo artwork into the web assets the frontend ships.

The source in deck/media is a 1536x1024 RGB render of the full lockup on an opaque
white field, which is unusable as-is: it carries ~40% dead margin, it is a megabyte,
and dropping it on the landing page's dark emerald hero would paint a white box.

So we derive, into frontend/public/:

  logo-lockup.png          trimmed stacked lockup, background keyed to transparent
  logo-lockup-ondark.png   the same, re-inked for dark backgrounds
  logo-horizontal.png      mark beside the wordmark, for page headers
  logo-horizontal-ondark.png
  logo-mark.png            just the bean-and-leaf symbol, square, transparent
  logo-mark-ondark.png     the symbol, re-inked for dark backgrounds
  logo-mark-white.png      flat white silhouette, for background texture
  favicon.png            32 px mark
  apple-touch-icon.png   180 px mark on white, no transparency (iOS composites
                         transparent icons onto black)
  og-image.png           1200x630 share card, lockup centred on white

The background is removed by flood-filling near-white inward from the border
rather than by thresholding every light pixel, so the white *inside* the artwork
(the leaf's highlight stroke, the notch in the bean, the dot of the "!") survives
and the mark still reads correctly on a dark background.

Run with the project venv, from anywhere:

    Hi-Protein/.venv/bin/python Hi-Protein/scripts/make_logo_assets.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "deck" / "media" / "Hi! Protein Plant-Based Logo.png"
OUT = ROOT / "Hi-Protein" / "frontend" / "public"

# A pixel this light, reached from the border, is background. The render has faint
# noise in the white field, so an exact-white key leaves a speckled halo.
BG_TOLERANCE = 28
# Alpha ramp: fully transparent at or above this luminance, fully opaque below the
# lower bound. Without the ramp the keyed edge is a hard 1 px stair.
EDGE_HI = 250
EDGE_LO = 218


def keyed_rgba(src: Path) -> Image.Image:
    """Load the artwork with its outer white field keyed to transparent."""
    rgb = Image.open(src).convert("RGB")

    # Flood-fill the border-connected white field with a colour that cannot occur
    # in the artwork, then read that colour back as the alpha mask.
    KEY = (255, 0, 255)
    filled = rgb.copy()
    w, h = filled.size
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        ImageDraw.floodfill(filled, seed, KEY, thresh=BG_TOLERANCE)

    arr = np.asarray(filled).astype(np.int16)
    is_key = (arr[..., 0] == 255) & (arr[..., 1] == 0) & (arr[..., 2] == 255)

    base = np.asarray(rgb).astype(np.float32)
    lum = base.mean(axis=2)
    ramp = np.clip((EDGE_HI - lum) / (EDGE_HI - EDGE_LO), 0.0, 1.0)

    # Only the pixels touching the keyed field get the luminance ramp: those are the
    # antialiased glyph edges, which should fade rather than end on a hard stair.
    # White that is enclosed by the artwork never borders the field, so it stays
    # fully opaque and the mark keeps its highlights on a dark background.
    fringe = np.zeros_like(is_key)
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        fringe |= np.roll(is_key, (dy, dx), axis=(0, 1))
    fringe &= ~is_key

    alpha = np.where(is_key, 0.0, np.where(fringe, ramp, 1.0))

    out = np.dstack([base, alpha * 255.0]).astype(np.uint8)
    return Image.fromarray(out, mode="RGBA")


def trim(img: Image.Image, pad: int = 0) -> Image.Image:
    """Crop to the alpha bounding box, optionally keeping a little breathing room."""
    box = img.split()[3].getbbox()
    if box is None:
        raise SystemExit("logo keyed out to nothing - check BG_TOLERANCE")
    left, top, right, bottom = box
    if pad:
        left, top = max(0, left - pad), max(0, top - pad)
        right, bottom = min(img.width, right + pad), min(img.height, bottom + pad)
    return img.crop((left, top, right, bottom))


def split_lockup(img: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Split the stacked lockup into (symbol, wordmark).

    The two parts are separated by a band of rows that are entirely transparent, so
    we cut at the widest such band.
    """
    alpha = np.asarray(img.split()[3])
    empty = alpha.max(axis=1) < 8

    runs, start = [], None
    for y, is_empty in enumerate(empty):
        if is_empty and start is None:
            start = y
        elif not is_empty and start is not None:
            runs.append((start, y))
            start = None
    if start is not None:
        runs.append((start, len(empty)))

    interior = [r for r in runs if r[0] > 0 and r[1] < len(empty)]
    if not interior:
        raise SystemExit("no gap found between mark and wordmark")
    gap = max(interior, key=lambda r: r[1] - r[0])
    return (
        trim(img.crop((0, 0, img.width, gap[0]))),
        trim(img.crop((0, gap[1], img.width, img.height))),
    )


def horizontal(mark: Image.Image, wordmark: Image.Image, height: int = 160) -> Image.Image:
    """Compose a wide lockup: symbol to the left of the wordmark, baselines centred.

    The stacked artwork is unusable in a page header - at a 36 px header height the
    wordmark inside it is about 8 px tall and illegible. Side by side, the same
    height gives the wordmark the full 36 px.
    """
    # The symbol is set slightly taller than the wordmark, which is what the deck
    # artwork does and what keeps the leaf from looking clipped.
    word = resized_to_height(wordmark, int(height * 0.62))
    sym = resized_to_height(mark, height)
    gap = int(height * 0.18)

    canvas = Image.new("RGBA", (sym.width + gap + word.width, height), (0, 0, 0, 0))
    canvas.alpha_composite(sym, (0, (height - sym.height) // 2))
    canvas.alpha_composite(word, (sym.width + gap, (height - word.height) // 2))
    return trim(canvas)


def resized_to_height(img: Image.Image, height: int) -> Image.Image:
    return img.resize((max(1, round(img.width * height / img.height)), height), Image.LANCZOS)


def square(img: Image.Image, size: int, margin: float = 0.08) -> Image.Image:
    """Fit onto a transparent square canvas with a small even margin."""
    inner = int(size * (1 - 2 * margin))
    scaled = img.copy()
    scaled.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2), scaled)
    return canvas


def whiten(img: Image.Image) -> Image.Image:
    """Recolour to a flat white silhouette, keeping the alpha channel.

    Used only for the decorative watermark, where the shape is all that matters.
    """
    arr = np.asarray(img).copy()
    arr[..., :3] = 255
    return Image.fromarray(arr, mode="RGBA")


# The artwork uses three inks, measured off the keyed render: a near-black green, a
# mid lime green, and the white of the interior highlights.
#   dark  (13, 63, 25)   g - b =  38
#   light (107, 155, 41) g - b = 114
#   white (248, 250, 248) g - b =  2
LIGHT_TARGET = (154, 214, 80)
# Green-minus-blue bounds over which a pixel counts as the light ink. The dark ink
# and the white sit well below the lower bound, and so does any blend of the two -
# which is what the counters of "P", "o" and "e" are made of. Classifying on this
# chroma gap rather than on distance to each ink is what keeps those edges clean;
# a nearest-ink blend tints them green, because mid-grey is closer to the lime than
# to either of the colours it is actually interpolating.
LIGHT_LO, LIGHT_HI = 48.0, 100.0


def recolour_for_dark(img: Image.Image) -> Image.Image:
    """Remap the inks for use on a dark background.

    On the landing page's emerald hero the dark ink has to become white or it
    disappears, while the light ink only needs brightening. Keeping two tones
    matters: a flat white silhouette loses the strokes that separate the bean from
    the leaf, and the mark collapses into a blob.
    """
    arr = np.asarray(img).astype(np.float32)
    g, b = arr[..., 1], arr[..., 2]

    # 1 on the light ink, 0 on the dark ink, the white, and every blend of those two.
    t = np.clip((g - b - LIGHT_LO) / (LIGHT_HI - LIGHT_LO), 0.0, 1.0)[..., None]

    light = np.array(LIGHT_TARGET, dtype=np.float32)
    white = np.array((255.0, 255.0, 255.0), dtype=np.float32)
    out = t * light + (1.0 - t) * white

    return Image.fromarray(
        np.dstack([np.clip(out, 0, 255), arr[..., 3]]).astype(np.uint8), mode="RGBA"
    )


def quantised(img: Image.Image, colors: int = 48) -> Image.Image:
    """Palette-reduce a flat-colour PNG.

    The source is a render, so its flat areas are faintly noisy and compress badly -
    the full-colour lockup is 280 KB. The artwork only really holds three inks, so a
    small palette is visually identical and an order of magnitude smaller.
    """
    return img.quantize(colors=colors, method=Image.FASTOCTREE)


def resized(img: Image.Image, width: int) -> Image.Image:
    if img.width <= width:
        return img
    return img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"source artwork missing: {SRC}")
    OUT.mkdir(parents=True, exist_ok=True)

    keyed = trim(keyed_rgba(SRC), pad=2)
    lockup = resized(keyed, 900)
    mark, wordmark = split_lockup(keyed)
    wide = horizontal(mark, wordmark)

    written = []

    def save(img: Image.Image, name: str) -> None:
        path = OUT / name
        img.save(path, optimize=True)
        written.append((name, img.size, path.stat().st_size))

    save(quantised(lockup), "logo-lockup.png")
    save(quantised(recolour_for_dark(lockup)), "logo-lockup-ondark.png")
    save(quantised(wide), "logo-horizontal.png")
    save(quantised(recolour_for_dark(wide)), "logo-horizontal-ondark.png")
    save(quantised(square(mark, 256)), "logo-mark.png")
    save(quantised(square(recolour_for_dark(mark), 256)), "logo-mark-ondark.png")
    # Flat silhouette, for the hero watermark only.
    save(quantised(square(whiten(mark), 512), colors=8), "logo-mark-white.png")
    save(square(mark, 32, margin=0.0), "favicon.png")

    # iOS draws the icon on black if it is transparent, so flatten onto white.
    touch = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
    touch.alpha_composite(square(mark, 180, margin=0.12))
    save(touch.convert("RGB"), "apple-touch-icon.png")

    og = Image.new("RGBA", (1200, 630), (255, 255, 255, 255))
    card = resized(lockup, 820)
    og.alpha_composite(card, ((1200 - card.width) // 2, (630 - card.height) // 2))
    save(og.convert("RGB"), "og-image.png")

    for name, size, nbytes in written:
        print(f"{name:24} {size[0]:>5}x{size[1]:<5} {nbytes / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
