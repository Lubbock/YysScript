import win32api
from utils.opencv_util import *
from utils.mouse_util import *
import time
from utils.email_util import *
from PIL import ImageGrab


class Remote(object):

    def __init__(self):
        self.name = "remote"

    @staticmethod
    def start():
        win32api.ShellExecute(0, 'open', r'C:\Program Files (x86)\TeamViewer\TeamViewer.exe', '', '', 1)
        time.sleep(15)

    @staticmethod
    def close():
        os.system("taskkill /F /IM TeamViewer.exe")
        # os.system("taskkill /F /IM TeamViewer_Service.exe")

    def keep_alive(self):
        img = screenshort()
        match_point = location(img, "lib/teamviewer.png")
        if match_point is None or len(match_point) == 0:
            Remote.start()
        else:
            # Remote.close()
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
                time.sleep(12*60) #有发送请求的话12分钟，停止12分钟后开始重新获取
            else:
                time.sleep(30) #没有发送请求的话 30s启动一次

if __name__ == '__main__':
    email_size = get_email_size() - 1
    remote = Remote()
    while True:
        print("开始检测")
        # time.sleep(10)
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
