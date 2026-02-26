#!/usr/bin/env python3
"""Generate initial appshots.yaml from an Xcode project."""

import json
import os
import subprocess
import re
from pathlib import Path


def generate_config(project_path: str, output_path: str):
    """Generate an appshots.yaml config from an Xcode project."""
    project = Path(os.path.expanduser(project_path))
    
    if not project.exists():
        print(f"❌ Project not found: {project}")
        return
    
    print(f"🔍 Analyzing {project.name}...")
    
    # Try to extract scheme and bundle ID
    scheme = project.stem  # Default to project name
    bundle_id = f"com.example.{scheme.lower()}"
    
    # Check for schemes
    result = subprocess.run(
        ["xcodebuild", "-project", str(project), "-list", "-json"],
        capture_output=True, text=True
    )
    
    if result.returncode == 0:
        try:
            info = json.loads(result.stdout)
            schemes = info.get("project", {}).get("schemes", [])
            if schemes:
                scheme = schemes[0]
                print(f"  Found scheme: {scheme}")
        except json.JSONDecodeError:
            pass
    
    # Try to find bundle ID from pbxproj
    pbxproj = project / "project.pbxproj"
    if pbxproj.exists():
        content = pbxproj.read_text()
        match = re.search(r'PRODUCT_BUNDLE_IDENTIFIER\s*=\s*"?([^";]+)"?', content)
        if match:
            bundle_id = match.group(1)
            # Handle $(PRODUCT_NAME) style variables
            if "$(" in bundle_id:
                bundle_id = bundle_id.replace("$(PRODUCT_NAME:rfc1034identifier)", scheme.lower())
            print(f"  Found bundle ID: {bundle_id}")
    
    # Find available runtimes
    result = subprocess.run(
        ["xcrun", "simctl", "list", "runtimes", "-j"],
        capture_output=True, text=True
    )
    runtime = "com.apple.CoreSimulator.SimRuntime.iOS-26-1"
    if result.returncode == 0:
        try:
            runtimes = json.loads(result.stdout).get("runtimes", [])
            ios_runtimes = [r for r in runtimes if r.get("platform") == "iOS" and r.get("isAvailable")]
            if ios_runtimes:
                runtime = ios_runtimes[-1]["identifier"]
                print(f"  Using runtime: {runtime}")
        except (json.JSONDecodeError, KeyError):
            pass
    
    # Scan Swift files for potential screens
    screens_hint = []
    swift_files = list(project.parent.rglob("*.swift"))
    tab_pattern = re.compile(r'case\s+(\w+)')
    
    for sf in swift_files:
        try:
            content = sf.read_text()
            if "TabView" in content or "selectedTab" in content:
                matches = tab_pattern.findall(content)
                for m in matches:
                    if m.lower() not in ("some", "none", "true", "false", "self"):
                        screens_hint.append(m)
        except Exception:
            pass
    
    # Generate config
    config = f"""# AppShots Configuration — {scheme}
# Generated from: {project}
# Edit screens below to match your app's navigation

app:
  project: {project}
  scheme: {scheme}
  bundle_id: {bundle_id}

runtime: {runtime}

# App Store Connect required devices
# Minimum: 6.9" and 6.7" (or just 6.9" if identical)
devices:
  - name: "iPhone 16 Pro Max"
    type: "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro-Max"
  - name: "iPhone 16 Pro"
    type: "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro"
  - name: "iPhone SE (3rd generation)"
    type: "com.apple.CoreSimulator.SimDeviceType.iPhone-SE-3rd-generation"

# Define your screens
# Each screen needs launch_args your app responds to
# See README.md for how to add launch argument support to your app
screens:
"""
    
    if screens_hint:
        for i, screen in enumerate(screens_hint[:10], 1):
            config += f"""  - name: "{i:02d}-{screen.lower()}"
    launch_args: ["-tab={screen.lower()}"]
    defaults:
      hasCompletedOnboarding: true
    caption: "{screen.replace('_', ' ').title()}"
    wait_seconds: 2

"""
    else:
        config += """  - name: "01-home"
    launch_args: []
    defaults: {}
    caption: "Welcome to your app"
    wait_seconds: 2

  - name: "02-feature"
    launch_args: ["-screen=feature"]
    defaults: {}
    caption: "Your key feature"
    wait_seconds: 2

"""
    
    config += """# Marketing text overlays (optional)
overlays:
  enabled: true
  font: "Arial Bold"
  font_size: 72
  text_color: "#FFFFFF"
  outline_color: "#000000"
  outline_width: 4
  position: "top"
  gradient_overlay: true

# Output settings
output:
  directory: "./screenshots"
  format: "png"
  organize_by: "device"
"""
    
    with open(output_path, "w") as f:
        f.write(config)
    
    print(f"\n✅ Config written to {output_path}")
    print(f"   Edit screens to match your app, then run: appshots capture")
