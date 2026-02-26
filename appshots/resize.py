#!/usr/bin/env python3
"""Resize engine - generates all App Store Connect required sizes."""

from pathlib import Path
from PIL import Image

# App Store Connect required screenshot specifications (2025/2026)
APP_STORE_SIZES = {
    # iPhone
    "iPhone-6.9": {"width": 1320, "height": 2868, "label": "6.9\" Display (iPhone 16 Pro Max)"},
    "iPhone-6.7": {"width": 1290, "height": 2796, "label": "6.7\" Display (iPhone 16 Plus)"},
    "iPhone-6.3": {"width": 1206, "height": 2622, "label": "6.3\" Display (iPhone 16 Pro)"},
    "iPhone-6.1": {"width": 1179, "height": 2556, "label": "6.1\" Display (iPhone 16)"},
    "iPhone-5.5": {"width": 1242, "height": 2208, "label": "5.5\" Display (iPhone 8 Plus)"},
    "iPhone-4.7": {"width": 750, "height": 1334, "label": "4.7\" Display (iPhone SE 3rd gen)"},
    # iPad
    "iPad-13": {"width": 2064, "height": 2752, "label": "13\" Display (iPad Pro M4)"},
    "iPad-11": {"width": 2360, "height": 1640, "label": "11\" Display (iPad Air)"},
    "iPad-10.9": {"width": 2360, "height": 1640, "label": "10.9\" Display (iPad 10th gen)"},
}

GROUPS = {
    "required": ["iPhone-6.9", "iPhone-6.7", "iPhone-6.1"],
    "iphone": [k for k in APP_STORE_SIZES if k.startswith("iPhone")],
    "ipad": [k for k in APP_STORE_SIZES if k.startswith("iPad")],
    "all": list(APP_STORE_SIZES.keys()),
}


class ResizeEngine:
    def resize(self, input_dir: str, output_dir: str = None, sizes: str = "required"):
        input_path = Path(input_dir)
        output_path = Path(output_dir) if output_dir else input_path / "resized"
        
        target_sizes = GROUPS.get(sizes, GROUPS["required"])
        
        images = sorted(list(input_path.glob("*.png")) + list(input_path.glob("*.jpg")))
        if not images:
            print(f"No images found in {input_dir}")
            return

        print(f"📐 Resizing {len(images)} images to {len(target_sizes)} sizes")
        
        for size_key in target_sizes:
            spec = APP_STORE_SIZES[size_key]
            size_dir = output_path / size_key
            size_dir.mkdir(parents=True, exist_ok=True)
            
            print(f"\n  {spec['label']} ({spec['width']}×{spec['height']})")
            
            for img_file in images:
                img = Image.open(img_file)
                
                # Calculate resize to fill target dimensions
                target_w, target_h = spec["width"], spec["height"]
                img_ratio = img.width / img.height
                target_ratio = target_w / target_h
                
                if img_ratio > target_ratio:
                    # Image is wider, fit height
                    new_h = target_h
                    new_w = int(target_h * img_ratio)
                else:
                    # Image is taller, fit width
                    new_w = target_w
                    new_h = int(target_w / img_ratio)
                
                img = img.resize((new_w, new_h), Image.LANCZOS)
                
                # Center crop to exact dimensions
                left = (new_w - target_w) // 2
                top = (new_h - target_h) // 2
                img = img.crop((left, top, left + target_w, top + target_h))
                
                out_path = size_dir / img_file.name
                img.save(str(out_path), "PNG")
                print(f"    ✅ {img_file.name}")
        
        print(f"\n🎉 Resized screenshots saved to {output_path}/")
