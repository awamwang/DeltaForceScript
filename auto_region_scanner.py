# -*- coding: utf-8 -*-
# @Description: 自动区域扫描模块

import os
import re
import time
import threading
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List

import cv2


@dataclass
class PatternDefinition:
    """预设文字区域定义"""
    label: str
    region_key: str
    area_ratio: Optional[Tuple[float, float, float, float]]
    patterns: Optional[List[re.Pattern]] = None
    region_percent: Optional[Tuple[float, float, float, float]] = None


PREDEFINED_PATTERNS: List[PatternDefinition] = [
    PatternDefinition(
        label="三角币数目",
        region_key="money",
        area_ratio=(0.75, 0.0, 1.0, 0.25),
        patterns=[
            re.compile(r'258\s*\+'),
            re.compile(r'\d{2,}\s*\+')
        ],
    ),
    PatternDefinition(
        label="倒数计时",
        region_key="time",
        area_ratio=(0.75, 0.75, 1.0, 1.0),
        patterns=[
            re.compile(r'(\d+小时)?(\d+分)?(\d+秒.*后解锁购买)'),
            re.compile(r'(\d+小时)?(\d+分)?(\d+秒)')
        ],
    ),
    PatternDefinition(
        label="成色筛选",
        region_key="quality_filter",
        area_ratio=None,
        patterns=[
            re.compile(r'所有成色'),
            re.compile(r'全部成色')
        ],
    ),
    PatternDefinition(
        label="公示期筛选",
        region_key="public_period_filter",
        area_ratio=None,
        patterns=[
            re.compile(r'不限公示期'),
            re.compile(r'全部公示期')
        ],
    ),
    PatternDefinition(
        label="排序修改",
        region_key="sort_modifier",
        area_ratio=None,
        patterns=[
            re.compile(r'默认排序'),
            re.compile(r'综合排序')
        ],
    ),
    PatternDefinition(
        label="目标描述",
        region_key="target_desc",
        area_ratio=None,
        patterns=[
            re.compile(r'.+的.+典藏外观'),
            re.compile(r'典藏外观')
        ],
    ),
    PatternDefinition(
        label="购买按钮",
        region_key="buy_button",
        area_ratio=None,
        patterns=[
            re.compile(r'公示中'),
        ],
    ),
    PatternDefinition(
        label="确认按钮",
        region_key="verify_check",
        area_ratio=None,
        region_percent=(55.72, 61.81, 71.27, 66.61),
    ),
]


