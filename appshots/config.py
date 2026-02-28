#!/usr/bin/env python3
"""Config management for AppShots — save/load API keys and preferences.

Stores configuration in ~/.appshots/config.json.
"""

import json
import sys
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path.home() / ".appshots" / "config.json"

PROVIDERS = {
    "1": ("gemini", "GEMINI_API_KEY", "Google Gemini (recommended, free tier available)"),
    "2": ("anthropic", "ANTHROPIC_API_KEY", "Anthropic Claude"),
    "3": ("openai", "OPENAI_API_KEY", "OpenAI GPT-4o"),
}

PROVIDER_URLS = {
    "gemini": "https://aistudio.google.com/apikey",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
}


def load_config() -> dict:
    """Load saved config from ~/.appshots/config.json.

    Returns an empty dict if the file doesn't exist or is invalid.
    """
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


def save_config(data: dict) -> None:
    """Save config to ~/.appshots/config.json (creates parent dirs)."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n")


def get_saved_api_key() -> tuple[Optional[str], Optional[str]]:
    """Return (provider, api_key) from saved config, or (None, None)."""
    cfg = load_config()
    if cfg.get("api_key"):
        return cfg.get("provider", "anthropic"), cfg["api_key"]
    return None, None


def prompt_for_api_key() -> tuple[str, str]:
    """Interactively prompt the user for an AI provider and API key.

    Returns (provider, api_key).
    Saves to ~/.appshots/config.json if user agrees.
    Raises ValueError if no key provided, KeyboardInterrupt/EOFError on cancel.
    """
    print("\n⚠️  No API key found. AppShots needs an AI provider to analyze your app.\n")
    print("Choose a provider:")
    for num, (_prov, _env, label) in PROVIDERS.items():
        print(f"  {num}. {label}")

    while True:
        choice = input("\nEnter choice (1-3): ").strip()
        if choice in PROVIDERS:
            break
        print("  Please enter 1, 2, or 3.")

    provider, env_var, label = PROVIDERS[choice]
    print(f"\nGet your key at:")
    print(f"  {PROVIDER_URLS[provider]}")

    api_key = input(f"\nEnter your {label} API key: ").strip()
    if not api_key:
        raise ValueError("No API key provided.")

    save_choice = input("\nSave to ~/.appshots/config.json for future runs? [Y/n]: ").strip().lower()
    if save_choice in ("", "y", "yes"):
        save_config({"provider": provider, "api_key": api_key})
        print(f"  ✅ Saved to {CONFIG_PATH}")

    return provider, api_key


def ensure_api_key(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
) -> tuple[str, str]:
    """Resolve an API key from args → saved config → env vars → interactive prompt.

    Priority order:
      1. Explicit provider + api_key arguments
      2. Saved config (~/.appshots/config.json)
      3. Environment variables (ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY)
      4. Interactive prompt (if TTY)

    Returns (provider, api_key).
    Raises ValueError if no key can be found.
    """
    import os

    # 1. Explicit args
    if provider and api_key:
        return provider, api_key

    # 2. Saved config
    saved_provider, saved_key = get_saved_api_key()
    if saved_key:
        return saved_provider, saved_key

    # 3. Environment variables
    for env_var, prov in [
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("OPENAI_API_KEY", "openai"),
        ("GEMINI_API_KEY", "gemini"),
    ]:
        key = os.environ.get(env_var)
        if key:
            return prov, key

    # 4. Interactive prompt (only if stdin is a TTY)
    if sys.stdin.isatty():
        try:
            return prompt_for_api_key()
        except (KeyboardInterrupt, EOFError):
            pass

    raise ValueError(
        "No API key found. Set one of:\n"
        "  ANTHROPIC_API_KEY (recommended)\n"
        "  OPENAI_API_KEY\n"
        "  GEMINI_API_KEY\n"
        "Or pass --api-key <key> --provider <anthropic|openai|gemini>\n"
        "Or run `appshots auto` interactively to be prompted."
    )
