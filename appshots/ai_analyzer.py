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
from pathlib import Path
from typing import Optional


SYSTEM_PROMPT = """You are an expert iOS developer analyzing a SwiftUI codebase to map every screen in the app.

Your job: identify every distinct screen/view the user can see, and for each one, determine:
1. The screen name (descriptive, kebab-case)
2. What launch arguments would navigate to it
3. What UserDefaults values need to be set to reach it
4. What data files need to exist (e.g., JSON in Documents directory)
5. A short marketing caption describing the screen

IMPORTANT RULES:
- Look for TabView tabs, NavigationStack destinations, .sheet modifiers, .fullScreenCover, alerts
- Identify @State, @AppStorage, @Binding variables that control navigation
- **CRITICAL: Check for CommandLine.arguments parsing (existing launch arg support).** If the app already reads launch arguments (e.g., `-tab=lock`, `-showQuiz`, etc.), USE THEM in launch_args for each screen. This is the primary navigation mechanism.
- Check for UserDefaults reads that gate screens (onboarding, splash, etc.)
- Check for file loads from Documents directory or app bundle
- If the app has a splash screen, include how to skip it via UserDefaults
- **ALL dates MUST use ISO 8601 string format** (e.g., "2026-06-01T00:00:00Z"). NEVER use Unix timestamps (integers/floats like 1770287400). Swift's UserDefaults.standard.object(forKey:) as? Date requires the `-date` flag format.
- **App group UserDefaults (suiteName: "group.xxx")** cannot be nested as YAML dicts. Use flat keys with a comment, e.g.: `lastUnlockDate: "2026-01-01T12:00:00Z"  # app group key`
- **Include EVERY distinct visual state**, not just navigation destinations. If a view looks different with data vs empty, include both states.
- **Only use launch args that ALREADY exist in CommandLine.arguments parsing code.** Mark new/suggested args with a comment `# suggested - add to app`.

Output ONLY valid YAML for the screens section of appshots.yaml. No explanation, no markdown fences.
Format:

screens:
  - name: "01-screen-name"
    launch_args: ["-argName=value"]
    defaults:
      key: value
    files:
      - src: "NEEDS_USER_INPUT"
        dest: "Documents/filename.json"
    caption: "Marketing text for this screen"
    wait_seconds: 3
  
  - name: "02-next-screen"
    ...

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


class AIAnalyzer:
    def __init__(self, provider: Optional[str] = None, api_key: Optional[str] = None):
        self.provider, self.api_key = self._detect_provider(provider, api_key)
        if not self.api_key:
            raise ValueError(
                "No API key found. Set one of:\n"
                "  ANTHROPIC_API_KEY (recommended)\n"
                "  OPENAI_API_KEY\n"
                "  GEMINI_API_KEY\n"
                "Or pass --api-key <key> --provider <anthropic|openai|gemini>"
            )

    def _detect_provider(self, provider, api_key):
        """Auto-detect provider from available API keys."""
        if provider and api_key:
            return provider, api_key

        # Check env vars in priority order
        for env_var, prov in [
            ("ANTHROPIC_API_KEY", "anthropic"),
            ("OPENAI_API_KEY", "openai"),
            ("GEMINI_API_KEY", "gemini"),
        ]:
            key = os.environ.get(env_var)
            if key:
                return prov, key

        return None, None

    def collect_swift_files(self, project_path: str) -> str:
        """Collect all Swift source files from the project."""
        project = Path(os.path.expanduser(project_path))
        project_dir = project.parent

        swift_files = sorted(project_dir.rglob("*.swift"))
        
        # Filter out build artifacts, pods, packages
        filtered = []
        for f in swift_files:
            rel = str(f.relative_to(project_dir))
            if any(skip in rel for skip in [
                "Pods/", "DerivedData/", ".build/", "Packages/",
                "Tests/", "UITests/", "Preview Content/"
            ]):
                continue
            filtered.append(f)

        if not filtered:
            raise FileNotFoundError(f"No Swift files found in {project_dir}")

        # Build context string
        context = []
        total_chars = 0
        max_chars = 150000  # Stay within token limits

        for f in filtered:
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

        print(f"  📄 Collected {len(filtered)} Swift files ({total_chars:,} chars)")
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
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.api_key}",
            data=data,
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read())
            try:
                return result["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                # Debug: print the actual response structure
                import sys
                print(f"\n⚠️  Unexpected Gemini response structure:", file=sys.stderr)
                # Check for blocked content
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
