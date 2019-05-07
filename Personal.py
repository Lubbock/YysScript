import time

import pyautogui

from utils.Logger import Logger
from utils.MapCv import MapCv
import random

log = Logger().getlog()


def click(x=None, y=None, clicks=1, interval=0.0, button='left', duration=0.0, pause=None, _pause=True):
    pyautogui.click(x, y, clicks, interval, button, duration, pause, _pause)


def lock_wait(lock_img=None, wait_time=2, max_timeout=30, after_action=None, loop_action=None):
    timeout = 0
    while not MapCv.__in_screenshot__(lock_img):
        time.sleep(wait_time)
        timeout += wait_time
        if loop_action is not None:
            loop_action()
        if timeout > max_timeout:
            log.error("程序已等待进入{} -{}秒，脚本停止运行".format(lock_img))
            exit(300)
    if after_action is not None:
        after_action()


def lock_wait_lost(lock_img=None, wait_time=2, max_timeout=30, after_action=None, loop_action=None):
    timeout = 0
    while MapCv.__in_screenshot__(lock_img):
        time.sleep(wait_time)
        timeout += wait_time
        if loop_action is not None:
            loop_action()
        if timeout > max_timeout:
            log.error("程序已等待进入{} -{}秒，脚本停止运行".format(lock_img))
            exit(300)
    if after_action is not None:
        after_action()


def lock_click(x=None, y=None, pause=1, duration=0.0, lock_img=None, wait_time=2, max_timeout=10):
    click(x, y, pause=pause + personal_pause(), duration=duration + personal_pause())
    if lock_img is not None:
        lock_wait(lock_img)


def lock_doubleclick(x=None, y=None, pause=1, duration=0.0, lock_img=None, wait_time=2, max_timeout=10):
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


class Personal:
    def __init__(self):
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.2
