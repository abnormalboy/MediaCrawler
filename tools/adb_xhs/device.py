# -*- coding: utf-8 -*-
"""ADB 设备封装：只做进程调用与基础手势，不包含业务语义。"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from .hierarchy import UiHierarchy


class AdbError(RuntimeError):
    """ADB 命令失败。"""


class AdbDevice:
    """对单台 Android 设备的薄封装，便于单测时替换。"""

    def __init__(self, serial: Optional[str] = None, adb_bin: Optional[str] = None) -> None:
        self.serial = serial
        self.adb_bin = adb_bin or shutil.which("adb") or "/Users/chm/Library/Android/sdk/platform-tools/adb"
        if not Path(self.adb_bin).exists() and shutil.which(self.adb_bin) is None:
            raise AdbError(f"找不到 adb：{self.adb_bin}")

    def _prefix(self) -> list[str]:
        cmd = [self.adb_bin]
        if self.serial:
            cmd.extend(["-s", self.serial])
        return cmd

    def run(self, *args: str, timeout: int = 20) -> str:
        completed = subprocess.run(
            [*self._prefix(), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            raise AdbError(f"adb {' '.join(args)} 失败：{stderr or completed.stdout}")
        return completed.stdout

    def shell(self, *args: str, timeout: int = 20) -> str:
        return self.run("shell", *args, timeout=timeout)

    def ensure_awake(self) -> None:
        """唤醒屏幕并尽量收起通知栏，避免 uiautomator dump 打到 SystemUI。"""
        self.shell("input", "keyevent", "KEYCODE_WAKEUP")
        time.sleep(0.3)
        try:
            self.shell("wm", "dismiss-keyguard")
        except AdbError:
            pass
        try:
            self.shell("cmd", "statusbar", "collapse")
        except AdbError:
            pass
        time.sleep(0.2)

    def current_focus(self) -> str:
        output = self.shell("dumpsys", "window")
        for line in output.splitlines():
            if "mCurrentFocus=" in line or "mFocusedApp=" in line:
                return line.strip()
        return ""

    def tap(self, x: int, y: int) -> None:
        self.shell("input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400) -> None:
        self.shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))

    def back(self) -> None:
        self.shell("input", "keyevent", "KEYCODE_BACK")

    def dump_ui(self, remote_path: str = "/sdcard/uidump.xml") -> UiHierarchy:
        self.shell("uiautomator", "dump", remote_path)
        local = Path("/tmp/xhs_uidump.xml")
        self.run("pull", remote_path, str(local))
        return UiHierarchy.from_file(local)
