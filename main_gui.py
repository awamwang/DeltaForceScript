# -*- coding: utf-8 -*-
# @Author: BugNotFound
# @Date: 2025-10-04
# @FilePath: /DeltaForceScript/main_gui.py
# @Description: 带 PyQt6 GUI 的主程序

import os
import sys
import re
import time
import ctypes
from typing import Optional, Tuple

from window_capture import *
from region_selector import RegionSelector
from gui_monitor import MonitorWindow

import numpy
import cv2
import easyocr
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal
import pydirectinput
from colormath.color_objects import sRGBColor, LabColor
from colormath.color_diff import delta_e_cie2000
from colormath.color_conversions import convert_color
from window_manager import ensure_target_window

def patch_asscalar(a):
    return a.item()

setattr(numpy, "asscalar", patch_asscalar)

def is_admin():
    """检查是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def run_as_admin():
    """以管理员权限重新启动程序"""
    if not is_admin():
        print("正在请求管理员权限...")
        # 获取当前脚本路径
        script = os.path.abspath(sys.argv[0])
        params = ' '.join([script] + sys.argv[1:])
        
        # 使用 ShellExecute 以管理员权限运行
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
        
        if ret > 32:  # 成功
            sys.exit(0)
        else:
            print("未获得管理员权限，继续以普通权限运行")
            return False
    return True


def click_region_center(region: tuple, clicks=1, interval=0.1):
    """点击区域的中心位置 - 使用多种方法尝试
    
    Args:
        region: (left, top, right, bottom) 格式的区域坐标
    """
    left, top, right, bottom = region
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    
    # print(f"准备点击位置: ({center_x}, {center_y})")
    # 在20个像素的范围内随机偏移，防止被检测
    center_x += int((os.urandom(1)[0] / 255 - 0.5) * 10)
    center_y += int((os.urandom(1)[0] / 255 - 0.5) * 10)

    pydirectinput.click(x=center_x, y=center_y, clicks=clicks, interval=interval, button=pydirectinput.LEFT)

def extract_and_merge_digits(s: str) -> str:
    """识别字符串中的所有数字并合并为一个新字符串"""
    return ''.join(re.findall(r'\d', s))


MONEY_PLUS_PATTERN = re.compile(r'(\d+)\s*\+')
UNLOCK_PATTERN = re.compile(r'(\d+)\s*分\s*(\d+)\s*秒.*后.*解锁')
DIRECT_BUY_PATTERN = re.compile(r'剩余[:：]?\s*(\d+)\s*分\s*(\d+)\s*秒')
COUNTDOWN_PATTERN = re.compile(r'(\d+)\s*分\s*(\d+)\s*秒')
    

class ScriptThread(QThread):
    """脚本运行线程"""
    
    status_updated = pyqtSignal(str)
    timer_updated = pyqtSignal(str, str)
    ocr_updated = pyqtSignal(str, float)
    click_performed = pyqtSignal()
    task_completed = pyqtSignal()
    
    def __init__(self, selector: RegionSelector, win_cap: WindowCapture, ocr, config):
        super().__init__()
        self.selector = selector
        self.win_cap = win_cap
        self.ocr = ocr
        self.config = config
        self.is_running = True
        self.is_paused = False
        self.output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
        os.makedirs(self.output_dir, exist_ok=True)
        self.window_region_cache: Optional[Tuple[int, int, int, int]] = None
        self.cached_money_region: Optional[Tuple[int, int, int, int]] = None
        self.cached_timer_region: Optional[Tuple[int, int, int, int]] = None
    
    def frame_cut(self, frame, region):
        """裁剪图像区域"""
        left, top, right, bottom = region
        return frame[top:bottom, left:right]

    def get_window_region(self) -> Optional[Tuple[int, int, int, int]]:
        """获取窗口范围"""
        if self.window_region_cache:
            return self.window_region_cache

        region = self.selector.get_region("window")
        if region:
            self.window_region_cache = region
            return region

        all_regions = getattr(self.selector, "get_all_regions", lambda: {})()
        if all_regions:
            coords = list(all_regions.values())
            left = min(r[0] for r in coords)
            top = min(r[1] for r in coords)
            right = max(r[2] for r in coords)
            bottom = max(r[3] for r in coords)
            self.window_region_cache = (left, top, right, bottom)
            return self.window_region_cache

        frame = self.win_cap.capture()
        if frame is not None and frame.size > 0:
            h, w = frame.shape[:2]
            self.window_region_cache = (0, 0, w, h)
            return self.window_region_cache
        return None

    def fraction_region(self, region: Tuple[int, int, int, int],
                        start_x_ratio: float, start_y_ratio: float,
                        end_x_ratio: float, end_y_ratio: float) -> Tuple[int, int, int, int]:
        """按比例获取子区域"""
        left, top, right, bottom = region
        width = max(1, right - left)
        height = max(1, bottom - top)
        sub_left = left + int(width * start_x_ratio)
        sub_top = top + int(height * start_y_ratio)
        sub_right = left + int(width * end_x_ratio)
        sub_bottom = top + int(height * end_y_ratio)
        if sub_right <= sub_left:
            sub_right = min(right, sub_left + 2)
        if sub_bottom <= sub_top:
            sub_bottom = min(bottom, sub_top + 2)
        return (sub_left, sub_top, sub_right, sub_bottom)

    def _parse_money_text(self, text: str) -> str:
        if not text:
            return ""
        match = MONEY_PLUS_PATTERN.search(text)
        if match:
            return match.group(1)
        digits = extract_and_merge_digits(text)
        return digits

    def read_money_value(self) -> str:
        """读取右上角金币数"""
        window_region = self.get_window_region()
        candidates = []
        if self.cached_money_region:
            candidates.append(("cache", self.cached_money_region))
        if window_region:
            region = self.fraction_region(window_region, 0.75, 0.0, 1.0, 0.25)
            candidates.append(("dynamic", region))

        for source, region in candidates:
            money_text = self.ocr_region(region)
            value = self._parse_money_text(money_text)
            if value:
                if source != "cache":
                    self.cached_money_region = region
                return value

        fallback_region = self.selector.get_region("money")
        if fallback_region:
            money_text = self.ocr_region(fallback_region)
            value = self._parse_money_text(money_text)
            if value:
                return value
        return ""

    def _parse_timer_text(self, text: str):
        if not text:
            return None
        unlock_match = UNLOCK_PATTERN.search(text)
        if unlock_match:
            return {
                'mode': 'unlock',
                'minutes': int(unlock_match.group(1)),
                'seconds': int(unlock_match.group(2)),
                'text': text
            }
        direct_match = DIRECT_BUY_PATTERN.search(text)
        if direct_match:
            return {
                'mode': 'direct',
                'minutes': int(direct_match.group(1)),
                'seconds': int(direct_match.group(2)),
                'text': text
            }
        pattern_match = COUNTDOWN_PATTERN.search(text)
        if pattern_match:
            return {
                'mode': 'countdown',
                'minutes': int(pattern_match.group(1)),
                'seconds': int(pattern_match.group(2)),
                'text': text
            }
        return None

    def read_timer_info(self):
        """读取右下角倒计时信息"""
        window_region = self.get_window_region()
        candidates = []
        if self.cached_timer_region:
            candidates.append(("cache", self.cached_timer_region))
        if window_region:
            region = self.fraction_region(window_region, 0.75, 0.75, 1.0, 1.0)
            candidates.append(("dynamic", region))

        for source, region in candidates:
            text = self.ocr_region(region)
            info = self._parse_timer_text(text)
            if info:
                if source != "cache":
                    self.cached_timer_region = region
                return info

        fallback_region = self.selector.get_region("time")
        if fallback_region:
            text = self.ocr_region(fallback_region)
            info = self._parse_timer_text(text)
            if info:
                return info
        return None

    def verify_window(self) -> bool:
        """检查确认按钮区域的颜色是否变化"""
        frame = self.win_cap.capture()
        while frame is None or frame.size == 0: frame = self.win_cap.capture()
        region = self.selector.get_region("verify_check")
        # 获取区域中心颜色
        color_tmp = frame[((region[1] + region[3]) // 2), ((region[0] + region[2]) // 2)]
        center_color = convert_color(
            sRGBColor(color_tmp[2], color_tmp[1], color_tmp[0]),  # BGR to sRGB
            LabColor
        )
        # 预设的确认按钮中心颜色 (BGR)
        target_color = convert_color(
            sRGBColor(175, 109, 65),  # BGR：适用于金色砖皮
            LabColor
        )
        # 计算颜色差异
        delta_e = delta_e_cie2000(center_color, target_color)
        # 色差小说明显示了确认窗口
        self.status_updated.emit(f"颜色：{color_tmp[2], color_tmp[1], color_tmp[0]}")
        self.status_updated.emit(f"色差: {delta_e}")
        if delta_e < 80:
            return True
        return False

    def ocr_region(self, region):
        """OCR 识别"""
        frame = self.win_cap.capture()
        # while frame is None or frame.size == 0: frame = self.win_cap.capture()
        if frame is None or frame.size == 0: return ""
        roi = self.frame_cut(frame, region)
        # file_path = os.path.join(self.output_dir, f"ocr_{int(time.time() * 1000)}.png")
        # if roi.size == 0:
        #     print(f"ROI为空，无法保存: {file_path}")
        # else:
        #     success, buffer = cv2.imencode(".png", roi)
        #     if success:
        #         buffer.tofile(file_path)
        #     else:
        #         print(f"图片编码失败: {file_path}")
        rgb_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB) if roi.ndim == 3 else roi
        res = self.ocr.readtext(rgb_roi, detail=1)
        if not res:
            return ""
        texts = [item[1] for item in res if len(item) >= 2]
        if not texts:
            return ""
        return ''.join(texts)

    def run(self):
        """运行脚本"""
        try:
            self.status_updated.emit("初始化中...")
            
            buy_region = self.selector.get_region("buy")
            verify_region = self.selector.get_region("verify")
            refresh_region = self.selector.get_region("refresh")
            window_region = self.get_window_region()
            if not window_region:
                raise RuntimeError("未找到窗口范围，请在区域配置中添加 window 区域或至少一个子区域。")

            money = self.read_money_value()
            if not money:
                money = "0"
            self.status_updated.emit(f"初始三角币: {money}")
            
            self.status_updated.emit("监控中...")
            refreshed = False  # 标记是否刚刚点击过刷新
            click_region_center(refresh_region)
            while self.is_running:
                # 暂停时等待
                while self.is_paused: time.sleep(0.2); continue
                # 截图并OCR识别时间
                timer_info = self.read_timer_info()
                if not timer_info:
                    time.sleep(self.config['ocr_interval'])
                    continue

                if timer_info['mode'] == 'direct':
                    self.status_updated.emit("当前商品可直接购买，不需要脚本操作")
                    self.task_completed.emit()
                    break

                minutes = timer_info['minutes']
                seconds = timer_info['seconds']
                self.timer_updated.emit(str(minutes), str(seconds))

                if minutes == 0 and seconds == 3 and self.config['click_refresh_at_3s'] and not refreshed:
                    self.status_updated.emit("🔄 点击刷新...")
                    click_region_center(refresh_region)
                    refreshed = True

                if minutes == 0 and seconds == 1:
                    self.status_updated.emit("准备点击...")
                    time.sleep(self.config['buy_click_delay'])
                    click_region_center(buy_region, interval=0)
                    buy_count = 0
                    while not self.verify_window() and buy_count < 5:
                        buy_count += 1
                        if buy_count <= 2:
                            time.sleep(self.config['buy_interval'])
                            click_region_center(buy_region, interval=0)
                    time.sleep(self.config['buy_to_verify_delay'])
                    click_region_center(verify_region, interval=self.config['verify_interval'])
                    self.status_updated.emit("点击确认按钮...")
                    verify_counter = 0
                    while self.verify_window():
                        verify_counter += 1
                        if verify_counter > 2:
                            pydirectinput.click(1, 1, interval=0.1)
                        click_region_center(verify_region, interval=self.config['verify_interval'])
                    
                    self.status_updated.emit("等待刷新...")
                    time.sleep(1.5)
                    if self.verify_window(): pydirectinput.press('esc')
                    click_region_center(refresh_region)
                    now_money = self.read_money_value()
                    if not now_money:
                        now_money = "0"
                    self.status_updated.emit(f"当前三角币: {now_money}")
                    self.config['continue_after_complete'] &= (now_money == money)
                    if not self.config['continue_after_complete']:
                        self.status_updated.emit("任务完成！")
                        self.task_completed.emit()
                        break
                    else:
                        refreshed = False
                        self.status_updated.emit("继续监控中...")
                else:
                    if minutes > 0 or seconds > 5:
                        time.sleep(self.config['ocr_interval'])
        except Exception as e:
            self.status_updated.emit(f"错误: {str(e)}")
            print(f"脚本运行错误: {e}")
    
    def pause(self):
        self.is_paused = True
    
    def resume(self):
        self.is_paused = False
    
    def stop(self):
        self.is_running = False


def main():
    """主函数"""
    app = QApplication(sys.argv)
    selector = RegionSelector()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_region_file = os.path.join(script_dir, "regions_config.json")
    win_cap = WindowCapture(max_buffer_len=2)
    
    # 初始化 OCR
    ocr = easyocr.Reader(["ch_sim", "en"], gpu=True)
    window = MonitorWindow(default_region_file=default_region_file)
    window.show()
    # 移动到屏幕右下角
    screen = app.primaryScreen().geometry()
    win_h = window.height()
    x = screen.x() + 10
    y = screen.y() + screen.height() - win_h - 30
    window.move(x, y)
    window.add_log("程序已启动")
    window.add_log("点击 [开始] 按钮启动监控")
    script_thread = None

    def load_region_file(filepath: str):
        """加载区域配置文件"""
        try:
            selector.load_regions_from_file(filepath)
            window.set_region_file(filepath)
            window.add_log(f"区域配置已加载: {os.path.basename(filepath)}")
        except Exception as exc:
            window.add_log(f"⚠️ 区域配置加载失败: {exc}")
    
    load_region_file(default_region_file)
    window.controller.region_file_changed.connect(load_region_file)
    
    def on_start():
        nonlocal script_thread
        window.add_log("正在检查目标窗口...")
        result = ensure_target_window()
        if not result.exists:
            window.add_log(result.message)
            window.update_status("⚠️ 目标窗口未找到")
            QMessageBox.warning(window, "提示", result.message)
            window.is_running = False
            window.start_btn.setEnabled(True)
            window.pause_btn.setEnabled(False)
            window.stop_btn.setEnabled(False)
            return
        else:
            window.add_log(result.message)
            if result.hwnd and "未能" in result.message:
                QMessageBox.information(window, "提示", result.message)
        window.add_log("正在启动监控线程...")
        
        # 获取当前配置
        config = window.get_config()
        window.add_log(f"配置: 购买延迟={config['buy_click_delay']}秒")
        
        script_thread = ScriptThread(selector, win_cap, ocr, config)
        
        script_thread.status_updated.connect(lambda s: window.update_status(s))
        script_thread.status_updated.connect(lambda s: window.add_log(s))
        script_thread.timer_updated.connect(lambda m, s: window.update_timer(m, s))
        script_thread.task_completed.connect(lambda: window.on_complete())
        
        script_thread.start()
    
    def on_pause():
        if script_thread:
            script_thread.pause()
    
    def on_resume():
        if script_thread:
            script_thread.resume()
    
    def on_stop():
        if script_thread:
            script_thread.stop()
            script_thread.wait()
    
    window.controller.start_requested.connect(on_start)
    window.controller.pause_requested.connect(on_pause)
    window.controller.resume_requested.connect(on_resume)
    window.controller.stop_requested.connect(on_stop)
    
    def cleanup():
        if script_thread and script_thread.isRunning():
            script_thread.stop()
            script_thread.wait()
        win_cap.stop()
    
    app.aboutToQuit.connect(cleanup)
    
    sys.exit(app.exec())


if __name__ == "__main__":
    # 检查并请求管理员权限
    if not is_admin():
        print("检测到程序未以管理员权限运行")
        run_as_admin()
    else:
        print("Delta Force 自动购买脚本 - PyQt6 GUI版本 (管理员模式)")
        main()
