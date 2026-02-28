#!/usr/bin/env python3
"""AI-powered codebase analyzer for automatic screen detection.

BYOKeys: Users provide their own API key for Claude, Gemini, or OpenAI.
Set via environment variable or --api-key flag.

Supported providers:
  ANTHROPIC_API_KEY  → Claude (default, best results)
  OPENAI_API_KEY     → GPT-4o
  GEMINI_API_KEY     → Gemini 3 Flash
"""

import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


SYSTEM_PROMPT = """You are an expert iOS developer analyzing an iOS app codebase to map every screen in the app.

Your job: identify every distinct screen/view the user can see, and for each one, determine:
1. The screen name (descriptive, kebab-case)
2. What launch arguments would navigate to it
3. What UserDefaults values need to be set to reach it
4. What data files need to exist (e.g., JSON in Documents directory)
5. A short marketing caption describing the screen

SWIFTUI PATTERNS TO DETECT:
- TabView tabs, NavigationStack destinations, .sheet modifiers, .fullScreenCover, alerts
- @State, @AppStorage, @Binding variables that control navigation
- CommandLine.arguments parsing (existing launch arg support)
- UserDefaults reads that gate screens (onboarding, splash, etc.)
- File loads from Documents directory or app bundle

UIKIT PATTERNS TO DETECT:
- UIViewController subclasses and their storyboard/xib names
- UIStoryboard instantiation (UIStoryboard(name:bundle:).instantiateViewController)
- Segue identifiers (performSegue(withIdentifier:), shouldPerformSegue)
- UINavigationController push/pop (pushViewController, popViewController)
- UITabBarController with viewControllers
- Modal presentation (present(_:animated:), dismiss(animated:))
- UITableView/UICollectionView with cell types that lead to detail screens
- Storyboard scene identifiers and Storyboard IDs

STORYBOARD DATA (if provided):
- View controller class names and storyboard IDs
- Segue identifiers and their destinations
- Tab bar items and their view controllers
- Navigation relationships

IMPORTANT RULES:
- **CRITICAL: Check for CommandLine.arguments parsing (existing launch arg support).** If the app already reads launch arguments (e.g., `-tab=lock`, `-showQuiz`, etc.), USE THEM in launch_args for each screen. This is the primary navigation mechanism.
- **ALL dates MUST use ISO 8601 string format** (e.g., "2026-06-01T00:00:00Z"). NEVER use Unix timestamps (integers/floats like 1770287400). Swift's UserDefaults.standard.object(forKey:) as? Date requires the `-date` flag format.
- **App group UserDefaults (suiteName: "group.xxx")** cannot be nested as YAML dicts. Use flat keys with a comment, e.g.: `lastUnlockDate: "2026-01-01T12:00:00Z"  # app group key`
- **Include EVERY distinct visual state**, not just navigation destinations. If a view looks different with data vs empty, include both states.
- **Only use launch args that ALREADY exist in CommandLine.arguments parsing code.** Mark new/suggested args with a comment `# suggested - add to app`.

Output ONLY valid YAML for the screens section of appshots.yaml. No explanation, no markdown fences.

EVERY screen MUST include a `navigation` key with XCUITest tap steps to reach it.
This is what makes AppShots work on ANY app without code modification.

The navigation steps use XCUITest element queries:
  - tap_tab: "TabName"           # Tap a tab bar button
  - tap: "ButtonLabel"           # Tap a button (falls back to staticText)
  - tap_text: "Some Text"        # Tap a static text element
  - tap_cell: "CellLabel"        # Tap a table/collection view cell
  - tap_nav: "BackButton"        # Tap a navigation bar button
  - tap_switch: "SwitchLabel"    # Toggle a switch
  - tap_id: "accessibilityID"    # Tap by accessibility identifier
  - swipe: "up"                  # Swipe direction (up/down/left/right)
  - scroll_to: "ElementLabel"    # Scroll until element visible, then tap
  - type_text: "hello"           # Type into focused text field
  - wait: 2                      # Wait N seconds
  - alert_accept: true           # Accept an alert dialog
  - alert_dismiss: true          # Dismiss an alert dialog
  - back: true                   # Tap the back button in nav bar

For the FIRST screen (splash/launch), use an empty navigation: []

Format:

screens:
  - name: "01-screen-name"
    navigation: []
    defaults:
      key: value
    caption: "Marketing text for this screen"
    wait_seconds: 3
  
  - name: "02-tab-screen"
    navigation:
      - tap_tab: "Settings"
    caption: "Customize your experience"
    wait_seconds: 2

  - name: "03-deep-screen"
    navigation:
      - tap_tab: "Home"
      - tap: "Start Session"
      - wait: 1
    caption: "Begin your session"
    wait_seconds: 2

If the app ALSO has existing launch argument support (CommandLine.arguments parsing),
include launch_args as a SECONDARY method alongside navigation.

For files that need user input (like question banks), set src to "NEEDS_USER_INPUT" with a comment.
For dates, use ISO 8601: "2026-01-01T12:00:00Z"
For booleans, use true/false (YAML native, not strings).
Order screens logically (splash → onboarding → main tabs → overlays/modals).
Include ALL screens, even error states if they have distinct views."""


