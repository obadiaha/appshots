# Contributing to AppShots

Thanks for your interest in contributing! Here's how to get started.

## Setup

```bash
git clone https://github.com/obadiaha/appshots.git
cd appshots
pip3 install -e .
```

**Requirements:** macOS 13+, Xcode 15+, Python 3.9+

## Development

1. Fork the repo
2. Create a branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Test against a real Xcode project: `python3 -m appshots.cli capture --config your-test.yaml --verbose`
5. Commit: `git commit -am "feat: description"`
6. Push and open a PR

## What We Need Help With

- **Device frame overlays** - Wrap screenshots in device bezels (iPhone, iPad frames)
- **AI-powered init** - Feed Swift codebase to LLM, auto-generate complete screen configs
- **Localization support** - Capture screenshots in multiple languages
- **CI/CD integration** - GitHub Actions workflow for automated screenshot generation
- **More overlay styles** - Gradient backgrounds, custom fonts, badge overlays

## Code Style

- Python 3.9+ compatible
- Type hints where practical
- Keep dependencies minimal (Pillow + PyYAML only)
- Test changes against a real iOS project before submitting

## Reporting Bugs

Open an issue with:
- Your macOS and Xcode versions
- The error output (run with `--verbose`)
- Your appshots.yaml (redact sensitive info)

## License

By contributing, you agree your code will be licensed under MIT.
