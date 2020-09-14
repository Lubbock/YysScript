import cv2
import numpy
import numpy as np
import pyautogui

from scripts.a_base import *

class Monster:

    @staticmethod
    def lock_exp(hsv):
        kernel_2 = np.ones((2, 2), np.uint8)  # 2x2的卷积核
        kernel_3 = np.ones((3, 3), np.uint8)  # 3x3的卷积核
        kernel_4 = np.ones((4, 4), np.uint8)  # 4x4的卷积核
        kernel_8 = np.ones((8, 8), np.uint8)  # 4x4的卷积核
        # 灰色识别
        lower_blue = np.array([5, 59, 170])
        upper_blue = np.array([20, 91, 202])
        mask = cv2.inRange(hsv, lower_blue, upper_blue)
        # 去噪点，铺平
        # erosion = cv2.erode(mask, kernel_4, iterations=1)
        erosion = cv2.erode(mask, kernel_2, iterations=1)
        # erosion = cv2.erode(erosion, kernel_4, iterations=1)
        # 污染
        dilation = cv2.dilate(erosion, kernel_4, iterations=3)
        dilation = cv2.dilate(dilation, kernel_8, iterations=2)

        ret, binary = cv2.threshold(dilation, 127, 255, cv2.THRESH_BINARY)
        _, contours, _ = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        return contours

    @staticmethod
    def lock_monster_inner(hsv):
        kernel_2 = np.ones((2, 2), np.uint8)  # 2x2的卷积核
        kernel_3 = np.ones((3, 3), np.uint8)  # 3x3的卷积核
        kernel_4 = np.ones((4, 4), np.uint8)  # 4x4的卷积核
        kernel_8 = np.ones((8, 8), np.uint8)  # 4x4的卷积核
        kernel_16 = np.ones((18, 18), np.uint8)  # 4x4的卷积核
        # 如果color中定义了几种颜色区间，都可以分割出来

        # 创建NumPy数组
        # change to hsv model
        # frame = cv2.resize(frame, (640, 400), interpolation=cv2.INTER_CUBIC)

        # 灰色识别
        lower_blue = np.array([7, 169, 30])
        upper_blue = np.array([14, 200, 67])
        # lower_blue = np.array([16, 20, 210])
        # upper_blue = np.array([30, 184, 255])
        # get mask
        mask = cv2.inRange(hsv, lower_blue, upper_blue)
        # cv2.imshow('hsv', mask)

        # detect blue
        # res = cv2.bitwise_and(frame, frame, mask=mask)
        # cv2.imshow('Result', res)
        erosion = cv2.erode(mask, kernel_2, iterations=1)
        # cv2.imshow("erosion", erosion)
        # erosion = cv2.erode(erosion, kernel_4, iterations=2)
        # erosion = cv2.erode(erosion, kernel_4, iterations=1)
        # dilation = cv2.dilate(erosion, kernel_16, iterations=4)
        dilation = cv2.dilate(erosion, kernel_8, iterations=2)

        ret, binary = cv2.threshold(dilation, 1, 127, cv2.THRESH_BINARY)
        cv2.imshow("binary", binary)
        #  cv2.imshow("mask", binary)
        _, contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

        return contours

    @staticmethod
    def paint_rect(frame, title, monster_contours, exp_contours, color=(0, 0, 255)):
        p = 1
        contours = Monster.ai_match(monster_contours, exp_contours)
        point = []
        for contour in contours:
            x = contour[0]
            y = contour[1]
            w = contour[2]
            h = contour[3]
            e_x = contour[4]
            e_y = contour[5]
            e_w = contour[6]
            e_h = contour[7]

            cv2.rectangle(frame, (e_x, e_y), (e_x + e_w, e_y + e_h), (0, 255, 0), 3)
            # 给识别对象写上标号
            font = cv2.FONT_HERSHEY_SIMPLEX
            cv2.putText(frame, title.format(p), (e_x - 10, e_y + 10), font, 1, (0, 255, 0), 2)  # 加减10是调整字符位置

            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 3)
            # 给识别对象写上标号
            font = cv2.FONT_HERSHEY_SIMPLEX
            cv2.putText(frame, title.format(p), (x - 10, y + 10), font, 1, color, 2)  # 加减10是调整字符位置
            p += 1
            x_real = int((x + w / 2) * 2)
            y_real = int((y + h / 2) * 2)
            if y_real < 400:
                point.append((x_real, y_real))
        return point

    @staticmethod
    def ai_match(monster_contours, exp_contours):
        exp_points = []
        exp_monsters = []
        tem = 9999
        for i in exp_contours:
            x, y, w, h = cv2.boundingRect(i)
            exp_points.append([x, y, w, h])
            min_monster = None
            log.info(y)
            if 50 < y < 300:
                for m in monster_contours:
                    m_x, m_y, m_w, m_h = cv2.boundingRect(m)
                    log.info("怪物y值{}".format(m_y))
                    if 50 < m_y < 300:
                        if abs(m_x - x) < tem:
                            tem = abs(m_x - x)
                            min_monster = [m_x, m_y, m_w, m_h, x, y, w, h]
                if min_monster is not None:
                    if min_monster[1] < 300:
                        exp_monsters.append(min_monster)
                tem = 9999
        return exp_monsters

    @staticmethod
    def lock_monster_exp():
        log.info("查找经验怪")
        frame = pyautogui.screenshot()
        frame = cv2.cvtColor(numpy.asarray(frame), cv2.COLOR_RGB2BGR)
        frame = cv2.resize(frame, (640, 400), interpolation=cv2.INTER_CUBIC)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        exp_contours = Monster.lock_exp(hsv)
        monster_contours = Monster.lock_monster_inner(hsv)
        point = Monster.paint_rect(frame, "{}", monster_contours, exp_contours, color=(255, 0, 0))
        # Monster.paint_rect(frame, "{}", monster_contours)
        print(point)
        return point

    @staticmethod
    def lock_monster():
        log.info("查找普通怪")
        # frame = cv2.imread('scc.png')
        frame = pyautogui.screenshot()
        frame = cv2.cvtColor(numpy.asarray(frame), cv2.COLOR_RGB2BGR)

        kernel_2 = np.ones((2, 2), np.uint8)  # 2x2的卷积核
        kernel_3 = np.ones((3, 3), np.uint8)  # 3x3的卷积核
        kernel_4 = np.ones((4, 4), np.uint8)  # 4x4的卷积核

        # 如果color中定义了几种颜色区间，都可以分割出来

        # 创建NumPy数组
        # change to hsv model
        frame = cv2.resize(frame, (640, 400), interpolation=cv2.INTER_CUBIC)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # 灰色识别
        lower_blue = np.array([7, 169, 30])
        upper_blue = np.array([14, 200, 67])
        # lower_blue = np.array([16, 20, 210])
        # upper_blue = np.array([30, 184, 255])
        # get mask
        mask = cv2.inRange(hsv, lower_blue, upper_blue)
        # cv2.imshow('hsv', mask)

        # detect blue
        # res = cv2.bitwise_and(frame, frame, mask=mask)
        # cv2.imshow('Result', res)
        erosion = cv2.erode(mask, kernel_2, iterations=1)
        # erosion = cv2.erode(erosion, kernel_4, iterations=1)
        dilation = cv2.dilate(erosion, kernel_4, iterations=1)
        dilation = cv2.dilate(dilation, kernel_4, iterations=1)

        ret, binary = cv2.threshold(dilation, 1, 127, cv2.THRESH_BINARY)
        #  cv2.imshow("mask", binary)
        _, contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        p = 0

        point = []
        for i in contours:  # 遍历所有的轮廓
            x, y, w, h = cv2.boundingRect(i)  # 将轮廓分解为识别对象的左上角坐标和宽、高
            if y > 50:
                point.append((x * 2, y * 2))

        # cv2.imshow("ss", frame)
        # cv2.waitKey(0)
        return point
