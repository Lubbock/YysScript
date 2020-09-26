import time

import pyautogui

from utils.Logger import Logger
from utils.MapCv import MapCv
import random
import datetime
from utils.grayscaness import SqlScan
import numpy as np

log = Logger().getlog()


def click(x=None, y=None, clicks=1, interval=0.0, button='left', duration=0.0, pause=None, _pause=True):
    pyautogui.click(x=x, y=y, clicks=clicks, interval=interval, button=button, duration=duration,
                    _pause=_pause)


def lock_wait(lock_img=None, wait_time=2, max_timeout=30, after_action=None, loop_action=None):
    timeout = 0
    lock = True
    while not MapCv.__in_screenshot__(lock_img):
        if loop_action is not None:
            loop_action(1)
        time.sleep(wait_time)
        timeout += wait_time
        if timeout > max_timeout:
            log.error("程序已等待进入{} -{}秒，脚本停止运行".format(lock_img, max_timeout))
            lock = False
            break
    if after_action is not None:
        after_action(1)
    return lock


def lock_wait_lost(lock_img=None, wait_time=2, max_timeout=30, after_action=None, loop_action=None):
    timeout = 0
    while MapCv.__in_screenshot__(lock_img):
        time.sleep(wait_time)
        timeout += wait_time
        if loop_action is not None:
            loop_action(1)
        if timeout > max_timeout:
            log.error("程序已等待进入{} -{}秒，脚本停止运行".format(lock_img))
            exit(300)
    if after_action is not None:
        after_action(1)


def lock_click(x=None, y=None, pause=0.2, duration=0.0, lock_img=None, wait_time=2, max_timeout=10):
    pause = pause + personal_pause()
    duration = duration + personal_pause()
    click(x, y, pause=pause, duration=0)
    if lock_img is not None:
        lock_wait(lock_img)


def lock_doubleclick(x=None, y=None, pause=0.2, duration=0.0, lock_img=None, wait_time=2, max_timeout=10):
    pyautogui.doubleClick(x, y, pause=pause + personal_pause(), duration=duration + personal_pause())
    if lock_img is not None:
        lock_wait(lock_img)


def personal_pause():
    return random.uniform(0, 1)


def next_page():
    pyautogui.moveTo(558, 538)
    pyautogui.dragTo(92, 519, 1)


def next_dog():
    pyautogui.moveTo(175, 673)
    pyautogui.dragTo(788, 674, 2)


class ExitEvent:
    def __init__(self, exit_count):
        self.exit_count = exit_count

    def start_event(self):
        self.exit_count = self.exit_count - 1
        if self.exit_count <= 0:
            exit(300)


class Personal:
    def __init__(self):
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.2


class StopWatch:
    def __init__(self):
        self.sw_map = {}
        self.sw_end = {}

    def start(self, kw):
        start = datetime.datetime.now()
        self.sw_map[kw] = start
        self.sw_end[kw] = start
        log.info(kw + " start watch ")

    def end(self, kw):
        end = datetime.datetime.now()
        start = self.sw_map[kw]
        self.sw_end[kw] = end
        print(kw + " 时间" + str((end - start).seconds) + "秒")
        return (end - start).seconds

    def duration(self, kw):
        start = self.sw_map[kw]
        end = self.sw_end[kw]
        print(kw + " 时间" + str((end - start).seconds) + "秒")
        return (end - start).seconds


class WaitPredication:

    def __init__(self):
        self.sw = StopWatch()

    """
    得到预测后的值
    """
    def get_predication(self, kw, dp_num=20):
        p_nums = SqlScan.list_gray_scan(kw)
        self.sw.start(kw)
        if len(p_nums) == 0:
            return dp_num
        return np.average(p_nums) + 1

    def record(self, kw):
        wp = self.sw.end(kw)
        SqlScan.gray_scan(kw, wp)
