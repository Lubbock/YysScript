from Personal import Personal
from utils.ActionPoint import ActionPoint
import pyautogui
import time
from Personal import *
# 成功
from utils.Logger import Logger
from utils.MapCv import MapCv

awake_200 = 558, 533
# 开始请求
awake_100 = 840, 502

pre_button = 1024, 536


class Awake(Personal):

    @staticmethod
    def loop_end():
        while not MapCv.__in_screenshot__("妖气封印打完_2.png"):
            time.sleep(2)
        pyautogui.click(awake_100, pause=2)

    @staticmethod
    def loop_start():
        while not MapCv.__in_screenshot__("挑战.png"):
            pyautogui.click(awake_100, pause=2)
            time.sleep(2)

    @staticmethod
    def start(awake_num=4, timer=20):
        log.info("第 {} 轮刷觉醒".format(awake_num))
        pyautogui.click(ActionPoint.find_logo(1), pause=1.5)
        pyautogui.click(ActionPoint.soul_awake(awake_num), pause=1.5)
        for i in range(0, timer):
            Awake.loop_start()
            log.info("第 {} 轮 第 {} 次 刷觉醒".format(awake_num, i))
            pyautogui.click(awake_100, pause=2)
            time.sleep(20)
            Awake.loop_end()
