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


class Aj8fer(Personal):
    @staticmethod
    def complete0001(loopNum):
        log.info("开始事件Aj8fer-0001")
        for i in range(loopNum):
            evt = ExitEvent(20)
            while not MapCv.__in_screenshot__("Aj8fer-1.png"):
                evt.start_event()
                log.info("evt leave ...-3")
                time.sleep(2)

            w, h = location_screen("Aj8fer-1.png")
            click(w, h, _pause=1, duration=1)
            time.sleep(45)
            evt = ExitEvent(150)
            while not MapCv.__in_screenshot__("Aband3t-2.png"):
                # evt.start_event()
                log.info("end... -2")
                time.sleep(3)
            time.sleep(3)
            w, h = MapCv.location_screen("Aband3t-2.png")
            click(w, h, _pause=1, duration=1)
            time.sleep(2)
        log.info("结束事件Aj8fer-0001")

    @staticmethod
    def start_event():
        Aj8fer.complete0001(101)


if __name__ == "__main__":
    log.info("开始事件 j8fer")
    Aj8fer.start_event()
