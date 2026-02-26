# AppShots 📸

**Automated App Store screenshot generation for iOS developers.**

Stop manually screenshotting 6 devices × 10 screens = 60 screenshots every release. AppShots automates the entire process.

## What It Does

1. **Boots iOS Simulators** for every required device size
2. **Navigates your app** to each screen using launch arguments
3. **Takes pixel-perfect screenshots** at every App Store Connect resolution
4. **Adds marketing overlays** (optional: text captions + device frames)
5. **Outputs organized folders** ready for App Store Connect upload

## Why AppShots?

| Problem | AppShots Solution |
|---------|-------------------|
| `xcrun simctl` has no tap/swipe | Launch arguments + UserDefaults injection |
| 60+ screenshots per release | One command, all devices, all screens |
| Manual text overlays in Figma | Built-in PIL-based text overlay engine |
| Different resolutions per device | Auto-handles all App Store sizes |
| fastlane snapshot needs Ruby + complex config | Zero dependencies beyond Xcode + Python 3 |

## Quick Start

```bash
# Clone
git clone https://github.com/obadiaha/appshots.git
cd appshots

# Install (Python 3.9+, Xcode required)
pip install -e .

# Generate config from your Xcode project
appshots init --project /path/to/YourApp.xcodeproj

# Edit the config to define your screens
nano appshots.yaml

# Run
appshots capture
```

## How It Works

AppShots uses three techniques to navigate your app without UI interaction:

### 1. Launch Arguments (Primary)
Define screens via launch arguments your app responds to:

```swift
// In your app's ContentView or App struct:
if CommandLine.arguments.contains("-screen=settings") {
    selectedTab = .settings
}
if CommandLine.arguments.contains("-showQuiz") {
    showQuiz = true
}
```

### 2. UserDefaults Injection
Set app state before launch:

```yaml
screens:
  - name: "main-dashboard"
    defaults:
      hasCompletedOnboarding: true
      isProtecting: true
```

AppShots runs `defaults write <bundle-id> <key> <value>` before each launch.

### 3. Environment Variables
Pass data via environment variables:

```yaml
screens:
  - name: "quiz-view"
    env:
      MOCK_QUESTION_INDEX: "5"
      SHOW_CORRECT_ANSWER: "true"
```

## Configuration (appshots.yaml)

```yaml
# App info
app:
  project: ~/Desktop/MyApp/MyApp.xcodeproj
  scheme: MyApp              # Xcode scheme to build
  bundle_id: com.example.myapp

# Devices to screenshot (maps to App Store Connect requirements)
devices:
  - name: "iPhone 16 Pro Max"   # 6.9" display (required)
    type: "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro-Max"
  - name: "iPhone 16 Pro"       # 6.3" display (required)
    type: "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro"
  - name: "iPhone SE"           # 4.7" display (optional)
    type: "com.apple.CoreSimulator.SimDeviceType.iPhone-SE-3rd-generation"
  - name: "iPad Pro 13"         # 12.9" display (if universal)
    type: "com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M4"

# Runtime
runtime: "com.apple.CoreSimulator.SimRuntime.iOS-26-1"

# Screens to capture
screens:
  - name: "01-home"
    launch_args: ["-tab=home"]
    defaults:
      hasCompletedOnboarding: true
    caption: "Your personalized dashboard"
    wait_seconds: 2

  - name: "02-settings"
    launch_args: ["-tab=settings"]
    defaults:
      hasCompletedOnboarding: true
    caption: "Customize everything"
    wait_seconds: 2

  - name: "03-onboarding"
    launch_args: []
    defaults:
      hasCompletedOnboarding: false
    caption: "Get started in seconds"
    wait_seconds: 3

# Marketing overlays (optional)
overlays:
  enabled: true
  font: "Arial Bold"
  font_size: 72
  text_color: "#FFFFFF"
  outline_color: "#000000"
  outline_width: 4
  position: "top"          # top, bottom, center
  gradient_overlay: true   # darken behind text for readability

# Output
output:
  directory: "./screenshots"
  format: "png"
  organize_by: "device"    # device (device/screen) or screen (screen/device)
```

## App Store Connect Required Sizes

AppShots automatically captures the correct resolution for each device:

| Display Size | Device | Resolution |
|-------------|--------|------------|
| 6.9" | iPhone 16 Pro Max | 1320 × 2868 |
| 6.7" | iPhone 16 Plus | 1290 × 2796 |
| 6.3" | iPhone 16 Pro | 1206 × 2622 |
| 6.1" | iPhone 16 | 1179 × 2556 |
| 4.7" | iPhone SE (3rd gen) | 750 × 1334 |
| 13" | iPad Pro (M4) | 2064 × 2752 |
| 11" | iPad Air (M3) | 2360 × 1640 |

## Resize Mode

Already have screenshots from one device? Resize to all required sizes:

```bash
appshots resize --input ./my-screenshots/ --sizes all
```

## CLI Reference

```bash
appshots init      # Generate config from Xcode project
appshots capture   # Full capture: build → boot → screenshot → overlay
appshots overlay   # Add text overlays to existing screenshots  
appshots resize    # Resize screenshots to all App Store sizes
appshots clean     # Delete created simulators and temp files
appshots validate  # Check screenshots meet App Store requirements
```

## Requirements

- macOS 13+ (Ventura or later)
- Xcode 15+ with iOS Simulator
- Python 3.9+
- Pillow (`pip install Pillow`)

## How We Built This

AppShots was born from building [Harden](https://github.com/obadiaha/harden), a cybersecurity study app. We needed screenshots for TikTok marketing and App Store submission, and discovered that `xcrun simctl` has no tap or swipe commands. 

Instead of fighting the simulator's UI, we built a system that:
1. Injects launch arguments to navigate directly to any screen
2. Manipulates UserDefaults to set any app state
3. Rebuilds and relaunches for each screen configuration

This approach is more reliable than coordinate-based tapping and works across all device sizes without adjustment.

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License. See [LICENSE](LICENSE) for details.

---

Built by [Go Digital](https://godigitalapps.com) • An AI-assisted development studio
