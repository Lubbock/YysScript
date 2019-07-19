import cv2
import pyautogui
import numpy as np
import os


def screenshort():
    return pyautogui.screenshot()


def location(img, template_path, threshold=0.7):
    img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 加载将要搜索的图像模板
    template = cv2.imread(template_path, 0)
    w, h = template.shape[::-1]
    res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
    # 设定阈值
    # res大于70%
    loc = np.where(res >= threshold)
    points = []
    for pt in zip(*loc[::-1]):  # *号表示可选参数
        point = (pt[0] + w), (pt[1] + h)
        points.append(point)
    print(points)
    return points
