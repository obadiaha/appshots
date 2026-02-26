#!/usr/bin/env python3
"""XCUITest-based capture engine — navigates UI without code modification.

Instead of requiring launch arguments in the user's app, this engine:
1. Creates a standalone XCUITest runner project (temp directory)
2. Generates Swift test code that taps through the UI to reach each screen
3. Each test method saves a screenshot directly to the filesystem
4. Cleans up the runner project after capture

The user's app code is NEVER modified.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

RUNNER_PROJECT = "AppShotsRunner"
RUNNER_TESTS = "AppShotsRunnerUITests"


class XCTestCapture:
    """Captures screenshots by generating and running XCUITests."""

    def __init__(self, config: dict, verbose: bool = False):
        self.config = config
        self.verbose = verbose
        self.app = config["app"]
        self.bundle_id = self.app["bundle_id"]
        self.runner_dir: Path | None = None
        self.screenshots_dir: Path | None = None

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

    # ── Project creation ──────────────────────────────────────────────

    def create_runner_project(self, output_base: str = "/tmp") -> Path:
        """Create a standalone XCUITest project in a temp directory."""
        self.runner_dir = Path(output_base) / "appshots-runner"
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

        # Screenshots will be saved here by the test code
        self.screenshots_dir = self.runner_dir / "Captures"
        self.screenshots_dir.mkdir()

        self.log(f"  📁 Runner project: {self.runner_dir}")
        return self.runner_dir

    # ── Test code generation ──────────────────────────────────────────

    def generate_test_code(self, screens: list) -> Path:
        """Generate Swift XCUITest code that navigates to each screen and saves a screenshot."""
        tests_dir = self.runner_dir / RUNNER_TESTS
        captures_path = str(self.screenshots_dir).replace("\\", "\\\\")

        methods = []
        for i, screen in enumerate(screens):
            nav = screen.get("navigation", [])
            wait = screen.get("wait_seconds", 2)
            name = screen["name"]
            safe_name = name.replace("-", "_").replace(" ", "_")
            method = f"test_{i:03d}_{safe_name}"

            defaults_code = self._generate_defaults_code(screen.get("defaults", {}))
            nav_code = self._generate_nav_code(nav)

            methods.append(f'''
    func {method}() {{
        let app = XCUIApplication(bundleIdentifier: "{self.bundle_id}")
{defaults_code}
        app.launch()
        sleep(UInt32({wait}))

{nav_code}

        sleep(UInt32({wait}))

        // Save screenshot to filesystem
        let screenshot = XCUIScreen.main.screenshot()
        let data = screenshot.pngRepresentation
        let url = URL(fileURLWithPath: "{captures_path}/{name}.png")
        try! data.write(to: url)
    }}''')

        code = f'''import XCTest

final class ScreenshotTests: XCTestCase {{

    override func setUpWithError() throws {{
        continueAfterFailure = true
    }}
{"".join(methods)}
}}
'''
        test_file = tests_dir / "ScreenshotTests.swift"
        test_file.write_text(code)
        self.debug(f"Generated {len(methods)} test methods → {test_file}")
        return test_file

    def _generate_defaults_code(self, defaults: dict) -> str:
        """Generate Swift code to set UserDefaults via launch args."""
        if not defaults:
            return ""
        # XCUIApplication supports setting launch arguments
        # We can pass UserDefaults via -AppleLanguages style or via launchArguments
        lines = ["        // Set UserDefaults via launch arguments"]
        args = []
        for key, value in defaults.items():
            if isinstance(value, bool):
                args.append(f'"-{key}"')
                args.append(f'"{str(value).lower()}"')
            else:
                args.append(f'"-{key}"')
                args.append(f'"{value}"')
        if args:
            args_str = ", ".join(args)
            lines.append(f"        app.launchArguments = [{args_str}]")
        return "\n".join(lines)

    def _generate_nav_code(self, steps: list) -> str:
        """Convert YAML navigation steps to Swift XCUITest code."""
        if not steps:
            return "        // Landing screen — no navigation needed"

        lines = []
        for step in steps:
            if isinstance(step, str):
                # Simple string = tap button by label
                lines.append(f'        app.buttons["{step}"].firstMatch.tap()')
            elif isinstance(step, dict):
                lines.extend(self._step_to_swift(step))
        return "\n".join(lines)

    def _step_to_swift(self, step: dict) -> list[str]:
        """Convert a single navigation step dict to Swift lines."""
        lines = []
        if "tap_tab" in step:
            lines.append(f'        app.tabBars.buttons["{step["tap_tab"]}"].firstMatch.tap()')
        elif "tap" in step:
            label = step["tap"]
            lines.append(f'        // Try button first, then any element')
            lines.append(f'        let btn = app.buttons["{label}"].firstMatch')
            lines.append(f'        if btn.waitForExistence(timeout: 3) {{ btn.tap() }}')
            lines.append(f'        else {{ app.staticTexts["{label}"].firstMatch.tap() }}')
        elif "tap_text" in step:
            lines.append(f'        app.staticTexts["{step["tap_text"]}"].firstMatch.tap()')
        elif "tap_cell" in step:
            lines.append(f'        app.cells.containing(.staticText, identifier: "{step["tap_cell"]}").firstMatch.tap()')
        elif "tap_nav" in step:
            lines.append(f'        app.navigationBars.buttons["{step["tap_nav"]}"].firstMatch.tap()')
        elif "tap_link" in step:
            lines.append(f'        app.links["{step["tap_link"]}"].firstMatch.tap()')
        elif "tap_switch" in step:
            lines.append(f'        app.switches["{step["tap_switch"]}"].firstMatch.tap()')
        elif "tap_id" in step:
            lines.append(f'        app.otherElements["{step["tap_id"]}"].firstMatch.tap()')
        elif "tap_image" in step:
            lines.append(f'        app.images["{step["tap_image"]}"].firstMatch.tap()')
        elif "swipe" in step:
            d = step["swipe"]
            lines.append(f'        app.swipe{d.capitalize()}()')
        elif "scroll_to" in step:
            label = step["scroll_to"]
            lines.append(f'        let target = app.staticTexts["{label}"].firstMatch')
            lines.append(f'        while !target.isHittable {{ app.swipeUp() }}')
            lines.append(f'        target.tap()')
        elif "type_text" in step:
            text = step["type_text"]
            field = step.get("field", None)
            if field:
                lines.append(f'        app.textFields["{field}"].firstMatch.tap()')
            else:
                lines.append(f'        app.textFields.firstMatch.tap()')
            lines.append(f'        app.typeText("{text}")')
        elif "wait" in step:
            lines.append(f'        sleep(UInt32({step["wait"]}))')
        elif "dismiss_keyboard" in step:
            lines.append(f'        app.keyboards.buttons["Return"].tap()')
        elif "back" in step:
            lines.append(f'        app.navigationBars.buttons.element(boundBy: 0).tap()')
        elif "alert_accept" in step:
            lines.append(f'        let alert = app.alerts.firstMatch')
            lines.append(f'        if alert.waitForExistence(timeout: 3) {{')
            lines.append(f'            alert.buttons.element(boundBy: 1).tap()')
            lines.append(f'        }}')
        elif "alert_dismiss" in step:
            lines.append(f'        let alert = app.alerts.firstMatch')
            lines.append(f'        if alert.waitForExistence(timeout: 3) {{')
            lines.append(f'            alert.buttons.element(boundBy: 0).tap()')
            lines.append(f'        }}')
        elif "sheet_select" in step:
            lines.append(f'        app.sheets.buttons["{step["sheet_select"]}"].firstMatch.tap()')
        return lines

    # ── Build and run ─────────────────────────────────────────────────

    def build_runner(self, device_udid: str):
        """Build the XCUITest runner for the given simulator."""
        project_path = self.runner_dir / f"{RUNNER_PROJECT}.xcodeproj"

        self.log("  🔨 Building UI test runner...")
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
        self.log("  ✅ Runner built")

    def run_tests(self, device_udid: str):
        """Run all UI tests (screenshot capture)."""
        # Find xctestrun file
        derived = self.runner_dir / "DerivedData"
        xctestrun_files = list(derived.rglob("*.xctestrun"))
        if not xctestrun_files:
            raise RuntimeError("No .xctestrun file found after build")

        xctestrun = xctestrun_files[0]
        self.debug(f"xctestrun: {xctestrun}")

        self.log("  🧪 Running screenshot tests...")
        results_path = self.runner_dir / "Results.xcresult"

        cmd = [
            "xcodebuild", "test-without-building",
            "-xctestrun", str(xctestrun),
            "-destination", f"id={device_udid}",
            "-resultBundlePath", str(results_path),
        ]
        # Don't check=True because test failures are OK (screenshots still saved)
        result = self.run_cmd(cmd, check=False)

        # Count captured screenshots
        captured = list(self.screenshots_dir.glob("*.png"))
        self.log(f"  ✅ Tests done — {len(captured)} screenshots captured")

        if result.returncode != 0 and not captured:
            self.log(f"  ⚠️  Tests failed and no screenshots captured")
            self.debug(result.stderr[-1000:])

        return captured

    # ── Full pipeline ─────────────────────────────────────────────────

    def capture_all(
        self,
        screens: list,
        device_udid: str,
        output_dir: str,
        device_name: str = "default",
    ) -> list[str]:
        """Full pipeline: create project → generate tests → build → run → collect."""
        self.create_runner_project()
        self.generate_test_code(screens)
        self.build_runner(device_udid)

        # Make sure app is installed first (caller should handle this)
        self.run_tests(device_udid)

        # Copy screenshots to final output directory
        out = Path(output_dir) / device_name
        out.mkdir(parents=True, exist_ok=True)

        results = []
        for png in sorted(self.screenshots_dir.glob("*.png")):
            dest = out / png.name
            shutil.copy2(png, dest)
            results.append(str(dest))
            self.log(f"    ✅ {dest}")

        return results

    def cleanup(self):
        """Remove the temporary runner project."""
        if self.runner_dir and self.runner_dir.exists():
            shutil.rmtree(self.runner_dir, ignore_errors=True)
            self.debug("Cleaned up runner project")

    # ── Template files ────────────────────────────────────────────────

    def _write_pbxproj(self, path: Path):
        """Write a minimal valid project.pbxproj for a UI test-only target."""
        content = """// !$*UTF8*$!
{
	archiveVersion = 1;
	classes = {
	};
	objectVersion = 56;
	objects = {

/* Begin PBXBuildFile section */
		AA000001 /* ScreenshotTests.swift in Sources */ = {isa = PBXBuildFile; fileRef = AA000002 /* ScreenshotTests.swift */; };
/* End PBXBuildFile section */

/* Begin PBXFileReference section */
		AA000002 /* ScreenshotTests.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = ScreenshotTests.swift; sourceTree = "<group>"; };
		AA000003 /* Info.plist */ = {isa = PBXFileReference; lastKnownFileType = text.plist.xml; path = Info.plist; sourceTree = "<group>"; };
		AA000004 /* AppShotsRunnerUITests.xctest */ = {isa = PBXFileReference; explicitFileType = wrapper.cfbundle; includeInIndex = 0; path = AppShotsRunnerUITests.xctest; sourceTree = BUILT_PRODUCTS_DIR; };
/* End PBXFileReference section */

/* Begin PBXGroup section */
		AA100001 = {
			isa = PBXGroup;
			children = (
				AA100002 /* AppShotsRunnerUITests */,
				AA100003 /* Products */,
			);
			sourceTree = "<group>";
		};
		AA100002 /* AppShotsRunnerUITests */ = {
			isa = PBXGroup;
			children = (
				AA000002 /* ScreenshotTests.swift */,
				AA000003 /* Info.plist */,
			);
			path = AppShotsRunnerUITests;
			sourceTree = "<group>";
		};
		AA100003 /* Products */ = {
			isa = PBXGroup;
			children = (
				AA000004 /* AppShotsRunnerUITests.xctest */,
			);
			name = Products;
			sourceTree = "<group>";
		};
/* End PBXGroup section */

/* Begin PBXNativeTarget section */
		AA200001 /* AppShotsRunnerUITests */ = {
			isa = PBXNativeTarget;
			buildConfigurationList = AA400002 /* Build configuration list for PBXNativeTarget "AppShotsRunnerUITests" */;
			buildPhases = (
				AA300001 /* Sources */,
				AA300002 /* Frameworks */,
			);
			buildRules = (
			);
			dependencies = (
			);
			name = AppShotsRunnerUITests;
			productName = AppShotsRunnerUITests;
			productReference = AA000004 /* AppShotsRunnerUITests.xctest */;
			productType = "com.apple.product-type.bundle.ui-testing";
		};
/* End PBXNativeTarget section */

/* Begin PBXProject section */
		AA500001 /* Project object */ = {
			isa = PBXProject;
			attributes = {
				BuildIndependentTargetsInParallel = 1;
				LastSwiftUpdateCheck = 1620;
				LastUpgradeCheck = 1620;
			};
			buildConfigurationList = AA400001 /* Build configuration list for PBXProject "AppShotsRunner" */;
			compatibilityVersion = "Xcode 14.0";
			developmentRegion = en;
			hasScannedForEncodings = 0;
			knownRegions = (
				en,
				Base,
			);
			mainGroup = AA100001;
			productRefGroup = AA100003 /* Products */;
			projectDirPath = "";
			projectRoot = "";
			targets = (
				AA200001 /* AppShotsRunnerUITests */,
			);
		};
/* End PBXProject section */

/* Begin PBXSourcesBuildPhase section */
		AA300001 /* Sources */ = {
			isa = PBXSourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
				AA000001 /* ScreenshotTests.swift in Sources */,
			);
			runOnlyForDeploymentPostprocessing = 0;
		};
/* End PBXSourcesBuildPhase section */

/* Begin PBXFrameworksBuildPhase section */
		AA300002 /* Frameworks */ = {
			isa = PBXFrameworksBuildPhase;
			buildActionMask = 2147483647;
			files = (
			);
			runOnlyForDeploymentPostprocessing = 0;
		};
/* End PBXFrameworksBuildPhase section */

/* Begin XCBuildConfiguration section */
		AA600001 /* Debug */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				ALWAYS_SEARCH_USER_PATHS = NO;
				CLANG_ENABLE_MODULES = YES;
				CODE_SIGNING_ALLOWED = NO;
				CODE_SIGN_IDENTITY = "";
				INFOPLIST_FILE = AppShotsRunnerUITests/Info.plist;
				IPHONEOS_DEPLOYMENT_TARGET = 17.0;
				LD_RUNPATH_SEARCH_PATHS = (
					"$(inherited)",
					"@executable_path/Frameworks",
					"@loader_path/Frameworks",
				);
				PRODUCT_BUNDLE_IDENTIFIER = com.appshots.runner.uitests;
				PRODUCT_NAME = "$(TARGET_NAME)";
				SDKROOT = iphoneos;
				SUPPORTED_PLATFORMS = "iphonesimulator iphoneos";
				SWIFT_VERSION = 5.0;
				TARGETED_DEVICE_FAMILY = "1,2";
				TEST_TARGET_NAME = "";
			};
			name = Debug;
		};
		AA600002 /* Debug */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				ALWAYS_SEARCH_USER_PATHS = NO;
				CLANG_ENABLE_MODULES = YES;
				CODE_SIGNING_ALLOWED = NO;
				CODE_SIGN_IDENTITY = "";
				IPHONEOS_DEPLOYMENT_TARGET = 17.0;
				SDKROOT = iphoneos;
				SUPPORTED_PLATFORMS = "iphonesimulator iphoneos";
				SWIFT_VERSION = 5.0;
			};
			name = Debug;
		};
