import cv2
import pyautogui
import numpy as np

adventure_200 = 831, 540


class MapCv:

    @staticmethod
    def start_adventure():
        return MapCv.__in_screenshot__('start_adventure.png')

    @staticmethod
    def wait_adventure():
        return MapCv.__in_screenshot__('wait_adventure.png')

    @staticmethod
    def append_power():
        return MapCv.__in_screenshot__('购买体力.png')

    @staticmethod
    def __in_screenshot__(filename, threshold=0.7,  path="E:/github/YysScript/res/img/"):
        img = pyautogui.screenshot()
        img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 加载将要搜索的图像模板
        template = cv2.imread(path + filename, 0)
        res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
        # 设定阈值
        # res大于70%
        loc = np.where(res >= threshold)
        match = False
        for pt in zip(*loc[::-1]):  # *号表示可选参数
            match = True
        return match

    @staticmethod
    def location_screen(filename, threshold=0.7, path="E:/github/YysScript/res/img/"):
        img = pyautogui.screenshot()
        img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 加载将要搜索的图像模板
        template = cv2.imread(path + filename, 0)
        w, h = template.shape[::-1]
        res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
        # 设定阈值
        # res大于70%
        loc = np.where(res >= threshold)
        match = False
        for pt in zip(*loc[::-1]):  # *号表示可选参数
            return (pt[0] + w), (pt[1] + h)
        return None

    @staticmethod
    def location_multiscreen(filename, threshold=0.7, path="res/img/"):
        img = pyautogui.screenshot()
        img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 加载将要搜索的图像模板
        template = cv2.imread(path + filename, 0)
        w, h = template.shape[::-1]
        res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
        # 设定阈值
        # res大于70%
        loc = np.where(res >= threshold)
        match = False
        points = []
        for pt in zip(*loc[::-1]):  # *号表示可选参数
            point = (pt[0] + w) , (pt[1] + h)
            points.append(point)
        return points

    @staticmethod
    def end_adventure():
        return MapCv.__in_screenshot__('end_adventure.png')
