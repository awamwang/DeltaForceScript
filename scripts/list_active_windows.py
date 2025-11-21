import argparse
import json
from typing import Any, Dict, List, Optional, Tuple

import win32api
import win32con
import win32gui
import win32process


def _get_process_path(pid: int) -> str:
    """获取进程可执行文件路径。"""
    handle: Optional[int] = None
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


def _normalize_window_rect(rect: Tuple[int, int, int, int]) -> Dict[str, int]:
    """整理窗口矩形信息。"""
    left, top, right, bottom = rect
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
    }


def _collect_window_info(hwnd: int) -> Optional[Dict[str, Any]]:
    """收集单个窗口的信息。"""
    if not win32gui.IsWindowVisible(hwnd):
        return None

    title = win32gui.GetWindowText(hwnd).strip()
    if not title:
        return None

    class_name = win32gui.GetClassName(hwnd)
    rect = win32gui.GetWindowRect(hwnd)
    _, pid = win32process.GetWindowThreadProcessId(hwnd)

    return {
        "hwnd": hwnd,
        "title": title,
        "class_name": class_name,
        "pid": pid,
        "exe_path": _get_process_path(pid),
        "rect": _normalize_window_rect(rect),
    }


def enumerate_active_windows() -> List[Dict[str, Any]]:
    """枚举所有活动窗口。"""
    windows: List[Dict[str, Any]] = []

    def _callback(hwnd: int, _: Any) -> None:
        info = _collect_window_info(hwnd)
        if info:
            windows.append(info)

    win32gui.EnumWindows(_callback, None)
    return sorted(windows, key=lambda item: item["title"].lower())


def _format_human_readable(windows: List[Dict[str, Any]]) -> str:
    """将窗口信息转为易读文本。"""
    if not windows:
        return "未发现活动窗口"

    lines: List[str] = []
    for index, info in enumerate(windows, 1):
        lines.extend(
            [
                f"[{index}] 标题: {info['title']}",
                f"    句柄: {info['hwnd']}",
                f"    类名: {info['class_name']}",
                f"    进程: {info['pid']}",
                f"    路径: {info['exe_path'] or '未知'}",
                (
                    "    区域: "
                    f"{info['rect']['left']},{info['rect']['top']} -> "
                    f"{info['rect']['right']},{info['rect']['bottom']} "
                    f"({info['rect']['width']}x{info['rect']['height']})"
                ),
            ]
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="列出当前 Windows 系统中所有活动窗口的信息"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出结果",
    )
    return parser.parse_args()


def main() -> None:
    """程序入口。"""
    args = parse_args()
    windows = enumerate_active_windows()

    if args.json:
        print(json.dumps(windows, ensure_ascii=False, indent=2))
    else:
        print(_format_human_readable(windows))


if __name__ == "__main__":
    main()


