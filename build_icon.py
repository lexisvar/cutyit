#!/usr/bin/env python3
"""Convert assets/icon.svg → assets/icon.png (1024×1024) and assets/icon.icns (macOS)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SVG  = ROOT / "assets" / "icon.svg"
PNG  = ROOT / "assets" / "icon.png"
ICONSET = ROOT / "assets" / "icon.iconset"

# ── 1. SVG → PNG via cairosvg or rsvg-convert ───────────────────────────── #
def svg_to_png():
    # Try rsvg-convert (part of librsvg, available via Homebrew)
    result = subprocess.run(
        ["rsvg-convert", "-w", "1024", "-h", "1024", str(SVG), "-o", str(PNG)],
        capture_output=True,
    )
    if result.returncode == 0:
        print(f"✓ PNG generated via rsvg-convert: {PNG}")
        return True

    # Fallback: cairosvg (pip install cairosvg)
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(url=str(SVG), write_to=str(PNG), output_width=1024, output_height=1024)
        print(f"✓ PNG generated via cairosvg: {PNG}")
        return True
    except ImportError:
        pass

    print("✗ Neither rsvg-convert nor cairosvg found. Install one of them:")
    print("  brew install librsvg   # preferred")
    print("  pip install cairosvg   # alternative")
    return False


# ── 2. PNG → ICNS (macOS) ────────────────────────────────────────────────── #
def png_to_icns():
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        print("✗ Pillow not installed. Run: pip install Pillow")
        return False

    ICONSET.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    img = Image.open(PNG).convert("RGBA")
    for s in sizes:
        img.resize((s, s), Image.LANCZOS).save(ICONSET / f"icon_{s}x{s}.png")
        if s <= 512:
            img.resize((s * 2, s * 2), Image.LANCZOS).save(ICONSET / f"icon_{s}x{s}@2x.png")

    result = subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(ROOT / "assets" / "icon.icns")],
        capture_output=True,
    )
    if result.returncode == 0:
        print(f"✓ ICNS generated: {ROOT / 'assets' / 'icon.icns'}")
        return True
    print(f"✗ iconutil failed: {result.stderr.decode()}")
    return False


if __name__ == "__main__":
    ok = svg_to_png()
    if ok:
        png_to_icns()
    sys.exit(0 if ok else 1)