/* End XCBuildConfiguration section */

/* Begin XCConfigurationList section */
		AA400001 /* Build configuration list for PBXProject "AppShotsRunner" */ = {
			isa = XCConfigurationList;
			buildConfigurations = (
				AA600002 /* Debug */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Debug;
		};
		AA400002 /* Build configuration list for PBXNativeTarget "AppShotsRunnerUITests" */ = {
			isa = XCConfigurationList;
			buildConfigurations = (
				AA600001 /* Debug */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Debug;
		};
/* End XCConfigurationList section */

	};
	rootObject = AA500001 /* Project object */;
}
"""
        path.write_text(content)

    def _write_scheme(self, path: Path):
        """Write a shared xcscheme so xcodebuild can find the target."""
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<Scheme
   LastUpgradeVersion = "1620"
   version = "1.7">
   <TestAction
      buildConfiguration = "Debug"
      selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB"
      selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB"
      shouldUseLaunchSchemeArgsEnv = "YES"
      shouldAutocreateTestPlan = "YES">
      <Testables>
         <TestableReference
            skipped = "NO">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "AA200001"
               BuildableName = "{RUNNER_TESTS}.xctest"
               BlueprintName = "{RUNNER_TESTS}"
               ReferencedContainer = "container:{RUNNER_PROJECT}.xcodeproj">
            </BuildableReference>
         </TestableReference>
      </Testables>
   </TestAction>
</Scheme>
"""
        path.write_text(content)

    def _write_info_plist(self, path: Path):
        content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>$(DEVELOPMENT_LANGUAGE)</string>
	<key>CFBundleExecutable</key>
	<string>$(EXECUTABLE_NAME)</string>
	<key>CFBundleIdentifier</key>
	<string>$(PRODUCT_BUNDLE_IDENTIFIER)</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>$(PRODUCT_NAME)</string>
	<key>CFBundlePackageType</key>
	<string>$(PRODUCT_BUNDLE_PACKAGE_TYPE)</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
</dict>
</plist>
"""
        path.write_text(content)
