"""安卓 / 模拟器方案入口（周边工具，未完成的实验代码）。

原 scripts/yys_adb/AdbYys.py，重构后仅修正 import 路径。
"""
import os

import uiautomator2 as u2

from constant_action import *  # noqa: F401,F403  同目录导入

abs_file = __file__
parent = os.path.dirname(os.path.realpath(__file__)) + r"\res"

if __name__ == '__main__':
    d = u2.connect('127.0.0.1')
