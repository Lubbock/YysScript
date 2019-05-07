from Personal import *
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


class Adventure(Personal):

    @staticmethod
    def activate(exp=False):
        wait_adventure = MapCv.wait_adventure()
        if not wait_adventure:
            time.sleep(2)
        log.info("开始锁定怪物")
        if exp:
            monsters = Monster.lock_monster_exp()
        else:
            monsters = Monster.lock_monster()
        feat = False
        log.info("找到怪物 {} 个，开始进行处理".format(len(monsters)))
        if len(monsters) > 0:
            feat = True
            pyautogui.click(monsters[0], pause=2)
            log.info("=======================")
            log.info(monsters[0])
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
        pyautogui.click(awake_200, duration=2)
        time.sleep(4)

    # 自动更换狗粮
    @staticmethod
    def loop_check_monster():
        time.sleep(2)
        while not MapCv.__in_screenshot__("准备2.png"):
            time.sleep(2)

        pyautogui.doubleClick(413, 558, duration=2, pause=2)

        points = MapCv.location_multiscreen("满.png")

        block_1 = 377
        block_2 = 760

        for point in points:
            if point[1] < 400:
                if block_1 < point[0] < block_2:
                    Adventure.next_dog()
                    time.sleep(2)
                    pyautogui.moveTo(472, 572, pause=2)
                    pyautogui.dragTo(point[0], point[1] + 100, 1)
                    break
                elif point[0] < block_1:
                    Adventure.next_dog()
                    time.sleep(2)
                    pyautogui.moveTo(472, 572, pause=2)
                    pyautogui.dragTo(point[0], point[1] + 100, 1)
                    break

        time.sleep(1)
        pyautogui.click(1048, 558, duration=1)
        time.sleep(2)
        pyautogui.click(1048, 558, duration=1)

        # 狗粮大队长 在第三个格子

    @staticmethod
    def next_page():
        pyautogui.moveTo(558, 538)
        pyautogui.dragTo(92, 519, 1)

    @staticmethod
    def next_dog():
        pyautogui.moveTo(175, 673)
        pyautogui.dragTo(788, 674, 2)

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
    def start(timer=10, exp=True):
        pyautogui.click(last_adventure, pause=3)

        for i in range(0, timer):
            log.info("开始第{}次探索副本".format(i + 1))
            pyautogui.click(adventure_200, pause=4)
            Adventure.next_page()
            activate_num = 0
            next_page_num = 1
            while True:
                log.info("判断是否还在扫怪阶段,不是重新进入地图")
                if Adventure.in_adventure_home():
                    break
                feat, append_power = Adventure.activate(exp)

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
                    Adventure.loop_check_monster()
                    # 不在检测的地方 说明已经在打怪了，等待
                    activate_num += 1
                    # 循环检测是否打完也怪
                    Adventure.loop_checkend()
                else:
                    log.info("未查询到怪物，进入下一步地图查找")
                    if next_page_num < 4:
                        next_page_num += 1
                        Adventure.next_page()
                    else:
                        pyautogui.click(49, 121)
                        log.info("退出到主页")
                        time.sleep(2)
                        pyautogui.click(686, 419)
                        time.sleep(5)
                        break
