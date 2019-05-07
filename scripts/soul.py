from Personal import Personal
import pyautogui
import time
from Personal import *
from utils.ActionPoint import ActionPoint
from utils.Logger import Logger

soul_50 = 320, 381
soul_100 = 840, 502
soul_200 = 558, 533

class Soul(Personal):

    @staticmethod
    def start(timer=2):
        log.info("刷御魂")
        pyautogui.click(ActionPoint.find_logo(2), pause=1.5)
        pyautogui.click(soul_50, pause=1.5)
        for i in range(0, timer):
            pyautogui.click(soul_100, pause=1.5)
            time.sleep(80)
            pyautogui.click(soul_200, pause=5)
