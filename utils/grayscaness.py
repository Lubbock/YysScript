import sqlite3
import numpy as np
import matplotlib.pyplot as plt
import datetime
import time


class SqlScan:

    @staticmethod
    def open_db():
        conn = sqlite3.connect('gray_scan.db')
        print("open database gray_scan")
        return conn

    @staticmethod
    def init_table():
        conn = SqlScan.open_db()
        c = conn.cursor()
        c.execute('''CREATE TABLE GAMETIME_RECORD
        (KEY_NAME TEXT NOT NULL,
        P_NUM INT NOT NULL);''')
        print("Table created successfully")
        conn.commit()
        conn.close()

    @staticmethod
    def gray_scan(keyword, prediction_num):
        conn = SqlScan.open_db()
        c = conn.cursor()
        cur_count = SqlScan.count_gray_scan(c, keyword)
        if cur_count > 1000:
            SqlScan.clear_kw(500)
            return
        c.execute(
            "INSERT INTO GAMETIME_RECORD(KEY_NAME,P_NUM) values (\"" + keyword + "\"," + str(prediction_num) + ")")
        conn.commit()
        conn.close()

    @staticmethod
    def clear_kw(keyword, limit):
        conn = SqlScan.open_db()
        c = conn.cursor()
        c.execute("DELETE from GAMETIME_RECORD where KEY_NAME=\"" + keyword + "\" limit " + limit)
        conn.commit()
        print(keyword + "已删除")

    @staticmethod
    def count_gray_scan(cursor, keyword):
        cur_count = cursor.execute("select count(*) from GAMETIME_RECORD where KEY_NAME=\"" + keyword + "\"")
        for row in cur_count:
            return row[0]

    @staticmethod
    def list_gray_scan(keyword):
        conn = SqlScan.open_db()
        c = conn.cursor()
        p_nums = []
        # SqlScan.init_table()
        cursor = c.execute("select KEY_NAME,P_NUM from GAMETIME_RECORD where KEY_NAME=\"" + keyword + "\"")
        for row in cursor:
            p_nums.append(row[1])
            # print("KEY_NAME = ", row[0])
            # print("P_NUM = ", row[1])
            # print("\n")
        conn.close()
        return p_nums

    @staticmethod
    def paint(keyword):
        glists = SqlScan.list_gray_scan(keyword)
        average = np.mean(glists)  # 一行解决。
        x = np.linspace(0, 1, len(average))
        plt.plot(x, average, color='red')
        plt.show()
        for k in glists:
            print(k)


if __name__ == "__main__":
    SqlScan.init_table()
