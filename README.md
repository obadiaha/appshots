# AppShots 📸

**One command. Every screen. Zero code changes.**

AppShots automatically captures every App Store screenshot for your iOS app using AI + XCUITest — no Fastlane, no Ruby, no code modifications required.

---

## Quick Start

```bash
pip install appshots

# Set an AI key (Gemini has a free tier)
export GEMINI_API_KEY="AIza..."

appshots auto --project ~/MyApp/MyApp.xcodeproj --bundle-id com.example.myapp
```

Screenshots land in `./screenshots/iPhone 16 Pro Max/`. Done.

---

## How It Works

AppShots runs a 5-step pipeline entirely on your machine:

```
1. 🔨 Build   → xcodebuild compiles your app for the simulator
2. 🧠 Analyze → AI reads your Swift source (+ storyboards) and maps every screen
3. 🔍 Explore → XCUITest dumps real accessibility trees for each app state
4. 🗺️  Plan   → AI cross-references screens with real elements → reliable navigation YAML
5. 📸 Capture → XCUITest navigates to each screen and saves a screenshot
```

No coordinate-based tapping. No brittle selectors. Navigation uses real element labels from the live app.

---

## Requirements

| Requirement | Version |
|------------|---------|
| macOS | 13+ (Ventura or later) |
| Xcode | 15+ with iOS Simulator |
| Python | 3.9+ |
| AI API key | Any one of: Gemini, Claude, or GPT-4o |

---

## Commands Reference

### `appshots auto` — Fully automatic ✨

The main command. AI + accessibility tree = screenshots for any iOS app.

```bash
appshots auto \
  --project ~/MyApp/MyApp.xcodeproj \
  --bundle-id com.example.myapp \
  --device "iPhone 16 Pro Max" \
  --output ./screenshots \
  --save-yaml appshots.yaml      # optional: save the generated config

# Specify AI provider explicitly
appshots auto --project ... --bundle-id ... \
  --provider gemini --api-key AIza...
```

### `appshots init` — Generate config manually

Generates `appshots.yaml` from your project. Use `--ai` for AI-powered screen detection.

```bash
appshots init --project ~/MyApp/MyApp.xcodeproj --ai
appshots init --project ~/MyApp/MyApp.xcodeproj      # manual (no AI)
```

### `appshots explore` — UI crawler (no AI needed)

Auto-discovers screens by crawling the UI without any AI or config.

```bash
appshots explore \
  --project ~/MyApp/MyApp.xcodeproj \
  --bundle-id com.example.myapp \
  --depth 3
```

### `appshots capture` — Run from existing config

Captures screenshots using an existing `appshots.yaml`.

```bash
appshots capture --config appshots.yaml
appshots capture --no-build     # skip xcodebuild (use existing build)
appshots capture --no-overlay   # raw screenshots, no text
```

### Other Commands

```bash
appshots overlay --input ./screenshots   # Add text overlays to existing shots
appshots resize --input ./screenshots    # Resize to all App Store sizes
appshots validate --input ./screenshots  # Check dimensions meet App Store rules
appshots clean                           # Delete temp simulators and build dirs
```

---

## AI API Key Setup

AppShots calls AI providers directly from your machine. No intermediary servers. Your key never leaves your computer.

**First run:** If no key is found, AppShots prompts you interactively:

```
⚠️  No API key found. AppShots needs an AI provider to analyze your app.

Choose a provider:
  1. Google Gemini (recommended, free tier available)
  2. Anthropic Claude
  3. OpenAI GPT-4o

Enter choice (1-3): 1

Enter your Google Gemini API key: AIza...
Save to ~/.appshots/config.json for future runs? [Y/n]: Y
  ✅ Saved to /Users/you/.appshots/config.json
```

**Or set via environment variable:**

```bash
export GEMINI_API_KEY="AIza..."          # Google Gemini (free tier)
export ANTHROPIC_API_KEY="sk-ant-..."   # Claude (best code analysis)
export OPENAI_API_KEY="sk-..."          # GPT-4o
```

**Priority order:** `--api-key` flag → `~/.appshots/config.json` → environment variable → interactive prompt.

### Supported AI Providers

