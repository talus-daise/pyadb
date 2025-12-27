import sys
import zipfile
import tempfile
import shutil
from pathlib import Path
import logging
from datetime import datetime

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
)
from PySide6.QtCore import QProcess
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
import shutil


# ===============================
# CLI ログ設定
# ===============================
logging.basicConfig(
    level=logging.DEBUG,
    format="[{asctime}] [{levelname}] {message}",
    style="{",
)
log = logging.getLogger("PyADB")


def cli_log(message, level=logging.INFO):
    log.log(level, message)


def get_adb_path():
    # frozen（PyInstaller）時
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
        bundled_adb = base / ("adb.exe" if sys.platform == "win32" else "adb")

        if bundled_adb.exists():
            cli_log(f"Using bundled adb: {bundled_adb}", logging.INFO)
            return str(bundled_adb)

        cli_log("Bundled adb not found, trying system adb", logging.WARNING)

    # PATH 上の adb を探す
    system_adb = shutil.which("adb")
    if system_adb:
        cli_log(f"Using system adb: {system_adb}", logging.INFO)
        return system_adb

    # どこにも無い場合
    cli_log("ADB not found (bundled nor system)", logging.ERROR)
    return "adb"  # 最後の保険（失敗時にエラーログが出る）


class AdbGui(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyADB")
        self.resize(700, 450)

        cli_log("Initializing AdbGui")

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_output)
        self.process.started.connect(
            lambda: cli_log("ADB process started", logging.DEBUG)
        )
        self.process.finished.connect(self.on_process_finished)

        self.temp_dir = None
        self.current_device = None
        self.init_ui()

    def init_ui(self):
        cli_log("Initializing UI", logging.DEBUG)

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

    # ===============================
    # ADB 実行
    # ===============================
    def run_adb(self, args):
        cmd = args
        if self.current_device and args[0] not in ("devices", "connect"):
            cmd = ["-s", self.current_device] + args

        cli_log(f"Executing adb command: adb {' '.join(cmd)}", logging.DEBUG)
        self.append_log(f"$ adb {' '.join(cmd)}", cmd=True)

        adb_path = get_adb_path()
        cli_log(f"ADB binary path: {adb_path}", logging.DEBUG)
        self.process.start(adb_path, cmd)

    def adb_connect(self):
        addr = self.addr_input.text().strip()
        cli_log(f"Connect requested: {addr}", logging.DEBUG)
        if addr:
            self.run_adb(["connect", addr])
            self.adb_devices()

    def adb_devices(self):
        cli_log("Refreshing device list", logging.DEBUG)
        self.devices_list.clear()
        self.run_adb(["devices"])

    def adb_uninstall(self):
        pkg = self.pkg_input.text().strip()
        cli_log(f"Uninstall requested: {pkg}", logging.DEBUG)
        if pkg:
            self.run_adb(["uninstall", pkg])

    # ===============================
    # APK / Bundle
    # ===============================
    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select APK / XAPK / APKM",
            "",
            "Android Packages (*.apk *.xapk *.apkm)",
        )
        cli_log(f"File selected: {path}", logging.DEBUG)
        if path:
            self.apk_input.setText(path)

    def install_auto(self):
        path = Path(self.apk_input.text())
        cli_log(f"Install requested: {path}", logging.DEBUG)

        if not path.exists():
            cli_log("Selected file does not exist", logging.ERROR)
            return

        suffix = path.suffix.lower()

        if suffix == ".apk":
            self.run_adb(["install", "-r", str(path)])
        elif suffix in (".xapk", ".apkm"):
            self.install_bundle(path)

    def install_bundle(self, archive_path: Path):
        cli_log(f"Extracting bundle: {archive_path}", logging.DEBUG)
        self.append_log("Extracting bundle...", cmd=True)

        self.temp_dir = Path(tempfile.mkdtemp(prefix="adb_bundle_"))
        cli_log(f"Temporary directory created: {self.temp_dir}", logging.DEBUG)

        with zipfile.ZipFile(archive_path, "r") as z:
            z.extractall(self.temp_dir)

        apk_files = sorted(str(p) for p in self.temp_dir.rglob("*.apk"))
        cli_log(f"APK files found: {apk_files}", logging.DEBUG)

        if not apk_files:
            self.append_log("ERROR: No APK files found", error=True)
            cli_log("No APK files found in bundle", logging.ERROR)
            return

        self.run_adb(["install-multiple", "-r", *apk_files])

    # ===============================
    # QProcess 出力
    # ===============================
    def read_output(self):
        out = self.process.readAllStandardOutput().data().decode(errors="ignore")
        err = self.process.readAllStandardError().data().decode(errors="ignore")

        if out:
            cli_log(f"STDOUT:\n{out.rstrip()}", logging.DEBUG)

            if "List of devices attached" in out:
                self.devices_list.clear()
                lines = out.strip().splitlines()[1:]
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 2:
                        serial, state = parts[0], parts[1]
                        cli_log(f"Device detected: {serial} [{state}]", logging.INFO)
                        self.devices_list.addItem(f"{serial}  [{state}]")
            else:
                self.append_log(out.strip())

        if err:
            cli_log(f"STDERR:\n{err.rstrip()}", logging.WARNING)
            self.append_log(err.strip(), error=True)

    def on_process_finished(self, code, status):
        cli_log(
            f"ADB process finished: exitCode={code}, status={status}", logging.DEBUG
        )

    # ===============================
    # UI 補助
    # ===============================
    def on_device_selected(self):
        items = self.devices_list.selectedItems()
        if items:
            self.current_device = items[0].text().split()[0]
            cli_log(f"Device selected: {self.current_device}", logging.INFO)
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

    def closeEvent(self, event):
        cli_log("Application closing", logging.DEBUG)
        if self.temp_dir and self.temp_dir.exists():
            cli_log(f"Removing temp directory: {self.temp_dir}", logging.DEBUG)
            shutil.rmtree(self.temp_dir)
        event.accept()


if __name__ == "__main__":
    cli_log("PyADB starting")
    app = QApplication(sys.argv)
    w = AdbGui()
    w.show()
    sys.exit(app.exec())