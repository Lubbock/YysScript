"""TeamViewer 远程控制保活（周边工具，非主流程）。

通过读取邮箱里的指令决定是否重启 TeamViewer，并回传屏幕截图。

重构说明：本文件原先依赖已删除的 utils/ 包，现在改用项目新结构——
图像识别来自 vision/，鼠标操作来自 actions/，邮件工具随本目录一起归档在
tools/remote/email_util.py。模板目录指向 tools/remote/lib。
"""
import os
import sys
import time
from pathlib import Path

import win32api
from PIL import ImageGrab

# 允许从任意目录直接运行本脚本
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from actions.mouse import HumanMouse                   # noqa: E402
from vision.capture import ScreenCapture               # noqa: E402
from vision.template_matcher import TemplateMatcher    # noqa: E402
from email_util import get_email_size, getNewestEmail, send_report  # noqa: E402

TEAMVIEWER_EXE = r"C:\Program Files (x86)\TeamViewer\TeamViewer.exe"
TEMPLATE_DIR = Path(__file__).resolve().parent / "lib"

_MOUSE = HumanMouse(humanize=False)
_CAPTURE = ScreenCapture()
_MATCHER = TemplateMatcher(capture=_CAPTURE, template_dir=TEMPLATE_DIR)


def screenshort():
    """兼容旧函数名：截取当前屏幕，返回 vision.types.Frame。"""
    return _CAPTURE.grab()


def location(_frame, template_path):
    """兼容旧函数名：定位模板，返回屏幕坐标点列表。

    注意：新版匹配器自己截图，传入的 _frame 仅为保持旧签名兼容。
    """
    matches = _MATCHER.match_all(os.path.basename(template_path))
    return [match.center for match in matches]


def click(x, y):
    _MOUSE.click((x, y))


class Remote(object):

    def __init__(self):
        self.name = "remote"

    @staticmethod
    def start():
        win32api.ShellExecute(0, 'open', TEAMVIEWER_EXE, '', '', 1)
        time.sleep(15)

    @staticmethod
    def close():
        os.system("taskkill /F /IM TeamViewer.exe")
        # os.system("taskkill /F /IM TeamViewer_Service.exe")

    def keep_alive(self):
        img = screenshort()
        match_point = location(img, "teamviewer.png")
        if match_point is None or len(match_point) == 0:
            Remote.start()
        else:
            time.sleep(30)
            click(100, 100)

    def execute(self, props):
        if len(props) > 0:
            progos_type = props['type']
            username = props['username']
            if progos_type == 'remote' and username == 'lame':
                self.close()
                time.sleep(5)
                self.start()
                time.sleep(120)
                pic = ImageGrab.grab()
                pic.save('9410.jpg')
                send_report('9410.jpg')
                time.sleep(12 * 60)  # 有发送请求的话 12 分钟后重新开始获取
            else:
                time.sleep(30)  # 没有发送请求的话 30s 轮询一次


if __name__ == '__main__':
    email_size = get_email_size() - 1
    remote = Remote()
    while True:
        print("开始检测")
        email_size, config = getNewestEmail(email_size)
        properties = {}
        if config != '':
            props = config.split(";")
            for prop in props:
                if prop.count("=") != 1:
                    break
                item = prop.split("=")
                properties[item[0]] = item[1]
        remote.execute(properties)
