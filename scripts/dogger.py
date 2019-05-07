from Personal import Personal
import pyautogui
import time
from Personal import *
from utils.Logger import Logger
from utils.MapCv import MapCv

dogger_100 = 216, 619
ghost_girl = 428, 402
ghost_100 = 674, 617

pre_button = 1024, 536
pre_end = 217, 452



class Dogger(Personal):

    @staticmethod
    def loop_pre():
        while not MapCv.__in_screenshot__("准备.png"):
            if MapCv.__in_screenshot__("开始战斗.png"):
                pyautogui.click(902, 573)
            time.sleep(2)
        pyautogui.click(pre_button, duration=1)

        if MapCv.__in_screenshot__("准备.png"):
            pyautogui.click(pre_button, duration=2)

    @staticmethod
    def loop_end():
        while not MapCv.__in_screenshot__("妖气封印打完_2.png"):
            time.sleep(2)
        pyautogui.click(pre_end, pause=2)

    @staticmethod
    def start(timer=30):
        for i in range(0, timer):
            pyautogui.click(dogger_100, pause=1)
            screen = MapCv.location_screen("骨女.png")
            pyautogui.click(screen, pause=1)
            pyautogui.click(ghost_100)
            Dogger.loop_pre()
            Dogger.loop_end()
            time.sleep(2)
            while not MapCv.__in_screenshot__("组队.png"):
                pyautogui.click(dogger_100)
                time.sleep(2)
            time.sleep(2)
