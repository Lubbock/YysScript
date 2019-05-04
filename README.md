# YysScript
pyautogui的使用demo,包含了opencv2一些图像识别的代码

还在开发的脚本，未考虑到游戏适应问题

通过opencv的matchtemplate方法实现，图形定位，matchtemplate太慢，所以在运动物体定位上，使用cv2对截屏图像进行二值处理，去躁点，加快了cv2对运动物体图标的定位速度。

