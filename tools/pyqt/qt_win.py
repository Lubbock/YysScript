import sys

from PyQt5.QtWidgets import QApplication, QMainWindow
import pyqt.hew as hew
from functools import partial


def convert(ui):
    print("hello world")
    ipnum = ui.lineEdit.text()
    result = float(ipnum) * 6.7
    ui.lineEdit_2.setText(str(result))


if __name__ == '__main__':
    app = QApplication(sys.argv)
    MainWindow = QMainWindow()
    ui = hew.Ui_MainWindow()
    ui.setupUi(MainWindow)
    MainWindow.show()
    ui.pushButton.clicked.connect(partial(convert, ui))
    sys.exit(app.exec_())
