import cv2
import numpy
import numpy as np
import pyautogui


class Monster:

    @staticmethod
    def lock_monster():

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
        #lower_blue = np.array([16, 20, 210])
        #upper_blue = np.array([30, 184, 255])
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
                point.append((x*2, y*2))
                # # 在图像上画上矩形（图片、左上角坐标、右下角坐标、颜色、线条宽度）
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255,), 3)
                #给识别对象写上标号
                font = cv2.FONT_HERSHEY_SIMPLEX
                cv2.putText(frame, str(p), (x - 10, y + 10), font, 1, (0, 0, 255), 2)  # 加减10是调整字符位置
                p += 1

       # cv2.imshow("ss", frame)
       # cv2.waitKey(0)
        return point
