#!/usr/bin/env python3
"""UI Explorer — discovers screens by actually interacting with the app.

Instead of guessing navigation from source code, this module:
1. Launches the app on a simulator
2. Dumps the real XCUITest accessibility tree
3. Finds all tappable elements
4. Taps each one, checks if a new screen appeared
5. Screenshots every unique screen
6. Repeats recursively up to a configurable depth

The user's app code is NEVER modified. No AI guessing needed for navigation.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

RUNNER_PROJECT = "AppShotsExplorer"
RUNNER_TESTS = "AppShotsExplorerUITests"


class UIExplorer:
    """Explores an app's UI by crawling the accessibility tree."""

    def __init__(self, bundle_id: str, verbose: bool = False):
        self.bundle_id = bundle_id
        self.verbose = verbose
        self.runner_dir: Path | None = None
        self.output_dir: Path | None = None
        self.tree_dir: Path | None = None
        self.seen_screens: dict[str, str] = {}  # hash -> name
        self._built = False

    def log(self, msg: str):
        print(msg)

    def debug(self, msg: str):
        if self.verbose:
            print(f"  [debug] {msg}")

    def run_cmd(self, cmd: list, check: bool = True) -> subprocess.CompletedProcess:
        self.debug(f"$ {' '.join(str(c) for c in cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(
                f"Command failed ({result.returncode}): {' '.join(str(c) for c in cmd)}\n"
                f"{result.stderr[-1000:]}"
            )
        return result

    def set_defaults(self, device_udid: str, defaults: dict):
        """Set UserDefaults via xcrun simctl spawn."""
        for key, value in defaults.items():
            if isinstance(value, bool):
                vtype, vstr = "-bool", "YES" if value else "NO"
            elif isinstance(value, int):
                vtype, vstr = "-int", str(value)
            elif isinstance(value, float):
                vtype, vstr = "-float", str(value)
            else:
                vtype, vstr = "-string", str(value)
            self.run_cmd([
                "xcrun", "simctl", "spawn", device_udid,
                "defaults", "write", self.bundle_id, key, vtype, vstr,
            ])

    def clear_defaults(self, device_udid: str):
        """Clear all UserDefaults for the app."""
        self.run_cmd([
            "xcrun", "simctl", "spawn", device_udid,
            "defaults", "delete", self.bundle_id,
        ], check=False)

    def terminate_app(self, device_udid: str):
        """Kill the app if running."""
        self.run_cmd([
            "xcrun", "simctl", "terminate", device_udid, self.bundle_id,
        ], check=False)

    # ── Explorer test generation ─────────────────────────────────────

    def create_explorer_project(self, output_base: str = "/tmp") -> Path:
        """Create a standalone XCUITest project for UI exploration."""
        self.runner_dir = Path(output_base) / "appshots-explorer"
        if self.runner_dir.exists():
            shutil.rmtree(self.runner_dir)

        project_dir = self.runner_dir / f"{RUNNER_PROJECT}.xcodeproj"
        scheme_dir = project_dir / "xcshareddata" / "xcschemes"
        tests_dir = self.runner_dir / RUNNER_TESTS

        project_dir.mkdir(parents=True)
        scheme_dir.mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        self._write_pbxproj(project_dir / "project.pbxproj")
        self._write_scheme(scheme_dir / f"{RUNNER_TESTS}.xcscheme")
        self._write_info_plist(tests_dir / "Info.plist")

        self.output_dir = self.runner_dir / "Screenshots"
        self.output_dir.mkdir()
        self.tree_dir = self.runner_dir / "Trees"
        self.tree_dir.mkdir()

        self.log(f"  📁 Explorer project: {self.runner_dir}")
        return self.runner_dir

    def generate_explorer_test(self, max_depth: int = 3, max_actions: int = 15) -> Path:
        """Generate a self-exploring XCUITest that crawls the UI.
        
        The test:
        1. Launches the app
        2. Dumps the accessibility tree + takes screenshot
        3. Finds all tappable elements (buttons, cells, links, tabs, images)
        4. For each element: taps it, checks if screen changed, screenshots if new
        5. Tries to go back (swipe right, nav back button, re-launch)
        6. Recurses up to max_depth levels
        """
        tests_dir = self.runner_dir / RUNNER_TESTS
        screenshots_path = str(self.output_dir).replace("\\", "\\\\")
        trees_path = str(self.tree_dir).replace("\\", "\\\\")

        code = f'''import XCTest

final class ExplorerTests: XCTestCase {{

    let bundleId = "{self.bundle_id}"
    let screenshotsPath = "{screenshots_path}"
    let treesPath = "{trees_path}"
    var seenHashes = Set<String>()
    var screenCount = 0
    let maxScreens = 30
    
    override func setUpWithError() throws {{
        continueAfterFailure = true
    }}
    
    // MARK: - Helpers
    
    func screenHash(_ app: XCUIApplication) -> String {{
        // Hash the visible text content to detect screen changes
        let texts = app.staticTexts.allElementsBoundByIndex.prefix(20).compactMap {{ $0.label }}
        let buttons = app.buttons.allElementsBoundByIndex.prefix(10).compactMap {{ $0.label }}
        let content = (texts + buttons).joined(separator: "|")
        // Simple hash
        var hash: UInt64 = 5381
        for c in content.utf8 {{ hash = ((hash << 5) &+ hash) &+ UInt64(c) }}
        return String(hash, radix: 16)
    }}
    
    func saveScreenshot(_ app: XCUIApplication, name: String) {{
        let screenshot = XCUIScreen.main.screenshot()
        let data = screenshot.pngRepresentation
        let url = URL(fileURLWithPath: "\\(screenshotsPath)/\\(name).png")
        try? data.write(to: url)
    }}
    
    func saveTree(_ app: XCUIApplication, name: String) {{
        let desc = app.debugDescription
        let url = URL(fileURLWithPath: "\\(treesPath)/\\(name).txt")
        try? desc.write(to: url, atomically: true, encoding: .utf8)
    }}
    
    func saveElementList(_ app: XCUIApplication, name: String) {{
        // Save a structured list of interactive elements
        var elements: [String] = []
        
        // Buttons
        for i in 0..<min(app.buttons.count, 30) {{
            let el = app.buttons.element(boundBy: i)
            if el.exists && el.isHittable {{
                elements.append("button[\\(i)]: \\(el.label) | id=\\(el.identifier)")
            }}
        }}
        
        // Static texts (some are tappable)
        for i in 0..<min(app.staticTexts.count, 30) {{
            let el = app.staticTexts.element(boundBy: i)
            if el.exists && el.isHittable {{
                elements.append("text[\\(i)]: \\(el.label)")
            }}
        }}
        
        // Tab bars
        for i in 0..<min(app.tabBars.buttons.count, 10) {{
            let el = app.tabBars.buttons.element(boundBy: i)
            if el.exists {{
                elements.append("tab[\\(i)]: \\(el.label)")
            }}
        }}
        
        // Cells
        for i in 0..<min(app.cells.count, 20) {{
            let el = app.cells.element(boundBy: i)
            if el.exists && el.isHittable {{
                elements.append("cell[\\(i)]: \\(el.label)")
            }}
        }}
        
        // Switches
        for i in 0..<min(app.switches.count, 10) {{
            let el = app.switches.element(boundBy: i)
            if el.exists {{
                elements.append("switch[\\(i)]: \\(el.label) = \\(el.value ?? "nil")")
            }}
        }}
        
        // Navigation bars
        for i in 0..<min(app.navigationBars.count, 5) {{
            let nav = app.navigationBars.element(boundBy: i)
            if nav.exists {{
                elements.append("navbar[\\(i)]: \\(nav.identifier)")
                for j in 0..<min(nav.buttons.count, 5) {{
                    let btn = nav.buttons.element(boundBy: j)
                    if btn.exists {{ elements.append("  navbtn[\\(j)]: \\(btn.label)") }}
                }}
            }}
        }}
        
        // Swipe directions available (check if content extends)
        elements.append("---")
        elements.append("swipeable: true (always try swipe left/right for paged views)")
        
        let output = elements.joined(separator: "\\n")
        let url = URL(fileURLWithPath: "\\(treesPath)/\\(name)-elements.txt")
        try? output.write(to: url, atomically: true, encoding: .utf8)
    }}
    
    func tryGoBack(_ app: XCUIApplication) {{
        // Try multiple back strategies
        let backBtn = app.navigationBars.buttons.element(boundBy: 0)
        if backBtn.exists && backBtn.isHittable {{
            backBtn.tap()
            sleep(1)
            return
        }}
        // Try close button
        let closeBtn = app.buttons["Close"].firstMatch
        if closeBtn.exists && closeBtn.isHittable {{
            closeBtn.tap()
            sleep(1)
            return
        }}
        let xBtn = app.buttons["xmark"].firstMatch
        if xBtn.exists && xBtn.isHittable {{
            xBtn.tap()
            sleep(1)
            return
        }}
        // Dismiss any presented view by swiping down
        app.swipeDown()
        sleep(1)
    }}
    
    func recordScreenIfNew(_ app: XCUIApplication, context: String) -> Bool {{
        let hash = screenHash(app)
        if seenHashes.contains(hash) {{ return false }}
        if screenCount >= maxScreens {{ return false }}
        
        seenHashes.insert(hash)
        screenCount += 1
        let name = String(format: "%02d-%@", screenCount, context)
        
        saveScreenshot(app, name: name)
        saveElementList(app, name: name)
        return true
    }}

    // MARK: - Main Explorer
    
    func test_explore() {{
        let app = XCUIApplication(bundleIdentifier: bundleId)
        app.launch()
        sleep(3)
        
        // Record initial screen
        let _ = recordScreenIfNew(app, context: "initial")
        
        // Phase 1: Try all buttons on the current screen
        exploreCurrentScreen(app, depth: 0, maxDepth: {max_depth})
        
        // Phase 2: Try swipe navigation (paged TabViews)
        let hashBefore = screenHash(app)
        
        app.swipeLeft()
        sleep(1)
        if screenHash(app) != hashBefore {{
            let _ = recordScreenIfNew(app, context: "swipe-left")
            exploreCurrentScreen(app, depth: 1, maxDepth: {max_depth})
        }}
        
        // Re-launch to reset
        app.terminate()
        app.launch()
        sleep(2)
        
        app.swipeRight()
        sleep(1)
        if screenHash(app) != hashBefore {{
            let _ = recordScreenIfNew(app, context: "swipe-right")
            exploreCurrentScreen(app, depth: 1, maxDepth: {max_depth})
        }}
        
        // Save summary
        let summary = "Total screens found: \\(screenCount)"
        let url = URL(fileURLWithPath: "\\(treesPath)/summary.txt")
        try? summary.write(to: url, atomically: true, encoding: .utf8)
    }}
    
    func exploreCurrentScreen(_ app: XCUIApplication, depth: Int, maxDepth: Int) {{
        guard depth < maxDepth else {{ return }}
        guard screenCount < maxScreens else {{ return }}
        
        let hashBefore = screenHash(app)
        
        // Collect tappable buttons (snapshot their labels first)
        var buttonLabels: [(Int, String)] = []
        for i in 0..<min(app.buttons.count, {max_actions}) {{
            let btn = app.buttons.element(boundBy: i)
            if btn.exists && btn.isHittable && !btn.label.isEmpty {{
                // Skip system/navigation buttons that would leave the app
                let skip = ["Back", "Cancel", "Done", "Close"]
                if !skip.contains(btn.label) {{
                    buttonLabels.append((i, btn.label))
                }}
            }}
        }}
        
        // Try tapping each button
        for (idx, label) in buttonLabels {{
            guard screenCount < maxScreens else {{ return }}
            
            let btn = app.buttons.element(boundBy: idx)
            guard btn.exists && btn.isHittable else {{ continue }}
            
            btn.tap()
            sleep(2)
            
            let hashAfter = screenHash(app)
            if hashAfter != hashBefore {{
                // New screen!
                let safeName = label
                    .replacingOccurrences(of: " ", with: "-")
                    .replacingOccurrences(of: "/", with: "-")
                    .prefix(30)
                let _ = recordScreenIfNew(app, context: "tap-\\(safeName)")
                
                // Recurse into the new screen
                exploreCurrentScreen(app, depth: depth + 1, maxDepth: maxDepth)
                
                // Try to go back
                tryGoBack(app)
                sleep(1)
                
                // If we couldn't go back, re-launch
                if screenHash(app) != hashBefore {{
                    app.terminate()
                    app.launch()
                    sleep(2)
                }}
            }}
        }}
        
        // Try tapping cells
        for i in 0..<min(app.cells.count, 10) {{
            guard screenCount < maxScreens else {{ return }}
            
            let cell = app.cells.element(boundBy: i)
            guard cell.exists && cell.isHittable else {{ continue }}
            
            let label = cell.label
            cell.tap()
            sleep(2)
            
            let hashAfter = screenHash(app)
            if hashAfter != hashBefore {{
                let safeName = label.prefix(30)
                    .replacingOccurrences(of: " ", with: "-")
                let _ = recordScreenIfNew(app, context: "cell-\\(safeName)")
                tryGoBack(app)
                sleep(1)
                if screenHash(app) != hashBefore {{
                    app.terminate()
                    app.launch()
                    sleep(2)
                }}
            }}
        }}
    }}
}}
'''
        test_file = tests_dir / "ExplorerTests.swift"
        test_file.write_text(code)
        self.debug(f"Generated explorer test → {test_file}")
        return test_file

    def build_explorer(self, device_udid: str):
        """Build the explorer XCUITest."""
        project_path = self.runner_dir / f"{RUNNER_PROJECT}.xcodeproj"
        self.log("  🔨 Building explorer...")
        cmd = [
            "xcodebuild", "build-for-testing",
            "-project", str(project_path),
            "-scheme", RUNNER_TESTS,
            "-destination", f"id={device_udid}",
            "-sdk", "iphonesimulator",
            "-derivedDataPath", str(self.runner_dir / "DerivedData"),
            "-quiet",
            "CODE_SIGNING_ALLOWED=NO",
        ]
        self.run_cmd(cmd)
        self._built = True
        self.log("  ✅ Explorer built")

    def run_exploration(self, device_udid: str):
        """Run the exploration test."""
        derived = self.runner_dir / "DerivedData"
        xctestrun_files = list(derived.rglob("*.xctestrun"))
        if not xctestrun_files:
            raise RuntimeError("No .xctestrun file found")
        xctestrun = xctestrun_files[0]

        self.log("  🔍 Exploring app UI...")
        results_path = self.runner_dir / "ExploreResults.xcresult"
        cmd = [
            "xcodebuild", "test-without-building",
            "-xctestrun", str(xctestrun),
            "-destination", f"id={device_udid}",
            "-resultBundlePath", str(results_path),
        ]
        result = self.run_cmd(cmd, check=False)
        
        screenshots = sorted(self.output_dir.glob("*.png"))
        self.log(f"  📸 Found {len(screenshots)} unique screens")
        return screenshots

    def explore(
        self,
        device_udid: str,
        defaults_states: list[dict] | None = None,
        max_depth: int = 3,
        max_actions: int = 15,
        output_dir: str = "./screenshots",
        device_name: str = "default",
    ) -> list[str]:
        """Full exploration pipeline.
        
        Args:
            device_udid: Simulator UDID
            defaults_states: List of UserDefaults dicts to try (each triggers a full exploration)
                           If None, explores with empty defaults only.
            max_depth: How deep to recurse into screens
            max_actions: Max buttons to try per screen
            output_dir: Where to save final screenshots
            device_name: Subfolder name
        """
        if defaults_states is None:
            defaults_states = [{}]

        self.create_explorer_project()
        self.generate_explorer_test(max_depth=max_depth, max_actions=max_actions)
        self.build_explorer(device_udid)

        all_results = []
        out = Path(output_dir) / device_name
        out.mkdir(parents=True, exist_ok=True)

        for state_idx, defaults in enumerate(defaults_states):
            state_name = f"state{state_idx}"
            if defaults:
                keys = "_".join(f"{k}={v}" for k, v in list(defaults.items())[:3])
                state_name = keys[:50].replace(" ", "")
            
            self.log(f"\n  🔄 Exploration pass {state_idx + 1}/{len(defaults_states)} ({state_name})")

            # Clear and set defaults
            self.clear_defaults(device_udid)
            self.set_defaults(device_udid, defaults)
            self.terminate_app(device_udid)

            # Clear previous screenshots for this pass
            for f in self.output_dir.glob("*.png"):
                f.unlink()

            # Run exploration
            self.run_exploration(device_udid)

            # Collect results
            for png in sorted(self.output_dir.glob("*.png")):
                dest = out / f"{state_name}_{png.name}"
                shutil.copy2(png, dest)
                all_results.append(str(dest))
                self.log(f"    ✅ {dest}")

        self.log(f"\n  📸 Total: {len(all_results)} screenshots across {len(defaults_states)} states")
        return all_results

    def cleanup(self):
        """Remove the temporary explorer project."""
        if self.runner_dir and self.runner_dir.exists():
            shutil.rmtree(self.runner_dir, ignore_errors=True)

    # ── Template files (same as xctest_capture.py) ───────────────────

    def _write_pbxproj(self, path: Path):
        content = """// !$*UTF8*$!
{
\tarchiveVersion = 1;
\tclasses = {
\t};
\tobjectVersion = 56;
\tobjects = {

/* Begin PBXBuildFile section */
\t\tAA000001 /* ExplorerTests.swift in Sources */ = {isa = PBXBuildFile; fileRef = AA000002 /* ExplorerTests.swift */; };
/* End PBXBuildFile section */

/* Begin PBXFileReference section */
\t\tAA000002 /* ExplorerTests.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = ExplorerTests.swift; sourceTree = "<group>"; };
\t\tAA000003 /* Info.plist */ = {isa = PBXFileReference; lastKnownFileType = text.plist.xml; path = Info.plist; sourceTree = "<group>"; };
\t\tAA000004 /* """ + RUNNER_TESTS + """.xctest */ = {isa = PBXFileReference; explicitFileType = wrapper.cfbundle; includeInIndex = 0; path = """ + RUNNER_TESTS + """.xctest; sourceTree = BUILT_PRODUCTS_DIR; };
/* End PBXFileReference section */

/* Begin PBXGroup section */
\t\tAA100001 = {
\t\t\tisa = PBXGroup;
\t\t\tchildren = (
\t\t\t\tAA100002 /* """ + RUNNER_TESTS + """ */,
\t\t\t\tAA100003 /* Products */,
\t\t\t);
\t\t\tsourceTree = "<group>";
\t\t};
\t\tAA100002 /* """ + RUNNER_TESTS + """ */ = {
\t\t\tisa = PBXGroup;
\t\t\tchildren = (
\t\t\t\tAA000002 /* ExplorerTests.swift */,
\t\t\t\tAA000003 /* Info.plist */,
\t\t\t);
\t\t\tpath = """ + RUNNER_TESTS + """;
\t\t\tsourceTree = "<group>";
\t\t};
\t\tAA100003 /* Products */ = {
\t\t\tisa = PBXGroup;
\t\t\tchildren = (
\t\t\t\tAA000004 /* """ + RUNNER_TESTS + """.xctest */,
\t\t\t);
\t\t\tname = Products;
\t\t\tsourceTree = "<group>";
\t\t};
/* End PBXGroup section */

/* Begin PBXNativeTarget section */
\t\tAA200001 /* """ + RUNNER_TESTS + """ */ = {
\t\t\tisa = PBXNativeTarget;
\t\t\tbuildConfigurationList = AA400002 /* Build configuration list for PBXNativeTarget \"""" + RUNNER_TESTS + """\" */;
\t\t\tbuildPhases = (
\t\t\t\tAA300001 /* Sources */,
\t\t\t\tAA300002 /* Frameworks */,
\t\t\t);
\t\t\tbuildRules = (
\t\t\t);
\t\t\tdependencies = (
\t\t\t);
\t\t\tname = """ + RUNNER_TESTS + """;
\t\t\tproductName = """ + RUNNER_TESTS + """;
\t\t\tproductReference = AA000004 /* """ + RUNNER_TESTS + """.xctest */;
\t\t\tproductType = "com.apple.product-type.bundle.ui-testing";
\t\t};
/* End PBXNativeTarget section */

/* Begin PBXProject section */
\t\tAA900001 /* Project object */ = {
\t\t\tisa = PBXProject;
\t\t\tattributes = {
\t\t\t\tBuildIndependentTargetsInParallel = 1;
\t\t\t\tLastUpgradeCheck = 1620;
\t\t\t};
\t\t\tbuildConfigurationList = AA400001 /* Build configuration list for PBXProject \"""" + RUNNER_PROJECT + """\" */;
\t\t\tcompatibilityVersion = "Xcode 14.0";
\t\t\tmainGroup = AA100001;
\t\t\tproductRefGroup = AA100003 /* Products */;
\t\t\tprojectDirPath = "";
\t\t\tprojectRoot = "";
\t\t\ttargets = (
\t\t\t\tAA200001 /* """ + RUNNER_TESTS + """ */,
\t\t\t);
\t\t};
/* End PBXProject section */

/* Begin PBXSourcesBuildPhase section */
\t\tAA300001 /* Sources */ = {
\t\t\tisa = PBXSourcesBuildPhase;
\t\t\tbuildActionMask = 2147483647;
\t\t\tfiles = (
\t\t\t\tAA000001 /* ExplorerTests.swift in Sources */,
\t\t\t);
\t\t\trunOnlyForDeploymentPostprocessing = 0;
\t\t};
/* End PBXSourcesBuildPhase section */

/* Begin PBXFrameworksBuildPhase section */
\t\tAA300002 /* Frameworks */ = {
\t\t\tisa = PBXFrameworksBuildPhase;
\t\t\tbuildActionMask = 2147483647;
\t\t\tfiles = (
\t\t\t);
\t\t\trunOnlyForDeploymentPostprocessing = 0;
\t\t};
/* End PBXFrameworksBuildPhase section */

/* Begin XCBuildConfiguration section */
\t\tAA500001 /* Debug */ = {
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {
\t\t\t\tALWAYS_SEARCH_USER_PATHS = NO;
\t\t\t\tCLANG_ENABLE_MODULES = YES;
\t\t\t\tCODE_SIGN_STYLE = Manual;
\t\t\t\tCURRENT_PROJECT_VERSION = 1;
\t\t\t\tGENERATE_INFOPLIST_FILE = YES;
\t\t\t\tIPHONEOS_DEPLOYMENT_TARGET = 17.0;
\t\t\t\tMARKETING_VERSION = 1.0;
\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = "com.appshots.explorer.uitests";
\t\t\t\tPRODUCT_NAME = "$(TARGET_NAME)";
\t\t\t\tSWIFT_VERSION = 5.0;
\t\t\t\tTARGETED_DEVICE_FAMILY = "1,2";
\t\t\t\tTEST_TARGET_NAME = "";
\t\t\t};
\t\t\tname = Debug;
\t\t};
\t\tAA500002 /* Release */ = {
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {
\t\t\t\tALWAYS_SEARCH_USER_PATHS = NO;
\t\t\t\tCLANG_ENABLE_MODULES = YES;
\t\t\t\tCODE_SIGN_STYLE = Manual;
\t\t\t\tCURRENT_PROJECT_VERSION = 1;
\t\t\t\tGENERATE_INFOPLIST_FILE = YES;
\t\t\t\tIPHONEOS_DEPLOYMENT_TARGET = 17.0;
\t\t\t\tMARKETING_VERSION = 1.0;
\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER = "com.appshots.explorer.uitests";
\t\t\t\tPRODUCT_NAME = "$(TARGET_NAME)";
\t\t\t\tSWIFT_VERSION = 5.0;
\t\t\t\tTARGETED_DEVICE_FAMILY = "1,2";
\t\t\t\tTEST_TARGET_NAME = "";
\t\t\t};
\t\t\tname = Release;
\t\t};
\t\tAA500003 /* Debug */ = {
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {
\t\t\t\tALWAYS_SEARCH_USER_PATHS = NO;
\t\t\t\tCLANG_CXX_LANGUAGE_STANDARD = "gnu++20";
\t\t\t\tCLANG_ENABLE_MODULES = YES;
\t\t\t\tCLANG_ENABLE_OBJC_ARC = YES;
\t\t\t\t"CODE_SIGN_IDENTITY[sdk=macosx*]" = "-";
\t\t\t\tCOPY_PHASE_STRIP = NO;
\t\t\t\tDEBUG_INFORMATION_FORMAT = dwarf;
\t\t\t\tENABLE_STRICT_OBJC_MSGSEND = YES;
\t\t\t\tENABLE_TESTABILITY = YES;
\t\t\t\tGCC_OPTIMIZATION_LEVEL = 0;
\t\t\t\tSDKROOT = iphoneos;
\t\t\t\tSWIFT_ACTIVE_COMPILATION_CONDITIONS = DEBUG;
\t\t\t\tSWIFT_OPTIMIZATION_LEVEL = "-Onone";
\t\t\t};
\t\t\tname = Debug;
\t\t};
\t\tAA500004 /* Release */ = {
\t\t\tisa = XCBuildConfiguration;
\t\t\tbuildSettings = {
\t\t\t\tALWAYS_SEARCH_USER_PATHS = NO;
\t\t\t\tCLANG_CXX_LANGUAGE_STANDARD = "gnu++20";
\t\t\t\tCLANG_ENABLE_MODULES = YES;
\t\t\t\tCLANG_ENABLE_OBJC_ARC = YES;
\t\t\t\t"CODE_SIGN_IDENTITY[sdk=macosx*]" = "-";
\t\t\t\tCOPY_PHASE_STRIP = NO;
\t\t\t\tDEBUG_INFORMATION_FORMAT = "dwarf-with-dsym";
\t\t\t\tENABLE_STRICT_OBJC_MSGSEND = YES;
\t\t\t\tSDKROOT = iphoneos;
\t\t\t\tSWIFT_OPTIMIZATION_LEVEL = "-Owholemodule";
\t\t\t};
\t\t\tname = Release;
\t\t};
/* End XCBuildConfiguration section */

/* Begin XCConfigurationList section */
\t\tAA400001 /* Build configuration list for PBXProject \"""" + RUNNER_PROJECT + """\" */ = {
\t\t\tisa = XCConfigurationList;
\t\t\tbuildConfigurations = (
\t\t\t\tAA500003 /* Debug */,
\t\t\t\tAA500004 /* Release */,
\t\t\t);
\t\t\tdefaultConfigurationIsVisible = 0;
\t\t\tdefaultConfigurationName = Debug;
\t\t};
\t\tAA400002 /* Build configuration list for PBXNativeTarget \"""" + RUNNER_TESTS + """\" */ = {
\t\t\tisa = XCConfigurationList;
\t\t\tbuildConfigurations = (
\t\t\t\tAA500001 /* Debug */,
\t\t\t\tAA500002 /* Release */,
\t\t\t);
\t\t\tdefaultConfigurationIsVisible = 0;
\t\t\tdefaultConfigurationName = Debug;
\t\t};
/* End XCConfigurationList section */

\t};
\trootObject = AA900001 /* Project object */;
}
"""
        path.write_text(content)

    def _write_scheme(self, path: Path):
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion = "1620" version = "1.7">
   <TestAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv = "YES" shouldAutocreateTestPlan = "YES">
      <Testables>
         <TestableReference skipped = "NO">
            <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "AA200001" BuildableName = "{RUNNER_TESTS}.xctest" BlueprintName = "{RUNNER_TESTS}" ReferencedContainer = "container:{RUNNER_PROJECT}.xcodeproj">
            </BuildableReference>
         </TestableReference>
      </Testables>
   </TestAction>
</Scheme>"""
        path.write_text(content)

    def _write_info_plist(self, path: Path):
        content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>CFBundleDevelopmentRegion</key>
\t<string>en</string>
\t<key>CFBundleExecutable</key>
\t<string>$(EXECUTABLE_NAME)</string>
\t<key>CFBundleIdentifier</key>
\t<string>$(PRODUCT_BUNDLE_IDENTIFIER)</string>
\t<key>CFBundleInfoDictionaryVersion</key>
\t<string>6.0</string>
\t<key>CFBundleName</key>
\t<string>$(PRODUCT_NAME)</string>
\t<key>CFBundlePackageType</key>
\t<string>BNDL</string>
\t<key>CFBundleShortVersionString</key>
\t<string>1.0</string>
\t<key>CFBundleVersion</key>
\t<string>1</string>
</dict>
</plist>"""
        path.write_text(content)
