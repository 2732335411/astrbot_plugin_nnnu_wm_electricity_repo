# 南宁师范大学-武鸣校区电费提醒插件（AstrBot）
这是 AstrBot 插件。

## 功能简介
- 电费余额查询（南宁师范大学-武鸣校区）
- 电费低于阈值自动提醒
- 余额增加（充值）提醒
- 支持订阅/退订提醒会话
- 支持账号密码自动刷新 AppUserToken（可选）

## 安装与加载
0. 插件市场可直接安装
1. 将 `astrbot_plugin_electricity_monitor` 复制到 AstrBot 的 `data/plugins/` 目录
2. 在插件管理中启用并重载
3. 安装依赖：`aiohttp`

## 配置说明
可在插件配置中填写，参考 `config.example.json` 或 `_conf_schema.json`。

关键字段：
- `electricity_token`：电费查询 AppUserToken（可选，账号密码可自动获取）
- `electricity_account` / `electricity_password`：账号密码，用于自动刷新 Token（可选）
- `threshold`：低电费阈值（默认 30.0）
- `check_interval_minutes`：自动检查间隔（分钟）
- `auto_check`：是否开启自动检查
- `auto_refresh_token`：Token 过期时是否自动刷新
- `last_balance`：上次电费余额（内部使用）
- `last_check_ts`：上次自动检查时间戳（内部使用）
- `use_onebot11_card`：QQ OneBot11 卡片消息（已废弃，仅保留兼容）

## 指令列表
- `电费` / `电费查询`
- `电费订阅` / `电费退订`
- `电费状态`
- `电费阈值 <数值>`
- `电费间隔 <分钟>`
- `电费监控开` / `电费监控关`
- `电费立即检查`
- `电费帮助`

## 使用方法
1. 配置 `electricity_token` 或填写 `electricity_account`/`electricity_password`
2. 在目标群或私聊中发送 `电费订阅`
3. 使用 `电费` 验证是否正常查询
4. 按需调整 `电费阈值` 与 `电费间隔`

## 说明
- 自动提醒会对已订阅的会话生效
- 若余额增加，会推送“电费充值提醒”
- 首次启动后建议手动执行一次 `电费` 验证配置
- 若使用 OneBot11，可开启卡片消息展示提醒（已废弃）

## 免责声明
本插件仅供学习与交流使用，使用过程中产生的风险由使用者自行承担。
如有侵权或不当使用，请联系并下架，邮箱：2732335411@qq.com。
