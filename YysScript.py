from Personal import *
from scripts.adventure import Adventure
from scripts.dogger import Dogger
from scripts.fight import Fight

if __name__ == "__main__":
    log.info("游戏脚本启动")
    # Heart.start(timer=15)
    #f = Fight(timer=1000)
    #f.start()
    #a = Adventure(exp=True, timer=100)
    #a.start()
    Dogger.start(timer=200)