SWIFT_MODIFICATION_PROMPT = """Also analyze whether the app already supports launch arguments for navigation.

If it does NOT have launch argument handling, generate the Swift code that should be added to the app's main ContentView or App struct to support the screens you identified.

Output this as a separate section after the YAML:

---SWIFT_MODIFICATIONS---
// Add to ContentView.swift or [AppName]App.swift:
[generated Swift code]
---END_SWIFT_MODIFICATIONS---

The Swift code should:
- Check CommandLine.arguments for each screen flag
- Set appropriate @State variables to navigate to each screen
- Be minimal and non-destructive (wrapped in #if DEBUG)
"""

# ── Config helpers (delegated to appshots.config) ──────────────────────────────

from .config import load_config as load_saved_config, save_config, prompt_for_api_key, ensure_api_key


# ── Storyboard/XIB parsing ─────────────────────────────────────────────────────

def parse_storyboard(path: Path) -> dict:
    """Parse a .storyboard or .xib file and extract UIKit screen information."""
    info = {
        "file": str(path.name),
        "view_controllers": [],
        "segues": [],
        "tab_items": [],
        "initial_vc": None,
    }
    
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        
        # Find initial view controller
        info["initial_vc"] = root.get("initialViewController")
        
        # Iterate all elements
        for elem in root.iter():
            tag = elem.tag.lower()
            
            # View controllers
            if tag in ("viewcontroller", "tableviewcontroller", "collectionviewcontroller",
                       "navigationcontroller", "tabbarcontroller", "splitviewcontroller",
                       "pageviewcontroller", "glkviewcontroller", "avplayerviewcontroller"):
                vc_info = {
                    "type": elem.tag,
                    "id": elem.get("id"),
                    "storyboard_id": elem.get("storyboardIdentifier"),
                    "custom_class": elem.get("customClass"),
                    "title": elem.get("title"),
                    "initial": elem.get("id") == info["initial_vc"],
                }
                if any(v for v in vc_info.values()):
                    info["view_controllers"].append(vc_info)
            
            # Segues
            elif tag == "segue":
                segue_info = {
                    "identifier": elem.get("identifier"),
                    "kind": elem.get("kind"),
                    "destination": elem.get("destination"),
                }
                if segue_info["identifier"] or segue_info["destination"]:
                    info["segues"].append(segue_info)
            
            # Tab bar items
            elif tag == "tabbaritem":
                item = {
                    "title": elem.get("title"),
                    "image": elem.get("image"),
                    "id": elem.get("id"),
                }
                if item["title"]:
                    info["tab_items"].append(item)
    
    except Exception as e:
        info["parse_error"] = str(e)
    
    return info


def format_storyboard_data(storyboard_infos: list[dict]) -> str:
    """Format parsed storyboard data for inclusion in the AI prompt."""
    if not storyboard_infos:
        return ""
    
    lines = ["// === STORYBOARD / XIB DATA ==="]
    for sb in storyboard_infos:
        lines.append(f"\n// File: {sb['file']}")
        if sb.get("initial_vc"):
            lines.append(f"//   Initial VC ID: {sb['initial_vc']}")
        
        if sb.get("view_controllers"):
            lines.append("//   View Controllers:")
            for vc in sb["view_controllers"]:
                parts = []
                if vc.get("custom_class"):
                    parts.append(f"class={vc['custom_class']}")
                if vc.get("storyboard_id"):
                    parts.append(f"storyboardID={vc['storyboard_id']}")
                if vc.get("title"):
                    parts.append(f"title={vc['title']}")
                if vc.get("initial"):
                    parts.append("INITIAL")
                lines.append(f"//     [{vc['type']}] {' | '.join(parts)}")
        
        if sb.get("segues"):
            lines.append("//   Segues:")
            for seg in sb["segues"]:
                parts = []
                if seg.get("identifier"):
                    parts.append(f"id={seg['identifier']}")
                if seg.get("kind"):
                    parts.append(f"kind={seg['kind']}")
                if seg.get("destination"):
                    parts.append(f"dest={seg['destination']}")
                lines.append(f"//     {' | '.join(parts)}")
        
        if sb.get("tab_items"):
            lines.append("//   Tab Bar Items:")
            for item in sb["tab_items"]:
                lines.append(f"//     {item.get('title', 'untitled')} (image={item.get('image', 'none')})")
    
    return "\n".join(lines)


# ── Main analyzer ──────────────────────────────────────────────────────────────

