#!/usr/bin/env python3
"""Hybrid capture: AI source analysis + real accessibility tree = reliable navigation.

Pipeline:
1. AI analyzes source code → detects screens, UserDefaults states, permissions
2. Explorer dumps real accessibility tree for each state
3. AI sees real elements + source analysis → generates reliable navigation steps
4. XCUITest executes the navigation and captures screenshots

This combines the intelligence of AI (knowing what screens exist) with the
ground truth of the accessibility tree (knowing what elements are tappable).
"""

import json
import os
import re
import shutil
import subprocess
import time
import yaml
from pathlib import Path
from typing import Optional

from .ai_analyzer import AIAnalyzer
from .explorer import UIExplorer


HYBRID_NAV_PROMPT = """You are an expert iOS XCUITest automation engineer.

You have TWO inputs:
1. SOURCE CODE ANALYSIS: A list of screens the AI detected from the Swift source code, including what UserDefaults states are needed to reach each screen.
2. REAL ACCESSIBILITY TREES: The actual XCUITest accessibility hierarchy dumped from the running app in different states.

Your job: For each screen in the source analysis, generate RELIABLE XCUITest navigation steps using ONLY elements that ACTUALLY EXIST in the accessibility trees.

RULES:
- NEVER guess element names. Only use labels/identifiers you see in the accessibility tree.
- If a screen requires a permission the simulator can't provide (FamilyControls, HealthKit, etc.), check if the source code has a #if DEBUG bypass or a "Simulate" toggle. Use it if available.
- If a screen truly cannot be reached (permission-gated with no bypass), mark it as `reachable: false` with a reason.
- For date pickers: use `tap` on the date picker element, then `adjust_picker` or skip if too complex.
- For tab bars: use `tap_tab: "TabName"` with the EXACT label from the tree.
- For buttons: use `tap: "ExactLabel"` matching the tree.
- Prefer the SIMPLEST path to each screen (fewest taps).
- Group screens by their required UserDefaults state to minimize app relaunches.

OUTPUT FORMAT (YAML only, no markdown fences, no explanation):

screens:
  - name: "01-screen-name"
    defaults:
      key: value
    navigation: []
    caption: "Marketing description"
    wait_seconds: 2
    reachable: true

  - name: "02-another-screen"
    defaults:
      hasCompletedOnboarding: true
    navigation:
      - tap_tab: "Settings"
    caption: "Customize your experience"
    wait_seconds: 2
    reachable: true

  - name: "03-gated-screen"
    defaults: {}
    navigation: []
    caption: "This screen needs permissions"
    reachable: false
    reason: "Requires FamilyControls authorization"

Navigation step types (use ONLY these):
  - tap: "ButtonLabel"           # Tap a button by exact label
  - tap_tab: "TabName"           # Tap a tab bar button
  - tap_text: "StaticText"       # Tap a static text element
  - tap_cell: "CellLabel"        # Tap a cell
  - tap_nav: "NavButtonLabel"    # Tap a navigation bar button
  - tap_switch: "SwitchLabel"    # Toggle a switch
  - tap_id: "accessibilityID"    # Tap by accessibility identifier
  - swipe: "left"                # Swipe direction
  - type_text: "hello"           # Type into focused text field
  - wait: 2                      # Wait N seconds
  - alert_accept: true           # Accept alert
  - alert_dismiss: true          # Dismiss alert
  - back: true                   # Tap back button
  - screen_tap: true             # Tap center of screen (dismiss splash)

Order screens logically. Include ALL reachable screens.
Mark unreachable ones at the end with reachable: false."""


