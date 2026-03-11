# KOOK 自动发卡机器人

- English: [README.md](/README.md)
- 中文: `README.zh-CN.md`

## 项目简介

这是一个运行在 KOOK 平台上的自动发卡机器人，主要功能包括：

- 充值卡生成与充值
- 用户余额管理
- 商品与卡密库存管理
- 用户购买后自动发货
- 缺货订阅与补货提醒
- 退款与卡密作废流程
- `super_admin`、`admin`、`user` 三层权限控制
- 命令模块热加载
- 通过环境变量切换 `sqlite` 或 `mysql`

所有命令交互统一使用英文。

机器人回复文案支持 i18n，并通过外置语言文件管理。

管理员命令可以限制在指定 KOOK 频道执行，管理员操作日志也可以推送到指定频道。

## 权限角色

- `super_admin`
  - 通过 `KOOK_SUPER_ADMIN_IDS` 配置
  - 默认包含 `2744428583`
  - 可以授予其他用户 `admin` 角色
- `admin`
  - 可管理充值卡、商品和卡密
- `user`
  - 默认角色

## 命令列表

### 用户命令

- `/help`
- `/hello`
- `/balance`
- `/profile`
- `/recharge <card_code>`
- `/products`
- `/buy <product_id> [quantity]`
- `/subscribe <product_id>`
- `/unsubscribe <product_id>`
- `/myrole`

### 管理员命令

- `/gen_card <amount> <count>`
- `/export_cards [all]`
- `/export_keys <product_id|all>`
- `/del_card <card_code>`
- `/add_product "<name>" "<description>"`
- `/add_key <product_id> <price> "<key_content>"`
- `/add_keys <product_id> <price> "<key1\nkey2\nkey3>"`
- `/import_file <product_id> <price> [attachment|web]`
- `/cancel_import`
- `/refund <user_id> "<key_content>"`

### 超级管理员命令

- `/addadmin <user_id>`

## 热加载

`src/kook_bot/command_modules/` 目录下的命令模块支持热加载。

也就是说：

- 新增一个命令模块文件
- 修改已有命令模块
- 保存文件

机器人会在下一次收到消息时自动重新加载命令定义。

## 数据库

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

机器人启动时会自动创建所需数据表。

## 库存热更新

商品列表、库存、余额、充值卡和购买流程都直接读取数据库。

这意味着：

- 通过命令新增或修改数据后会立即生效
- 手动修改 sqlite/mysql 数据也会立即生效
- 库存相关数据变化不需要重启机器人

## 环境变量示例

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
KOOK_LOG_IMPORTS=false
KOOK_IMPORT_WEB_ENABLED=false
KOOK_IMPORT_WEB_HOST=127.0.0.1
KOOK_IMPORT_WEB_PORT=18080
KOOK_IMPORT_WEB_BASE_URL=http://127.0.0.1:18080
KOOK_IMPORT_WEB_TTL_SECONDS=600
KOOK_LOG_TO_FILE=true
KOOK_LOG_DIR=logs
KOOK_LOG_FILE=kook-bot.log
KOOK_LOG_MAX_BYTES=5242880
KOOK_LOG_BACKUP_COUNT=7
```

## 安装依赖

```powershell
py -m pip install -r requirements.txt
```

## 语言文件

默认语言文件位于 `locales/` 目录：

- `locales/en-US.json`
- `locales/zh-CN.json`

可以通过以下环境变量切换语言：

```env
KOOK_LOCALE=en-US
KOOK_LOCALE_DIR=locales
```

如果要新增语言，直接增加一个 JSON 文件即可，例如 `locales/ja-JP.json`。

翻译器会直接读取它，不需要改 Python 代码。
语言文件修改后，会在下一次回复时自动生效。

## 管理员频道与日志频道

你可以限制管理员命令只能在特定频道执行，并把管理员操作日志推送到指定频道：

```env
KOOK_ADMIN_COMMAND_CHANNEL_ID=4760888878941680
KOOK_LOG_CHANNEL_ID=4760888878941680
```

默认行为：

- 需要 `admin` 或 `super_admin` 权限的命令只能在 `KOOK_ADMIN_COMMAND_CHANNEL_ID` 执行
- 管理员命令成功、失败、以及在错误频道执行的情况，都会推送到 `KOOK_LOG_CHANNEL_ID`

## 导入模式

`/import_file <product_id> <price> [attachment|web]` 支持两种导入方案：

- `attachment`
  - 默认模式
  - 执行命令后，需要在 30 秒内于同一频道上传 `.txt` 或 `.csv` 文件
- `web`
  - 机器人会生成一次性上传页面
  - 上传链接和密码通过私信发送
  - 页面会在 `KOOK_IMPORT_WEB_TTL_SECONDS` 后自动过期

如果要启用网页上传模式：

```env
KOOK_IMPORT_WEB_ENABLED=true
KOOK_IMPORT_WEB_HOST=0.0.0.0
KOOK_IMPORT_WEB_PORT=18080
KOOK_IMPORT_WEB_BASE_URL=https://your-domain.example.com:18080
KOOK_IMPORT_WEB_TTL_SECONDS=600
```

## 启动

```powershell
py main.py
```

## 导入调试

如果文件上传成功但导入没有开始，可以打开导入链路日志：

```env
KOOK_LOG_LEVEL=INFO
KOOK_LOG_IMPORTS=true
KOOK_LOG_TO_FILE=true
```

然后查看 `logs/kook-bot.log`，重点看这些阶段：

- 待上传会话是否创建成功
- 附件是否匹配到
- 下载是否成功
- 解码后行数是否正确
- 数据库导入结果或拒绝原因
