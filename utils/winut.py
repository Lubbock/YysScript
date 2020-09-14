import win32gui
import win32con
from scripts.a_base import *


def find_window_rect(classname, titlename):
    hwnd = win32gui.FindWindow(classname, titlename)
    log.info("获得句柄 {:08X}".format(hwnd))
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    show_win(hwnd, left, top, right, bottom)
    return left, top, right, bottom


def get_child_windows(parent):
    '''     
    获得parent的所有子窗口句柄
     返回子窗口句柄列表
     '''
    if not parent:
        return
    hwndChildList = []
    win32gui.EnumChildWindows(parent, lambda hwnd, param: param.append(hwnd), hwndChildList)
    return hwndChildList


# 获取某个句柄的类名和标题
def get_window_text(hwnd):
    return win32gui.GetWindowText(hwnd)


def get_classname(hwnd):
    return win32gui.GetClassName(hwnd)


def get_parent_child(hwnd, clsname):
    # 获取父句柄hwnd类名为clsname的子句柄
    return win32gui.FindWindowEx(hwnd, None, clsname, None)


def show_win(hwnd, left, top, right, bottom):
    # windows handlers
    # win32gui.SetForegroundWindow(hwnd)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, left-20, top-20, right - left, bottom - top,
                          win32con.SWP_NOMOVE | win32con.SWP_NOACTIVATE | win32con.SWP_NOOWNERZORDER | win32con.SWP_SHOWWINDOW)
    # X11LockScreenWindow.show(self)


def hide_win(hwnd):
    # X11LockScreenWindow.hide(self)
    # windows handlers
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                          win32con.SWP_HIDEWINDOW | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_NOOWNERZORDER)


if __name__ == "__main__":
    print(find_window_rect("Win32Window", "阴阳师-网易游戏"))
