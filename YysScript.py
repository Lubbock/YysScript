import pyautogui

from scripts.adventure import Adventure
from utils.Logger import Logger

from utils.Monster import Monster

log = Logger().getlog()
if __name__ == "__main__":
    log.info("游戏脚本启动")
    Adventure.start(exp=True, timer=1000)
