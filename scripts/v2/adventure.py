from Personal import *
from utils.Logger import Logger
from utils.MapCv import MapCv
from utils.Monster import Monster

log = Logger().getlog()

# 右下方选择副本的位置
last_adventure = 1023, 597
adventure_200 = 831, 540
move_right = 674, 590
move_left = 476, 565
awake_200 = 558, 533
log = Logger().getlog()


class Adventure(Personal):

    def __init__(self, timer=-1, exp=False):
        super().__init__()
        self.timer = timer
        self.exp = exp
        self.adventure_retry = 34
        self.max_page_num = 4  # 一次探索最多拖4下
        self.page_click = 2  # 没有怪物的时候 一个地图定位两次
        self.auto_power = False  # 自动补充体力

    def activate(self, monster):
        # 得到怪物的坐标点 开始打怪
        lock_click(monster)
        if MapCv.append_power():
            log.info("体力已经耗尽，程序运行停止...")
            exit(300)

        lock_wait("准备2.png", after_action=lambda x: lock_doubleclick(413, 558, pause=2))
        # 替换狗粮大队长
        log.info("------------------------开始替换狗粮")
        points = MapCv.location_multiscreen("满.png")
        log.info("查找狗粮是否需要替换")
        block_1 = 377
        block_2 = 760

        for point in points:
            if point[1] < 400:
                if block_1 < point[0] < block_2:
                    next_dog()
                    time.sleep(2)
                    pyautogui.moveTo(472, 572, pause=2)
                    pyautogui.dragTo(point[0], point[1] + 100, 1)
                    break
                elif point[0] < block_1:
                    next_dog()
                    time.sleep(2)
                    pyautogui.moveTo(472, 572, pause=2)
                    pyautogui.dragTo(point[0], point[1] + 100, 1)
                    break

        pyautogui.click(1048, 558, duration=2)
        log.info("开始探索\n_________________________________")
        time.sleep(30)
        while not MapCv.end_adventure():
            log.info("打怪中....")
            time.sleep(10)
        log.info("打怪完成\n##################################")
        click(awake_200)
        lock_wait_lost("end_adventure.png", loop_action=click(awake_200))
        log.info("退出单次打怪页面....")
        # 判断当前所在页面
        time.sleep(4)
        if MapCv.start_adventure():  # 如果在开始探索页面 如果有boss奖励就拿，然后退出，重新进入探索模式 没有就继续下一次找怪
            # 判断是不是boss奖励不是继续探索
            return

        if MapCv.__in_screenshot__("首页.png"):  # 如果在首页 判断是不是有石距，或者宝箱
            # box = MapCv.__in_screenshot__("宝箱.png")  # 回到首页宝箱
            # bigMonster = MapCv.__in_screenshot__("愤怒的石距.png")  # 回到首页石距
            lock_click(last_adventure, lock_img="start_adventure.png")

    def start(self):
        # lock_wait("wait_adventure.png")
        lock_click(last_adventure, lock_img="start_adventure.png")
        log.info("已经进入探索副本，开始进行自动扫怪")
        for i in range(self.timer):
            lock_click(adventure_200, lock_img="wait_adventure.png")
            log.info("第{}次探索副本开始\n--------------------------------".format(i + 1))
            next_page()
            while True:
                for retry in range(self.adventure_retry):
                    monsters = Monster.lock_monster_exp() if self.exp else Monster.lock_monster()
                    page_num = 0
                    log.info("当前在地图第{}页,已定位怪物数量{}".format(page_num, len(monsters)))
                    lost_monster = 0
                    if len(monsters) > 0:
                        lost_monster = 0
                        self.activate(monsters[0])
                    else:
                        # 未定位到怪物进入下一页
                        lost_monster += 1
                        log.info("第{}次，未找到怪兽".format(lost_monster))
                        if lost_monster > 3:
                            log.info("进入下一页寻找怪兽")
                            page_num += 1
                            next_page()
                    if page_num > self.max_page_num:
                        log.info("已经第4次拖图，结束本次探索")
                        break
                log.info("------------------------------\n第{}次副本探索结束...")
                break
