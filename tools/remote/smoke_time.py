import time

if __name__ == '__main__':
    print(time.time())
    time.localtime(time.time())
    x = time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time()))
    print(x)
