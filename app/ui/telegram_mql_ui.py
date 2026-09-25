#!/usr/bin/env python
# #support	:Trolard Vincent
# copyright	:Vincannes

import os
import json
import logging
import asyncio
import threading
from urllib import request, parse
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QMetaObject, Q_ARG
from PySide6.QtWidgets import QFileDialog, QMessageBox
from app import constants


class QTextEditHandler(logging.Handler):
    """Logging handler that appends records to a QTextEdit widget."""

    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        self.setFormatter(fmt)

    def emit(self, record):
        msg = self.format(record)
        QMetaObject.invokeMethod(
            self.widget, "append",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, msg)
        )


class MainController(object):
    def __init__(self, ui_file):
        # Load UI
        ui_file = QFile(ui_file)
        ui_file.open(QFile.ReadOnly)

        loader = QUiLoader()
        self.window = loader.load(ui_file)
        ui_file.close()

        if not self.window:
            raise RuntimeError("Failed to load UI")

        self.groups_locked = False
        self.on_validate_callback = None

        # ----- INITIAL STATE -----
        self.window.stackedWidget.setCurrentIndex(0)
        self.reset_login_view()

        # ----- SIGNALS -----
        # pseudo code
        self.window.btnSelectFolder.clicked.connect(self.select_folder)

        self.window.btnLoginQR.clicked.connect(self.show_qr_code)
        self.window.btnBackQR.clicked.connect(self.back_from_qr)

        self.window.btnSendCode.clicked.connect(self.on_send_code)
        self.window.btnValidate.clicked.connect(self.on_validate_group)

        self.window.btnLoginCode.clicked.connect(self.go_to_groups)
        self.window.actionChangeMQLFolder.triggered.connect(self.show_select_folder)
        self.window.actionCleanSignals.triggered.connect(self.clean_signals)
        self.window.actionExportLog.triggered.connect(self.export_log)
        self.window.listGroups.itemClicked.connect(self._toggle_check)
        self.window.btnClearLogs.clicked.connect(self.window.logTextEdit.clear)

        # Attach log handler to root logger
        self._log_handler = QTextEditHandler(self.window.logTextEdit)
        self._log_handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(self._log_handler)

    # ================= LOGIN =================

    def show_qr_code(self):
        # Show QR + Back
        self.window.qrCodeLabel.setVisible(True)
        self.window.btnBackQR.setVisible(True)

        # Hide phone login
        self.window.lineEditPhone.setVisible(False)
        self.window.btnSendCode.setVisible(False)
        self.window.btnLoginQR.setVisible(False)

    def back_from_qr(self):
        self.reset_login_view()

    def reset_login_view(self):
        # ----- Cacher QR -----
        self.window.qrCodeLabel.setVisible(False)
        # ----- Cacher code login -----
        self.window.labelEnterCode.setVisible(False)
        self.window.lineEditCode.setVisible(False)
        self.window.btnLoginCode.setVisible(False)
        # ----- Cacher back QR/code -----
        self.window.btnBackQR.setVisible(False)

        # ----- Montrer telephone login -----
        self.window.lineEditPhone.setVisible(True)
        self.window.btnSendCode.setVisible(True)
        self.window.btnLoginQR.setVisible(True)

    def on_send_code(self):
        phone = self.window.lineEditPhone.text().strip()
        if not phone:
            return
        self.show_code_login()

    def show_code_login(self):
        # Hide phone login
        self.window.lineEditPhone.setVisible(False)
        self.window.btnSendCode.setVisible(False)
        self.window.btnLoginQR.setVisible(False)

        # Hide QR if it was visible
        self.window.qrCodeLabel.setVisible(False)
        self.window.btnBackQR.setVisible(False)

        # Show code login widgets
        self.window.labelEnterCode.setVisible(True)
        self.window.lineEditCode.setVisible(True)
        self.window.btnLoginCode.setVisible(True)

        # Show Back button (reuse btnBackQR)
        self.window.btnBackQR.setVisible(True)

    def back_from_qr(self):
        self.reset_login_view()

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(
            parent=self.window,
            caption="Select the MetaTrader 5 Terminal folder",
            options=QFileDialog.ShowDirsOnly
        )
        if folder:
            self.window.lineEditFolderPath.setText(folder)
            with open(constants.SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"MQL_DIR_PATH": folder}, f, indent=4, ensure_ascii=False)

    def show_select_folder(self):
        page_index = self.window.stackedWidget.indexOf(self.window.page_select_folder)
        if page_index != -1:
            self.window.stackedWidget.setCurrentIndex(page_index)
            self.window.lineEditFolderPath.clear()
            self.window.labelFolderStatus.setText("")


    # ================= CLEAN SIGNALS =================
    def clean_signals(self):
        logger = logging.getLogger()
        path = constants.SIGNALS_FILENAME

        if not path:
            QMessageBox.warning(
                self.window, "Clean signals",
                "No MQL folder configured, signals.json path is unknown."
            )
            return

        confirm = QMessageBox.question(
            self.window, "Clean signals",
            "Delete and recreate an empty signals.json?\n{}".format(path),
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            if os.path.exists(path):
                os.remove(path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump([], f, indent=4)
            logger.info("signals.json cleaned: %s", path)
        except Exception as exc:
            logger.error("Failed to clean signals.json: %s", exc)
            QMessageBox.critical(
                self.window, "Clean signals",
                "Failed to clean signals.json:\n{}".format(exc)
            )

    # ================= EXPORT LOG =================
    def export_log(self):
        log_text = self.window.logTextEdit.toPlainText().strip()
        if not log_text:
            QMessageBox.information(self.window, "Export log", "No log to export.")
            return

        if not constants.TELEGRAM_LOG_BOT_TOKEN or not constants.TELEGRAM_LOG_CHAT_ID:
            QMessageBox.warning(
                self.window, "Export log",
                "TELEGRAM_LOG_BOT_TOKEN / TELEGRAM_LOG_CHAT_ID missing in .env."
            )
            return

        logging.getLogger().info("Exporting logs to Telegram...")
        threading.Thread(
            target=self._send_log_to_telegram,
            args=(log_text,),
            daemon=True,
        ).start()

    def _send_log_to_telegram(self, log_text):
        logger = logging.getLogger()
        url = "https://api.telegram.org/bot{}/sendMessage".format(
            constants.TELEGRAM_LOG_BOT_TOKEN
        )
        # Telegram limite un message a 4096 caracteres -> on decoupe le log
        max_len = 4000
        chunks = [log_text[i:i + max_len] for i in range(0, len(log_text), max_len)]
        try:
            for idx, chunk in enumerate(chunks, 1):
                prefix = ""
                if len(chunks) > 1:
                    prefix = "[{}/{}]\n".format(idx, len(chunks))
                query = parse.urlencode({
                    "chat_id": constants.TELEGRAM_LOG_CHAT_ID,
                    "text": prefix + chunk,
                })
                full_url = "{}?{}".format(url, query)
                req = request.Request(url, data=query.encode("utf-8"))
                with request.urlopen(req, timeout=20) as resp:
                    resp.read()
                # Trace de l URL sendMessage appelee
                logger.info("sendMessage called: %s", full_url)
            logger.info("Logs exported to Telegram (%d message(s))", len(chunks))
        except Exception as exc:
            logger.error("Failed to export logs to Telegram: %s", exc)

    # ================= NAVIGATION =================
    def go_to_groups(self):
        self.window.stackedWidget.setCurrentIndex(1)

    def go_to_login(self):
        self.window.stackedWidget.setCurrentIndex(0)
        self.reset_login_view()

    # ================= GROUP =================
    def _toggle_check(self, item):
        if not self.groups_locked:
            new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
            item.setCheckState(new_state)

    def _checked_items(self):
        result = []
        for i in range(self.window.listGroups.count()):
            item = self.window.listGroups.item(i)
            if item.checkState() == Qt.Checked:
                result.append(item)
        return result

    def on_validate_group(self):
        if not self.groups_locked:
            checked_items = self._checked_items()
            if not checked_items:
                return

            # Lock unchecked items
            checked_set = set(id(item) for item in checked_items)
            for i in range(self.window.listGroups.count()):
                item = self.window.listGroups.item(i)
                if id(item) not in checked_set:
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsUserCheckable)

            names = ", ".join(item.text() for item in checked_items)
            self.window.btnValidate.setText("Unvalidate")
            self.window.titleGroups.setText("Listening: {}".format(names))
            self.groups_locked = True
            self.window.labelStatus.setVisible(True)
            self.window.btnConfigure.setEnabled(True)

            group_configs = {
                item.data(Qt.UserRole): item.text()
                for item in checked_items
            }
            if self.on_validate_callback:
                asyncio.create_task(self.on_validate_callback(group_configs))

        else:
            # Unlock all items and uncheck
            for i in range(self.window.listGroups.count()):
                item = self.window.listGroups.item(i)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)

            self.window.btnConfigure.setEnabled(False)
            self.window.titleGroups.setText("Select groups:")
            self.window.btnValidate.setText("Validate")
            self.groups_locked = False
            self.window.labelStatus.setVisible(False)

    def show(self):
        self.window.show()
