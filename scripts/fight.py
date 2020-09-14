import math

from scripts.a_base import *

from utils.MapCv import MapCv
from utils.Monster import Monster

y = [198, 319, 436]
x = [275, 576, 867]


class Fight(Personal):
    def __init__(self, timer=-1, exp=False):
        super().__init__()
        self.timer = timer

    def start(self):
        lock_click(281, 649, lock_img="结界突破.png")
        while True:
            for now in range(9):
                now = now + 1
                x_index = math.ceil(float(now) / 3)
                y_index = now % 3
                click(x[x_index - 1], y[y_index - 1])
                time.sleep(3)
                fight = MapCv.location_screen("突破进攻.png")
                if fight is None:
                    continue
                log.info(fight)
                lock_click(fight, lock_img="准备2.png")
                lock_wait_lost(lock_img="准备2.png", loop_action=lambda x: click(1022, 541))
                time.sleep(20)
                while True:
                    sb = MapCv.__in_screenshot__("突破失败.png")
                    end = MapCv.__in_screenshot__("妖气封印打完_2.png")
                    if sb or end:
                        click(x[0], y[0])
                        time.sleep(4)
                        break
                time.sleep(2)
            lock_wait_lost(lock_img="突破刷新.png", loop_action=lambda x: {click(927, 541), click(667, 443)})
            time.sleep(3)
