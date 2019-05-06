import os
import time
import pyautogui as pag

try:
    while True:
        print("Press Ctrl-C to end")
        screenWidth, screenHeight = pag.size()  # 获取屏幕的尺寸
        print(screenWidth, screenHeight)
        x, y = pag.position()  # 获取当前鼠标的位置
        posStr = "Position:" + str(x).rjust(4) + ',' + str(y).rjust(4)
        print(posStr)
        time.sleep(1)
        os.system('cls')  # 清楚屏幕
except KeyboardInterrupt:
    print('end....')
