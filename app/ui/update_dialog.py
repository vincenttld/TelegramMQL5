#!/usr/bin/env python
"""Dialogs related to the automatic update flow.

All dialogs use QDialog.open() instead of exec() so they don't spin a nested
Qt event loop, which would otherwise freeze the qasync/asyncio loop running
the rest of the app.
"""
import asyncio

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog


async def show_update_available_dialog(
    parent, current_version: str, version: str, notes: str
) -> bool:
    """Shows the update announcement dialog, returns True if the user accepts."""
    box = QMessageBox(parent)
    box.setWindowTitle("Update available")
    box.setIcon(QMessageBox.Information)

    text = (
        f"Update available {current_version} to {version}\n"
        "Would you like to update ?"
    )
    if notes:
        text += f"\n\n{notes}"
    box.setText(text)

    update_btn = box.addButton("Yes", QMessageBox.AcceptRole)
    box.addButton("No", QMessageBox.RejectRole)

    future = asyncio.get_event_loop().create_future()

    def on_finished(_result):
        if not future.done():
            future.set_result(box.clickedButton() == update_btn)

    box.finished.connect(on_finished)
    box.open()

    return await future


def make_download_progress_dialog(parent) -> QProgressDialog:
    """Indeterminate progress dialog shown while the update is downloading."""
    dialog = QProgressDialog("Downloading update...", None, 0, 0, parent)
    dialog.setWindowTitle("Updating")
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setCancelButton(None)
    dialog.setMinimumDuration(0)
    return dialog


def show_update_failed_dialog(parent, error: str) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Update")
    box.setText(f"The update failed and will be skipped for this session.\n\n{error}")
    box.open()