def _bbox_from_points(points):
    """将OCR坐标点转换为矩形"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    left = int(min(xs))
    top = int(min(ys))
    right = int(max(xs))
    bottom = int(max(ys))
    return (left, top, right, bottom)


def _rect_from_ratio(frame_shape, ratio):
    """根据比例生成限制区域"""
    h, w = frame_shape[:2]
    left = int(w * ratio[0])
    top = int(h * ratio[1])
    right = int(w * ratio[2])
    bottom = int(h * ratio[3])
    return (left, top, right, bottom)


def _bbox_in_rect(bbox, rect):
    """检测矩形是否在限制区域内"""
    bx1, by1, bx2, by2 = bbox
    rx1, ry1, rx2, ry2 = rect
    cx = (bx1 + bx2) / 2
    cy = (by1 + by2) / 2
    return rx1 <= cx <= rx2 and ry1 <= cy <= ry2


def _prepare_scan_frame(frame, window_region: Optional[Tuple[int, int, int, int]]):
    """根据窗口区域准备扫描图像"""
    if frame is None or frame.size == 0:
        return None, (0, 0, 0, 0)
    if not window_region:
        h, w = frame.shape[:2]
        return frame, (0, 0, w, h)
    left, top, right, bottom = window_region
    left = max(0, int(left))
    top = max(0, int(top))
    right = min(frame.shape[1], int(right))
    bottom = min(frame.shape[0], int(bottom))
    if right <= left or bottom <= top:
        return frame, (0, 0, frame.shape[1], frame.shape[0])
    return frame[top:bottom, left:right], (left, top, right, bottom)


def _intersect_with_region(bbox: Tuple[int, int, int, int], region: Optional[Tuple[int, int, int, int]],
                           frame_shape: Tuple[int, int, int]) -> Optional[Tuple[int, int, int, int]]:
    """将bbox限制在窗口区域与帧范围内"""
    fh, fw = frame_shape[0], frame_shape[1]
    left, top, right, bottom = bbox
    left = max(0, min(left, fw))
    right = max(0, min(right, fw))
    top = max(0, min(top, fh))
    bottom = max(0, min(bottom, fh))
    if region:
        left = max(left, region[0])
        right = min(right, region[2])
        top = max(top, region[1])
        bottom = min(bottom, region[3])
    if right - left <= 0 or bottom - top <= 0:
        return None
    return (left, top, right, bottom)


def save_region_image_async(frame, bbox, output_dir, label, window_region: Optional[Tuple[int, int, int, int]] = None):
    """异步保存识别区域截图"""
    if frame is None or frame.size == 0:
        return ""
    clipped_bbox = _intersect_with_region(bbox, window_region, frame.shape)
    if not clipped_bbox:
        return ""
    left, top, right, bottom = clipped_bbox
    roi = frame[top:bottom, left:right].copy()
    filename = f"{label}.png"
    path = os.path.join(output_dir, filename)

    def _save():
        os.makedirs(output_dir, exist_ok=True)
        if roi.size > 0:
            cv2.imencode(".png", roi)[1].tofile(path)

    threading.Thread(target=_save, daemon=True).start()
    return path


def scan_predefined_regions(frame, ocr, output_dir, window_region: Optional[Tuple[int, int, int, int]] = None,
                            debug: bool = False):
    """扫描预设文字区域"""
    detected: Dict[str, Dict[str, object]] = {}
    scan_frame, actual_region = _prepare_scan_frame(frame, window_region)
    if scan_frame is None or scan_frame.size == 0:
        print("自动扫描失败：未获取到窗口截图")
        return detected
    rgb_frame = cv2.cvtColor(scan_frame, cv2.COLOR_BGR2RGB)
    try:
        ocr_results = ocr.readtext(rgb_frame, detail=1)
    except Exception as exc:
        print(f"OCR 扫描失败: {exc}")
        return detected
    entries = []
    for item in ocr_results:
        if len(item) < 2:
            continue
        points, text = item[0], item[1]
        bbox = _bbox_from_points(points)
        entry = {
            "text": text.strip(),
            "bbox": bbox
        }
        entries.append(entry)
        if debug:
            print(f"[DEBUG][OCR] 文本='{entry['text']}' 区域={entry['bbox']}")
    if debug:
        print(f"[DEBUG] OCR结果数量: {len(entries)}")
    for definition in PREDEFINED_PATTERNS:
        # 处理 region_percent 百分比坐标的情况
        if definition.region_percent:
            # 根据窗口实际大小转换为像素坐标
            h, w = scan_frame.shape[:2]
            left_pct, top_pct, right_pct, bottom_pct = definition.region_percent
            abs_bbox = (
                int(w * left_pct / 100) + actual_region[0],
                int(h * top_pct / 100) + actual_region[1],
                int(w * right_pct / 100) + actual_region[0],
                int(h * bottom_pct / 100) + actual_region[1],
            )
            image_path = save_region_image_async(frame, abs_bbox, output_dir, definition.label, actual_region)
            info = {
                "bbox": abs_bbox,
                "text": "",
                "pattern": "",
                "region_key": definition.region_key,
                "image_path": image_path,
            }
            detected[definition.label] = info
            print(f"[自动区域] {definition.label}: {abs_bbox} (百分比坐标转换)")
            continue
        
        # 处理 OCR 模式匹配的情况
        if not definition.patterns:
            continue
        region_limit = None
        if definition.area_ratio:
            region_limit = _rect_from_ratio(scan_frame.shape, definition.area_ratio)
        for entry in entries:
            if region_limit and not _bbox_in_rect(entry["bbox"], region_limit):
                continue
            for pattern in definition.patterns:
                if pattern.search(entry["text"]):
                    abs_bbox = (
                        entry["bbox"][0] + actual_region[0],
                        entry["bbox"][1] + actual_region[1],
                        entry["bbox"][2] + actual_region[0],
                        entry["bbox"][3] + actual_region[1],
                    )
                    image_path = save_region_image_async(frame, abs_bbox, output_dir, definition.label, actual_region)
                    info = {
                        "bbox": abs_bbox,
                        "text": entry["text"],
                        "pattern": pattern.pattern,
                        "region_key": definition.region_key,
                        "image_path": image_path,
                    }
                    detected[definition.label] = info
                    print(f"[自动区域] {definition.label}: {abs_bbox} 文本='{entry['text']}' 模式='{pattern.pattern}'")
                    break
            if definition.label in detected:
                break
    return detected


def run_initial_pattern_scan(win_cap, ocr, output_dir, window_region: Optional[Tuple[int, int, int, int]] = None,
                             debug: bool = False):
    """获取窗口截图并执行自动扫描"""
    attempts = 0
    frame = win_cap.capture()
    while (frame is None or frame.size == 0) and attempts < 5:
        time.sleep(0.2)
        frame = win_cap.capture()
        attempts += 1
    if frame is None or frame.size == 0:
        print("自动扫描失败：无法截取窗口")
        return {}, None
    detected = scan_predefined_regions(frame, ocr, output_dir, window_region, debug=debug)
    return detected, frame

