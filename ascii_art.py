"""Convert a headshot into ASCII art for the profile card.

Writes two variants, because the same characters read differently on a light
and a dark background:
  ascii_light.txt  dark pixels -> dense characters (dark text on light card)
  ascii_dark.txt   bright pixels -> dense characters (light text on dark card)

The photo background is masked to spaces in both, so the face floats on the card.

Usage: py ascii_art.py ../headshot.jpg.png [--rows 40] [--crop L,T,R,B]
"""
import argparse
import os
from collections import deque

from PIL import Image, ImageFilter, ImageOps

# Sparse -> dense. No XML-special characters, so the art can go straight into SVG.
RAMP = " .,:;-~=+*cvoaxzYUJCLQ0OZmwqpdbkhB#W%@"

# Each character cell is about twice as tall as it is wide (0.6em wide, 1.2em line height).
CELL_ASPECT = 0.5


def background_mask(img, cols, rows):
    """Flood-fill the bright, low-saturation backdrop inward from the top/left/right edges.

    The bottom edge is skipped because the white shirt touches it.
    """
    small = img.resize((cols, rows), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6))
    px = small.load()

    def is_bg(x, y):
        r, g, b = px[x, y]
        return (r + g + b) / 3 > 165 and (r - b) < 45

    mask = [[False] * cols for _ in range(rows)]
    queue = deque()
    seeds = [(x, 0) for x in range(cols)]
    seeds += [(0, y) for y in range(rows)] + [(cols - 1, y) for y in range(rows)]
    for x, y in seeds:
        if is_bg(x, y) and not mask[y][x]:
            mask[y][x] = True
            queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < cols and 0 <= ny < rows and not mask[ny][nx] and is_bg(nx, ny):
                mask[ny][nx] = True
                queue.append((nx, ny))

    # A few looser passes eat the half-lit halo around the hair and stray cells
    # that are mostly surrounded by backdrop.
    def is_rim(x, y):
        r, g, b = px[x, y]
        return (r + g + b) / 3 > 130 and (r - b) < 45

    def masked_neighbors(x, y):
        return sum(
            1
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            if not (0 <= x + dx < cols and 0 <= y + dy < rows) or mask[y + dy][x + dx]
        )

    for _ in range(3):
        grow = [
            (x, y)
            for y in range(rows)
            for x in range(cols)
            if not mask[y][x]
            and ((is_rim(x, y) and masked_neighbors(x, y) >= 1) or masked_neighbors(x, y) >= 3)
        ]
        for x, y in grow:
            mask[y][x] = True
    return keep_largest_region(mask)


def keep_largest_region(mask):
    """Mask out every subject region except the biggest one (the head), so bits of
    shoulder cut off by the crop don't float around the portrait."""
    rows, cols = len(mask), len(mask[0])
    seen = [[False] * cols for _ in range(rows)]
    regions = []
    for sy in range(rows):
        for sx in range(cols):
            if mask[sy][sx] or seen[sy][sx]:
                continue
            region, queue = [], deque([(sx, sy)])
            seen[sy][sx] = True
            while queue:
                x, y = queue.popleft()
                region.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < cols and 0 <= ny < rows and not mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        queue.append((nx, ny))
            regions.append(region)
    regions.sort(key=len)
    for region in regions[:-1]:
        for x, y in region:
            mask[y][x] = True
    return mask


def to_ascii(gray, mask, dense_is_dark, knee, gamma):
    """Above `knee`, density rises at 40% speed, so a big dark mass (the hair, in the
    light variant) stays lighter than the face features. `gamma` > 1 pushes low
    densities down; the dark variant uses it so the half-lit hair edge doesn't turn
    into a ring of letters around the head."""
    px = gray.load()
    cols, rows = gray.size
    top = len(RAMP) - 1
    lines = []
    for y in range(rows):
        chars = []
        for x in range(cols):
            if mask[y][x]:
                chars.append(" ")
                continue
            level = px[x, y] / 255
            if dense_is_dark:
                level = 1 - level
            level **= gamma
            if level > knee:
                level = knee + (level - knee) * 0.4
            chars.append(RAMP[round(level * top)])
        lines.append("".join(chars).rstrip())

    # drop empty rows above/below and shared indentation, so the art's box is its content
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    indent = min(len(l) - len(l.lstrip()) for l in lines if l)
    return [l[indent:] for l in lines]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--rows", type=int, default=40)
    ap.add_argument("--crop", default="150,25,630,655", help="face box L,T,R,B in source pixels")
    ap.add_argument("--knee", type=float, default=0.6, help="light variant: soften density above this level")
    ap.add_argument("--dark-gamma", type=float, default=1.6, help="dark variant: >1 fades the hair edge")
    ap.add_argument("--gamma", type=float, default=1.0, help="<1 brightens midtones, >1 darkens")
    ap.add_argument("--local", type=int, default=24, help="local-contrast radius in source px")
    ap.add_argument("--strength", type=int, default=120, help="local-contrast amount (%%)")
    ap.add_argument("--out", default=".", help="output directory")
    args = ap.parse_args()

    img = Image.open(args.image).convert("RGB")
    box = tuple(int(v) for v in args.crop.split(","))
    face = img.crop(box)

    rows = args.rows
    cols = round(rows * (face.width / face.height) / CELL_ASPECT)

    mask = background_mask(face, cols, rows)

    # Contrast: sharpen at full size so eyes, brows and the jawline survive the
    # downscale, then stretch levels using only the subject (backdrop excluded),
    # so the whole ramp goes to the face and hair instead of hair-vs-wall.
    gray = ImageOps.grayscale(face)
    # local contrast at a few-character scale (a cell is ~8x17 source px), then fine detail
    gray = gray.filter(ImageFilter.UnsharpMask(radius=args.local, percent=args.strength, threshold=0))
    gray = gray.filter(ImageFilter.UnsharpMask(radius=5, percent=150, threshold=2))
    gray = gray.resize((cols, rows), Image.LANCZOS)
    subject = sorted(
        gray.getpixel((x, y)) for y in range(rows) for x in range(cols) if not mask[y][x]
    )
    lo = subject[int(len(subject) * 0.03)]
    hi = subject[int(len(subject) * 0.97)]
    gamma = args.gamma
    gray = gray.point(
        lambda v: round(255 * min(1, max(0, (v - lo) / max(1, hi - lo))) ** gamma)
    )

    # Dark variant only: blank the outline cells that are really hair. They mix hair with
    # the bright wall, so the contrast boost turns them into a ring of letters.
    small = face.resize((cols, rows), Image.LANCZOS).load()
    dark_mask = [row[:] for row in mask]
    for y in range(rows):
        for x in range(cols):
            # past the top/left/right border counts as wall; the bottom border cuts the collar
            on_edge = any(
                y + dy < rows and (not (0 <= x + dx < cols and 0 <= y + dy) or mask[y + dy][x + dx])
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            )
            if not mask[y][x] and on_edge and sum(small[x, y]) / 3 < 140:
                dark_mask[y][x] = True

    variants = (
        ("ascii_light.txt", mask, True, args.knee, 1.0),
        ("ascii_dark.txt", dark_mask, False, 1.0, args.dark_gamma),
    )
    for name, variant_mask, dense_is_dark, knee, variant_gamma in variants:
        lines = to_ascii(gray, variant_mask, dense_is_dark, knee, variant_gamma)
        with open(os.path.join(args.out, name), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        print(f"wrote {name}: {max(map(len, lines))}x{len(lines)}")


if __name__ == "__main__":
    main()
