# -*- coding: utf-8 -*-
# @Description: 窗口检测与前台激活工具

from dataclasses import dataclass
from typing import Optional, Set, Tuple
import os

import win32api
import win32con
import win32gui
import win32process
import ctypes


TARGET_TITLE = "三角洲行动"
TARGET_CLASSES: Set[str] = {"UnrealWindow"}
TARGET_EXE_NAMES = {
    "deltaforceclient-win64-shipping.exe",
}


@dataclass
class TargetWindowResult:
    """目标窗口检测结果"""
    exists: bool
    hwnd: Optional[int]
    message: str


def _get_process_path(pid: int) -> str:
    """获取进程可执行路径"""
    handle = None
    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
            False,
            pid,
        )
        return win32process.GetModuleFileNameEx(handle, 0)
    except win32process.error:
        return ""
    except win32api.error:
        return ""
    finally:
        if handle:
            win32api.CloseHandle(handle)


def _match_target(hwnd: int) -> bool:
    """校验窗口是否为目标程序"""
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    exe_path = _get_process_path(pid)
    if not exe_path:
        return False
    exe_name = os.path.basename(exe_path).lower()
    if exe_name not in TARGET_EXE_NAMES:
        return False
    class_name = win32gui.GetClassName(hwnd)
    return class_name in TARGET_CLASSES


def _find_window() -> Optional[int]:
    """查找目标窗口句柄"""
    for target_class in TARGET_CLASSES:
        hwnd = win32gui.FindWindow(target_class, TARGET_TITLE)
        if hwnd and _match_target(hwnd):
            return hwnd

    found_hwnd: Optional[int] = None

    def _callback(candidate_hwnd: int, _: Optional[int]) -> None:
        nonlocal found_hwnd
        if found_hwnd:
            return
        if not win32gui.IsWindowVisible(candidate_hwnd):
            return
        title = win32gui.GetWindowText(candidate_hwnd).strip()
        if title != TARGET_TITLE:
            return
        if _match_target(candidate_hwnd):
            found_hwnd = candidate_hwnd

    win32gui.EnumWindows(_callback, None)
    return found_hwnd


def _activate_window(hwnd: int) -> bool:
    """尝试将窗口置于前台"""
    if not win32gui.IsWindow(hwnd):
        return False

    try:
        foreground = win32gui.GetForegroundWindow()
    except win32gui.error:
        foreground = None

    try:
        if foreground == hwnd:
            return True

        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        attached_pairs: Set[Tuple[int, int]] = set()

        def _attach(from_thread: int, to_thread: int, attach: bool):
            if from_thread and to_thread and from_thread != to_thread:
                if attach:
                    if (from_thread, to_thread) not in attached_pairs:
                        if ctypes.windll.user32.AttachThreadInput(from_thread, to_thread, True):
                            attached_pairs.add((from_thread, to_thread))
                else:
                    ctypes.windll.user32.AttachThreadInput(from_thread, to_thread, False)

        current_thread = win32api.GetCurrentThreadId()
        target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
        _attach(current_thread, target_thread, True)

        if foreground:
            foreground_thread, _ = win32process.GetWindowThreadProcessId(foreground)
            _attach(current_thread, foreground_thread, True)

        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        win32gui.SetFocus(hwnd)
        win32gui.SetActiveWindow(hwnd)

        return win32gui.GetForegroundWindow() == hwnd
    except win32gui.error:
        return False
    finally:
        if 'attached_pairs' in locals():
            for from_thread, to_thread in attached_pairs:
                try:
                    _attach(from_thread, to_thread, False)
                except win32gui.error:
                    pass


def ensure_target_window() -> TargetWindowResult:
    """确认目标窗口是否存在并尝试置顶"""
    hwnd = _find_window()
    if not hwnd:
        return TargetWindowResult(
            exists=False,
            hwnd=None,
            message="未检测到“三角洲行动”窗口，请打开游戏后重试。",
        )

    activated = _activate_window(hwnd)
    if activated:
        return TargetWindowResult(
            exists=True,
            hwnd=hwnd,
            message="目标窗口已找到并置于前台。",
        )

    return TargetWindowResult(
        exists=True,
        hwnd=hwnd,
        message="已找到目标窗口，但未能自动置前，请手动切换到“三角洲行动”。",
    )

