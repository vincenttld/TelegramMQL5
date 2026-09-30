#!/usr/bin/env python
# -*- coding: utf-8 -*-
# support : Trolard Vincent
# copyright : vincenttld

import os
import json
import asyncio
from datetime import datetime
from telethon import TelegramClient, events

from app import constants
from app.domain.logging import setup_logger
from app.domain.exceptions import FailedParseMessage
from app.domain.message_filter import MessageFilter
from app.domain import telegram_notify
from app.domain.model.order_model import OrderModel

client_lock = asyncio.Lock()


def get_regex_values():
    if not os.path.exists(constants.JSON_DATA_FILE):
        return
    with open(constants.JSON_DATA_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
    return data


async def get_channels(client):
    channels = {}
    async for dialog in client.iter_dialogs():
        channels[dialog.name] = dialog.id
    return {k: channels[k] for k in sorted(channels.keys())}

logger = setup_logger(log_file=constants.LOG_FILE)


def register_listener(client: TelegramClient, group_configs: dict, post_action=False):
    """
    Register a NewMessage handler for the given groups.
    Returns the handler so it can be removed later with client.remove_event_handler(handler).
    group_configs: dict mapping group_id (int) -> group_name (str)
    """
    chat_ids = list(group_configs.keys())

    @client.on(events.NewMessage(chats=chat_ids))
    async def handler(event):
        if not event.message.text:
            return

        group_name = group_configs.get(event.chat_id, str(event.chat_id))

        logger.info(
            "New message | group=%s | sender=%s | text=%s",
            group_name,
            event.sender_id,
            event.message.text
        )

        data = get_regex_values()
        model = None
        # A config saved before a keyword field existed (e.g. "Close Trade
        # Keyword") has no entry for it: fall back to the default for every
        # key the saved config does not define. A key saved as an empty
        # string is kept empty — that is how a channel disables a keyword.
        group_data = (data.get(group_name) if data else None) or {}
        template = dict(constants.DEFAULT_FIELDS)
        template.update(group_data)
        MessageFilter.TEMPLATE_REGEX = template
        logger.info("Group name: %s" % group_name)
        logger.info(MessageFilter.TEMPLATE_REGEX)
        try:
            message = MessageFilter(event.message.text)
            logger.info(message.text)
            model = message.parse_signal()

            if model.is_close:
                logger.info("Close message parsed for %s", model.pair or "ALL positions")
            elif model.is_breakeven:
                logger.info("BreakEven message parsed for %s", model.pair or "ALL positions")
            else:
                if not model.order_type:
                    failed_error(post_action, event, "Order type missing")
                    return
                if not model.pair:
                    failed_error(post_action, event, "Pair is missing")
                    return
                if not model.price:
                    failed_error(post_action, event, "Price is missing")
                    return
                if not model.stop:
                    failed_error(post_action, event, "Stop-Loss is missing")
                    return
                if not model.profits:
                    failed_error(post_action, event, "Take-Profits is missing")
                    return

            logger.info("Message successfully parsed")
            logger.debug("Parsed model: %s", model)

        except Exception as e:
            failed_error(post_action, event, e)
            return

        if not model:
            logger.warning("Message not recognized (no signal detected)")
            return

        signal = model.to_dict()
        signal["date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        signal["channel_id"] = event.chat_id

        async with client_lock:
            if os.path.exists(constants.SIGNALS_FILENAME):
                try:
                    with open(constants.SIGNALS_FILENAME, "r", encoding="utf-8") as f:
                        signals = json.load(f)
                        if not isinstance(signals, list):
                            signals = []
                except json.JSONDecodeError:
                    logger.error("Invalid JSON in signals file, resetting")
                    signals = []
            else:
                signals = []

            signal["index"] = len(signals) + 1
            signals.append(signal)

            os.makedirs(os.path.dirname(constants.SIGNALS_FILENAME), exist_ok=True)
            with open(constants.SIGNALS_FILENAME, "w", encoding="utf-8") as f:
                json.dump(signals, f, indent=4)

        logger.info(
            "Signal saved | index=%s | file=%s",
            signal["index"],
            constants.SIGNALS_FILENAME
        )
        logger.info("Signal content: %s", json.dumps(signal, ensure_ascii=False))
        if telegram_notify.is_configured():
            # Envoi bloquant -> dans un thread pour ne pas bloquer la boucle asyncio
            await asyncio.to_thread(
                telegram_notify.send_text,
                format_signal_message(signal),
            )
        if post_action:
            post_action(
                f"Signal saved for Symbol={signal['symbol']}"
            )

    logger.info("Listening to groups: %s", list(group_configs.keys()))
    return handler


def format_signal_message(signal):
    """Signal #2 → Symbol=XAUUSD, Type=SELL, Entry=4210.00000000, SL=..., TPs=4207.0 4200.0 , Date: ..."""
    head = "Signal #{} → Symbol={}".format(signal["index"], signal.get("symbol") or "ALL")
    date = signal["date"]

    action = signal.get("action")
    if action != OrderModel.ACTION_OPEN:
        return "{}, Action={}, Date: {}".format(head, action.upper(), date)

    order_type = "BUY" if signal["type"] == OrderModel.ORDER_TYPE_BUY else "SELL"
    tps = "".join("{} ".format(tp) for tp in signal["tp"])
    return "{}, Type={}, Entry={:.8f}, SL={:.8f}, TPs={}, Date: {}".format(
        head, order_type, float(signal["entry"]), float(signal["sl"]), tps, date
    )


def failed_error(post_action, event, error):
    err = FailedParseMessage(event.message.text, error)
    logger.warning(
        "Message parsing failed | text=%s",
        event.message.text
    )
    logger.exception(err)
    if post_action:
        post_action(
            f"Message parsing failed.."
        )
