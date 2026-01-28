# -*- coding: utf-8 -*-
import asyncio
import json
import time
from typing import Optional

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register

_GLOBAL_MONITOR_TASK: Optional[asyncio.Task] = None
_GLOBAL_MONITOR_OWNER = None


class ElectricityClient:
    def __init__(
        self,
        config: AstrBotConfig,
        token: Optional[str],
        account: Optional[str],
        password: Optional[str],
    ):
        self._config = config
        self.token = token
        self.account = account
        self.password = password
        self._session: Optional[aiohttp.ClientSession] = None
        self._balance_url = "https://wpp.nnnu.edu.cn/Home/GetUserBindDevices"
        self._login_url = "https://wpp.nnnu.edu.cn/Login/LoginJson"

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def login_and_get_token(self) -> str:
        if not self.account or not self.password:
            raise RuntimeError("missing account/password for token refresh")

        session = await self._ensure_session()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "x-requested-with": "XMLHttpRequest",
            "origin": "https://wpp.nnnu.edu.cn",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "referer": "https://wpp.nnnu.edu.cn/Login/Login",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        data = {"account": self.account, "password": self.password}

        async with session.post(self._login_url, headers=headers, data=data) as resp:
            resp.raise_for_status()
            result = await resp.json(content_type=None)
            if result.get("Tag") != 1:
                raise RuntimeError(
                    f"login failed: {result.get('Message', 'unknown error')}"
                )

            token_cookie = resp.cookies.get("AppUserToken")
            if not token_cookie:
                raise RuntimeError("login succeeded but token missing")

            self.token = token_cookie.value
            self._config["electricity_token"] = self.token
            self._config.save_config()
            return self.token

    async def get_balance(self, auto_retry: bool = True) -> dict:
        try:
            logger.info("electricity_api: get_balance called")
            if auto_retry and not self.token and self.account and self.password:
                await self.login_and_get_token()
            data = await self._request_balance()
            return self._parse_balance(data)
        except Exception as exc:
            if (
                auto_retry
                and self.account
                and self.password
                and _looks_like_login_expired(str(exc))
            ):
                await self.login_and_get_token()
                data = await self._request_balance()
                return self._parse_balance(data)
            raise

    async def _request_balance(self) -> dict:
        if not self.token:
            raise RuntimeError("missing electricity_token")

        session = await self._ensure_session()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "x-requested-with": "XMLHttpRequest",
            "origin": "https://wpp.nnnu.edu.cn",
            "referer": "https://wpp.nnnu.edu.cn/Home/Index",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cookie": f"AppUserToken={self.token}",
        }

        async with session.post(self._balance_url, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    @staticmethod
    def _parse_balance(data: dict) -> dict:
        if data.get("Tag") != 1:
            raise RuntimeError(f"api error: {data.get('Message')}")

        devices_list = data.get("Data", {}).get("DevicesList", [])
        room_name = data.get("Data", {}).get("RoomName", "unknown")
        if not devices_list:
            raise RuntimeError("no bound devices found")

        for device in devices_list:
            if device.get("DeviceType") == 1:
                return {
                    "room_name": room_name,
                    "device_name": device.get("DeviceName"),
                    "balance": device.get("DeviceBalance"),
                    "price": device.get("DevicePrice"),
                    "update_time": device.get("UpdateTime"),
                    "is_online": device.get("IsOnline") == 1,
                    "switch_status": device.get("SwitchStatus") == 1,
                }

        raise RuntimeError("no electricity meter device found")


def _looks_like_login_expired(message: str) -> bool:
    keywords = [
        "登录过期",
        "登录已过期",
        "请登录",
        "请先登录",
        "未登录",
        "账号过期",
        "token过期",
        "Token过期",
    ]
    return any(keyword in message for keyword in keywords)


def _normalize_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return parsed
        if value.strip():
            return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _dedupe_list(items: list) -> list:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _to_cq_card(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return text
    title = lines[0]
    desc = "\n".join(lines[1:])
    payload = {
        "app": "com.tencent.miniapp",
        "desc": "",
        "view": "notification",
        "ver": "1.0.0.0",
        "prompt": title,
        "meta": {
            "notification": {
                "appInfo": {"appName": "电费监控", "appType": 4},
                "title": title,
                "desc": desc,
            }
        },
        "config": {"forward": 1},
    }
    data = json.dumps(payload, ensure_ascii=False)
    data = (
        data.replace("&", "&amp;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace(",", "&#44;")
    )
    return f"[CQ:json,data={data}]"


@register(
    "astrbot_plugin_electricity_monitor",
    "Tom?",
    "electricity balance monitor with optional auto checks",
    "1.1.0",
)
class ElectricityMonitorPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._monitor_task: Optional[asyncio.Task] = None
        self._stopped = False

        global _GLOBAL_MONITOR_TASK, _GLOBAL_MONITOR_OWNER
        if _GLOBAL_MONITOR_TASK and not _GLOBAL_MONITOR_TASK.done():
            if _GLOBAL_MONITOR_OWNER:
                _GLOBAL_MONITOR_OWNER._stopped = True
            _GLOBAL_MONITOR_TASK.cancel()

        self._client = ElectricityClient(
            config,
            token=self._get_config("electricity_token"),
            account=self._get_config("electricity_account"),
            password=self._get_config("electricity_password"),
        )

        if self._get_config("auto_check", True):
            self._ensure_monitor_task()

    def _get_config(self, key: str, default=None):
        value = self.config.get(key)
        if value is None:
            return default
        return value

    def _get_notify_origins(self) -> list:
        return _normalize_list(self.config.get("notify_origins"))

    def _set_notify_origins(self, origins: list) -> None:
        self.config["notify_origins"] = _dedupe_list(origins)
        self.config.save_config()

    def _ensure_monitor_task(self) -> None:
        if self._monitor_task and not self._monitor_task.done():
            return
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        global _GLOBAL_MONITOR_TASK, _GLOBAL_MONITOR_OWNER
        _GLOBAL_MONITOR_TASK = self._monitor_task
        _GLOBAL_MONITOR_OWNER = self

    def _restart_monitor_task(self) -> None:
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        self._monitor_task = None
        self._stopped = False
        self._ensure_monitor_task()

    async def on_unload(self):
        self._stopped = True
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        global _GLOBAL_MONITOR_TASK, _GLOBAL_MONITOR_OWNER
        if _GLOBAL_MONITOR_TASK is self._monitor_task:
            _GLOBAL_MONITOR_TASK = None
            _GLOBAL_MONITOR_OWNER = None

    async def _monitor_loop(self) -> None:
        while not self._stopped:
            interval_minutes = self._get_config("check_interval_minutes", 60)
            try:
                interval_minutes = max(1, int(interval_minutes))
            except (TypeError, ValueError):
                interval_minutes = 60
            interval_seconds = interval_minutes * 60
            last_check_ts = self._get_config("last_check_ts")
            now = time.time()
            if last_check_ts is not None:
                last_check_ts = float(last_check_ts)
                if now >= last_check_ts:
                    elapsed = now - last_check_ts
                    if elapsed < interval_seconds:
                        await asyncio.sleep(interval_seconds - elapsed)
                        continue
                else:
                    self.config["last_check_ts"] = None
                    self.config.save_config()

            if self._get_config("auto_check", True):
                origins = self._get_notify_origins()
                if origins:
                    try:
                        info = await self._client.get_balance(
                            auto_retry=self._get_config("auto_refresh_token", True)
                        )
                        balance = float(info.get("balance", 0))
                        threshold = float(self._get_config("threshold", 30.0))
                        last_balance = self._get_config("last_balance")
                        if balance < threshold:
                            message = self._format_low_balance_message(
                                balance, info.get("update_time")
                            )
                            await self._send_to_origins(origins, message, use_card=True)
                        if last_balance is not None and balance > float(last_balance):
                            message = self._format_recharge_message(
                                balance, float(last_balance), info.get("update_time")
                            )
                            await self._send_to_origins(origins, message, use_card=True)
                        self.config["last_balance"] = balance
                        self.config["last_check_ts"] = now
                        self.config.save_config()
                    except Exception as exc:
                        logger.error(f"electricity auto check failed: {exc}")
                        await self._send_to_origins(
                            origins,
                            f"电费自动检查失败: {exc}",
                        )

            await asyncio.sleep(interval_minutes * 60)

    async def _send_to_origins(
        self, origins: list, text: str, use_card: bool = False
    ) -> None:
        for origin in origins:
            try:
                payload = (
                    _to_cq_card(text)
                    if use_card and self._get_config("use_onebot11_card", True)
                    else text
                )
                chain = MessageChain().message(payload)
                await self.context.send_message(origin, chain)
            except Exception as exc:
                logger.warning(f"failed to notify {origin}: {exc}")

    def _format_balance_message(self, info: dict) -> str:
        return (
            "🔍 电费查询结果\n"
            f"🏠 房间: {info.get('room_name')}\n"
            f"💰 余额: {info.get('balance')} 元\n"
            f"⚡ 电价: {info.get('price')} 元/度\n"
            f"📶 在线: {'是' if info.get('is_online') else '否'}\n"
            f"🕒 更新时间: {info.get('update_time')}"
        )

    def _format_low_balance_message(self, balance: float, update_time: str) -> str:
        threshold = self._get_config("threshold", 30.0)
        return (
            "⚠️ 电费不足提醒\n"
            f"💰 当前余额: {balance} 元\n"
            f"📉 阈值: {threshold} 元\n"
            f"🕒 更新时间: {update_time}"
        )

    def _format_recharge_message(
        self, balance: float, last_balance: float, update_time: str
    ) -> str:
        delta = balance - last_balance
        interval_minutes = self._get_config("check_interval_minutes", 60)
        return (
            f"🔔【{interval_minutes}分钟内】有人充值了电费哦\n"
            f"💰 当前余额: {balance} 元\n"
            f"➕ 本次增加: {delta:.2f} 元\n"
            f"🕒 更新时间: {update_time}"
        )

    @filter.command("电费", alias={"电费查询"})
    async def query_balance(self, event: AstrMessageEvent):
        try:
            info = await self._client.get_balance(
                auto_retry=self._get_config("auto_refresh_token", True)
            )
            yield event.plain_result(self._format_balance_message(info))
        except Exception as exc:
            yield event.plain_result(f"⚠️ 电费查询失败: {exc}")

    @filter.command("电费订阅")
    async def subscribe(self, event: AstrMessageEvent):
        origin = event.unified_msg_origin
        origins = self._get_notify_origins()
        if origin in origins:
            yield event.plain_result("✅ 当前会话已订阅电费提醒。")
            return
        origins.append(origin)
        self._set_notify_origins(origins)
        yield event.plain_result("✅ 已订阅电费提醒。")

    @filter.command("电费退订")
    async def unsubscribe(self, event: AstrMessageEvent):
        origin = event.unified_msg_origin
        origins = self._get_notify_origins()
        if origin not in origins:
            yield event.plain_result("ℹ️ 当前会话未订阅电费提醒。")
            return
        origins.remove(origin)
        self._set_notify_origins(origins)
        yield event.plain_result("✅ 已退订电费提醒。")

    @filter.command("电费状态")
    async def status(self, event: AstrMessageEvent):
        interval_minutes = self._get_config("check_interval_minutes", 60)
        threshold = self._get_config("threshold", 30.0)
        auto_check = self._get_config("auto_check", True)
        origins = self._get_notify_origins()
        yield event.plain_result(
            "📊 电费监控状态\n"
            f"✅ 自动检查: {'开启' if auto_check else '关闭'}\n"
            f"⏱️ 检查间隔: {interval_minutes} 分钟\n"
            f"📉 阈值: {threshold} 元\n"
            f"👥 订阅会话数: {len(origins)}"
        )

    @filter.command("电费阈值")
    async def set_threshold(self, event: AstrMessageEvent, threshold: float):
        if threshold <= 0:
            yield event.plain_result("⚠️ 阈值必须大于 0。")
            return
        self.config["threshold"] = float(threshold)
        self.config.save_config()
        yield event.plain_result(f"✅ 已更新阈值为 {threshold} 元。")

    @filter.command("电费间隔")
    async def set_interval(self, event: AstrMessageEvent, minutes: int):
        if minutes < 1:
            yield event.plain_result("⚠️ 间隔必须大于等于 1 分钟。")
            return
        self.config["check_interval_minutes"] = int(minutes)
        self.config["last_check_ts"] = None
        self.config.save_config()
        if self._get_config("auto_check", True):
            self._restart_monitor_task()
        yield event.plain_result(f"✅ 已更新检查间隔为 {minutes} 分钟。")

    @filter.command("电费监控开")
    async def enable_monitor(self, event: AstrMessageEvent):
        self.config["auto_check"] = True
        self.config.save_config()
        self._ensure_monitor_task()
        yield event.plain_result("✅ 已开启电费自动检查。")

    @filter.command("电费监控关")
    async def disable_monitor(self, event: AstrMessageEvent):
        self.config["auto_check"] = False
        self.config.save_config()
        yield event.plain_result("✅ 已关闭电费自动检查。")

    @filter.command("电费立即检查")
    async def run_check_now(self, event: AstrMessageEvent):
        try:
            info = await self._client.get_balance(
                auto_retry=self._get_config("auto_refresh_token", True)
            )
            balance = float(info.get("balance", 0))
            threshold = float(self._get_config("threshold", 30.0))
            if balance < threshold:
                yield event.plain_result(
                    self._format_low_balance_message(
                        balance, info.get("update_time")
                    )
                )
            else:
                yield event.plain_result(self._format_balance_message(info))
        except Exception as exc:
            yield event.plain_result(f"⚠️ 电费检查失败: {exc}")

    @filter.command("电费帮助")
    async def help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "可用命令:\n"
            "电费 / 电费查询\n"
            "电费订阅 / 电费退订\n"
            "电费状态\n"
            "电费阈值 <数值>\n"
            "电费间隔 <分钟>\n"
            "电费监控开 / 电费监控关\n"
            "电费立即检查"
        )

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        if text.startswith("电费间隔"):
            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                async for result in self.set_interval(event, int(parts[1])):
                    yield result
            else:
                yield event.plain_result("用法: 电费间隔 <分钟>")
            event.stop_event()
            return
        if text.startswith("电费阈值"):
            parts = text.split()
            if len(parts) >= 2:
                try:
                    value = float(parts[1])
                except ValueError:
                    yield event.plain_result("用法: 电费阈值 <数值>")
                else:
                    async for result in self.set_threshold(event, value):
                        yield result
            else:
                yield event.plain_result("用法: 电费阈值 <数值>")
            event.stop_event()
            return
        if text in ("电费", "电费查询"):
            async for result in self.query_balance(event):
                yield result
            event.stop_event()
            return
        if text == "电费订阅":
            async for result in self.subscribe(event):
                yield result
            event.stop_event()
            return
        if text == "电费退订":
            async for result in self.unsubscribe(event):
                yield result
            event.stop_event()
            return
        if text == "电费状态":
            async for result in self.status(event):
                yield result
            event.stop_event()
            return
        if text == "电费监控开":
            async for result in self.enable_monitor(event):
                yield result
            event.stop_event()
            return
        if text == "电费监控关":
            async for result in self.disable_monitor(event):
                yield result
            event.stop_event()
            return
        if text == "电费立即检查":
            async for result in self.run_check_now(event):
                yield result
            event.stop_event()
            return
        if text == "电费帮助":
            async for result in self.help(event):
                yield result
            event.stop_event()
            return

    async def terminate(self):
        await self.on_unload()
        await self._client.close()
