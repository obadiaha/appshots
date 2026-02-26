#!/usr/bin/env python3
"""Core capture engine - builds app, boots simulators, takes screenshots."""

import json
import os
import subprocess
import time
import yaml
from pathlib import Path


# App Store Connect required screenshot sizes per device
DEVICE_RESOLUTIONS = {
    "iPhone-16-Pro-Max": {"width": 1320, "height": 2868, "display": "6.9\""},
    "iPhone-16-Plus": {"width": 1290, "height": 2796, "display": "6.7\""},
    "iPhone-16-Pro": {"width": 1206, "height": 2622, "display": "6.3\""},
    "iPhone-16": {"width": 1179, "height": 2556, "display": "6.1\""},
    "iPhone-17-Pro-Max": {"width": 1320, "height": 2868, "display": "6.9\""},
    "iPhone-17-Pro": {"width": 1206, "height": 2622, "display": "6.3\""},
    "iPhone-17": {"width": 1206, "height": 2622, "display": "6.3\""},
    "iPhone-SE-3rd-generation": {"width": 750, "height": 1334, "display": "4.7\""},
    "iPad-Pro-13-inch-M4": {"width": 2064, "height": 2752, "display": "13\""},
    "iPad-Air-13-inch-M3": {"width": 2360, "height": 1640, "display": "11\""},
}


