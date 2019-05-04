class ActionPoint:

    # 1 觉醒材料 | 2 御魂 | 3 结界突破 | 4 御灵 | 5 平安百物语 | 6 式神委派 | 7 秘闻副本 | 8 地域鬼王 | 9 平安奇缘
    @staticmethod
    def find_logo(lognm=1):
        start_x = 70
        y = 650
        return (start_x + (lognm - 1) * 98), y

    # 1 火御魂 | 2 风麒麟 | 3 水麒麟 | 4 雷麒麟
    @staticmethod
    def soul_awake(awake_num=1):
        return 201 + (awake_num - 1) * 250, 363


