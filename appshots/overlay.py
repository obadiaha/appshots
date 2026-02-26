#!/usr/bin/env python3
"""Text overlay engine for marketing screenshots."""

import os
import yaml
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


class OverlayEngine:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        
        self.overlay_config = self.config.get("overlays", {})
        self.font_name = self.overlay_config.get("font", "Arial Bold")
        self.font_size = self.overlay_config.get("font_size", 72)
        self.text_color = self.overlay_config.get("text_color", "#FFFFFF")
        self.outline_color = self.overlay_config.get("outline_color", "#000000")
        self.outline_width = self.overlay_config.get("outline_width", 4)
        self.position = self.overlay_config.get("position", "top")
        self.use_gradient = self.overlay_config.get("gradient_overlay", True)

    def find_font(self, size: int) -> ImageFont.FreeTypeFont:
        font_paths = [
            f"/System/Library/Fonts/Supplemental/{self.font_name}.ttf",
            f"/Library/Fonts/{self.font_name}.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    return ImageFont.truetype(fp, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def draw_text_with_outline(self, draw, text, position, font, fill, outline, outline_width):
        x, y = position
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx * dx + dy * dy <= outline_width * outline_width:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline)
        draw.text((x, y), text, font=font, fill=fill)

    def add_gradient(self, img: Image.Image, position: str, height: int = 400) -> Image.Image:
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        w, h = img.size

        if position == "top":
            for y in range(height):
                alpha = int(200 * (1 - y / height))
                draw.rectangle([(0, y), (w, y + 1)], fill=(0, 0, 0, alpha))
        elif position == "bottom":
            for y in range(h - height, h):
                alpha = int(200 * ((y - (h - height)) / height))
                draw.rectangle([(0, y), (w, y + 1)], fill=(0, 0, 0, alpha))
        elif position == "center":
            center = h // 2
            half = height // 2
            for y in range(center - half, center + half):
                dist = abs(y - center)
                alpha = int(180 * (1 - dist / half))
                draw.rectangle([(0, y), (w, y + 1)], fill=(0, 0, 0, alpha))

        return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    def apply_text(self, img: Image.Image, caption: str) -> Image.Image:
        if not caption:
            return img

        if self.use_gradient:
            img = self.add_gradient(img, self.position)

        draw = ImageDraw.Draw(img)
        font = self.find_font(self.font_size)
        
        lines = caption.split("\n") if "\n" in caption else [caption]
        line_height = self.font_size + 10
        total_height = len(lines) * line_height
        w, h = img.size

        if self.position == "top":
            start_y = 80
        elif self.position == "bottom":
            start_y = h - total_height - 80
        else:
            start_y = (h - total_height) // 2

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            x = (w - tw) // 2
            y = start_y + i * line_height
            self.draw_text_with_outline(
                draw, line, (x, y), font,
                fill=self.text_color,
                outline=self.outline_color,
                outline_width=self.outline_width,
            )

        return img

    def apply(self, input_dir: str, output_dir: str = None):
        """Apply overlays to all images in a directory."""
        input_path = Path(input_dir)
        output_path = Path(output_dir) if output_dir else input_path / "overlaid"
        output_path.mkdir(parents=True, exist_ok=True)

        screens = self.config.get("screens", [])
        caption_map = {s["name"]: s.get("caption", "") for s in screens}

        for img_file in sorted(input_path.glob("*.png")):
            stem = img_file.stem
            caption = caption_map.get(stem, "")
            
            if not caption:
                print(f"  ⏭️  {stem} — no caption, copying as-is")
                img = Image.open(img_file)
            else:
                print(f"  🎨 {stem} — \"{caption}\"")
                img = Image.open(img_file)
                img = self.apply_text(img, caption)
            
            out = output_path / img_file.name
            img.save(str(out), "PNG")

        print(f"  ✅ Overlaid screenshots saved to {output_path}/")

    def apply_to_captures(self, base_dir: str, screens: list, organize_by: str):
        """Apply overlays to captured screenshots organized by device or screen."""
        base = Path(base_dir)
        caption_map = {s["name"]: s.get("caption", "") for s in screens}

        count = 0
        for img_file in sorted(base.rglob("*.png")):
            stem = img_file.stem
            caption = caption_map.get(stem, "")
            
            if not caption:
                continue
            
            img = Image.open(img_file)
            img = self.apply_text(img, caption)
            img.save(str(img_file), "PNG")
            count += 1

        print(f"  ✅ Applied overlays to {count} screenshots")
