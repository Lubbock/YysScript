# YysScript
pyautogui的使用demo,包含了opencv2一些图像识别的代码

还在开发的脚本，未考虑到游戏适应问题

通过opencv的matchtemplate方法实现，图形定位，matchtemplate太慢，所以在运动物体定位上，使用cv2对截屏图像进行二值处理，去躁点，加快了cv2对运动物体图标的定位速度。

# 实现功能
- 自动御魂
- 自动觉醒
- 自动探索 （开发中...,暂时还不能识别经验怪）

# 项目依赖
- py-opencv
- numpy
- python3.7
- yys
- pyautogui
