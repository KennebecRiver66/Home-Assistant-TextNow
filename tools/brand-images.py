#!/usr/bin/env python3
"""Build the brand images Home Assistant and HACS load, from one master.

    python3 tools/brand-images.py        # rewrite the files
    python3 tools/brand-images.py --check  # fail if they are out of date

Needs Pillow, which is a development dependency only; the integration itself
has none.

Home Assistant serves these through ``/api/brands/integration/textnow/``,
preferring a custom integration's own ``brand/`` directory over the brands
CDN since 2026.3. The API resolves a missing file the same way the CDN does,
and those chains do not cross between the plain and the hDPI names: a request
for ``logo@2x.png`` falls back to ``logo.png`` and then ``icon.png``, never to
``icon@2x.png``. Shipping all four is what keeps the mark sharp on a hDPI
screen wherever the frontend asks for it. The ``dark_`` variants are left to
fall back, because a white mark on TextNow purple needs no dark treatment.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
MASTER = REPO / "custom_components" / "textnow" / "frontend" / "textnow-logo.png"
BRAND = REPO / "custom_components" / "textnow" / "brand"

# Home Assistant's brand image specification: 256 square for the icon, 512 for
# the hDPI version. The logo is the same square mark, so it gets the same two.
SIZES = {
    "icon.png": 256,
    "logo.png": 256,
    "icon@2x.png": 512,
    "logo@2x.png": 512,
}


def render(master: Image.Image, size: int) -> bytes:
    """Return an optimised PNG of the master at one edge length."""
    image = master if master.size == (size, size) else master.resize(
        (size, size), Image.LANCZOS
    )
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report files that would change instead of writing them",
    )
    args = parser.parse_args()

    master = Image.open(MASTER).convert("RGBA")
    if master.size != (512, 512):
        print(f"{MASTER} is {master.size}, expected 512x512", file=sys.stderr)
        return 2

    BRAND.mkdir(exist_ok=True)
    stale = []
    for name, size in SIZES.items():
        path = BRAND / name
        data = render(master, size)
        if path.is_file() and path.read_bytes() == data:
            print(f"  {name:<14} {len(data):>7,} bytes  unchanged")
            continue
        stale.append(name)
        if args.check:
            print(f"  {name:<14} out of date")
            continue
        path.write_bytes(data)
        print(f"  {name:<14} {len(data):>7,} bytes  written")

    if args.check and stale:
        print(f"\n{len(stale)} file(s) out of date; run tools/brand-images.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
