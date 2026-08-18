from __future__ import annotations

import os
from pathlib import Path

from .models import MicropileInput, PileType


def render_pile_soil_schematic(data: MicropileInput, output_path: Path, width: int = 1200, height: int = 760) -> Path:
    """Render the same proportional pile-soil concept used by the Tkinter UI."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _font(ImageFont, 24)
    font_small = _font(ImageFont, 19)
    font_bold = _font(ImageFont, 25, bold=True)
    font_dimension = _font(ImageFont, 22, bold=True)

    h0 = data.common.above_ground_height_m
    ht = data.common.embedment_m
    soil_sum = sum(layer.thickness_m for layer in data.soils)
    below_extent = max(ht, soil_sum, 0.1)
    top, bottom = 70, 70
    scale = (height - top - bottom) / max(h0 + below_extent, 0.1)
    ground_y = top + h0 * scale
    tip_y = ground_y + ht * scale
    soil_left, soil_right = 245, width - 120
    pile_x = (soil_left + soil_right) / 2
    palette = ("#F3DFB3", "#D9C39A", "#E8C98D", "#C9D8AD", "#D7B89C", "#BDD4D8", "#DDD0AA")

    depth = 0.0
    for index, layer in enumerate(data.soils):
        y1 = ground_y + depth * scale
        y2 = ground_y + (depth + layer.thickness_m) * scale
        draw.rectangle((soil_left, y1, soil_right, y2), fill=palette[index % len(palette)], outline="#7E8791", width=2)
        label = f"{layer.name}  {layer.thickness_m:g} m"
        bbox = draw.textbbox((0, 0), label, font=font)
        draw.text((soil_right - 18 - (bbox[2] - bbox[0]), (y1 + y2) / 2 - 14), label, fill="#263238", font=font)
        draw.text((soil_left + 12, y2 - 28), f"深度 {depth + layer.thickness_m:g} m", fill="#59636E", font=font_small)
        depth += layer.thickness_m

    draw.line((soil_left - 16, ground_y, soil_right + 16, ground_y), fill="#2F3B45", width=5)
    draw.text((soil_left, ground_y - 38), "设计地面", fill="#263238", font=font_bold)

    diameter_mm = data.common.diameter_m * 1000
    if data.pile_type is PileType.GROUTED:
        pile_width = max(34, min(84, diameter_mm / 5))
        draw.rectangle((pile_x - pile_width / 2, top, pile_x + pile_width / 2, tip_y), fill="#D8DDE3", outline="#3E4A55", width=4)
        pile_title = "微型灌注桩"
        end_label = "桩端"
    else:
        assert data.helical is not None
        shaft_width = max(16, min(34, diameter_mm / 5))
        point_height = max(22, min(38, 0.05 * (tip_y - ground_y)))
        point_base = tip_y - point_height
        draw.rectangle((pile_x - shaft_width / 2, top, pile_x + shaft_width / 2, point_base), fill="#8E9AA5", outline="#34404A", width=4)
        draw.polygon(((pile_x - shaft_width / 2, point_base), (pile_x + shaft_width / 2, point_base), (pile_x, tip_y)), fill="#8E9AA5", outline="#34404A")
        blade_half = shaft_width * data.helical.blade_diameter_m / data.common.diameter_m / 2
        blade_height = max(8, min(16, blade_half * 0.30))
        for number, blade_depth in enumerate(data.helical.blade_depths_m, start=1):
            y = ground_y + blade_depth * scale
            box = (pile_x - blade_half, y - blade_height, pile_x + blade_half, y + blade_height)
            draw.ellipse(box, fill="#FFD36A", outline="#C33A2C", width=5)
            draw.line((pile_x - blade_half, y + blade_height * 0.55, pile_x + blade_half, y - blade_height * 0.55), fill="#A9271B", width=5)
            draw.ellipse((pile_x - shaft_width, y - blade_height * 0.35, pile_x + shaft_width, y + blade_height * 0.35), fill="#C46B2D", outline="#7D231B", width=3)
            label_y = y - 35 if tip_y - y < 45 else y - 13
            draw.text((pile_x + blade_half + 14, label_y), f"叶片{number}  {blade_depth:g} m", fill="#5B4317", font=font_small)
        pile_title = "钢螺旋桩"
        end_label = "桩尖"

    title_bbox = draw.textbbox((0, 0), pile_title, font=font_bold)
    draw.text((pile_x - (title_bbox[2] - title_bbox[0]) / 2, top - 42), pile_title, fill="#263238", font=font_bold)
    dimension_x = soil_left - 78
    _dimension(image, draw, dimension_x, top, ground_y, f"h0={h0:g} m", font_dimension)
    _dimension(image, draw, dimension_x, ground_y, tip_y, f"ht={ht:g} m", font_dimension)
    draw.line((pile_x - 62, tip_y, pile_x + 62, tip_y), fill="#59636E", width=2)
    draw.text((pile_x + 72, tip_y + 5), end_label, fill="#263238", font=font_small)
    draw.rectangle((1, 1, width - 2, height - 2), outline="#B8C0CA", width=2)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True, dpi=(150, 150))
    return output_path


def _dimension(image, draw, x: float, y1: float, y2: float, label: str, font) -> None:
    from PIL import Image, ImageDraw

    color = "#7A5B00"
    draw.line((x, y1, x, y2), fill=color, width=3)
    arrow = 9
    draw.polygon(((x, y1), (x - arrow, y1 + 16), (x + arrow, y1 + 16)), fill=color)
    draw.polygon(((x, y2), (x - arrow, y2 - 16), (x + arrow, y2 - 16)), fill=color)
    draw.line((x, y1, x + 35, y1), fill=color, width=2)
    draw.line((x, y2, x + 35, y2), fill=color, width=2)
    bbox = draw.textbbox((0, 0), label, font=font)
    label_width = bbox[2] - bbox[0]
    label_height = bbox[3] - bbox[1]
    label_image = Image.new("RGBA", (label_width + 8, label_height + 8), (255, 255, 255, 0))
    label_draw = ImageDraw.Draw(label_image)
    label_draw.text((4 - bbox[0], 4 - bbox[1]), label, fill="#5E4700", font=font)
    rotated = label_image.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)
    image.paste(
        rotated,
        (int(x - 16 - rotated.width / 2), int((y1 + y2) / 2 - rotated.height / 2)),
        rotated,
    )


def _font(ImageFont, size: int, bold: bool = False):
    windir = Path(os.environ.get("WINDIR", "C:/Windows"))
    candidates = [
        windir / "Fonts" / ("msyhbd.ttc" if bold else "msyh.ttc"),
        windir / "Fonts" / ("simhei.ttf" if bold else "simsun.ttc"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()
