from Personal import Personal
import pyautogui
import time

from utils.Logger import Logger
from utils.MapCv import MapCv
from utils.Monster import Monster

last_adventure = 1023, 597
adventure_200 = 831, 540
move_right = 674, 590
move_left = 476, 565
awake_200 = 558, 533
log = Logger().getlog()


class Adventure(Personal):

    @staticmethod
    def activate():
        wait_adventure = MapCv.wait_adventure()
        if not wait_adventure:
            time.sleep(2)
        log.info("开始锁定怪物")
        monsters = Monster.lock_monster()
        feat = False
        log.info("找到怪物 {} 个，开始进行处理".format(len(monsters)))
        if len(monsters) > 0:
            feat = True
            print(monsters[0])
            pyautogui.click(monsters[0], pause=2)
        else:
            feat = False
        return feat, MapCv.append_power()

    @staticmethod
    def loop_checkend(pause=2):
        while not MapCv.end_adventure():
            log.info("打怪中....")
            time.sleep(pause)
        log.info("打怪完成,返回主图...")
        pyautogui.click(awake_200, pause=3)
        pyautogui.click(awake_200)
        time.sleep(4)

    @staticmethod
    def next_page():
        pyautogui.moveTo(558, 538)
        pyautogui.dragTo(92, 519, 1)

    # 校验是不是已经回到主页了
    @staticmethod
    def in_adventure_home():
        start_adventure = MapCv.start_adventure()  # 二次探索的，首页，无宝箱，石距等等
        # box = MapCv.__in_screenshot__("宝箱.png")  # 回到首页宝箱
        # bigMonster = MapCv.__in_screenshot__("愤怒的石距.png")  # 回到首页石距
        in_home = MapCv.__in_screenshot__("首页.png")
        restart_adventure = False
        if in_home:
            log.info("正在主页面，重新进入探索地图")
            pyautogui.click(last_adventure, pause=3)
            restart_adventure = True
        if start_adventure:
            log.info("在探索主页，重新进入探索")
            restart_adventure = True
        return restart_adventure

        # 回到首页
        # 打完boss等着拿奖励

    @staticmethod
    def start(timer=2):
        pyautogui.click(last_adventure, pause=3)
        for i in range(0, timer):
            log.info("开始第{}次探索副本".format(i + 1))
            pyautogui.click(adventure_200, pause=4)
            Adventure.next_page()
            activate_num = 0
            while True:
                log.info("判断是否还在扫怪阶段,不是重新进入地图")
                if Adventure.in_adventure_home():
                    break
                feat, append_power = Adventure.activate()
                log.info("扫怪结束...")
                if append_power:
                    log.info("体力已耗尽 需要补充体力，结束探索")
                    exit()
                if feat:
                    log.info("开始第{}次探索副本,的第{}次小怪检索".format(i + 1, activate_num + 1))
                    if MapCv.wait_adventure():
                        # 如果没有开始打怪还在等待的地方，重新查找monster. 找到错误的monster需要重新搜索
                        log.info("怪物定位出现问题，重新寻找")
                        continue

                    # 不在检测的地方 说明已经在打怪了，等待
                    activate_num += 1
                    # 循环检测是否打完也怪
                    Adventure.loop_checkend()
                else:
                    log.info("未查询到怪物，进入下一步地图查找")
                    Adventure.next_page()