| Provider | Env Variable | Notes |
|----------|-------------|-------|
| Google Gemini | `GEMINI_API_KEY` | **Recommended.** Free tier available at [aistudio.google.com](https://aistudio.google.com/apikey) |
| Anthropic Claude | `ANTHROPIC_API_KEY` | Best code understanding. [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| OpenAI GPT-4o | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com/api-keys) |

---

## Example Output

Running `appshots auto` on [Potodoro](https://apps.apple.com/app/potodoro/id6737168967) (a pomodoro timer app):

```
📸 AppShots Hybrid Capture
═══════════════════════════════════════════════════════
🔨 Building app...
  🧹 Cleaning stale build dir...
  ✅ Built in 34.2s: Potodoro.app

🧠 Step 1: AI analyzing source code...
  📐 Collected 2 storyboard/xib files
  📄 Collected 47 Swift files (98,432 chars)
  🔄 Sending to gemini...
  📋 Found 8 screens, 3 UserDefaults states

🔍 Step 2: Dumping real accessibility trees...
  📱 State 1/3: state0
    ✅ Tree dumped (4,821 chars)
  📱 State 2/3: hasCompletedOnboarding=True
    ✅ Tree dumped (6,103 chars)

🧠 Step 3: AI planning navigation from real elements...
  ✅ Navigation plan generated

📸 Step 4: Capturing screenshots...
  🎯 Capturing 7 reachable screens...
    [1/7] 01-launch-splash           ✅ ./screenshots/iPhone 16 Pro Max/01-launch-splash.png
    [2/7] 08-harvest-ready           ✅ ./screenshots/iPhone 16 Pro Max/08-harvest-ready.png
    [3/7] 09-harvest-rewards-overlay ✅ ./screenshots/iPhone 16 Pro Max/09-harvest-rewards-overlay.png
    [4/7] 10-stash-warehouse         ✅ ./screenshots/iPhone 16 Pro Max/10-stash-warehouse.png
    [5/7] 11-settings-menu          ✅ ./screenshots/iPhone 16 Pro Max/11-settings-menu.png
    [6/7] 13-pro-paywall             ✅ ./screenshots/iPhone 16 Pro Max/13-pro-paywall.png
    [7/7] 16-tag-management          ✅ ./screenshots/iPhone 16 Pro Max/16-tag-management.png
  📸 7/7 screenshots captured

═══════════════════════════════════════════════════════
⏱️  Total: 4m 23s
📸 Screenshots: 7
```

---

## Configuration (appshots.yaml)

When you need fine-grained control, edit the generated YAML:

```yaml
app:
  project: ~/MyApp/MyApp.xcodeproj
  scheme: MyApp
  bundle_id: com.example.myapp

devices:
  - name: "iPhone 16 Pro Max"
    type: "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro-Max"

runtime: "com.apple.CoreSimulator.SimRuntime.iOS-18-0"

screens:
  - name: "01-onboarding"
    navigation: []
    defaults:
      hasCompletedOnboarding: false
    caption: "Get started in seconds"
    wait_seconds: 3

  - name: "02-dashboard"
    navigation:
      - tap_tab: "Home"
    defaults:
      hasCompletedOnboarding: true
    caption: "Your command center"
    wait_seconds: 2

  - name: "03-settings"
    navigation:
      - tap_tab: "Settings"
    defaults:
      hasCompletedOnboarding: true
    caption: "Customize everything"
    wait_seconds: 2
```

### Navigation Step Reference

| Step | Example | Description |
|------|---------|-------------|
| `tap` | `tap: "Start Session"` | Tap button (falls back to static text) |
| `tap_tab` | `tap_tab: "Settings"` | Tap tab bar button by exact label |
| `tap_text` | `tap_text: "Learn More"` | Tap static text element |
| `tap_cell` | `tap_cell: "Premium Plan"` | Tap table/collection view cell |
| `tap_nav` | `tap_nav: "Back"` | Tap navigation bar button |
| `tap_switch` | `tap_switch: "Dark Mode"` | Toggle a switch |
| `tap_id` | `tap_id: "startButton"` | Tap by accessibility identifier |
| `swipe` | `swipe: "left"` | Swipe direction (up/down/left/right) |
| `scroll_to` | `scroll_to: "Privacy Policy"` | Scroll until visible, then tap |
| `type_text` | `type_text: "hello"` | Type into focused text field |
| `wait` | `wait: 2` | Wait N seconds |
| `alert_accept` | `alert_accept: true` | Accept alert dialog |
| `alert_dismiss` | `alert_dismiss: true` | Dismiss alert dialog |
| `back` | `back: true` | Tap back button in nav bar |

---

## FAQ

**Does it work with UIKit apps (Storyboards)?**
Yes. AppShots parses `.storyboard` and `.xib` files to extract view controller names, segue identifiers, and tab bar items. The AI uses this data alongside Swift source to detect UIKit screens. Navigation uses XCUITest, which works with both UIKit and SwiftUI apps.

**Does it support iPad screenshots?**
Yes. Add iPad devices to your `appshots.yaml`:
```yaml
devices:
  - name: "iPad Pro 13"
    type: "com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M4"
```

**Can I use multiple devices?**
Yes. Run `appshots capture` with multiple devices configured in `appshots.yaml`. Or run `appshots auto` separately per device with `--device`.

**What if a screen requires a real device permission (Camera, FaceID, etc.)?**
The AI marks these screens as `reachable: false` with a reason. Other screens are still captured. If the app has a `#if DEBUG` bypass (e.g., a "Simulate" toggle), AppShots uses it automatically.

**Do I need to modify my app code?**
No. AppShots navigates entirely via XCUITest (accessibility tree) and UserDefaults injection. Zero code changes required.

**Can I use it in CI?**
Yes, once `~/.appshots/config.json` is configured (or an env var is set). No interactive prompts in non-TTY environments.

**It found the wrong .app file — what happened?**
AppShots cleans the build directory before each run and matches the `.app` filename to your scheme name. If you see a mismatch, make sure `--scheme` matches your Xcode scheme exactly.

---

## App Store Connect Required Sizes

| Display Size | Device | Resolution |
|------------|--------|------------|
| 6.9" | iPhone 16 Pro Max | 1320 × 2868 |
| 6.7" | iPhone 16 Plus | 1290 × 2796 |
| 6.3" | iPhone 16 Pro | 1206 × 2622 |
| 6.1" | iPhone 16 | 1179 × 2556 |
| 4.7" | iPhone SE (3rd gen) | 750 × 1334 |
| 13" | iPad Pro (M4) | 2064 × 2752 |
| 11" | iPad Air (M3) | 2360 × 1640 |

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

Built by [Go Digital](https://godigitalapps.com) • An AI-assisted development studio
