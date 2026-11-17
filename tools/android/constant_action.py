import os
import uuid
import uiautomator2 as u2

def adb_connect():
    os.system("adb connect 127.0.0.1:7555")


def adb_screenshot(file_path):
    screenshot = file_path+"\\"+uuid.uuid4().__str__() + ".png"
    os.system("adb exec-out /system/bin/screencap -p /sdcard/" + screenshot)
    os.system("adb pull /sdcard/screenshot.png "+screenshot)

def adb_getsize():
    return os.system("adb shell wm size")

def u_connect():
    d = u2.connect('127.0.0.1')

