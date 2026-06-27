from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.dependencies import get_current_user
from app.models import AdminUser
from app.telegram_bot.guangya_api import GuangyaApiClient
from app.telegram_bot.runtime import metrics, push_bot, search_bot, store

router = APIRouter()


class BotConfigPayload(BaseModel):
    telegram_bot_token: str | None = Field(default=None)
    guangya_api_base: str | None = Field(default=None)
    guangya_api_key: str | None = Field(default=None)
    page_size: int | None = Field(default=None, ge=1, le=50)
    max_results: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, max_length=32)
    request_timeout_seconds: int | None = Field(default=None, ge=3, le=120)
    bot_enabled: bool | None = Field(default=None)
    proxy_enabled: bool | None = Field(default=None)
    proxy_url: str | None = Field(default=None, max_length=512)
    hot_window_hours: int | None = Field(default=None, ge=1, le=720)
    push_bot_token: str | None = Field(default=None)
    push_chat_id: str | None = Field(default=None)
    push_enabled: bool | None = Field(default=None)
    push_api_base: str | None = Field(default=None)
    push_api_key: str | None = Field(default=None)
    push_proxy_enabled: bool | None = Field(default=None)
    push_proxy_url: str | None = Field(default=None, max_length=512)
    push_poll_interval: int | None = Field(default=None, ge=5, le=3600)
    push_batch_size: int | None = Field(default=None, ge=1, le=100)
    push_send_interval: float | None = Field(default=None, ge=0, le=60)
    push_lease_stale_minutes: int | None = Field(default=None, ge=5, le=1440)
    push_parse_mode: str | None = Field(default=None, max_length=32)

    def clean(self) -> dict[str, Any]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


def _config_response() -> dict[str, Any]:
    data = store.get().public_dict()
    data["bot_running"] = search_bot.running()
    data["push_bot_running"] = push_bot.running()
    return data


@router.get("/config")
async def get_config(user: AdminUser = Depends(get_current_user)):
    return _config_response()


@router.put("/config")
async def update_config(payload: BotConfigPayload, user: AdminUser = Depends(get_current_user)):
    old_config = store.get()
    config = store.update(payload.clean())
    should_restart_search = (
        old_config.telegram_bot_token != config.telegram_bot_token
        or old_config.proxy_enabled != config.proxy_enabled
        or old_config.proxy_url != config.proxy_url
        or old_config.request_timeout_seconds != config.request_timeout_seconds
    )
    if should_restart_search and search_bot.running():
        await search_bot.restart()

    should_restart_push = (
        old_config.push_bot_token != config.push_bot_token
        or old_config.push_api_base != config.push_api_base
        or old_config.push_api_key != config.push_api_key
        or old_config.push_chat_id != config.push_chat_id
        or old_config.push_proxy_enabled != config.push_proxy_enabled
        or old_config.push_proxy_url != config.push_proxy_url
        or old_config.proxy_enabled != config.proxy_enabled
        or old_config.proxy_url != config.proxy_url
    )
    if should_restart_push and push_bot.running():
        await push_bot.restart()
    return _config_response()

@router.post("/search/start")
async def start_search_bot(user: AdminUser = Depends(get_current_user)):
    message = search_bot.start_background()
    return {"message": message, "bot_running": search_bot.running()}


@router.post("/search/stop")
async def stop_search_bot(user: AdminUser = Depends(get_current_user)):
    await search_bot.stop()
    return {"message": "搜索 Bot 已停止", "bot_running": search_bot.running()}


@router.post("/search/restart")
async def restart_search_bot(user: AdminUser = Depends(get_current_user)):
    message = await search_bot.restart()
    return {"message": message, "bot_running": search_bot.running()}


@router.post("/push/start")
async def start_push_bot(user: AdminUser = Depends(get_current_user)):
    message = push_bot.start_background()
    return {"message": message, "push_bot_running": push_bot.running()}


@router.post("/push/stop")
async def stop_push_bot(user: AdminUser = Depends(get_current_user)):
    await push_bot.stop()
    return {"message": "推送 Bot 已停止", "push_bot_running": push_bot.running()}


@router.post("/push/restart")
async def restart_push_bot(user: AdminUser = Depends(get_current_user)):
    message = await push_bot.restart()
    return {"message": message, "push_bot_running": push_bot.running()}


@router.post("/push/once")
async def push_once(user: AdminUser = Depends(get_current_user)):
    try:
        count = await push_bot.push_once()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": f"已推送 {count} 条资源", "pushed": count}


@router.get("/health")
async def health(user: AdminUser = Depends(get_current_user)):
    started = time.monotonic()
    try:
        api_health = await GuangyaApiClient(store.get()).health()
        api_ok = True
        api_error = ""
    except Exception as exc:
        api_health = {}
        api_ok = False
        api_error = str(exc)
    latency_ms = int((time.monotonic() - started) * 1000)
    metrics.record_health(api_ok, latency_ms if api_ok else None, api_health.get("key_name"), api_error)
    return {
        "ok": True,
        "bot_running": search_bot.running(),
        "push_bot_running": push_bot.running(),
        "guangya_api_ok": api_ok,
        "guangya_api": api_health,
        "guangya_api_error": api_error,
        "latency_ms": latency_ms,
    }


@router.get("/stats")
async def stats(user: AdminUser = Depends(get_current_user)):
    return metrics.snapshot(search_bot.running(), push_bot.running())


@router.get("/logs")
async def logs(
    after: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=400),
    user: AdminUser = Depends(get_current_user),
):
    events = metrics.events_after(after_id=after, limit=limit)
    return {
        "events": events,
        "last_event_id": metrics.snapshot(search_bot.running(), push_bot.running())["last_event_id"],
    }


@router.get("/hot")
async def hot_resources(user: AdminUser = Depends(get_current_user)):
    window = store.get().hot_window_hours
    top = metrics.top_resources(window_hours=window, limit=20)
    return {"window_hours": window, "resources": top}
