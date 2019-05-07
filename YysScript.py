import pyautogui
from Personal import *
from scripts.v2.adventure import Adventure
from scripts.heart import Heart
from utils.Logger import Logger

from utils.Monster import Monster

if __name__ == "__main__":
    log.info("游戏脚本启动")
    # Heart.start(timer=15)
    a = Adventure(exp=True, timer=100)
    a.start()
