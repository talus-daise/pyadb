import sys
import zipfile
import tempfile
import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import QProcess
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QFont


def get_adb_path():
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
        return str(base / ("adb.exe" if sys.platform == "win32" else "adb"))
    return "adb"


class AdbGui(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyADB")
        self.resize(700, 450)

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_output)

        self.temp_dir = None
        self.current_device = None
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout()

        # ========= 左ペイン =========
        left_layout = QVBoxLayout()

        connect_layout = QHBoxLayout()
        self.addr_input = QLineEdit()
        self.addr_input.setPlaceholderText("IP:PORT")
        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self.adb_connect)
        connect_layout.addWidget(self.addr_input)
        connect_layout.addWidget(connect_btn)

        device_btn = QPushButton("Refresh Devices")
        device_btn.clicked.connect(self.adb_devices)

        self.devices_list = QListWidget()
        self.devices_list.itemSelectionChanged.connect(self.on_device_selected)

        left_layout.addWidget(QLabel("Connection"))
        left_layout.addLayout(connect_layout)
        left_layout.addWidget(device_btn)
        left_layout.addWidget(QLabel("Devices"))
        left_layout.addWidget(self.devices_list)

        # ========= 右ペイン =========
        right_layout = QVBoxLayout()

        install_layout = QHBoxLayout()
        self.apk_input = QLineEdit()
        self.apk_input.setPlaceholderText("choose file...")
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.select_file)
        install_btn = QPushButton("Install")
        install_btn.clicked.connect(self.install_auto)
        install_layout.addWidget(self.apk_input)
        install_layout.addWidget(browse_btn)
        install_layout.addWidget(install_btn)

        uninstall_layout = QHBoxLayout()
        self.pkg_input = QLineEdit()
        self.pkg_input.setPlaceholderText("com.example.app")
        uninstall_btn = QPushButton("Uninstall")
        uninstall_btn.clicked.connect(self.adb_uninstall)
        uninstall_layout.addWidget(self.pkg_input)
        uninstall_layout.addWidget(uninstall_btn)

        self.log = QTextEdit()
        self.log.setReadOnly(True)

        right_layout.addWidget(QLabel("Install"))
        right_layout.addLayout(install_layout)
        right_layout.addLayout(uninstall_layout)
        right_layout.addWidget(QLabel("Log"))
        right_layout.addWidget(self.log)

        main_layout.addLayout(left_layout)
        main_layout.addLayout(right_layout)

        main_layout.setStretch(0, 1)
        main_layout.setStretch(1, 3)

        self.setLayout(main_layout)

    def run_adb(self, args):
        cmd = args
        if self.current_device and args[0] not in ("devices", "connect"):
            cmd = ["-s", self.current_device] + args

        self.append_log(f"$ adb {' '.join(cmd)}", cmd=True)
        self.process.start(get_adb_path(), cmd)

    def adb_connect(self):
        addr = self.addr_input.text().strip()
        if addr:
            self.run_adb(["connect", addr])

    def adb_uninstall(self):
        pkg = self.pkg_input.text().strip()
        if pkg:
            self.run_adb(["uninstall", pkg])

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select APK / XAPK / APKM",
            "",
            "Android Packages (*.apk *.xapk *.apkm)",
        )
        if path:
            self.apk_input.setText(path)

    def install_auto(self):
        path = Path(self.apk_input.text())
        if not path.exists():
            return

        suffix = path.suffix.lower()

        if suffix == ".apk":
            self.run_adb(["install", "-r", str(path)])
        elif suffix in (".xapk", ".apkm"):
            self.install_bundle(path)

    def install_bundle(self, archive_path: Path):
        self.append_log("Extracting bundle...", cmd=True)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="adb_bundle_"))

        with zipfile.ZipFile(archive_path, "r") as z:
            z.extractall(self.temp_dir)

        apk_files = sorted(str(p) for p in self.temp_dir.rglob("*.apk"))

        if not apk_files:
            self.log.append("ERROR: No APK files found")
            return

        self.append_log("install-multiple:", cmd=True)
        for apk in apk_files:
            self.log.append(f"  {apk}")

        self.append_log("\nInstalling bundle...\n", cmd=True)

        self.run_adb(["install-multiple", "-r", *apk_files])

    def read_output(self):
        out = self.process.readAllStandardOutput().data().decode()
        err = self.process.readAllStandardError().data().decode()

        if out:
            if "List of devices attached" in out:
                lines = out.strip().splitlines()[1:]
                for line in lines:
                    if not line.strip():
                        continue
                    serial, state = line.split()
                    self.devices_list.addItem(f"{serial}  [{state}]")
            else:
                self.append_log(out.strip())

        if err:
            self.append_log(err.strip(), error=True)

    def closeEvent(self, event):
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        event.accept()

    def adb_devices(self):
        self.devices_list.clear()
        self.run_adb(["devices"])

    def on_device_selected(self):
        items = self.devices_list.selectedItems()
        if items:
            self.current_device = items[0].text().split()[0]
            self.append_log(f"Selected device: {self.current_device}", cmd=True)

    def append_log(self, text, cmd=False, error=False):
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt = QTextCharFormat()

        if error:
            fmt.setForeground(QColor("#ff4d4d"))
        elif cmd:
            fmt.setForeground(QColor("#555555"))
        else:
            fmt.setForeground(QColor("#000000"))

        cursor.insertText(text + "\n", fmt)
        self.log.setTextCursor(cursor)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = AdbGui()
    w.show()
    sys.exit(app.exec())
