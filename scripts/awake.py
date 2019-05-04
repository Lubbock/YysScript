from Personal import Personal
from utils.ActionPoint import ActionPoint
import pyautogui
import time

# 成功
awake_200 = 558, 533
# 开始请求
awake_100 = 840, 502


class Awake(Personal):

    @staticmethod
    def start(awake_num=4, timer=2):
        print("刷觉醒 {}".format(awake_num))
        pyautogui.click(ActionPoint.find_logo(1), pause=1.5)
        pyautogui.click(ActionPoint.soul_awake(awake_num), pause=1.5)
        for i in range(0, timer):
            print("刷觉醒 {} 第 {} 次 ".format(awake_num, i))
            pyautogui.click(awake_100, pause=2)
            time.sleep(75)
            pyautogui.click(awake_200, pause=1)
            pyautogui.click(awake_200, pause=3)