class HybridCapture:
    """Combines AI analysis with real accessibility tree data for reliable navigation."""

    def __init__(
        self,
        project_path: str,
        bundle_id: str,
        scheme: Optional[str] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        verbose: bool = False,
    ):
        self.project_path = os.path.expanduser(project_path)
        self.bundle_id = bundle_id
        self.scheme = scheme or Path(self.project_path).stem
        self.verbose = verbose
        self.ai = AIAnalyzer(provider=provider, api_key=api_key)
        self.explorer = UIExplorer(bundle_id, verbose=verbose)

    def log(self, msg: str):
        print(msg)

    def debug(self, msg: str):
        if self.verbose:
            print(f"  [debug] {msg}")

    def run_cmd(self, cmd: list, check: bool = True) -> subprocess.CompletedProcess:
        self.debug(f"$ {' '.join(str(c) for c in cmd)}")
        return subprocess.run(cmd, capture_output=True, text=True)

    # ── Step 1: Build & Install ──────────────────────────────────────

    def build_and_install(self, device_udid: str) -> str:
        """Build the app and install on simulator. Returns .app path."""
        self.log("🔨 Building app...")
        build_start = time.time()
        build_dir = "/tmp/appshots-hybrid-build"

        cmd = [
            "xcodebuild", "build",
            "-project", self.project_path,
            "-scheme", self.scheme,
            "-sdk", "iphonesimulator",
            "-configuration", "Debug",
            "-derivedDataPath", build_dir,
            "-quiet",
        ]
        result = self.run_cmd(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"Build failed:\n{result.stderr[-1000:]}")

        # Find .app
        app_path = None
        for p in Path(build_dir).rglob("*.app"):
            if "Debug-iphonesimulator" in str(p) and "Extension" not in p.name:
                app_path = str(p)
                break
        if not app_path:
            raise RuntimeError("Could not find built .app")

        elapsed = time.time() - build_start
        self.log(f"  ✅ Built in {elapsed:.1f}s: {Path(app_path).name}")

        # Boot and install
        self.run_cmd(["xcrun", "simctl", "boot", device_udid], check=False)
        self.run_cmd(["xcrun", "simctl", "install", device_udid, app_path])
        return app_path

    # ── Step 2: AI Source Analysis ───────────────────────────────────

    def analyze_source(self) -> dict:
        """Use AI to analyze source code and detect screens + states."""
        self.log("\n🧠 Step 1: AI analyzing source code...")
        result = self.ai.analyze(self.project_path, generate_swift=False)
        
        # Parse the YAML
        yaml_text = result["screens_yaml"]
        try:
            parsed = yaml.safe_load(yaml_text)
            screens = parsed.get("screens", []) if isinstance(parsed, dict) else []
        except yaml.YAMLError:
            screens = []
        
        # Extract unique defaults states
        states = [{}]  # Always include empty state
        seen_states = [frozenset()]
        for screen in screens:
            defaults = screen.get("defaults", {})
            if defaults:
                key = frozenset(defaults.items())
                if key not in seen_states:
                    seen_states.append(key)
                    states.append(defaults)

        self.log(f"  📋 Found {len(screens)} screens, {len(states)} UserDefaults states")
        return {"screens": screens, "states": states, "raw_yaml": yaml_text}

    # ── Step 3: Dump Accessibility Trees ─────────────────────────────

    def dump_trees(self, device_udid: str, states: list[dict]) -> dict[str, str]:
        """Launch app in each state and dump the real accessibility tree."""
        self.log("\n🔍 Step 2: Dumping real accessibility trees...")
        
        self.explorer.create_explorer_project()
        
        # Generate a tree-dump-only test (no crawling)
        tests_dir = self.explorer.runner_dir / "AppShotsExplorerUITests"
        screenshots_path = str(self.explorer.output_dir).replace("\\", "\\\\")
        trees_path = str(self.explorer.tree_dir).replace("\\", "\\\\")

        code = f'''import XCTest

final class ExplorerTests: XCTestCase {{

    let bundleId = "{self.bundle_id}"
    let treesPath = "{trees_path}"
    let screenshotsPath = "{screenshots_path}"

    override func setUpWithError() throws {{
        continueAfterFailure = true
    }}

    func test_dump_tree() {{
        let app = XCUIApplication(bundleIdentifier: bundleId)
        app.launch()
        sleep(3)

        // Save full debug description
        let tree = app.debugDescription
        let url = URL(fileURLWithPath: "\\(treesPath)/tree.txt")
        try? tree.write(to: url, atomically: true, encoding: .utf8)

        // Save structured element list
        var elements: [String] = []

        elements.append("=== BUTTONS ===")
        for i in 0..<min(app.buttons.count, 50) {{
            let el = app.buttons.element(boundBy: i)
            if el.exists {{
                elements.append("button[\\(i)]: label=\\(el.label) | id=\\(el.identifier) | hittable=\\(el.isHittable) | enabled=\\(el.isEnabled)")
            }}
        }}

        elements.append("\\n=== STATIC TEXTS ===")
        for i in 0..<min(app.staticTexts.count, 50) {{
            let el = app.staticTexts.element(boundBy: i)
            if el.exists {{
                elements.append("text[\\(i)]: label=\\(el.label) | hittable=\\(el.isHittable)")
            }}
        }}

        elements.append("\\n=== TAB BARS ===")
        for i in 0..<min(app.tabBars.buttons.count, 10) {{
            let el = app.tabBars.buttons.element(boundBy: i)
            if el.exists {{
                elements.append("tab[\\(i)]: label=\\(el.label) | selected=\\(el.isSelected)")
            }}
        }}

        elements.append("\\n=== CELLS ===")
        for i in 0..<min(app.cells.count, 30) {{
            let el = app.cells.element(boundBy: i)
            if el.exists {{
                elements.append("cell[\\(i)]: label=\\(el.label) | hittable=\\(el.isHittable)")
            }}
        }}

        elements.append("\\n=== SWITCHES ===")
        for i in 0..<min(app.switches.count, 10) {{
            let el = app.switches.element(boundBy: i)
            if el.exists {{
                elements.append("switch[\\(i)]: label=\\(el.label) | value=\\(el.value ?? "nil")")
            }}
        }}

        elements.append("\\n=== NAVIGATION BARS ===")
        for i in 0..<min(app.navigationBars.count, 5) {{
            let nav = app.navigationBars.element(boundBy: i)
            if nav.exists {{
                elements.append("navbar[\\(i)]: id=\\(nav.identifier)")
                for j in 0..<min(nav.buttons.count, 10) {{
                    let btn = nav.buttons.element(boundBy: j)
                    if btn.exists {{ elements.append("  navbtn[\\(j)]: label=\\(btn.label)") }}
                }}
            }}
        }}

        elements.append("\\n=== IMAGES ===")
        for i in 0..<min(app.images.count, 20) {{
            let el = app.images.element(boundBy: i)
            if el.exists {{
                elements.append("image[\\(i)]: label=\\(el.label) | id=\\(el.identifier)")
            }}
        }}

        elements.append("\\n=== PICKERS ===")
        for i in 0..<min(app.pickers.count, 5) {{
            let el = app.pickers.element(boundBy: i)
            if el.exists {{
                elements.append("picker[\\(i)]: label=\\(el.label)")
            }}
        }}

        elements.append("\\n=== SCROLL VIEWS ===")
        elements.append("scrollViews: \\(app.scrollViews.count)")

        elements.append("\\n=== OTHER ===")
        elements.append("alerts: \\(app.alerts.count)")
        elements.append("sheets: \\(app.sheets.count)")
        elements.append("popovers: \\(app.popovers.count)")

        // Also try tapping each tab and dumping the tree for that tab
        let tabCount = app.tabBars.buttons.count
        if tabCount > 0 {{
            for t in 0..<tabCount {{
                let tab = app.tabBars.buttons.element(boundBy: t)
                if tab.exists && tab.isHittable {{
                    tab.tap()
                    sleep(1)
                    elements.append("\\n=== TAB \\(t): \\(tab.label) ===")
                    for i in 0..<min(app.buttons.count, 30) {{
                        let el = app.buttons.element(boundBy: i)
                        if el.exists && el.isHittable {{
                            elements.append("  button[\\(i)]: label=\\(el.label) | id=\\(el.identifier)")
                        }}
                    }}
                    for i in 0..<min(app.staticTexts.count, 30) {{
                        let el = app.staticTexts.element(boundBy: i)
                        if el.exists {{
                            elements.append("  text[\\(i)]: \\(el.label)")
                        }}
                    }}
                    for i in 0..<min(app.switches.count, 10) {{
                        let el = app.switches.element(boundBy: i)
                        if el.exists {{
                            elements.append("  switch[\\(i)]: \\(el.label) = \\(el.value ?? "nil")")
                        }}
                    }}
                }}
            }}
        }} else {{
            // No tab bar — try swipes for paged views
            elements.append("\\n=== SWIPE LEFT ===")
            let beforeHash = app.staticTexts.allElementsBoundByIndex.prefix(10).map {{ $0.label }}.joined(separator: "|")
            app.swipeLeft()
            sleep(1)
            let afterHash = app.staticTexts.allElementsBoundByIndex.prefix(10).map {{ $0.label }}.joined(separator: "|")
            if afterHash != beforeHash {{
                elements.append("SWIPE LEFT: NEW SCREEN")
                for i in 0..<min(app.buttons.count, 20) {{
                    let el = app.buttons.element(boundBy: i)
                    if el.exists && el.isHittable {{
                        elements.append("  button[\\(i)]: \\(el.label)")
                    }}
                }}
                for i in 0..<min(app.staticTexts.count, 20) {{
                    let el = app.staticTexts.element(boundBy: i)
                    if el.exists {{
                        elements.append("  text[\\(i)]: \\(el.label)")
                    }}
                }}
            }} else {{
                elements.append("SWIPE LEFT: SAME SCREEN")
            }}
            
            // Swipe back
            app.swipeRight()
            sleep(1)
            
            elements.append("\\n=== SWIPE RIGHT ===")
            app.swipeRight()
            sleep(1)
            let afterRight = app.staticTexts.allElementsBoundByIndex.prefix(10).map {{ $0.label }}.joined(separator: "|")
            if afterRight != beforeHash {{
                elements.append("SWIPE RIGHT: NEW SCREEN")
                for i in 0..<min(app.buttons.count, 20) {{
                    let el = app.buttons.element(boundBy: i)
                    if el.exists && el.isHittable {{
                        elements.append("  button[\\(i)]: \\(el.label)")
                    }}
                }}
                for i in 0..<min(app.staticTexts.count, 20) {{
                    let el = app.staticTexts.element(boundBy: i)
                    if el.exists {{
                        elements.append("  text[\\(i)]: \\(el.label)")
                    }}
                }}
            }} else {{
                elements.append("SWIPE RIGHT: SAME SCREEN")
            }}
        }}

        // Save screenshot too
        let screenshot = XCUIScreen.main.screenshot()
        let data = screenshot.pngRepresentation
        let ssUrl = URL(fileURLWithPath: "\\(screenshotsPath)/tree-dump.png")
        try? data.write(to: ssUrl)

        let output = elements.joined(separator: "\\n")
        let elUrl = URL(fileURLWithPath: "\\(treesPath)/elements.txt")
        try? output.write(to: elUrl, atomically: true, encoding: .utf8)
    }}
}}
'''
        test_file = tests_dir / "ExplorerTests.swift"
        test_file.write_text(code)

        # Build once
        self.explorer.build_explorer(device_udid)

        # Run for each state
        trees = {}
        for idx, defaults in enumerate(states):
            state_key = f"state{idx}"
            if defaults:
                state_key = "_".join(f"{k}={v}" for k, v in list(defaults.items())[:3])[:50]

            self.log(f"  📱 State {idx + 1}/{len(states)}: {state_key}")

            # Clear and set defaults
            self.explorer.clear_defaults(device_udid)
            self.explorer.set_defaults(device_udid, defaults)
            self.explorer.terminate_app(device_udid)

            # Clean previous tree files
            for f in self.explorer.tree_dir.glob("*"):
                f.unlink()

            # Run the tree dump test
            derived = self.explorer.runner_dir / "DerivedData"
            xctestrun_files = list(derived.rglob("*.xctestrun"))
            if not xctestrun_files:
                raise RuntimeError("No .xctestrun found")

            results_path = self.explorer.runner_dir / f"TreeDump-{idx}.xcresult"
            cmd = [
                "xcodebuild", "test-without-building",
                "-xctestrun", str(xctestrun_files[0]),
                "-destination", f"id={device_udid}",
                "-resultBundlePath", str(results_path),
            ]
            self.run_cmd(cmd, check=False)

            # Read the element list
            elements_file = self.explorer.tree_dir / "elements.txt"
            if elements_file.exists():
                trees[state_key] = elements_file.read_text()
                self.log(f"    ✅ Tree dumped ({len(trees[state_key])} chars)")
            else:
                trees[state_key] = "(no elements captured)"
                self.log(f"    ⚠️  No tree captured")

        return trees

    # ── Step 4: AI Plans Navigation ──────────────────────────────────

    def plan_navigation(self, source_analysis: dict, trees: dict[str, str]) -> str:
        """AI combines source analysis + real trees to generate reliable YAML."""
        self.log("\n🧠 Step 3: AI planning navigation from real elements...")

        # Build the prompt with both inputs
        tree_section = ""
        for state_key, tree_data in trees.items():
            tree_section += f"\n--- State: {state_key} ---\n{tree_data}\n"

        user_msg = f"""SOURCE CODE ANALYSIS (what screens exist):
{source_analysis['raw_yaml']}

REAL ACCESSIBILITY TREES (what elements are actually tappable):
{tree_section}

Generate the YAML config with reliable navigation steps.
For each screen, use ONLY elements you can see in the real accessibility trees.
Mark unreachable screens as reachable: false."""

        if self.ai.provider == "anthropic":
            response = self.ai._call_anthropic(HYBRID_NAV_PROMPT, user_msg)
        elif self.ai.provider == "openai":
            response = self.ai._call_openai(HYBRID_NAV_PROMPT, user_msg)
        elif self.ai.provider == "gemini":
            response = self.ai._call_gemini(HYBRID_NAV_PROMPT, user_msg)
        else:
            raise ValueError(f"Unknown provider: {self.ai.provider}")

        # Clean up YAML
        response = re.sub(r'^```ya?ml\s*\n?', '', response.strip())
        response = re.sub(r'\n?```\s*$', '', response)

        self.log(f"  ✅ Navigation plan generated")
        return response.strip()

    # ── Step 5: Execute Screenshots ──────────────────────────────────

    def capture(
        self,
        device_udid: str,
        yaml_config: str,
        output_dir: str = "./screenshots",
        device_name: str = "default",
    ) -> list[str]:
        """Execute the YAML config using XCTestCapture."""
        from .xctest_capture import XCTestCapture

        self.log("\n📸 Step 4: Capturing screenshots...")

        # Parse YAML
        parsed = yaml.safe_load(yaml_config)
        screens = parsed.get("screens", []) if isinstance(parsed, dict) else []

        # Filter to reachable screens only
        reachable = [s for s in screens if s.get("reachable", True)]
        unreachable = [s for s in screens if not s.get("reachable", True)]

        if unreachable:
            self.log(f"  ⚠️  {len(unreachable)} screens marked unreachable:")
            for s in unreachable:
                self.log(f"    - {s['name']}: {s.get('reason', 'unknown')}")

        self.log(f"  🎯 Capturing {len(reachable)} reachable screens...")

        # XCTestCapture expects a config dict
        config = {
            "app": {
                "bundle_id": self.bundle_id,
                "project": self.project_path,
                "scheme": self.scheme,
            }
        }
        capture = XCTestCapture(config, verbose=self.verbose)
        try:
            results = capture.capture_all(
                screens=reachable,
                device_udid=device_udid,
                output_dir=output_dir,
                device_name=device_name,
            )
            return results
        finally:
            capture.cleanup()

    # ── Full Pipeline ────────────────────────────────────────────────

    def run(
        self,
        device_udid: str,
        output_dir: str = "./screenshots",
        device_name: str = "default",
        save_yaml: Optional[str] = None,
    ) -> list[str]:
        """Run the full hybrid pipeline."""
        total_start = time.time()

        self.log("📸 AppShots Hybrid Capture")
        self.log("=" * 55)

        # Step 1: Build & install
        self.build_and_install(device_udid)

        # Step 2: AI source analysis
        source = self.analyze_source()

        # Step 3: Dump real accessibility trees
        trees = self.dump_trees(device_udid, source["states"])

        # Step 4: AI plans navigation with real elements
        yaml_config = self.plan_navigation(source, trees)

        # Save YAML if requested
        if save_yaml:
            Path(save_yaml).write_text(yaml_config)
            self.log(f"\n  💾 YAML saved: {save_yaml}")

        # Step 5: Execute screenshots
        results = self.capture(device_udid, yaml_config, output_dir, device_name)

        total = time.time() - total_start
        self.log(f"\n{'=' * 55}")
        self.log(f"⏱️  Total: {total:.1f}s")
        self.log(f"📸 Screenshots: {len(results)}")

        # Cleanup
        self.explorer.cleanup()

        return results