class AppShotsCapture:
    def __init__(self, config_path: str, verbose: bool = False):
        self.verbose = verbose
        self.config_path = Path(config_path)
        
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}. Run 'appshots init' first.")
        
        with open(self.config_path) as f:
            self.config = yaml.safe_load(f)
        
        self.app = self.config["app"]
        self.devices = self.config["devices"]
        self.screens = self.config["screens"]
        self.runtime = self.config.get("runtime", "com.apple.CoreSimulator.SimRuntime.iOS-26-1")
        self.output_dir = Path(self.config.get("output", {}).get("directory", "./screenshots"))
        self.organize_by = self.config.get("output", {}).get("organize_by", "device")
        self.created_devices = []

    def log(self, msg: str):
        print(msg)

    def debug(self, msg: str):
        if self.verbose:
            print(f"  [debug] {msg}")

    def run_cmd(self, cmd: list, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
        self.debug(f"$ {' '.join(str(c) for c in cmd)}")
        result = subprocess.run(cmd, capture_output=capture, text=True)
        if check and result.returncode != 0:
            stderr = result.stderr if capture else ""
            raise RuntimeError(f"Command failed: {' '.join(str(c) for c in cmd)}\n{stderr}")
        return result

    def build_app(self):
        """Build the app with xcodebuild."""
        project = os.path.expanduser(self.app["project"])
        scheme = self.app["scheme"]
        
        self.log(f"🔨 Building {scheme}...")
        
        # Get build destination
        cmd = [
            "xcodebuild", "build",
            "-project", project,
            "-scheme", scheme,
            "-sdk", "iphonesimulator",
            "-configuration", "Debug",
            "-derivedDataPath", "/tmp/appshots-build",
            "-quiet",
        ]
        
        self.run_cmd(cmd)
        
        # Find the .app bundle
        build_dir = Path("/tmp/appshots-build/Build/Products/Debug-iphonesimulator")
        apps = list(build_dir.glob("*.app"))
        if not apps:
            raise RuntimeError(f"No .app found in {build_dir}")
        
        self.app_path = str(apps[0])
        self.log(f"  ✅ Built: {self.app_path}")

    def find_or_create_device(self, device_config: dict) -> str:
        """Find existing device or create a new one. Returns device UDID."""
        device_name = f"AppShots-{device_config['name']}"
        device_type = device_config["type"]
        
        # Check if device already exists
        result = self.run_cmd(["xcrun", "simctl", "list", "devices", "-j"])
        devices = json.loads(result.stdout)
        
        for runtime_key, device_list in devices.get("devices", {}).items():
            for d in device_list:
                if d["name"] == device_name and d.get("isAvailable", False):
                    self.debug(f"Found existing device: {device_name} ({d['udid']})")
                    return d["udid"]
        
        # Create new device
        self.log(f"  📱 Creating simulator: {device_name}")
        result = self.run_cmd([
            "xcrun", "simctl", "create", device_name, device_type, self.runtime
        ])
        udid = result.stdout.strip()
        self.created_devices.append(udid)
        return udid

    def boot_device(self, udid: str):
        """Boot a simulator device."""
        result = self.run_cmd(["xcrun", "simctl", "list", "devices", "-j"])
        devices = json.loads(result.stdout)
        
        for runtime_key, device_list in devices.get("devices", {}).items():
            for d in device_list:
                if d["udid"] == udid and d["state"] == "Booted":
                    self.debug(f"Device already booted: {udid}")
                    return
        
        self.run_cmd(["xcrun", "simctl", "boot", udid])
        time.sleep(3)  # Wait for boot

    def shutdown_device(self, udid: str):
        """Shutdown a simulator device."""
        self.run_cmd(["xcrun", "simctl", "shutdown", udid], check=False)

    def set_defaults(self, udid: str, defaults: dict):
        """Write UserDefaults for the app."""
        bundle_id = self.app["bundle_id"]
        for key, value in defaults.items():
            if isinstance(value, bool):
                self.run_cmd([
                    "xcrun", "simctl", "spawn", udid,
                    "defaults", "write", bundle_id, key, "-bool",
                    "YES" if value else "NO"
                ])
            elif isinstance(value, int):
                self.run_cmd([
                    "xcrun", "simctl", "spawn", udid,
                    "defaults", "write", bundle_id, key, "-int", str(value)
                ])
            elif isinstance(value, float):
                self.run_cmd([
                    "xcrun", "simctl", "spawn", udid,
                    "defaults", "write", bundle_id, key, "-float", str(value)
                ])
            else:
                self.run_cmd([
                    "xcrun", "simctl", "spawn", udid,
                    "defaults", "write", bundle_id, key, "-string", str(value)
                ])

    def clear_defaults(self, udid: str):
        """Clear all UserDefaults for the app."""
        bundle_id = self.app["bundle_id"]
        self.run_cmd([
            "xcrun", "simctl", "spawn", udid,
            "defaults", "delete", bundle_id
        ], check=False)

    def launch_app(self, udid: str, launch_args: list = None, env: dict = None):
        """Launch the app with optional arguments and environment."""
        bundle_id = self.app["bundle_id"]
        
        # Terminate any running instance
        self.run_cmd(["xcrun", "simctl", "terminate", udid, bundle_id], check=False)
        time.sleep(0.5)
        
        cmd = ["xcrun", "simctl", "launch", udid, bundle_id]
        if launch_args:
            cmd.extend(launch_args)
        
        # Set environment variables if specified
        if env:
            for k, v in env.items():
                os.environ[f"SIMCTL_CHILD_{k}"] = str(v)
        
        self.run_cmd(cmd)
        
        # Clean up env vars
        if env:
            for k in env:
                os.environ.pop(f"SIMCTL_CHILD_{k}", None)

    def take_screenshot(self, udid: str, output_path: str):
        """Take a screenshot of the simulator."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        self.run_cmd(["xcrun", "simctl", "io", udid, "screenshot", output_path])

    def get_output_path(self, device_name: str, screen_name: str) -> str:
        """Get the output path for a screenshot."""
        fmt = self.config.get("output", {}).get("format", "png")
        
        if self.organize_by == "device":
            return str(self.output_dir / device_name / f"{screen_name}.{fmt}")
        else:
            return str(self.output_dir / screen_name / f"{device_name}.{fmt}")

    def run(self, device_filter=None, screen_filter=None, skip_overlay=False, skip_build=False):
        """Main capture flow."""
        self.log("📸 AppShots — Automated App Store Screenshot Generation")
        self.log("=" * 55)
        
        # Step 1: Build
        if not skip_build:
            self.build_app()
        else:
            # Find existing build
            build_dir = Path("/tmp/appshots-build/Build/Products/Debug-iphonesimulator")
            apps = list(build_dir.glob("*.app"))
            if not apps:
                raise RuntimeError("No existing build found. Remove --no-build flag.")
            self.app_path = str(apps[0])
            self.log(f"♻️  Using existing build: {self.app_path}")
        
        # Step 2: Process each device
        devices = self.devices
        if device_filter:
            devices = [d for d in devices if device_filter.lower() in d["name"].lower()]
        
        screens = self.screens
        if screen_filter:
            screens = [s for s in screens if screen_filter.lower() in s["name"].lower()]
        
        total = len(devices) * len(screens)
        count = 0
        
        for device in devices:
            self.log(f"\n📱 {device['name']}")
            
            udid = self.find_or_create_device(device)
            self.boot_device(udid)
            
            # Install app
            self.run_cmd(["xcrun", "simctl", "install", udid, self.app_path])
            self.debug("App installed")
            
            for screen in screens:
                count += 1
                self.log(f"  [{count}/{total}] {screen['name']}")
                
                # Clear previous state
                self.clear_defaults(udid)
                
                # Set defaults for this screen
                if "defaults" in screen:
                    self.set_defaults(udid, screen["defaults"])
                
                # Launch with args
                launch_args = screen.get("launch_args", [])
                env = screen.get("env", {})
                self.launch_app(udid, launch_args, env)
                
                # Wait for screen to settle
                wait = screen.get("wait_seconds", 2)
                time.sleep(wait)
                
                # Screenshot
                output_path = self.get_output_path(device["name"], screen["name"])
                self.take_screenshot(udid, output_path)
                self.log(f"    ✅ {output_path}")
            
            # Shutdown device after all screens
            self.shutdown_device(udid)
        
        self.log(f"\n🎉 Done! {count} screenshots saved to {self.output_dir}/")
        
        # Apply overlays
        if not skip_overlay and self.config.get("overlays", {}).get("enabled", False):
            self.log("\n🎨 Applying text overlays...")
            from .overlay import OverlayEngine
            overlay = OverlayEngine(str(self.config_path))
            overlay.apply_to_captures(str(self.output_dir), self.screens, self.organize_by)

    def clean(self):
        """Delete all AppShots-created simulators."""
        result = self.run_cmd(["xcrun", "simctl", "list", "devices", "-j"])
        devices = json.loads(result.stdout)
        
        deleted = 0
        for runtime_key, device_list in devices.get("devices", {}).items():
            for d in device_list:
                if d["name"].startswith("AppShots-"):
                    self.log(f"  🗑️  Deleting {d['name']} ({d['udid']})")
                    self.run_cmd(["xcrun", "simctl", "delete", d["udid"]], check=False)
                    deleted += 1
        
        self.log(f"Cleaned {deleted} AppShots simulators.")
