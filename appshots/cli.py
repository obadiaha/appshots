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