class AIAnalyzer:
    def __init__(self, provider: Optional[str] = None, api_key: Optional[str] = None):
        self.provider, self.api_key = ensure_api_key(provider, api_key)

    def collect_swift_files(self, project_path: str) -> str:
        """Collect all Swift source files, storyboards, and xibs from the project."""
        project = Path(os.path.expanduser(project_path))
        project_dir = project.parent

        # Exclusion list for build artifacts / dependencies
        skip_dirs = {"Pods", "DerivedData", ".build", "Packages", "Tests", "UITests", "Preview Content"}

        def should_skip(path: Path) -> bool:
            rel = str(path.relative_to(project_dir))
            return any(f"{skip}/" in rel or rel.startswith(f"{skip}/") for skip in skip_dirs)

        # Swift files
        swift_files = sorted(f for f in project_dir.rglob("*.swift") if not should_skip(f))

        # Storyboard and XIB files (UIKit support)
        ib_files = sorted(
            f for f in list(project_dir.rglob("*.storyboard")) + list(project_dir.rglob("*.xib"))
            if not should_skip(f)
        )

        if not swift_files and not ib_files:
            raise FileNotFoundError(f"No Swift or IB files found in {project_dir}")

        # Parse storyboards/xibs and format
        storyboard_data = ""
        if ib_files:
            parsed_ibs = [parse_storyboard(f) for f in ib_files]
            storyboard_data = format_storyboard_data(parsed_ibs)
            print(f"  📐 Collected {len(ib_files)} storyboard/xib files")

        # Build context string from Swift files
        context = []
        total_chars = 0
        max_chars = 150000  # Stay within token limits

        # Include storyboard data first
        if storyboard_data:
            context.append(storyboard_data + "\n\n")
            total_chars += len(storyboard_data)

        for f in swift_files:
            try:
                content = f.read_text()
                header = f"// === {f.relative_to(project_dir)} ===\n"
                chunk = header + content + "\n\n"

                if total_chars + len(chunk) > max_chars:
                    context.append(f"// === {f.relative_to(project_dir)} === (TRUNCATED - file too large)\n")
                    context.append(content[:5000] + "\n...(truncated)\n\n")
                    total_chars += 5000
                else:
                    context.append(chunk)
                    total_chars += len(chunk)
            except Exception:
                continue

        print(f"  📄 Collected {len(swift_files)} Swift files ({total_chars:,} chars)")
        return "".join(context)

    def analyze(self, project_path: str, generate_swift: bool = True) -> dict:
        """Analyze the codebase and return screens config + optional Swift modifications."""
        print(f"🧠 AI Analysis ({self.provider})")
        
        code = self.collect_swift_files(project_path)
        
        prompt = SYSTEM_PROMPT
        if generate_swift:
            prompt += "\n\n" + SWIFT_MODIFICATION_PROMPT

        user_msg = f"Analyze this iOS app codebase and generate the appshots.yaml screens config:\n\n{code}"

        print(f"  🔄 Sending to {self.provider}...")
        
        if self.provider == "anthropic":
            response = self._call_anthropic(prompt, user_msg)
        elif self.provider == "openai":
            response = self._call_openai(prompt, user_msg)
        elif self.provider == "gemini":
            response = self._call_gemini(prompt, user_msg)
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

        # Parse response
        result = {"screens_yaml": "", "swift_code": ""}
        
        if "---SWIFT_MODIFICATIONS---" in response:
            parts = response.split("---SWIFT_MODIFICATIONS---")
            result["screens_yaml"] = parts[0].strip()
            swift_part = parts[1].split("---END_SWIFT_MODIFICATIONS---")[0] if "---END_SWIFT_MODIFICATIONS---" in parts[1] else parts[1]
            result["swift_code"] = swift_part.strip()
        else:
            result["screens_yaml"] = response.strip()

        # Clean up yaml (remove markdown fences if AI added them)
        yaml_text = result["screens_yaml"]
        yaml_text = re.sub(r'^```ya?ml\s*\n?', '', yaml_text)
        yaml_text = re.sub(r'\n?```\s*$', '', yaml_text)
        result["screens_yaml"] = yaml_text.strip()

        return result

    def _call_anthropic(self, system: str, user: str) -> str:
        """Call Claude API."""
        import urllib.request
        
        data = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 16384,
            "system": system,
            "messages": [{"role": "user", "content": user}]
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result["content"][0]["text"]

    def _call_openai(self, system: str, user: str) -> str:
        """Call OpenAI API."""
        import urllib.request
        
        data = json.dumps({
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 16384,
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"]

    def _call_gemini(self, system: str, user: str) -> str:
        """Call Gemini API."""
        import urllib.request
        
        data = json.dumps({
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": 65536},
        }).encode()

        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={self.api_key}",
            data=data,
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
            try:
                return result["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                import sys
                print(f"\n⚠️  Unexpected Gemini response structure:", file=sys.stderr)
                if "candidates" in result and result["candidates"]:
                    cand = result["candidates"][0]
                    if "finishReason" in cand:
                        print(f"  Finish reason: {cand['finishReason']}", file=sys.stderr)
                    if "content" in cand:
                        print(f"  Content keys: {list(cand['content'].keys())}", file=sys.stderr)
                    else:
                        print(f"  Candidate keys: {list(cand.keys())}", file=sys.stderr)
                elif "error" in result:
                    print(f"  Error: {result['error']}", file=sys.stderr)
                else:
                    print(f"  Top-level keys: {list(result.keys())}", file=sys.stderr)
                raise RuntimeError(f"Failed to parse Gemini response: {e}")
