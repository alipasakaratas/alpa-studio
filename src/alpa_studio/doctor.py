from __future__ import annotations

import os
import platform
import plistlib
import re
import shutil
from pathlib import Path
from typing import Any

from .util import command_path, now_iso, run_capture


def _version(command: str, *args: str) -> str | None:
    path = command_path(command)
    if not path:
        return None
    _, output = run_capture([path, *args])
    return output.splitlines()[0] if output else "installed"


def _unity_installations() -> list[dict[str, str]]:
    roots = [Path("/Applications/Unity/Hub/Editor"), Path.home() / "Applications/Unity/Hub/Editor"]
    found: list[dict[str, str]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for app in sorted(root.glob("*/Unity.app")):
            found.append({"version": app.parent.name, "path": str(app)})
    cli = command_path("Unity") or command_path("unity")
    if cli and all(item["path"] != cli for item in found):
        found.append({"version": "cli", "path": cli})
    return found


def _android() -> dict[str, Any]:
    adb = command_path("adb")
    devices: list[dict[str, str]] = []
    adb_error = None
    if adb:
        rc, output = run_capture([adb, "devices", "-l"])
        if rc != 0:
            adb_error = output.splitlines()[-1] if output else f"adb exited {rc}"
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] in {"device", "offline", "unauthorized", "recovery", "sideload", "bootloader"}:
                devices.append({"serial": parts[0], "state": parts[1], "details": " ".join(parts[2:])})
    avd_dir = Path.home() / ".android/avd"
    avds = sorted(path.stem for path in avd_dir.glob("*.ini")) if avd_dir.is_dir() else []
    connected = any(item["state"] == "device" for item in devices)
    if connected:
        reason = None
    elif adb_error:
        reason = f"No verified device; adb check failed: {adb_error}"
    elif avds:
        reason = "AVDs are configured, but no emulator or physical Android device is connected"
    else:
        reason = "ADB or usable device/emulator missing"
    return {"adb": adb, "devices": devices, "avds": avds, "configured": bool(adb and avds),
            "healthy": connected, "reason": reason}


def _ios() -> dict[str, Any]:
    xcrun = command_path("xcrun")
    runtimes: list[str] = []
    devices: list[str] = []
    if xcrun:
        rc, output = run_capture([xcrun, "simctl", "list", "runtimes"])
        if rc == 0:
            runtimes = [line.strip() for line in output.splitlines() if "iOS" in line and "unavailable" not in line]
        rc, output = run_capture([xcrun, "simctl", "list", "devices", "available"])
        if rc == 0:
            devices = [line.strip() for line in output.splitlines() if re.search(r"\([0-9A-F-]{8,}\)", line)]
    return {"xcrun": xcrun, "runtimes": runtimes, "simulators": devices,
            "healthy": bool(runtimes and devices),
            "reason": None if runtimes and devices else "No available iOS Simulator runtime/device detected"}


def _hardware() -> dict[str, Any]:
    total = None
    if platform.system() == "Darwin":
        rc, output = run_capture(["/usr/sbin/sysctl", "-n", "hw.memsize"])
        if rc == 0 and output.isdigit():
            total = int(output)
    disk = shutil.disk_usage(Path.home())
    memory_gb = round(total / (1024 ** 3), 1) if total else None
    concurrency = 1 if not memory_gb or memory_gb < 16 else (2 if memory_gb < 32 else 3)
    return {
        "machine": platform.machine(), "os": platform.platform(), "cpu_count": os.cpu_count(),
        "memory_gb": memory_gb, "disk_free_gb": round(disk.free / (1024 ** 3), 1),
        "recommended_parallel_heavy_jobs": concurrency,
    }


def inspect_project(project: Path | None) -> dict[str, Any] | None:
    if not project:
        return None
    version_file = project / "ProjectSettings/ProjectVersion.txt"
    unity_version = None
    if version_file.exists():
        match = re.search(r"m_EditorVersion:\s*(.+)", version_file.read_text(encoding="utf-8", errors="replace"))
        unity_version = match.group(1).strip() if match else "unknown"
    rc, status = run_capture(["git", "status", "--porcelain"], cwd=project)
    return {
        "path": str(project), "is_unity_project": version_file.exists(), "unity_version": unity_version,
        "is_git_repo": rc == 0, "git_dirty": bool(status) if rc == 0 else None,
        "has_claude_settings": (project / ".claude/settings.json").exists(),
        "has_studio_install": (project / ".alpa-studio/manifest.json").exists(),
        "writable": os.access(project, os.W_OK),
    }


def health_report(project: Path | None = None) -> dict[str, Any]:
    tools = {
        "git": _version("git", "--version"), "python": _version("python3", "--version"),
        "claude": _version("claude", "--version"), "node": _version("node", "--version"),
        "blender": _version("blender", "--version"), "ffmpeg": _version("ffmpeg", "-version"),
    }
    unity = _unity_installations()
    required_ok = bool(tools["git"] and tools["python"] and tools["claude"] and unity)
    return {
        "schema": 1, "generated_at": now_iso(), "status": "ready" if required_ok else "degraded",
        "core_ready": required_ok, "tools": tools, "unity": unity, "android": _android(), "ios": _ios(),
        "hardware": _hardware(), "project": inspect_project(project),
        "truth_policy": "Unavailable capabilities are never treated as passed or certified.",
    }

