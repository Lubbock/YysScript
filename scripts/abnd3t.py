from scripts.a_base import *
import pyautogui
from utils.winut import *
from utils.MapCv import MapCv
from decorator import decorator


@decorator
def win_location_screen(func, *args, **kwargs):
    w, h = MapCv.location_screen(*args, **kwargs)
    return w - 50, h - 50


@win_location_screen
def location_screen(*args, **kwargs):
    log.info("location screen...")


class Aband3t(Personal):

    @staticmethod
    def complete00000():
        log.info("开始事件Aband3t-0000")
        w, h = location_screen("Aband3t-0.png")
        log.info(w)
        pyautogui.moveTo(w, h)
        pyautogui.click(w, h)
        log.info("结束事件Aband3t-0000")

    @staticmethod
    def complete0001(loopNum):
        log.info("开始事件Aband3t-0001")
        w, h = location_screen("Aband3t-1.png")
        log.info(w)
        pyautogui.moveTo(w + 60, h)
        click(w+60, h, _pause=1, duration=1)
        time.sleep(2)
        for i in range(loopNum):
            evt = ExitEvent(20)
            while not MapCv.__in_screenshot__("Aband3t-3.png"):
                evt.start_event()
                log.info("evt leave ...-3")
                time.sleep(2)
            w, h = location_screen("Aband3t-3.png")
            click(w, h, _pause=1, duration=1)
            time.sleep(40)
            evt = ExitEvent(50)
            while not MapCv.__in_screenshot__("Aband3t-2.png"):
                evt.start_event()
                log.info("end... -2")
                time.sleep(5)
            w, h = MapCv.location_screen("Aband3t-2.png")
            click(w, h, _pause=1, duration=1)
            time.sleep(2)

        log.info("结束事件Aband3t-0001")

    @staticmethod
    def start_event():
        Aband3t.complete0001(8)


if __name__ == "__main__":
    log.info("开始事件 band3t")
    Aband3t.start_event()
