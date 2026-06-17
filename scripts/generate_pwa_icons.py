"""Generate PWA icons (192, 512, 512-maskable) for the WC2026 predictor.

Run once to (re)create static/icons/*.png. PIL only, no SVG renderer needed.

    python scripts/generate_pwa_icons.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Install Pillow first:  pip install Pillow")
    sys.exit(1)


ICON_DIR = os.path.join(ROOT, "static", "icons")
os.makedirs(ICON_DIR, exist_ok=True)


def _font(size: int):
    """Pick a bold, condensed-friendly font that ships with most OSes.
    Falls back to PIL default if nothing usable found."""
    candidates = [
        # Windows
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def make_icon(size: int, *, maskable: bool = False) -> Image.Image:
    """Draw the icon at `size`x`size` pixels.

    Layout (mirrors the favicon we already use):
      • Gold rounded-square background (full-bleed on maskable, inset on regular)
      • Tri-stripe at top (USA red / CAN red / MEX green) — host-country motif
      • Black soccer-ball outline (circle)
      • Bold "26" centered inside the ball
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Maskable icons get a "safe zone" — actual art lives in the inner 80%.
    # We just expand the gold background to bleed to the edges in maskable mode.
    pad = 0 if maskable else int(size * 0.04)
    radius = int(size * 0.22) if not maskable else 0  # no rounding on maskable
    body = [pad, pad, size - pad, size - pad]

    # Gold rounded-square background (with optional gradient look via two layers)
    gold = (251, 191, 36, 255)  # #fbbf24
    gold_deep = (245, 158, 11, 255)  # #f59e0b
    if radius > 0:
        d.rounded_rectangle(body, radius=radius, fill=gold)
        # subtle bottom darkening for depth
        for i in range(int(size * 0.15)):
            alpha = int(60 * (i / (size * 0.15)))
            y = size - pad - i
            d.line([(pad + radius // 2, y), (size - pad - radius // 2, y)],
                   fill=(245, 158, 11, alpha), width=1)
    else:
        d.rectangle(body, fill=gold)

    # Inner content area (for maskable, shrink everything into the safe zone)
    inner_pad = int(size * 0.12) if maskable else int(size * 0.10)
    inner = (inner_pad, inner_pad, size - inner_pad, size - inner_pad)
    inner_w = inner[2] - inner[0]

    # Tri-stripe near the top (host country bars: USA red, CAN red, MEX green)
    stripe_y = inner[1] + int(inner_w * 0.05)
    stripe_h = max(3, int(size * 0.05))
    stripe_w = inner_w // 3
    colors = [(178, 34, 52, 255), (213, 43, 30, 255), (0, 104, 71, 255)]
    for i, c in enumerate(colors):
        x1 = inner[0] + i * stripe_w
        x2 = x1 + stripe_w
        d.rectangle([x1, stripe_y, x2, stripe_y + stripe_h], fill=c)

    # Soccer ball outline (circle)
    ball_cx = size // 2
    ball_cy = inner[1] + int(inner_w * 0.55)
    ball_r = int(inner_w * 0.34)
    ring_w = max(3, int(size * 0.025))
    d.ellipse(
        [ball_cx - ball_r, ball_cy - ball_r, ball_cx + ball_r, ball_cy + ball_r],
        outline=(26, 26, 26, 255), width=ring_w
    )

    # "26" centered inside the ball
    font_size = int(ball_r * 1.15)
    f = _font(font_size)
    text = "26"
    try:
        bbox = d.textbbox((0, 0), text, font=f)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = ball_cx - tw // 2 - bbox[0]
        ty = ball_cy - th // 2 - bbox[1]
    except AttributeError:
        # PIL <8: fall back to textsize
        tw, th = d.textsize(text, font=f)
        tx, ty = ball_cx - tw // 2, ball_cy - th // 2
    d.text((tx, ty), text, fill=(26, 26, 26, 255), font=f)
    return img


def main():
    targets = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable.png", 512, True),
        ("apple-touch-icon.png", 180, False),
    ]
    for name, size, maskable in targets:
        img = make_icon(size, maskable=maskable)
        out = os.path.join(ICON_DIR, name)
        img.save(out, "PNG", optimize=True)
        print(f"  wrote {out}  ({size}x{size}{', maskable' if maskable else ''})")
    print("\nDone. Icons are in static/icons/")


if __name__ == "__main__":
    main()
