#!/usr/bin/env python3
"""Validate screenshots meet App Store Connect requirements."""

from pathlib import Path
from PIL import Image

# App Store requirements
MIN_SCREENSHOTS = 1
MAX_SCREENSHOTS = 10
ALLOWED_FORMATS = {".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE_MB = 30  # App Store limit

REQUIRED_SIZES = {
    (1320, 2868): "6.9\" iPhone 16 Pro Max",
    (2868, 1320): "6.9\" iPhone 16 Pro Max (landscape)",
    (1290, 2796): "6.7\" iPhone 16 Plus",
    (2796, 1290): "6.7\" iPhone 16 Plus (landscape)",
    (1206, 2622): "6.3\" iPhone 16 Pro",
    (2622, 1206): "6.3\" iPhone 16 Pro (landscape)",
    (1179, 2556): "6.1\" iPhone 16",
    (2556, 1179): "6.1\" iPhone 16 (landscape)",
    (750, 1334): "4.7\" iPhone SE",
    (1334, 750): "4.7\" iPhone SE (landscape)",
    (2064, 2752): "13\" iPad Pro",
    (2752, 2064): "13\" iPad Pro (landscape)",
}


def validate_screenshots(input_dir: str):
    """Validate all screenshots in a directory."""
    input_path = Path(input_dir)
    
    if not input_path.exists():
        print(f"❌ Directory not found: {input_dir}")
        return
    
    print(f"🔍 Validating screenshots in {input_dir}")
    print("=" * 50)
    
    # Find all image files recursively
    images = []
    for ext in ALLOWED_FORMATS:
        images.extend(input_path.rglob(f"*{ext}"))
    images = sorted(images)
    
    if not images:
        print("❌ No screenshots found")
        return
    
    print(f"Found {len(images)} screenshots\n")
    
    errors = []
    warnings = []
    valid = 0
    
    sizes_found = set()
    
    for img_path in images:
        rel = img_path.relative_to(input_path)
        img = Image.open(img_path)
        w, h = img.size
        file_size_mb = img_path.stat().st_size / (1024 * 1024)
        
        size_key = (w, h)
        device = REQUIRED_SIZES.get(size_key, "Unknown device")
        sizes_found.add(size_key)
        
        issues = []
        
        # Check file size
        if file_size_mb > MAX_FILE_SIZE_MB:
            issues.append(f"Too large: {file_size_mb:.1f}MB (max {MAX_FILE_SIZE_MB}MB)")
        
        # Check if recognized size
        if size_key not in REQUIRED_SIZES:
            issues.append(f"Non-standard size: {w}×{h}")
        
        # Check format
        if img_path.suffix.lower() not in ALLOWED_FORMATS:
            issues.append(f"Unsupported format: {img_path.suffix}")
        
        if issues:
            for issue in issues:
                if "Non-standard" in issue:
                    warnings.append(f"⚠️  {rel}: {issue}")
                else:
                    errors.append(f"❌ {rel}: {issue}")
        else:
            valid += 1
            print(f"  ✅ {rel} — {w}×{h} ({device}, {file_size_mb:.1f}MB)")
    
    print()
    
    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  {w}")
        print()
    
    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  {e}")
        print()
    
    # Check coverage
    required_portrait = {(1320, 2868), (1290, 2796)}  # Minimum required
    missing = required_portrait - sizes_found
    if missing:
        for m in missing:
            device = REQUIRED_SIZES.get(m, "Unknown")
            print(f"⚠️  Missing required size: {m[0]}×{m[1]} ({device})")
    
    print(f"\nSummary: {valid} valid, {len(warnings)} warnings, {len(errors)} errors")
    
    if not errors and not missing:
        print("✅ All screenshots pass App Store validation!")
    else:
        print("⚠️  Fix issues above before uploading to App Store Connect")
