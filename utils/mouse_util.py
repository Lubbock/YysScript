import pyautogui


def move(x, y=None):
    pyautogui.moveTo(x, y)


def click(x, y=None):
    pyautogui.click(x, y, duration=2)
