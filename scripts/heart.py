from Personal import Personal
import pyautogui
import time

from utils.MapCv import MapCv
from utils.Monster import Monster

# 简单觉醒
start_yuhun = 384, 367
simple_yuhun = 817, 203
simple_yuhun2 = 610, 399
pre_activate = 975, 531

start_activate = 1039, 548


# 御心道场
class Heart(Personal):

    @staticmethod
    def start(timer=10):
        pyautogui.click(start_yuhun, pause=2)
        pyautogui.click(simple_yuhun, pause=1)
        for i in range(0, timer):
            while not MapCv.__in_screenshot__("觉醒道场.png"):
                pyautogui.click(simple_yuhun)
                time.sleep(5)
            pyautogui.click(simple_yuhun2)
            pyautogui.click(pre_activate, pause=2)
            print("开始打怪")
            time.sleep(5)
            while MapCv.__in_screenshot__("准备2.png"):
                print("查找准备按钮")
                pyautogui.click(start_activate)
                time.sleep(2)
            time.sleep(120)
            while not MapCv.__in_screenshot__("妖气封印打完_2.png"):
                print("查找打完按钮")
                time.sleep(5)
            pyautogui.click(simple_yuhun)
