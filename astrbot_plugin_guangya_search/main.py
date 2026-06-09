from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


@dataclass
class SearchSessionState:
    keyword: str
    cursor: Optional[str]
    items: list[dict[str, Any]]
    updated_at: datetime
    page_no: int = 1


class GuangyaSearchClient:
    def __init__(self, api_base: str, api_key: str, timeout_seconds: int = 20):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @property
    def headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.get(f"{self.api_base}/api/external/search/health", headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def search(self, keyword: str, limit: int, cursor: str | None = None, status: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"q": keyword, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        if status:
            params["status"] = status
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.get(f"{self.api_base}/api/external/search/resources", headers=self.headers, params=params)
            resp.raise_for_status()
            return resp.json()

    async def detail(self, resource_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.get(
                f"{self.api_base}/api/external/search/resources/{resource_id}",
                headers=self.headers,
            )
            resp.raise_for_status()
            return resp.json()


@register("astrbot_plugin_guangya_search", "Codex", "光鸭资源检索插件，负责关键词搜索和详情查询", "0.1.0")
class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        self._session_lock = asyncio.Lock()
        self._sessions: dict[str, SearchSessionState] = {}

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

    def _api_base(self) -> str:
        return str(self._config_value("api_base", "")).strip()

    def _api_key(self) -> str:
        return str(self._config_value("api_key", "")).strip()

    def _enabled(self) -> bool:
        return bool(self._config_value("enabled", True))

    def _default_limit(self) -> int:
        return max(1, min(int(self._config_value("default_limit", 10)), 50))

    def _session_ttl_seconds(self) -> int:
        return max(60, int(self._config_value("session_ttl_seconds", 900)))

    def _search_status(self) -> str:
        return str(self._config_value("status", "")).strip()

    def _client(self) -> GuangyaSearchClient:
        api_base = self._api_base()
        api_key = self._api_key()
        if not api_base:
            raise RuntimeError("未配置 api_base")
        if not api_key:
            raise RuntimeError("未配置 api_key")
        return GuangyaSearchClient(api_base, api_key, timeout_seconds=int(self._config_value("request_timeout_seconds", 20)))

    def _session_key(self, event: AstrMessageEvent) -> str:
        origin = getattr(event, "unified_msg_origin", None)
        if origin:
            return str(origin)
        session_id = str(getattr(event, "session_id", "") or "")
        if session_id:
            return session_id
        message_obj = getattr(event, "message_obj", None)
        if message_obj is not None:
            fallback_session = getattr(message_obj, "session_id", "")
            if fallback_session:
                return str(fallback_session)
        return "default"

    async def _get_session(self, key: str) -> Optional[SearchSessionState]:
        async with self._session_lock:
            state = self._sessions.get(key)
            if not state:
                return None
            age = datetime.now(timezone.utc) - state.updated_at
            if age.total_seconds() > self._session_ttl_seconds():
                self._sessions.pop(key, None)
                return None
            return state

    async def _set_session(self, key: str, state: SearchSessionState) -> None:
        async with self._session_lock:
            self._sessions[key] = state

    async def _clear_session(self, key: str) -> None:
        async with self._session_lock:
            self._sessions.pop(key, None)

    def _parse_keyword(self, event: AstrMessageEvent) -> str:
        raw = (event.message_str or "").strip()
        if not raw:
            return ""
        tokens = raw.split()
        first = tokens[0].lstrip("/!").lower()
        if first in {"gy", "search", "检索", "搜", "gy_search"}:
            return " ".join(tokens[1:]).strip()
        return raw

    def _parse_selection(self, event: AstrMessageEvent) -> str:
        raw = (event.message_str or "").strip()
        if not raw:
            return ""
        tokens = raw.split()
        first = tokens[0].lstrip("/!").lower()
        if first in {"gy_detail", "detail", "详情"}:
            return tokens[1].strip() if len(tokens) >= 2 else ""
        return raw

    def _format_search_list(self, keyword: str, items: list[dict[str, Any]], page_no: int, has_more: bool, cursor: str | None) -> str:
        if not items:
            return f'没有找到关键词「{keyword}」的结果。'

        lines = [
            f'关键词「{keyword}」的检索结果',
            f'第 {page_no} 页，当前 {len(items)} 条' + ("，还有更多" if has_more else ""),
            "",
        ]
        for idx, item in enumerate(items, start=1):
            rid = item.get("id")
            name = item.get("name") or "-"
            tags = item.get("tags") or "-"
            link = item.get("link") or "-"
            lines.append(f"{idx}. [{rid}] {name}")
            lines.append(f"   标签：{tags}")
            lines.append(f"   链接：{link}")
        lines.extend(
            [
                "",
                f"查看详情：/gy_detail 序号 或 /gy_detail 资源ID",
            ]
        )
        if has_more and cursor:
            lines.append("下一页：/gy_more")
        lines.append("新搜索：/gy 关键词")
        return "\n".join(lines)

    def _format_detail(self, item: dict[str, Any]) -> str:
        lines = [
            f"名称：{item.get('name') or '-'}",
            f"标签：{item.get('tags') or '-'}",
            f"链接：{item.get('link') or '-'}",
        ]
        extract_code = item.get("extract_code")
        if extract_code:
            lines.append(f"提取码：{extract_code}")
        lines.append(f"ID：{item.get('id')}")
        return "\n".join(lines)

    @filter.command("gy", alias={"search", "检索", "搜"})
    async def search(self, event: AstrMessageEvent):
        if not self._enabled():
            yield event.plain_result("检索插件当前未启用")
            return
        try:
            keyword = self._parse_keyword(event)
            if not keyword:
                yield event.plain_result("请直接发送 /gy 关键词")
                return

            client = self._client()
            result = await client.search(keyword, self._default_limit(), status=self._search_status() or None)
            items = result.get("items") or []
            session_key = self._session_key(event)
            state = SearchSessionState(
                keyword=keyword,
                cursor=result.get("next_cursor"),
                items=items,
                updated_at=datetime.now(timezone.utc),
                page_no=1,
            )
            await self._set_session(session_key, state)
            yield event.plain_result(
                self._format_search_list(
                    keyword,
                    items,
                    page_no=1,
                    has_more=bool(result.get("has_more")),
                    cursor=result.get("next_cursor"),
                )
            )
        except Exception as exc:
            logger.error(f"光鸭检索失败: {exc}")
            yield event.plain_result(f"检索失败：{exc}")

    @filter.command("gy_more", alias={"更多", "下一页"})
    async def more(self, event: AstrMessageEvent):
        if not self._enabled():
            yield event.plain_result("检索插件当前未启用")
            return
        session_key = self._session_key(event)
        state = await self._get_session(session_key)
        if not state:
            yield event.plain_result("没有可继续的检索结果，请先发送 /gy 关键词")
            return
        if not state.cursor:
            yield event.plain_result("已经没有更多结果了")
            return

        try:
            client = self._client()
            result = await client.search(state.keyword, self._default_limit(), cursor=state.cursor, status=self._search_status() or None)
            items = result.get("items") or []
            state.cursor = result.get("next_cursor")
            state.items = items
            state.page_no += 1
            state.updated_at = datetime.now(timezone.utc)
            await self._set_session(session_key, state)
            yield event.plain_result(
                self._format_search_list(
                    state.keyword,
                    items,
                    page_no=state.page_no,
                    has_more=bool(result.get("has_more")),
                    cursor=result.get("next_cursor"),
                )
            )
        except Exception as exc:
            logger.error(f"光鸭检索翻页失败: {exc}")
            yield event.plain_result(f"翻页失败：{exc}")

    @filter.command("gy_detail", alias={"detail", "详情"})
    async def detail(self, event: AstrMessageEvent):
        if not self._enabled():
            yield event.plain_result("检索插件当前未启用")
            return
        selection = self._parse_selection(event)
        if not selection:
            yield event.plain_result("请发送 /gy_detail 序号 或 /gy_detail 资源ID")
            return

        try:
            resource_id = int(selection)
        except ValueError:
            yield event.plain_result("请发送数字序号或资源ID")
            return

        session_key = self._session_key(event)
        state = await self._get_session(session_key)
        item: Optional[dict[str, Any]] = None

        if state and 1 <= resource_id <= len(state.items):
            item = state.items[resource_id - 1]
        else:
            try:
                client = self._client()
                item = await client.detail(resource_id)
            except Exception as exc:
                logger.error(f"光鸭详情查询失败: {exc}")
                yield event.plain_result(f"详情查询失败：{exc}")
                return

        yield event.plain_result(self._format_detail(item))

    @filter.command("gy_reset", alias={"清空", "重置"})
    async def reset(self, event: AstrMessageEvent):
        await self._clear_session(self._session_key(event))
        yield event.plain_result("已清空当前会话的检索缓存")

    @filter.command("gy_status", alias={"检索状态"})
    async def status(self, event: AstrMessageEvent):
        try:
            client = self._client()
            health = await client.health()
            yield event.plain_result(
                "光鸭检索接口正常\n"
                f"Key: {health.get('key_name', '-')}\n"
                f"默认条数: {self._default_limit()}\n"
                f"会话缓存: {self._session_ttl_seconds()} 秒"
            )
        except Exception as exc:
            yield event.plain_result(f"光鸭检索接口异常：{exc}")
