import asyncio
from typing import Any

import httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star


class GuangyaPushClient:
    def __init__(self, api_base: str, api_key: str):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key

    @property
    def headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/api/external/push/health", headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def lease(self, limit: int, retry_stale_minutes: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.api_base}/api/external/push/lease",
                headers=self.headers,
                params={"limit": limit, "retry_stale_minutes": retry_stale_minutes},
            )
            resp.raise_for_status()
            return resp.json()

    async def callback(
        self,
        resource_id: int,
        status: str,
        error_message: str | None = None,
        message_id: str | None = None,
        response_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.api_base}/api/external/push/callback",
                headers=self.headers,
                json={
                    "resource_id": resource_id,
                    "status": status,
                    "error_message": error_message,
                    "message_id": message_id,
                    "response_payload": response_payload,
                },
            )
            resp.raise_for_status()
            return resp.json()


class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        self._poll_task: asyncio.Task | None = None
        self._pushing = False
        self._start_poll_task()

    def _config_value(self, key: str, default: Any = None) -> Any:
        if hasattr(self.config, "get"):
            return self.config.get(key, default)
        return getattr(self.config, key, default)

    def _set_config_value(self, key: str, value: Any) -> None:
        try:
            self.config[key] = value
        except Exception:
            setattr(self.config, key, value)
        save_config = getattr(self.config, "save_config", None)
        if callable(save_config):
            save_config()

    def _client(self) -> GuangyaPushClient:
        api_base = str(self._config_value("api_base", "")).strip()
        api_key = str(self._config_value("api_key", "")).strip()
        if not api_base:
            raise RuntimeError("未配置 api_base")
        if not api_key:
            raise RuntimeError("未配置 api_key")
        return GuangyaPushClient(api_base, api_key)

    def _target_origin(self) -> str:
        return str(self._config_value("target_unified_msg_origin", "")).strip()

    def _send_mode(self) -> str:
        mode = str(self._config_value("send_mode", "telegram_api")).strip()
        return mode if mode in ("telegram_api", "astrbot") else "telegram_api"

    def _telegram_bot_token(self) -> str:
        return str(self._config_value("telegram_bot_token", "")).strip()

    def _telegram_chat_id(self) -> str:
        return str(self._config_value("telegram_chat_id", "")).strip()

    def _telegram_parse_mode(self) -> str:
        return str(self._config_value("telegram_parse_mode", "")).strip()

    def _batch_size(self) -> int:
        return max(1, min(int(self._config_value("batch_size", 5)), 100))

    def _poll_interval(self) -> int:
        return max(5, int(self._config_value("poll_interval_seconds", 30)))

    def _send_interval(self) -> float:
        return max(0, float(self._config_value("send_interval_seconds", 1.0)))

    def _lease_stale_minutes(self) -> int:
        return max(5, int(self._config_value("lease_stale_minutes", 30)))

    def _is_enabled(self) -> bool:
        return bool(self._config_value("enabled", True))

    def _start_poll_task(self) -> None:
        if self._poll_task and not self._poll_task.done():
            return
        try:
            self._poll_task = asyncio.create_task(self._poll_loop())
        except RuntimeError:
            logger.warning("光鸭推送插件暂未进入事件循环，稍后会通过命令触发轮询")

    async def _poll_loop(self) -> None:
        await asyncio.sleep(3)
        while True:
            try:
                if self._is_enabled() and self._can_send():
                    await self._push_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"光鸭资源自动推送失败: {exc}")
            await asyncio.sleep(self._poll_interval())

    def _can_send(self) -> bool:
        if self._send_mode() == "telegram_api":
            return bool(self._telegram_bot_token() and self._telegram_chat_id())
        return bool(self._target_origin())

    async def _send_text(self, text: str) -> Any:
        if self._send_mode() == "telegram_api":
            return await self._send_telegram_text(text)

        target = self._target_origin()
        if not target:
            raise RuntimeError("未绑定推送目标，请在目标会话发送 /gy_bind_push")
        chain = MessageChain().message(text)
        return await self.context.send_message(target, chain)

    async def _send_telegram_text(self, text: str) -> dict[str, Any]:
        token = self._telegram_bot_token()
        chat_id = self._telegram_chat_id()
        if not token:
            raise RuntimeError("未配置 telegram_bot_token")
        if not chat_id:
            raise RuntimeError("未配置 telegram_chat_id")

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": False,
        }
        parse_mode = self._telegram_parse_mode()
        if parse_mode:
            payload["parse_mode"] = parse_mode

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}
            if resp.status_code >= 400 or data.get("ok") is False:
                raise RuntimeError(f"Telegram 发送失败: HTTP {resp.status_code}, {data}")
            return data

    async def _callback_with_retry(
        self,
        client: GuangyaPushClient,
        resource_id: int,
        status: str,
        error_message: str | None = None,
        message_id: str | None = None,
        response_payload: dict[str, Any] | None = None,
    ) -> None:
        last_error = None
        for _ in range(3):
            try:
                await client.callback(
                    resource_id=resource_id,
                    status=status,
                    error_message=error_message,
                    message_id=message_id,
                    response_payload=response_payload,
                )
                return
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(2)
        logger.error(f"光鸭资源回调失败 resource_id={resource_id}: {last_error}")

    async def _push_once(self) -> int:
        if self._pushing:
            return 0
        self._pushing = True
        pushed = 0
        try:
            client = self._client()
            lease = await client.lease(self._batch_size(), self._lease_stale_minutes())
            items = lease.get("items") or []
            for item in items:
                resource_id = int(item["id"])
                text = item.get("text") or self._fallback_text(item)
                try:
                    send_result = await self._send_text(text)
                    await self._callback_with_retry(
                        client,
                        resource_id,
                        "success",
                        message_id=self._message_id(send_result),
                        response_payload={"send_result": str(send_result)},
                    )
                    pushed += 1
                except Exception as exc:
                    await self._callback_with_retry(
                        client,
                        resource_id,
                        "failed",
                        error_message=str(exc)[:500],
                    )
                await asyncio.sleep(self._send_interval())
            return pushed
        finally:
            self._pushing = False

    def _fallback_text(self, item: dict[str, Any]) -> str:
        return "\n".join([
            f"名称：{item.get('name') or ''}",
            f"标签：{item.get('tags') or ''}",
            f"链接：{item.get('share_link') or ''}",
        ])

    def _message_id(self, send_result: Any) -> str | None:
        if send_result is None:
            return None
        for attr in ("message_id", "id"):
            value = getattr(send_result, attr, None)
            if value:
                return str(value)
        if isinstance(send_result, dict):
            result = send_result.get("result")
            if isinstance(result, dict):
                value = result.get("message_id") or result.get("id")
                if value:
                    return str(value)
            value = send_result.get("message_id") or send_result.get("id")
            if value:
                return str(value)
        return None

    @filter.command("gy_bind_push")
    async def bind_push_target(self, event: AstrMessageEvent):
        origin = getattr(event, "unified_msg_origin", None)
        if not origin:
            yield event.plain_result("绑定失败：当前平台没有 unified_msg_origin")
            return
        self._set_config_value("target_unified_msg_origin", origin)
        self._start_poll_task()
        yield event.plain_result(f"已绑定当前会话为光鸭资源推送目标：{origin}")

    @filter.command("gy_push_status")
    async def push_status(self, event: AstrMessageEvent):
        try:
            client = self._client()
            health = await client.health()
            if self._send_mode() == "telegram_api":
                target = self._telegram_chat_id() or "未配置 telegram_chat_id"
            else:
                target = self._target_origin() or "未绑定"
            enabled = "开启" if self._is_enabled() else "暂停"
            yield event.plain_result(
                f"光鸭推送接口正常\n"
                f"Key: {health.get('key_name', '-')}\n"
                f"模式: {self._send_mode()}\n"
                f"目标: {target}\n"
                f"自动轮询: {enabled}"
            )
        except Exception as exc:
            yield event.plain_result(f"光鸭推送接口异常：{exc}")

    @filter.command("gy_push_once")
    async def push_once_command(self, event: AstrMessageEvent):
        try:
            count = await self._push_once()
            yield event.plain_result(f"本次已推送 {count} 条资源")
        except Exception as exc:
            yield event.plain_result(f"手动推送失败：{exc}")

    @filter.command("gy_push_pause")
    async def pause_push(self, event: AstrMessageEvent):
        self._set_config_value("enabled", False)
        yield event.plain_result("已暂停光鸭资源自动推送")

    @filter.command("gy_push_resume")
    async def resume_push(self, event: AstrMessageEvent):
        self._set_config_value("enabled", True)
        self._start_poll_task()
        yield event.plain_result("已恢复光鸭资源自动推送")

    async def terminate(self):
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
