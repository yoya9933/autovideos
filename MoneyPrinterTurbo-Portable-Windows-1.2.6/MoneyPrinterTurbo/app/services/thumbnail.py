"""
thumbnail.py
------------
Generate YouTube Shorts thumbnails using Pillow (PIL).

Pillow handles CJK text reliably on Windows without the code-page
issues that affect ImageMagick's command-line text rendering.

Design:
  - 1280 x 720 px (standard YouTube thumbnail ratio)
  - Dark navy to forest-green vertical gradient background
  - Hot-pink (#f72585) top & bottom accent bars
  - Bold white title text with drop-shadow
  - "#SHORTS" label centred on the bottom bar
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

from loguru import logger

from app.config import config


def _cjk_font_path() -> str:
    """Return the path to a CJK-capable font file."""
    font_name = config.app.get("font_name", "MicrosoftYaHeiBold.ttc")
    resource_font = Path(config.root_dir) / "resource" / "fonts" / font_name
    if resource_font.exists():
        return str(resource_font)
    for p in [
        r"C:\Windows\Fonts\msjhbd.ttc",
        r"C:\Windows\Fonts\msjh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
    ]:
        if os.path.isfile(p):
            return p
    return ""


def _wrap_title(title: str, chars_per_line: int = 13) -> str:
    lines = textwrap.wrap(title, width=chars_per_line)
    return "\n".join(lines) if lines else title


def _vertical_gradient(draw, width: int, height: int,
                        top_color: tuple, bottom_color: tuple) -> None:
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))


def generate_thumbnail(
    title: str,
    output_path: str,
    width: int = 1280,
    height: int = 720,
    topic: str = "",
) -> str:
    """
    Generate a branded YouTube thumbnail and save it to *output_path*.
    Returns output_path on success, empty string on failure.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.error("Pillow is not installed; cannot generate thumbnail")
        return ""

    try:
        font_path = _cjk_font_path()
        if not font_path:
            logger.warning("No CJK font found; thumbnail text may not render correctly")

        # Theme-specific color configuration
        theme_styles = {
            "ai_tools": {
                "top": (10, 10, 26),         # Deep space dark
                "bottom": (25, 4, 130),      # Cyber blue/purple
                "accent": (114, 9, 183),     # Neon purple (#7209b7)
            },
            "semiconductor_stock": {
                "top": (13, 27, 42),         # Deep navy
                "bottom": (43, 45, 66),      # Slate gray
                "accent": (247, 127, 0),     # Amber/Orange (#f77f00)
            },
            "security_fraud": {
                "top": (20, 10, 10),         # Cyber dark red
                "bottom": (55, 6, 23),       # Deep wine red
                "accent": (208, 0, 0),       # Warning red (#d00000)
            },
            "default": {
                "top": (13, 27, 42),         # Original navy
                "bottom": (27, 67, 50),      # Original forest green
                "accent": (247, 37, 133),    # Original hot pink
            }
        }

        style = theme_styles.get(topic, theme_styles["default"])
        top_color = style["top"]
        bottom_color = style["bottom"]
        accent = style["accent"]

        bar_h  = 64
        shadow = (0, 0, 0, 160)    # semi-transparent black

        # 1. Canvas + gradient background
        img  = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img, "RGBA")
        _vertical_gradient(draw, width, height,
                           top_color=top_color,
                           bottom_color=bottom_color)

        # 2. Accent bars
        draw.rectangle([(0, 0), (width, bar_h)], fill=accent)
        draw.rectangle([(0, height - bar_h), (width, height)], fill=accent)

        # 3. Load fonts
        try:
            title_font  = ImageFont.truetype(font_path, size=80) if font_path else ImageFont.load_default()
            shorts_font = ImageFont.truetype(font_path, size=34) if font_path else ImageFont.load_default()
        except Exception as fe:
            logger.warning(f"font load failed ({fe}); using default")
            title_font  = ImageFont.load_default()
            shorts_font = ImageFont.load_default()

        # 4. #SHORTS label
        shorts_text = "#SHORTS"
        bbox = draw.textbbox((0, 0), shorts_text, font=shorts_font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        sx = (width - tw) // 2
        sy = height - bar_h + (bar_h - th) // 2
        draw.text((sx, sy), shorts_text, font=shorts_font, fill="white")

        # 5. Title (auto-wrapped, vertically centred between the two bars)
        wrapped = _wrap_title(title, chars_per_line=13)
        lines = wrapped.split("\n")
        line_spacing = 12

        line_widths, line_heights = [], []
        for line in lines:
            b = draw.textbbox((0, 0), line, font=title_font)
            line_widths.append(b[2] - b[0])
            line_heights.append(b[3] - b[1])

        total_h  = sum(line_heights) + line_spacing * (len(lines) - 1)
        usable_t = bar_h + 20
        usable_h = (height - bar_h) - usable_t
        y = usable_t + (usable_h - total_h) // 2

        for i, line in enumerate(lines):
            x = (width - line_widths[i]) // 2
            draw.text((x + 3, y + 3), line, font=title_font, fill=shadow)   # shadow
            draw.text((x, y), line, font=title_font, fill="white")           # text
            y += line_heights[i] + line_spacing

        # 6. Save
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        img.save(output_path, "JPEG", quality=92)

        size_kb = os.path.getsize(output_path) // 1024
        logger.success(f"thumbnail generated: {output_path} ({size_kb} KB)")
        return output_path

    except Exception as exc:
        logger.error(f"generate_thumbnail error: {exc}")
        return ""
