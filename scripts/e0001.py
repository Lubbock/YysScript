from scripts.a_base import *
import pyautogui
from utils.winut import *

'''
事件e0001 定位窗体，调整配置参数
'''


def complete00001():
    left, top, right, bottom = find_window_rect("Win32Window", "阴阳师-网易游戏")
    log.info("窗体 左-{:d} 顶-{:d} 右-{:d} 底部-{:d}".format(left, top, right, bottom))
    pyautogui.moveTo(left + 20, top + 20)
    pyautogui.click(left + 20, top + 20)
    pyautogui.dragTo(10, 20)



if __name__ == "__main__":
    complete00001()
