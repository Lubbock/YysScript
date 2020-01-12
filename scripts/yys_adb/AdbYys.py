
from scripts.yys_adb.actions.constant_action import *
abs_file = __file__
parent = os.path.dirname(os.path.realpath(__file__))+r"\res"
import uiautomator2 as u2
if __name__ == '__main__':
    d = u2.connect('127.0.0.1')