#!/usr/bin/env python3
"""AppShots CLI - Automated App Store screenshot generation."""

import argparse
import sys
from pathlib import Path

from .capture import AppShotsCapture
from .overlay import OverlayEngine
from .resize import ResizeEngine


def main():
    parser = argparse.ArgumentParser(
        prog="appshots",
        description="Automated App Store screenshot generation for iOS developers"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    init_parser = subparsers.add_parser("init", help="Generate config from Xcode project")
    init_parser.add_argument("--project", "-p", required=True, help="Path to .xcodeproj")
    init_parser.add_argument("--output", "-o", default="appshots.yaml", help="Config output path")
    init_parser.add_argument("--ai", action="store_true", help="Use AI to analyze codebase and auto-detect screens")
    init_parser.add_argument("--provider", choices=["anthropic", "openai", "gemini"], help="AI provider (auto-detected from env vars)")
    init_parser.add_argument("--api-key", help="API key (or set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY)")
    init_parser.add_argument("--no-swift", action="store_true", help="Skip generating Swift code modifications")

    # capture
    capture_parser = subparsers.add_parser("capture", help="Build, boot, screenshot, overlay")
    capture_parser.add_argument("--config", "-c", default="appshots.yaml", help="Config file path")
    capture_parser.add_argument("--device", "-d", help="Capture single device only")
    capture_parser.add_argument("--screen", "-s", help="Capture single screen only")
    capture_parser.add_argument("--no-overlay", action="store_true", help="Skip text overlays")
    capture_parser.add_argument("--no-build", action="store_true", help="Skip xcodebuild (use existing build)")
    capture_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    # overlay
    overlay_parser = subparsers.add_parser("overlay", help="Add text overlays to existing screenshots")
    overlay_parser.add_argument("--config", "-c", default="appshots.yaml", help="Config file path")
    overlay_parser.add_argument("--input", "-i", required=True, help="Input screenshots directory")
    overlay_parser.add_argument("--output", "-o", help="Output directory (default: input/overlaid)")

    # resize
    resize_parser = subparsers.add_parser("resize", help="Resize screenshots to App Store sizes")
    resize_parser.add_argument("--input", "-i", required=True, help="Input screenshots directory")
    resize_parser.add_argument("--output", "-o", help="Output directory")
    resize_parser.add_argument("--sizes", default="required", choices=["all", "required", "iphone", "ipad"],
                              help="Which sizes to generate")

    # explore
    explore_parser = subparsers.add_parser("explore", help="Auto-discover all screens by crawling the UI (no AI needed)")
    explore_parser.add_argument("--project", "-p", required=True, help="Path to .xcodeproj")
    explore_parser.add_argument("--scheme", help="Build scheme (default: auto-detect)")
    explore_parser.add_argument("--bundle-id", required=True, help="App bundle ID")
    explore_parser.add_argument("--device", "-d", default="iPhone 16 Pro Max", help="Simulator device")
    explore_parser.add_argument("--depth", type=int, default=3, help="Max exploration depth (default: 3)")
    explore_parser.add_argument("--output", "-o", default="./screenshots", help="Output directory")
    explore_parser.add_argument("--defaults", action="append", nargs="*", help="UserDefaults key=value pairs for a state (repeatable)")
    explore_parser.add_argument("--ai-defaults", action="store_true", help="Use AI to detect UserDefaults states from source code")
    explore_parser.add_argument("--provider", choices=["anthropic", "openai", "gemini"], help="AI provider for --ai-defaults")
    explore_parser.add_argument("--api-key", help="API key for --ai-defaults")
    explore_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    # clean
    clean_parser = subparsers.add_parser("clean", help="Delete created simulators and temp files")
    clean_parser.add_argument("--config", "-c", default="appshots.yaml", help="Config file path")

    # validate
    validate_parser = subparsers.add_parser("validate", help="Check screenshots meet App Store requirements")
    validate_parser.add_argument("--input", "-i", required=True, help="Screenshots directory to validate")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        if getattr(args, "ai", False):
            from .ai_init import ai_generate_config
            ai_generate_config(
                args.project, args.output,
                provider=getattr(args, "provider", None),
                api_key=getattr(args, "api_key", None),
                generate_swift=not getattr(args, "no_swift", False),
            )
        else:
            from .init_config import generate_config
            generate_config(args.project, args.output)

    elif args.command == "capture":
        engine = AppShotsCapture(args.config, verbose=getattr(args, "verbose", False))
        engine.run(
            device_filter=args.device,
            screen_filter=args.screen,
            skip_overlay=args.no_overlay,
            skip_build=args.no_build,
        )

    elif args.command == "explore":
        from .explorer import UIExplorer
        from .capture import AppShotsCapture
        import yaml

        verbose = getattr(args, "verbose", False)

        # Build the app first
        print("📸 AppShots Explorer — Auto-discover every screen")
        print("=" * 55)

        scheme = args.scheme
        if not scheme:
            # Auto-detect scheme from project name
            proj = Path(args.project)
            scheme = proj.stem  # e.g., Potodoro.xcodeproj -> Potodoro

        print(f"🔨 Building {scheme}...")
        import subprocess
        build_dir = "/tmp/appshots-build"
        cmd = [
            "xcodebuild", "build",
            "-project", args.project,
            "-scheme", scheme,
            "-sdk", "iphonesimulator",
            "-configuration", "Debug",
            "-derivedDataPath", build_dir,
            "-quiet",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Build failed:\n{result.stderr[-1000:]}")
            sys.exit(1)

        # Find the .app
        app_path = None
        for p in Path(build_dir).rglob("*.app"):
            if "Debug-iphonesimulator" in str(p):
                app_path = str(p)
                break
        if not app_path:
            print("❌ Could not find built .app")
            sys.exit(1)
        print(f"  ✅ Built: {app_path}")

        # Find or create simulator
        runtime = "com.apple.CoreSimulator.SimRuntime.iOS-26-1"
        device_type = args.device.replace(" ", "-")
        device_name = f"AppShots-{args.device}"

        # Check for existing device
        import json as _json
        devs_result = subprocess.run(
            ["xcrun", "simctl", "list", "devices", "-j"],
            capture_output=True, text=True,
        )
        devs = _json.loads(devs_result.stdout)
        udid = None
        for rt, device_list in devs.get("devices", {}).items():
            for dev in device_list:
                if dev["name"] == device_name and dev["state"] != "Shutdown":
                    udid = dev["udid"]
                    break
                elif dev["name"] == device_name:
                    udid = dev["udid"]
            if udid:
                break

        if not udid:
            # Create the device
            dt = f"com.apple.CoreSimulator.SimDeviceType.{device_type}"
            res = subprocess.run(
                ["xcrun", "simctl", "create", device_name, dt, runtime],
                capture_output=True, text=True,
            )
            udid = res.stdout.strip()

        # Boot
        subprocess.run(["xcrun", "simctl", "boot", udid], capture_output=True)
        # Install
        subprocess.run(["xcrun", "simctl", "install", udid, app_path], capture_output=True)

        # Parse defaults states
        defaults_states = [{}]  # Always start with empty defaults

        if getattr(args, "ai_defaults", False):
            # Use AI to detect UserDefaults from source code
            from .ai_analyzer import AIAnalyzer
            analyzer = AIAnalyzer(
                provider=getattr(args, "provider", None),
                api_key=getattr(args, "api_key", None),
            )
            print("\n🧠 AI detecting UserDefaults states from source code...")
            states = analyzer.detect_defaults_states(args.project)
            if states:
                defaults_states = states
                print(f"  Found {len(states)} UserDefaults states")
        elif getattr(args, "defaults", None):
            # Manual defaults from CLI
            for state_args in args.defaults:
                state = {}
                for pair in (state_args or []):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        # Try to parse booleans/ints
                        if v.lower() in ("true", "yes"):
                            state[k] = True
                        elif v.lower() in ("false", "no"):
                            state[k] = False
                        elif v.isdigit():
                            state[k] = int(v)
                        else:
                            state[k] = v
                if state:
                    defaults_states.append(state)

        # Run explorer
        explorer = UIExplorer(args.bundle_id, verbose=verbose)
        try:
            results = explorer.explore(
                device_udid=udid,
                defaults_states=defaults_states,
                max_depth=args.depth,
                output_dir=args.output,
                device_name=args.device,
            )
            print(f"\n🎉 Done! {len(results)} screenshots saved to {args.output}/")
        finally:
            explorer.cleanup()
            subprocess.run(["xcrun", "simctl", "shutdown", udid], capture_output=True)

    elif args.command == "overlay":
        overlay = OverlayEngine(args.config)
        overlay.apply(args.input, args.output)

    elif args.command == "resize":
        resizer = ResizeEngine()
        resizer.resize(args.input, args.output, args.sizes)

    elif args.command == "clean":
        engine = AppShotsCapture(args.config)
        engine.clean()

    elif args.command == "validate":
        from .validate import validate_screenshots
        validate_screenshots(args.input)


if __name__ == "__main__":
    main()
