# KOOK Auto-delivery Bot

## Overview

This project is a KOOK bot for:

- recharge card generation and redemption
- balance management
- product and key inventory management
- automatic key delivery after purchase
- permission control with `super_admin`, `admin`, and `user`
- hot reload for command modules
- sqlite or mysql backend switch by environment variables

All command interaction is in English.

Reply messages support i18n through external locale files.

Admin commands can be restricted to a specific KOOK channel, and admin operation logs can be pushed to a specific KOOK channel.

## Roles

- `super_admin`
  - configured by `KOOK_SUPER_ADMIN_IDS`
  - default includes `2744428583`
  - can grant admin role
- `admin`
  - can manage recharge cards, products, and keys
- `user`
  - default role

## Commands

### User commands

- `/help`
- `/hello`
- `/balance`
- `/profile`
- `/recharge <card_code>`
- `/products`
- `/buy <product_id> [quantity]`
- `/myrole`

### Admin commands

- `/gen_card <amount> <count>`
- `/export_cards [all]`
- `/export_keys <product_id|all>`
- `/del_card <card_code>`
- `/add_product "<name>" "<description>"`
- `/add_key <product_id> <price> "<key_content>"`
- `/add_keys <product_id> <price> "<key1\nkey2\nkey3>"`
- `/import_file <product_id> <price>` with a `.txt` or `.csv` attachment

### Super admin commands

- `/addadmin <user_id>`

## Hot reload

Command modules under `src/kook_bot/command_modules/` are hot reloaded.

That means:

- add a new command module file
- modify an existing command module
- save the file

The bot will reload command definitions automatically on the next message event.

## Database

### SQLite

```env
KOOK_DB_BACKEND=sqlite
KOOK_SQLITE_PATH=data/kook-bot.db
```

### MySQL

```env
KOOK_DB_BACKEND=mysql
KOOK_MYSQL_HOST=127.0.0.1
KOOK_MYSQL_PORT=3306
KOOK_MYSQL_USER=root
KOOK_MYSQL_PASSWORD=
KOOK_MYSQL_DATABASE=kook_bot
```

The bot will auto-create the database tables on startup.

## Inventory hot update

Product list, stock, balance, recharge cards, and purchase flow all read from the database directly.

That means:

- commands that add or update data take effect immediately
- manual sqlite/mysql updates also take effect immediately
- no bot restart is required for inventory data changes

## Environment example

```env
KOOK_BOT_TOKEN=Bot your-token-here
KOOK_COMMAND_PREFIX=/
KOOK_LOCALE=en-US
KOOK_LOCALE_DIR=locales
KOOK_ADMIN_COMMAND_CHANNEL_ID=4760888878941680
KOOK_LOG_CHANNEL_ID=4760888878941680
KOOK_SUPER_ADMIN_IDS=2744428583

KOOK_DB_BACKEND=sqlite
KOOK_SQLITE_PATH=data/kook-bot.db
KOOK_MYSQL_HOST=127.0.0.1
KOOK_MYSQL_PORT=3306
KOOK_MYSQL_USER=root
KOOK_MYSQL_PASSWORD=
KOOK_MYSQL_DATABASE=kook_bot

KOOK_LOG_LEVEL=INFO
KOOK_LOG_HTTP=false
KOOK_LOG_EVENTS=false
KOOK_LOG_COMMANDS=false
KOOK_LOG_COMMAND_STATUS=false
KOOK_LOG_TO_FILE=true
KOOK_LOG_DIR=logs
KOOK_LOG_FILE=kook-bot.log
KOOK_LOG_MAX_BYTES=5242880
KOOK_LOG_BACKUP_COUNT=7
```

## Install

```powershell
py -m pip install -r requirements.txt
```

## Locale files

Default locale files are stored under `locales/`:

- `locales/en-US.json`
- `locales/zh-CN.json`

You can switch locale with:

```env
KOOK_LOCALE=en-US
KOOK_LOCALE_DIR=locales
```

To add a new language, create another JSON file such as `locales/ja-JP.json`.
The translator will read it directly without changing Python code.
Changes to locale JSON files take effect on the next translated reply.

## Admin channel and log channel

You can restrict admin commands to a specific channel and push admin command logs to a specific channel:

```env
KOOK_ADMIN_COMMAND_CHANNEL_ID=4760888878941680
KOOK_LOG_CHANNEL_ID=4760888878941680
```

Default behavior:

- commands requiring `admin` or `super_admin` can only be used in `KOOK_ADMIN_COMMAND_CHANNEL_ID`
- admin command success, failure, and rejected channel attempts are pushed to `KOOK_LOG_CHANNEL_ID`

## Run

```powershell
py main.py
```
