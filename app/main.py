#!/usr/bin/env python
import os
import sys
import json
import qasync
import asyncio

sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from telethon import TelegramClient
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem

from app import constants
from app.domain.logging import setup_logger
from app.domain.valid_session import authorize_qt
from app.domain.telegram_listener import register_listener, get_channels
from app.domain import updater
from app.ui.telegram_mql_ui import MainController
from app.ui.config_windows_ui import ConfigWindow
from app.ui.update_dialog import (
    show_update_available_dialog,
    make_download_progress_dialog,
    show_update_failed_dialog,
)


api_id = int(constants.config["telegram"]["api_id"])
api_hash = constants.config["telegram"]["api_hash"]

logger = setup_logger(constants.LOG_FILE)

UPDATE_CHECK_INTERVAL_SECONDS = 60 * 60


class AppController(MainController):
    def __init__(self, ui_file):
        super().__init__(ui_file)

        # Client Telegram unique
        self.client = TelegramClient(constants.SESSION_PATH, api_id, api_hash)
        self.listener_task = None
        self.active_handler = None
        self.group_configs = {}
        self._update_check_running = False

        logger.info(f"Session path: {constants.SESSION_PATH}")

        # Boutons
        self.window.btnLoginQR.clicked.connect(
            lambda: asyncio.create_task(self.on_login_qr())
        )
        self.window.btnBackQR.clicked.connect(self.on_back_qr)
        self.window.btnConfigure.clicked.connect(self.open_config_window)
        self.window.btnNextFolder.clicked.connect(
            lambda: asyncio.create_task(self.on_next_folder())
        )

        # Callback sur Validate
        self.on_validate_callback = self.handle_validate
        self.window.btnConfigure.setEnabled(False)
        self.window.footerVersion.setText(f"2026 • v{constants.APP_VERSION}")

    async def load_existing_session(self) -> bool:
        if os.path.exists(constants.SESSION_PATH) and constants.MQL_DIR_PATH:
            await self.client.connect()
            if await self.client.is_user_authorized():
                await self.fill_groups()
                return True

            await self.client.disconnect()
        return False

    async def initialize_ui(self):
        self.window.stackedWidget.setCurrentWidget(self.window.page_loading)

        # Laisse le temps à l UI de s'afficher
        await asyncio.sleep(0.1)

        if constants.MQL_DIR_PATH:
            logger.info("MQL dir: {}".format(constants.MQL_DIR_PATH))
            authorized = await self.load_existing_session()

            if authorized:
                self.window.stackedWidget.setCurrentWidget(self.window.page_groups)
                self.window.footerLog.setText("Session restored")
                return

            # dossier OK mais pas de session
            self.window.stackedWidget.setCurrentWidget(self.window.page_phone)
            return

        # Aucun dossier selectionne
        self.window.stackedWidget.setCurrentWidget(self.window.page_select_folder)

    async def fill_groups(self):
        groups = await get_channels(self.client)
        self.window.listGroups.clear()
        for key, value in groups.items():
            item = QListWidgetItem(str(key))
            item.setData(Qt.UserRole, value)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.window.listGroups.addItem(item)

    async def on_login_qr(self):
        self.window.lineEditPhone.setVisible(False)
        self.window.btnSendCode.setVisible(False)
        self.window.btnLoginQR.setVisible(False)
        self.window.btnBackQR.setVisible(True)

        await self.client.connect()
        try:
            qr = await self.client.qr_login()
            await authorize_qt(self.client, self.window.qrCodeLabel, qr)
            self.window.footerLog.setText("QR code scanned successfully")
            self.window.stackedWidget.setCurrentWidget(self.window.page_groups)
            self.window.footerLog.setText("")
            await self.fill_groups()

        except asyncio.TimeoutError:
            logger.info("⏰ QR code expired")
            self.window.footerLog.setText("QR code expired")
            self.reset_login_ui()
        except asyncio.CancelledError:
            self.window.footerLog.setText("QR login cancelled ")
            logger.info("QR login cancelled")
            self.reset_login_ui()

    async def handle_validate(self, group_configs: dict):
        if not group_configs:
            return

        if self.active_handler:
            self.client.remove_event_handler(self.active_handler)
            self.active_handler = None

        names = ", ".join(group_configs.values())
        logger.info(f"Selected groups: {names}")
        self.window.footerLog.setText(f"Listening: {names}")

        self.window.labelStatus.setText("<b>Status:</b> Listening")
        self.window.labelStatus.setVisible(True)

        int_configs = {int(gid): gname for gid, gname in group_configs.items()}
        self.active_handler = register_listener(self.client, int_configs, self.logger_widget)

    async def on_next_folder(self):
        with open(constants.SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        constants.MQL_DIR_PATH = data.get("MQL_DIR_PATH")
        authorized = await self.load_existing_session()
        if authorized:
            self.window.stackedWidget.setCurrentWidget(self.window.page_groups)
            self.window.footerLog.setText("Session restored")
        else:
            self.window.stackedWidget.setCurrentWidget(self.window.page_phone)

    def open_config_window(self):
        groups = []
        for i in range(self.window.listGroups.count()):
            item = self.window.listGroups.item(i)
            if item.checkState() == Qt.Checked:
                groups.append(item.text())

        if not groups:
            logger.info("No group selected")
            return

        config_window = ConfigWindow(groups, self.window)
        config_window.exec()

    def on_back_qr(self):
        self.reset_login_ui()

    def reset_login_ui(self):
        """Réinitialise les éléments de la page login"""
        self.window.lineEditPhone.setVisible(True)
        self.window.btnSendCode.setVisible(True)
        self.window.btnLoginQR.setVisible(True)
        self.window.btnBackQR.setVisible(False)
        self.window.qrCodeLabel.clear()
        self.window.stackedWidget.setCurrentWidget(self.window.page_phone)

    def logger_widget(self, msg):
        self.window.footerLog.setText(msg)

    async def periodic_update_check(self):
        """Check for updates every hour (the startup check is done separately)."""
        while True:
            await asyncio.sleep(UPDATE_CHECK_INTERVAL_SECONDS)
            await self.check_for_updates()

    async def check_for_updates(self):
        # Avoid stacking popups if a check is already in progress
        if self._update_check_running:
            return
        self._update_check_running = True
        try:
            await self._check_for_updates()
        finally:
            self._update_check_running = False

    async def _check_for_updates(self):
        loop = asyncio.get_event_loop()
        try:
            update_info = await loop.run_in_executor(None, updater.check_for_update)
        except Exception as exc:
            logger.warning(f"Update check error: {exc}")
            return

        if not update_info:
            return

        accepted = await show_update_available_dialog(
            self.window, constants.APP_VERSION, update_info.version, update_info.notes
        )
        if not accepted:
            return

        progress = make_download_progress_dialog(self.window)
        progress.show()
        try:
            new_exe_path = await loop.run_in_executor(
                None, updater.download_update, update_info.download_url
            )
        except Exception as exc:
            progress.close()
            logger.warning(f"Update download failed: {exc}")
            show_update_failed_dialog(self.window, str(exc))
            return

        progress.close()
        install_target = sys.executable if getattr(sys, "frozen", False) else None
        updater.launch_downloaded_exe(new_exe_path, install_target=install_target)
        QApplication.quit()


def main():
    app = QApplication(sys.argv)

    if os.path.exists(constants.CSS_FILE):
        with open(constants.CSS_FILE, "r") as f:
            app.setStyleSheet(f.read())

    # Boucle qasync
    loop = qasync.QEventLoop(app)
    import asyncio
    asyncio.set_event_loop(loop)

    controller = AppController(constants.MAIN_UI_FILE)
    controller.show()

    # Charger session existante
    # loop.create_task(controller.load_existing_session())
    loop.create_task(controller.initialize_ui())
    loop.create_task(controller.check_for_updates())
    loop.create_task(controller.periodic_update_check())

    install_target = updater.get_pending_install_target(sys.argv)
    if install_target:
        loop.run_in_executor(None, updater.install_self_over, install_target)

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
