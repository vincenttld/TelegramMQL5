#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from urllib import parse, request

from app import constants

# Telegram limite un message a 4096 caracteres
MAX_LEN = 4000


def is_configured():
    return bool(constants.TELEGRAM_LOG_BOT_TOKEN and constants.TELEGRAM_LOG_CHAT_ID)


def send_text(text):
    """Send text to the log chat via the Telegram Bot API (blocking).
    Long texts are split in several messages. Returns True on success."""
    logger = logging.getLogger()
    if not is_configured():
        logger.warning("TELEGRAM_LOG_BOT_TOKEN / TELEGRAM_LOG_CHAT_ID missing in .env.")
        return False

    url = "https://api.telegram.org/bot{}/sendMessage".format(
        constants.TELEGRAM_LOG_BOT_TOKEN
    )
    chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]
    try:
        for idx, chunk in enumerate(chunks, 1):
            prefix = "[{}/{}]\n".format(idx, len(chunks)) if len(chunks) > 1 else ""
            query = parse.urlencode({
                "chat_id": constants.TELEGRAM_LOG_CHAT_ID,
                "text": prefix + chunk,
            })
            req = request.Request(url, data=query.encode("utf-8"))
            with request.urlopen(req, timeout=20) as resp:
                resp.read()
        return True
    except Exception as exc:
        logger.error("Failed to send message to Telegram: %s", exc)
        return False
