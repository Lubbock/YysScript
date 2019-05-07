from Personal import *
from scripts.adventure import Adventure

if __name__ == "__main__":
    log.info("游戏脚本启动")
    #Heart.start(timer=15)
    a = Adventure(exp=True, timer=100)
    a.start()
