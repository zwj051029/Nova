import sys
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtGui import QPalette, QColor


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nova")
        self.resize(1200, 800)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#F0F4F8"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        actual = self.size()
        print(f"窗口实际尺寸: {actual.width()} x {actual.height()}")
        print("窗口创建成功")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
