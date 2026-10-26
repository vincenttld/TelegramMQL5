# TelegramMQL5

TelegramMQL5 is a Python project that listens to a Telegram group, parses trading signals, and saves them in JSON format for integration with MQL5 trading platforms. 

It supports **MessageFilter parsing**, **signal mapping**, and **secure login** via Telegram API with QR code or 2FA.

---

## Table of Contents

* [Features](#features)
* [Requirements](#requirements)
* [Installation](#installation)
* [Configuration](#configuration)
* [Usage](#usage)
  * [Running the main bot](#running-the-main-bot)
  * [Testing MessageFilter](#testing-messagefilter)
  * [Getting Private Group IDs](#getting-private-group-ids)
* [Project Structure](#project-structure)
* [Session Management](#session-management)
* [License](#license)

---

## Features

* Listen to a Telegram group for trading signals.
* Parse messages using `MessageFilter` and handle errors gracefully.
* Supports multi-line signals with emojis and multiple TP/SL values.
* Map user-friendly names (`GOLD`, `SILVER`) to actual trading symbols (`XAUUSD`, `XAGUSD`).
* Save signals in `signals.json` with timestamps and metadata.
* Easy testing modes via `test.py` (`MessageFilter`).

---

## Requirements

* Python 3.11+
* Packages:

```text
telethon
qrcode
python-dotenv
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Installation

1. Clone the repository:

```bash
git clone https://github.com/yourusername/TelegramMQL5.git
cd TelegramMQL5
```

2. Create a virtual environment (optional but recommended):

```bash
python -m venv venv
venv\Scripts\activate     # Windows
```

3. Install requirements:

```bash
pip install -r requirements.txt
```

---

## Configuration

2. Fill in your Telegram API credentials, session name, and trading pairs to `app/config/config.ini`.

**Example `config.ini`**:

```ini
[telegram]
api_id = 123456
api_hash = abcdef1234567890
phone = +33123456789
session_name = telegram_session
group_name = MyTradingGroup

[paths]
mql_file_dir = C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\...\MQL5\Files

[trading]
pairs = XAUUSD, EURUSD, SILVER, BTCUSD

[pair_mapping]
GOLD = XAUUSD
SILVER = XAGUSD
ETH = ETHUSD

[mql]
default_lot = 0.01
comment = TelegramSignal
```

---

## Usage

### Running the main bot

```bash
python -m app.main
```

* Automatically checks for an existing session.
* Uses **QR code** or **2FA** login if the session doesn’t exist.
* Starts listening to the Telegram group and logs signals.

---

### Testing MessageFilter

```bash
python -m app.test
```

* Allows you to paste **any Telegram message** manually.
* Multi-line messages with emojis are supported.
* Shows parsing results interactively.

**Example message to test:**

```
Buy : XAUUSD
🎯 Entry : 4822
⛔️ Stop : 4812,62
🚀 TP 1 : 4842,6
🚀 TP 2 : 4962,62
🚀 TP 3 : 4852,62
```

* Paste this message in the terminal after running the test.
* Finish by entering an **empty line** to start parsing.
* The `MessageFilter` will parse the direction, entry price, stop loss, and all TP values.

**Expected behavior:**

* Signal is displayed in the console as a structured object or dictionary.
* Any parsing errors are logged using `FailedParseMessage`.

---
### Getting Private Group IDs

Sometimes you need the ID of private groups to configure your bot. 
Telegram private groups cannot be accessed by name, only by their ID.

```bash
python -m app.get_id_channels
>>
  Telegram 777000
  MyRobotTrading 6774403370
```

The script will list all groups you belong to, including private groups.

Use the ID (usually starts with -100...) in your main bot configuration instead of the name.

This allows Telethon to listen to private groups safely, avoiding ValueError: Cannot find any entity.

💡 **Tip:** You can replace in your `config/config.ini` file

---

## Project Structure

```
TelegramMQL5/
├── app/
│   ├── __init__.py
│   ├── main.py                 # Main bot script
│   ├── test.py                 # Manual testing script
│   ├── config/
│   │   ├── config.ini        # User configuration
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── message_filter.py   # Message parsing logic
│   │   ├── exceptions.py       # Custom exceptions
│   │   └── valid_session.py    # QR code / 2FA login
├── logs/
│   └── telegram_log.txt        # Message log file
└── requirements.txt
```

---

## Session Management

* Session files are saved as `session_name.session`.
* If a session exists, Telethon will **reuse it automatically**.
* To force a new login, delete the session file:

```bash
del telegram_session.session # Windows
```

* QR code login is displayed in the terminal if the session is missing.
* 2FA login is prompted if the account has a password enabled.

---
## Compile

```bash
pyinstaller app/TelegramMQL.spec --clean --noconfirm
```

---
TODO:

---

## License

© 2026 Trolard Vincent – All rights reserved.
