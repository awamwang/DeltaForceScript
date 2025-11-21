#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_SCRIPT = PROJECT_ROOT / "main_gui.py"
OUTPUT_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
PYINSTALLER_WORK = BUILD_DIR / "pyinstaller"


DEFAULT_DATA_TARGETS = [
    (PROJECT_ROOT / "models", "models"),
    (PROJECT_ROOT / "assets", "assets"),
    (PROJECT_ROOT / "regions_2k.json", "regions_2k.json"),
    (PROJECT_ROOT / "regions_config.json", "regions_config.json"),
]


def ensure_dependencies():
    """选择可用的 PyInstaller 命令"""
    exe_path = shutil.which("pyinstaller")
    if exe_path:
        return [exe_path]
    if importlib.util.find_spec("PyInstaller") is None:
        raise RuntimeError("未找到 PyInstaller，请先执行 pip install pyinstaller")
    return [sys.executable, "-m", "PyInstaller"]


def format_data_arg(source: Path, destination: str) -> str:
    """生成符合 PyInstaller 规范的 --add-data 参数"""
    separator = ";" if sys.platform.startswith("win") else ":"
    return f"{source}{separator}{destination}"


def collect_data_targets(extra_targets):
    """合并默认数据和额外数据"""
    targets = []
    for src, dst in DEFAULT_DATA_TARGETS + extra_targets:
        if not src.exists():
            print(f"[警告] 数据路径不存在，跳过：{src}")
            continue
        targets.append((src, dst))
    return targets


def parse_extra_data_args(arg_values):
    """解析用户通过 --add-data 传入的路径"""
    extra = []
    for value in arg_values:
        if ":" not in value:
            raise ValueError("--add-data 参数需使用 源路径:目标路径 格式")
        src, dst = value.rsplit(":", 1)
        extra.append((Path(src).resolve(), dst))
    return extra


def build_command(onefile: bool, name: str, data_targets):
    """构建 PyInstaller 命令"""
    cmd = ensure_dependencies()
    cmd += [
        str(MAIN_SCRIPT),
        "--noconfirm",
        "--name",
        name,
        "--distpath",
        str(OUTPUT_DIR),
        "--workpath",
        str(PYINSTALLER_WORK),
        "--specpath",
        str(PYINSTALLER_WORK),
    ]
    if onefile:
        cmd.append("--onefile")
    for src, dst in data_targets:
        cmd += ["--add-data", format_data_arg(src, dst)]
    return cmd


def clean_directories():
    """清理历史构建输出"""
    for path in (OUTPUT_DIR, BUILD_DIR):
        if path.exists():
            print(f"[信息] 删除目录：{path}")
            shutil.rmtree(path)


def run_build(cmd):
    """执行 PyInstaller 打包"""
    print("[信息] 即将执行命令：")
    print(" ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError("系统找不到 PyInstaller，可尝试安装后重试") from exc
    print(f"[完成] 可执行文件已生成到：{OUTPUT_DIR}")


def main():
    parser = argparse.ArgumentParser(description="打包 main_gui.py 为独立可执行文件")
    parser.add_argument(
        "--name",
        default="DeltaForceGUI",
        help="生成的可执行文件名称",
    )
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="使用 onedir 模式输出（默认 onefile）",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="打包前清理 dist 与 build 目录",
    )
    parser.add_argument(
        "--add-data",
        action="append",
        default=[],
        help="额外的数据路径，格式：源路径:目标路径，可重复传入多次",
    )
    args = parser.parse_args()

    if not MAIN_SCRIPT.exists():
        raise FileNotFoundError(f"未找到主脚本：{MAIN_SCRIPT}")

    if args.clean:
        clean_directories()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PYINSTALLER_WORK.mkdir(parents=True, exist_ok=True)

    extra_targets = parse_extra_data_args(args.add_data) if args.add_data else []
    data_targets = collect_data_targets(extra_targets)

    cmd = build_command(not args.onedir, args.name, data_targets)
    run_build(cmd)


if __name__ == "__main__":
    main()

