from scripts.a_base import *
import pyautogui
from utils.winut import *
from utils.MapCv import MapCv


class Aband3t(Personal):

    @staticmethod
    def complete00000():
        log.info("开始事件Aband3t-0000")
        w, h = MapCv.location_screen("Aband3t-0.png")
        log.info(w, h)
        pyautogui.moveTo(w - 40, h - 40)
        pyautogui.click(w - 40, h - 40)
        log.info("结束事件Aband3t-0000")

    @staticmethod
    def complete0001(loopNum):
        log.info("开始事件Aband3t-0001")
        w, h = MapCv.location_screen("Aband3t-1.png")
        log.info(w)
        pyautogui.moveTo(w - 40, h - 40)
        click(w - 40, h - 40, _pause=1, duration=1)
        time.sleep(2)
        for i in range(loopNum):
            j = 1
            while not MapCv.__in_screenshot__("Aband3t-3.png"):
                j += 1
                if j > 20:
                    log.info("end... -3")
                    exit(300)
                time.sleep(2)
            w, h = MapCv.location_screen("Aband3t-3.png")
            click(w - 40, h - 40, _pause=1, duration=1)
            time.sleep(40)
            j = 1
            while not MapCv.__in_screenshot__("Aband3t-2.png"):
                j += 1
                if j > 50:
                    log.info("end... -2")
                    exit(300)
                time.sleep(5)
            w, h = MapCv.location_screen("Aband3t-2.png")
            click(w - 40, h - 40, _pause=1, duration=1)
            time.sleep(2)

        log.info("结束事件Aband3t-0001")

    @staticmethod
    def start_event():
        Aband3t.complete0001(8)


if __name__ == "__main__":
    log.info("开始事件 band3t")
    Aband3t.start_event()
