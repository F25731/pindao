"""
转存任务执行器。
单个资源的完整转存流程，带 checkpoint 断点续跑。
"""
import logging
import re
from datetime import datetime, timezone, timedelta
from secrets import token_hex
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, select, update, func
import httpx

from app.models import Task, Resource, GuangyaAccount
from app.services.guangya_client import GuangyaClient
from app.services.account_pool import (
    select_available_account,
    mark_account_used,
    mark_account_error,
    mark_account_full,
    mark_account_expired,
    mark_account_rate_limited,
    reset_account_error,
    refresh_account_capacity,
    update_account_tokens,
)
from app.utils.link_parser import build_share_link
from app.config import settings
from app.services.system_log import append_system_log

logger = logging.getLogger("worker.transfer")


def generate_extract_code() -> str:
    """生成 4 位随机提取码。"""
    return token_hex(2)


async def execute_transfer(db: AsyncSession, task: Task, resource: Resource):
    """
    执行完整转存流程。每步保存 checkpoint，支持断点续跑。

    步骤:
    1. 选择可用账号
    2. 获取分享访问令牌
    3. 获取分享文件列表
    4. 转存到自己账号
    5. 创建新分享
    6. 更新数据库
    """
    checkpoint = task.checkpoint or {}

    try:
        if await _pause_if_requested(db, task, resource, checkpoint):
            return

        if not checkpoint and await _skip_if_exact_duplicate(db, task, resource):
            return

        # STEP 1: 选择账号
        if "account_id" not in checkpoint:
            account = await select_available_account(db)
            if not account:
                await _pause_until_account_available(
                    db,
                    task,
                    resource,
                    "没有可用账号，请新增或启用账号后点击一键继续转存",
                )
                return
            checkpoint["account_id"] = account.id
            task.account_id = account.id
            task.checkpoint = checkpoint
            await db.commit()
        else:
            result = await db.execute(
                select(GuangyaAccount).where(GuangyaAccount.id == checkpoint["account_id"])
            )
            account = result.scalar_one_or_none()
            if not account or account.status != "available":
                # 账号不可用，重新选择
                del checkpoint["account_id"]
                task.checkpoint = checkpoint
                await db.commit()
                await _fail_retryable(db, task, resource, "分配的账号不可用，将重新选择")
                return

        try:
            await refresh_account_capacity(db, account)
            if account.status == "full":
                checkpoint.pop("account_id", None)
                task.checkpoint = checkpoint
                await _continue_with_new_account(
                    db,
                    task,
                    resource,
                    "账号容量已满，已切换账号等待继续",
                    {"account_id": account.id, "used": account.used_capacity_bytes, "total": account.total_capacity_bytes},
                )
                return
            await db.commit()
        except Exception as exc:
            account.last_error = f"刷新容量失败: {str(exc)[:200]}"
            await db.commit()

        client = GuangyaClient(
            access_token=account.access_token,
            refresh_token=account.refresh_token,
            device_id=account.device_id,
        )

        if await _pause_if_requested(db, task, resource, checkpoint):
            return

        # STEP 2: 获取分享访问令牌
        if "share_access_token" not in checkpoint:
            try:
                token_resp = await GuangyaClient.share_access_token(
                    share_id=resource.share_id,
                    code=resource.extract_code or "",
                )
            except httpx.HTTPStatusError as e:
                await _handle_share_error(db, task, resource, account, e)
                return
            except Exception as e:
                await _fail_retryable(db, task, resource, f"获取分享访问令牌网络异常: {str(e)[:200]}")
                return

            if _has_api_error(token_resp):
                await _fail_final(db, task, resource, _format_api_error("获取分享访问令牌失败", token_resp), token_resp)
                return

            share_token = _extract_access_token(token_resp)
            if not share_token:
                await _fail_final(db, task, resource, _format_api_error("获取分享访问令牌失败", token_resp), token_resp)
                return

            checkpoint["share_access_token"] = share_token
            task.checkpoint = checkpoint
            await db.commit()

        if await _pause_if_requested(db, task, resource, checkpoint):
            return

        # STEP 3: 获取分享文件列表
        if "file_ids" not in checkpoint:
            try:
                files_resp = await GuangyaClient.share_files_list(
                    access_token=checkpoint["share_access_token"]
                )
            except httpx.HTTPStatusError as e:
                await _handle_share_error(db, task, resource, account, e)
                return
            except Exception as e:
                await _fail_retryable(db, task, resource, f"获取分享文件列表网络异常: {str(e)[:200]}")
                return

            if _has_api_error(files_resp):
                await _fail_final(db, task, resource, _format_api_error("获取分享文件列表失败", files_resp), files_resp)
                return

            file_ids = _extract_file_ids(files_resp)
            if not file_ids:
                await _fail_final(db, task, resource, _format_api_error("分享文件列表为空", files_resp), files_resp)
                return

            checkpoint["file_ids"] = file_ids
            checkpoint["source_file_items"] = _compact_file_items(files_resp)
            task.checkpoint = checkpoint
            await db.commit()

        if await _pause_if_requested(db, task, resource, checkpoint):
            return

        # STEP 4: 转存到自己账号
        if "source_file_items" not in checkpoint and checkpoint.get("share_access_token"):
            try:
                files_resp = await GuangyaClient.share_files_list(
                    access_token=checkpoint["share_access_token"]
                )
                if not _has_api_error(files_resp):
                    source_file_ids = _extract_file_ids(files_resp)
                    if source_file_ids:
                        checkpoint["file_ids"] = source_file_ids
                    checkpoint["source_file_items"] = _compact_file_items(files_resp)
                    task.checkpoint = checkpoint
                    await db.commit()
            except Exception:
                pass

        if "restore_done" not in checkpoint:
            if "target_existing_file_ids" not in checkpoint:
                try:
                    before_resp = await client.get_file_list(parent_id=account.default_parent_id or "", page=0)
                    checkpoint["target_existing_file_ids"] = _extract_file_ids_from_file_list(before_resp)
                    task.checkpoint = checkpoint
                    await db.commit()
                except Exception:
                    checkpoint["target_existing_file_ids"] = []

            try:
                restore_resp = await client.restore_share(
                    access_token=checkpoint["share_access_token"],
                    file_ids=checkpoint["file_ids"],
                    parent_id=account.default_parent_id or "",
                )
            except httpx.HTTPStatusError as e:
                await _handle_transfer_error(db, task, resource, account, e)
                return
            except Exception as e:
                await _fail_retryable(db, task, resource, f"转存操作网络异常: {str(e)[:200]}")
                return

            if _has_api_error(restore_resp):
                await _handle_transfer_business_error(
                    db, task, resource, account, restore_resp, checkpoint, "转存失败"
                )
                return

            checkpoint["restore_done"] = True
            checkpoint["restore_resp"] = restore_resp
            restored_response_file_ids = _extract_restored_file_ids(restore_resp)
            transferred_file_ids = (
                restored_response_file_ids
                if _looks_like_target_file_ids(restored_response_file_ids, checkpoint.get("file_ids") or [])
                else []
            )
            source_file_ids = checkpoint.get("file_ids") or []
            try:
                file_list_resp = await client.get_file_list(parent_id=account.default_parent_id or "", page=0)
                located_file_ids = _locate_transferred_file_ids(
                    file_list_resp,
                    checkpoint,
                    resource.name,
                )
                if located_file_ids:
                    transferred_file_ids = located_file_ids
                checkpoint["file_list_resp"] = file_list_resp
            except Exception:
                pass
            if transferred_file_ids:
                checkpoint["transferred_file_ids"] = transferred_file_ids
            task.checkpoint = checkpoint
            await db.commit()

        if await _pause_if_requested(db, task, resource, checkpoint):
            return

        # STEP 5: 创建新分享
        if "new_share_link" not in checkpoint:
            # 获取转存后的文件 ID
            transferred_file_ids = checkpoint.get("transferred_file_ids")
            if not transferred_file_ids:
                try:
                    file_list_resp = await client.get_file_list(parent_id=account.default_parent_id or "", page=0)
                    transferred_file_ids = _locate_transferred_file_ids(file_list_resp, checkpoint, resource.name)
                    checkpoint["file_list_resp"] = file_list_resp
                    if transferred_file_ids:
                        checkpoint["transferred_file_ids"] = transferred_file_ids
                        task.checkpoint = checkpoint
                        await db.commit()
                except Exception:
                    pass

            if not transferred_file_ids:
                await _fail_retryable(
                    db,
                    task,
                    resource,
                    "转存成功但无法定位新文件ID：已保存接口响应，稍后重试定位；若持续出现，请检查账号目录是否已有同名文件",
                    {
                        "restore_resp": checkpoint.get("restore_resp"),
                        "source_file_items": checkpoint.get("source_file_items"),
                    },
                    retry_minutes=2,
                )
                return

            source_file_ids = checkpoint.get("file_ids") or []
            if not _looks_like_target_file_ids(transferred_file_ids, source_file_ids):
                bad_count = len(transferred_file_ids)
                source_count = max(len(source_file_ids), 1)
                checkpoint.pop("transferred_file_ids", None)
                checkpoint.pop("target_existing_file_ids", None)
                checkpoint.pop("restore_done", None)
                checkpoint.pop("restore_resp", None)
                checkpoint.pop("file_list_resp", None)
                task.checkpoint = checkpoint
                await _fail_retryable(
                    db,
                    task,
                    resource,
                    f"转存后的文件ID数量异常：源分享 {source_count} 个文件，系统定位到 {bad_count} 个，已重置定位步骤避免创建错误分享",
                    {"source_file_ids": source_file_ids, "bad_transferred_file_ids": transferred_file_ids[:50]},
                    retry_minutes=2,
                )
                return

            new_code = generate_extract_code()
            try:
                share_resp = await client.create_share(
                    file_ids=transferred_file_ids,
                    title=resource.name,
                    code=new_code,
                )
            except httpx.HTTPStatusError as e:
                await _handle_transfer_error(db, task, resource, account, e)
                return
            except Exception as e:
                await _fail_retryable(db, task, resource, f"创建分享网络异常: {str(e)[:200]}")
                return

            if _has_api_error(share_resp):
                checkpoint["share_resp"] = share_resp
                task.checkpoint = checkpoint
                await _handle_transfer_business_error(
                    db, task, resource, account, share_resp, checkpoint, "创建分享失败"
                )
                return

            new_share_url = _extract_share_url(share_resp)
            new_share_id = _extract_new_share_id(share_resp)
            actual_code = _extract_share_code(share_resp) or new_code
            if new_share_url:
                url_share_id, url_code = _parse_built_share_link(new_share_url)
                new_share_id = url_share_id or new_share_id
                actual_code = url_code or actual_code
            if not new_share_id:
                # 尝试从分享列表获取
                try:
                    list_resp = await client.get_share_list(page=0)
                    share_info = _find_share_info_from_list(list_resp, resource.name, new_share_id)
                    if share_info:
                        new_share_id = share_info.get("share_id") or new_share_id
                        actual_code = share_info.get("code") or actual_code
                        new_share_url = share_info.get("url") or new_share_url
                    checkpoint["share_list_resp"] = list_resp
                except Exception:
                    pass

            if not new_share_id:
                checkpoint["share_resp"] = share_resp
                task.checkpoint = checkpoint
                await _fail_retryable(
                    db,
                    task,
                    resource,
                    _format_api_error("创建分享成功但无法获取分享ID", share_resp),
                    share_resp,
                    retry_minutes=2,
                )
                return

            new_link = _normalize_share_url(new_share_url, actual_code) if new_share_url else build_share_link(new_share_id, actual_code)
            checkpoint["new_share_id"] = new_share_id
            checkpoint["new_extract_code"] = actual_code
            checkpoint["new_share_link"] = new_link
            task.checkpoint = checkpoint
            await db.commit()

        if await _pause_if_requested(db, task, resource, checkpoint):
            return

        # STEP 6: 更新资源记录，标记成功
        resource.status = "待推送"
        resource.transfer_account_id = account.id
        resource.transferred_file_id = ",".join(checkpoint.get("transferred_file_ids") or checkpoint.get("file_ids", []))
        resource.new_share_id = checkpoint["new_share_id"]
        resource.new_extract_code = checkpoint["new_extract_code"]
        resource.new_share_link = checkpoint["new_share_link"]
        resource.transferred_at = datetime.now(timezone.utc)
        resource.error_message = None
        resource.error_response = None

        task.status = "success"
        task.completed_at = datetime.now(timezone.utc)

        await mark_account_used(db, account)
        await reset_account_error(db, account)

        # 如果 token 被刷新了，保存回数据库
        if client.access_token != account.access_token:
            await update_account_tokens(
                db, account,
                client.access_token,
                client.refresh_token_value,
            )

        await append_system_log(
            db,
            "success",
            "transfer",
            f"转存成功: resource_id={resource.id}, task_id={task.id}",
            {"new_link": resource.new_share_link},
        )
        await db.commit()
        logger.info(f"转存成功: resource_id={resource.id}, new_link={resource.new_share_link}")

    except Exception as e:
        logger.error(f"转存异常: task_id={task.id}, error={e}")
        await _fail_retryable(db, task, resource, f"未知错误: {str(e)[:500]}")


# ===== 辅助函数 =====

async def _skip_if_exact_duplicate(
    db: AsyncSession,
    task: Task,
    resource: Resource,
) -> bool:
    conditions = []
    if resource.original_link:
        conditions.append(Resource.original_link == resource.original_link)
    if resource.share_id:
        extract_code = resource.extract_code or ""
        if extract_code:
            extract_condition = Resource.extract_code == extract_code
        else:
            extract_condition = or_(Resource.extract_code == "", Resource.extract_code.is_(None))
        conditions.append(and_(Resource.share_id == resource.share_id, extract_condition))
    if not conditions:
        return False

    result = await db.execute(
        select(Resource).where(
            Resource.id != resource.id,
            Resource.status.notin_(["精确重复已跳过", "人工确认跳过", "已取消"]),
            or_(*conditions),
        ).order_by(Resource.id.asc()).limit(1)
    )
    existing = result.scalar_one_or_none()
    if not existing:
        return False

    message = f"转存前发现数据库已有重复资源，已跳过；重复资源ID={existing.id}"
    resource.status = "精确重复已跳过"
    resource.duplicate_of_id = existing.id
    resource.error_message = message
    task.status = "skipped"
    task.error_message = message
    task.completed_at = datetime.now(timezone.utc)
    await append_system_log(
        db,
        "warning",
        "transfer",
        f"精确重复已跳过: resource_id={resource.id}, duplicate_of={existing.id}",
    )
    await db.commit()
    logger.info(
        "转存前精确去重跳过: task_id=%s, resource_id=%s, duplicate_of=%s",
        task.id,
        resource.id,
        existing.id,
    )
    return True

async def _pause_if_requested(
    db: AsyncSession,
    task: Task,
    resource: Resource,
    checkpoint: dict,
) -> bool:
    await db.refresh(task)
    checkpoint.update(task.checkpoint or {})
    if task.status == "cancel_requested" or checkpoint.get("cancel_requested"):
        checkpoint.pop("cancel_requested", None)
        task.status = "skipped"
        task.checkpoint = checkpoint
        task.completed_at = datetime.now(timezone.utc)
        resource.status = "已取消"
        await db.commit()
        logger.info(f"任务已取消: task_id={task.id}, resource_id={resource.id}")
        return True

    if task.status != "pause_requested" and not checkpoint.get("pause_requested"):
        return False

    checkpoint.pop("pause_requested", None)
    task.status = "paused"
    task.checkpoint = checkpoint
    resource.status = "转存暂停"
    await db.commit()
    logger.info(f"任务已暂停: task_id={task.id}, resource_id={resource.id}")
    return True


def _extract_access_token(resp: dict) -> Optional[str]:
    if isinstance(resp, dict):
        data = resp.get("data", resp)
        return data.get("accessToken") or data.get("access_token")
    return None


def _extract_file_ids(resp: dict) -> list:
    if isinstance(resp, dict):
        data = resp.get("data", resp)
        files = data.get("list") or data.get("files") or data.get("fileList") or []
        return [f.get("id") or f.get("fileId") for f in files if f.get("id") or f.get("fileId")]
    return []


def _extract_restored_file_ids(resp: dict) -> list:
    ids = _collect_values(resp, ("fileId", "fileID", "resId"))
    return _dedupe_ids(ids)


def _looks_like_target_file_ids(restored_ids: list, source_ids: list) -> bool:
    if not restored_ids:
        return False
    restored = {str(file_id) for file_id in restored_ids if file_id}
    source = {str(file_id) for file_id in source_ids if file_id}
    if source and restored and restored.issubset(source):
        return False
    source_count = max(len(source_ids), 1)
    return len(restored_ids) <= source_count


def _extract_new_share_id(resp: dict) -> Optional[str]:
    candidates = _collect_values(
        resp,
        ("publicShareId", "public_share_id", "shareId", "share_id", "sid", "url", "shareUrl", "shareLink", "link"),
    )
    for val in candidates:
        sid = _normalize_share_id(val)
        if sid:
            return sid
    return None


def _extract_share_code(resp: dict) -> Optional[str]:
    candidates = _collect_share_codes(
        resp,
        ("code", "extractCode", "extract_code", "shareCode", "share_code", "pwd", "password"),
    )
    for val in candidates:
        code = _normalize_share_code(val)
        if code:
            return code
    return None


def _extract_share_url(resp: dict) -> Optional[str]:
    candidates = _collect_values(resp, ("url", "shareUrl", "shareLink", "link"))
    for val in candidates:
        url = _normalize_share_url(str(val), None)
        if url:
            return url
    return None


def _extract_share_info(item: dict) -> dict:
    url = _extract_share_url(item)
    share_id = _extract_new_share_id(item)
    code = _extract_share_code(item)
    if url:
        url_share_id, url_code = _parse_built_share_link(url)
        share_id = url_share_id or share_id
        code = url_code or code
    return {
        "share_id": share_id,
        "code": code,
        "url": url,
        "title": item.get("title") or item.get("name") or item.get("fileName"),
    }


def _find_share_info_from_list(resp: dict, title: str, share_id: Optional[str] = None) -> Optional[dict]:
    if not isinstance(resp, dict):
        return None
    data = resp.get("data", resp)
    shares = data.get("list") or data.get("shares") or []
    for item in shares:
        info = _extract_share_info(item)
        if share_id and info["share_id"] == share_id:
            return info
    for item in shares:
        info = _extract_share_info(item)
        if title and info["title"] and info["title"] != title:
            continue
        if info["share_id"]:
            return info
    for item in shares:
        info = _extract_share_info(item)
        if info["share_id"]:
            return info
    return None


def _find_share_id_from_list(resp: dict, title: str) -> Optional[str]:
    info = _find_share_info_from_list(resp, title)
    return info.get("share_id") if info else None


def _extract_file_items(resp: dict) -> list:
    if not isinstance(resp, dict):
        return []
    data = resp.get("data", resp)
    return data.get("list") or data.get("files") or data.get("fileList") or []


def _compact_file_items(resp: dict) -> list:
    compacted = []
    for item in _extract_file_items(resp):
        file_id = _file_item_id(item)
        name = _file_item_name(item)
        compacted.append({
            "id": file_id,
            "name": name,
            "size": item.get("size") or item.get("fileSize"),
            "type": item.get("type") or item.get("fileType"),
        })
    return compacted


def _file_item_id(item: dict) -> Optional[str]:
    file_id = item.get("id") or item.get("fileId") or item.get("fileID") or item.get("resId")
    return str(file_id) if file_id else None


def _file_item_name(item: dict) -> str:
    return str(
        item.get("name")
        or item.get("fileName")
        or item.get("title")
        or ""
    ).strip()


def _extract_file_ids_from_file_list(resp: dict) -> list:
    return _dedupe_ids([_file_item_id(item) for item in _extract_file_items(resp)])


def _locate_transferred_file_ids(resp: dict, checkpoint: dict, resource_name: str) -> list:
    source_file_ids = checkpoint.get("file_ids") or []
    source_count = max(len(source_file_ids), 1)
    existing_ids = checkpoint.get("target_existing_file_ids") or []
    files = _extract_file_items(resp)
    if not files:
        return []

    new_items = _find_new_file_items(files, existing_ids)
    candidates = _match_file_items_by_names(new_items, _source_names(checkpoint, resource_name))
    if _looks_like_target_file_ids(candidates, source_file_ids):
        return candidates

    if len(new_items) == source_count:
        new_ids = _dedupe_ids([_file_item_id(item) for item in new_items])
        if _looks_like_target_file_ids(new_ids, source_file_ids):
            return new_ids

    candidates = _match_file_items_by_names(files, _source_names(checkpoint, resource_name))
    if _looks_like_target_file_ids(candidates, source_file_ids):
        return candidates

    return []


def _find_new_file_items(files: list, existing_ids: list) -> list:
    existing = {str(file_id) for file_id in existing_ids if file_id}
    new_items = []
    for item in files:
        file_id = _file_item_id(item)
        if file_id and file_id not in existing:
            new_items.append(item)
    return new_items


def _source_names(checkpoint: dict, resource_name: str) -> list:
    names = []
    for item in checkpoint.get("source_file_items") or []:
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    if resource_name:
        names.append(str(resource_name).strip())
    return _dedupe_ids(names)


def _match_file_items_by_names(items: list, names: list) -> list:
    wanted = {name for name in names if name}
    if not wanted:
        return []
    matched = []
    for item in items:
        if _file_item_name(item) in wanted:
            file_id = _file_item_id(item)
            if file_id:
                matched.append(file_id)
    return _dedupe_ids(matched)


def _find_new_file_ids_from_list(resp: dict, existing_ids: list, title: str) -> list:
    existing = {str(file_id) for file_id in existing_ids if file_id}
    new_items = []
    for item in _extract_file_items(resp):
        file_id = _file_item_id(item)
        if file_id and file_id not in existing:
            new_items.append(item)

    if not new_items:
        return []

    matched = []
    for item in new_items:
        if title and item.get("name") and item.get("name") != title:
            continue
        file_id = _file_item_id(item)
        if file_id:
            matched.append(file_id)
    if matched:
        return _dedupe_ids(matched)

    return _dedupe_ids([_file_item_id(item) for item in new_items])


def _find_file_ids_from_list(resp: dict, title: str) -> list:
    files = _extract_file_items(resp)
    matched = []
    for item in files:
        if title and item.get("name") and item.get("name") != title:
            continue
        file_id = _file_item_id(item)
        if file_id:
            matched.append(file_id)
    if matched:
        return _dedupe_ids(matched)
    if len(files) == 1:
        return _dedupe_ids([_file_item_id(files[0])])
    return []


def _collect_values(value, keys: tuple[str, ...]) -> list:
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and item:
                found.append(item)
            found.extend(_collect_values(item, keys))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_values(item, keys))
    return found


def _collect_share_codes(value, keys: tuple[str, ...]) -> list:
    found = []
    if isinstance(value, dict):
        looks_like_api_envelope = "data" in value and ("msg" in value or "message" in value)
        for key, item in value.items():
            if key in keys and item:
                if key == "code" and looks_like_api_envelope:
                    pass
                else:
                    found.append(item)
            found.extend(_collect_share_codes(item, keys))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_share_codes(item, keys))
    return found


def _dedupe_ids(values: list) -> list:
    ids = []
    seen = set()
    for val in values:
        if val is None:
            continue
        text = str(val)
        if text and text not in seen:
            seen.add(text)
            ids.append(text)
    return ids


def _normalize_share_id(value) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"/s/([^/?#]+)", text)
    if match:
        text = match.group(1)
    text = text.split("?", 1)[0].split("#", 1)[0].strip()
    if not re.match(r"^[A-Za-z0-9_-]+$", text):
        return None
    if "_" not in text:
        return None
    return text


def _normalize_share_code(value) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"[?&]code=([^&#]+)", text)
    if match:
        return match.group(1)
    if text in ("0", "200"):
        return None
    if 4 <= len(text) <= 16 and re.match(r"^[A-Za-z0-9_-]+$", text):
        return text
    return None


def _parse_built_share_link(url: str) -> tuple[Optional[str], Optional[str]]:
    normalized = _normalize_share_url(url, None)
    if not normalized:
        return None, None
    parsed = urlparse(normalized.split("#", 1)[0])
    match = re.search(r"/s/([^/?#]+)", parsed.path)
    share_id = _normalize_share_id(match.group(1)) if match else None
    code = parse_qs(parsed.query).get("code", [None])[0]
    return share_id, _normalize_share_code(code)


def _normalize_share_url(url: Optional[str], code: Optional[str]) -> Optional[str]:
    if not url:
        return None
    text = str(url).strip()
    if not text:
        return None
    if text.startswith("//"):
        text = "https:" + text
    elif text.startswith("/s/"):
        text = "https://www.guangyapan.com" + text
    elif text.startswith("www.guangyapan.com"):
        text = "https://" + text

    if "guangyapan.com/s/" not in text:
        share_id = _normalize_share_id(text)
        if not share_id:
            return None
        return build_share_link(share_id, code or "")

    parsed = urlparse(text)
    match = re.search(r"/s/([^/?#]+)", parsed.path)
    share_id = _normalize_share_id(match.group(1)) if match else None
    if not share_id:
        return None

    query = parse_qs(parsed.query)
    normalized_code = _normalize_share_code(code) or _normalize_share_code(query.get("code", [None])[0])
    new_query = urlencode({"code": normalized_code}) if normalized_code else ""
    return urlunparse(("https", "www.guangyapan.com", f"/s/{share_id}", "", new_query, ""))


def _has_api_error(resp: dict) -> bool:
    if not isinstance(resp, dict):
        return False
    code = resp.get("code")
    if code is not None and str(code) not in ("0", "200"):
        return True
    if resp.get("error") is True:
        return True
    success = resp.get("success")
    if success is False:
        return True
    return False


def _format_api_error(prefix: str, resp: dict = None) -> str:
    if not isinstance(resp, dict):
        return prefix
    msg = resp.get("msg") or resp.get("message") or resp.get("error") or resp.get("raw")
    code = resp.get("code")
    parts = [prefix]
    if msg:
        parts.append(str(msg))
    text = "：".join(parts)
    if code is not None:
        text = f"{text} (code={code})"
    return text[:500]


async def _fail_retryable(
    db: AsyncSession, task: Task, resource: Resource,
    message: str, resp: dict = None, retry_minutes: int = 2,
):
    if task.attempt >= task.max_attempts:
        await _fail_final(db, task, resource, message, resp)
        return

    task.status = "failed_retryable"
    task.error_message = message
    task.error_response = resp
    task.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=retry_minutes * task.attempt)
    resource.status = "失败待重试"
    resource.error_message = message
    resource.retry_count += 1
    await append_system_log(
        db,
        "warning",
        "transfer",
        f"任务可重试失败: task_id={task.id}, resource_id={resource.id}, attempt={task.attempt}, msg={message}",
    )
    await db.commit()
    logger.warning(f"任务可重试失败: task_id={task.id}, attempt={task.attempt}, msg={message}")


async def _fail_final(
    db: AsyncSession, task: Task, resource: Resource,
    message: str, resp: dict = None, pause_following: bool = False,
):
    task.status = "failed_final"
    task.error_message = message
    task.error_response = resp
    task.completed_at = datetime.now(timezone.utc)
    resource.status = "最终失败"
    resource.error_message = message
    resource.error_response = resp
    paused_count = await _pause_following_transfer_tasks(db, task.id, message) if pause_following else 0
    await append_system_log(
        db,
        "error",
        "transfer",
        f"任务最终失败: task_id={task.id}, resource_id={resource.id}, paused_following={paused_count}, msg={message}",
    )
    await db.commit()
    logger.error(f"任务最终失败: task_id={task.id}, paused_following={paused_count}, msg={message}")


async def _pause_following_transfer_tasks(
    db: AsyncSession,
    failed_task_id: int,
    reason: str,
) -> int:
    pending_tasks = (
        select(Task.id, Task.resource_id)
        .where(
            Task.id != failed_task_id,
            Task.task_type == "transfer",
            Task.status.in_(("pending", "failed_retryable")),
        )
        .subquery()
    )

    count_result = await db.execute(select(func.count()).select_from(pending_tasks))
    task_count = count_result.scalar() or 0
    if task_count <= 0:
        return 0

    message = f"前序资源最终失败，队列已自动暂停，请检查后手动继续：{reason[:200]}"
    await db.execute(
        update(Resource)
        .where(
            Resource.id.in_(select(pending_tasks.c.resource_id)),
            Resource.status.in_(("待转存", "失败待重试")),
        )
        .values(status="转存暂停", error_message=message)
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        update(Task)
        .where(Task.id.in_(select(pending_tasks.c.id)))
        .values(
            status="paused",
            next_retry_at=None,
            error_message=func.coalesce(Task.error_message, message),
        )
        .execution_options(synchronize_session=False)
    )
    return task_count


async def _pause_until_account_available(
    db: AsyncSession,
    task: Task,
    resource: Resource,
    message: str,
    resp: dict = None,
):
    task.status = "paused"
    task.error_message = message
    task.error_response = resp
    task.next_retry_at = None
    task.completed_at = None
    resource.status = "转存暂停"
    resource.error_message = message
    resource.error_response = resp
    paused_count = await _pause_following_transfer_tasks(db, task.id, message)
    await db.commit()
    logger.warning(f"账号池无可用账号，转存队列已暂停: task_id={task.id}, paused_following={paused_count}")


async def _continue_with_new_account(
    db: AsyncSession,
    task: Task,
    resource: Resource,
    message: str,
    resp: dict = None,
):
    task.status = "pending"
    task.error_message = message
    task.error_response = resp
    task.next_retry_at = None
    resource.status = "待转存"
    resource.error_message = message
    resource.error_response = resp
    await append_system_log(
        db,
        "warning",
        "transfer",
        f"任务切换账号继续: task_id={task.id}, resource_id={resource.id}, msg={message}",
    )
    await db.commit()
    logger.warning(f"任务切换账号继续: task_id={task.id}, msg={message}")


async def _handle_transfer_business_error(
    db: AsyncSession,
    task: Task,
    resource: Resource,
    account: GuangyaAccount,
    resp_body: dict,
    checkpoint: dict,
    prefix: str,
):
    message = _format_api_error(prefix, resp_body)
    raw_text = str(resp_body)

    if resp_body.get("code") in (401, "401") or "登录" in raw_text or "token" in raw_text.lower():
        await mark_account_expired(db, account)
        checkpoint.pop("account_id", None)
        task.checkpoint = checkpoint
        await _fail_retryable(db, task, resource, message, resp_body)
    elif resp_body.get("code") in (429, "429") or "风控" in raw_text or "频繁" in raw_text:
        await mark_account_rate_limited(db, account)
        await _fail_retryable(db, task, resource, message, resp_body, retry_minutes=10)
    elif (
        resp_body.get("code") in (157, 507, "157", "507")
        or "容量" in raw_text
        or "空间不足" in raw_text
    ):
        await mark_account_full(db, account)
        checkpoint.pop("account_id", None)
        task.checkpoint = checkpoint
        await _continue_with_new_account(db, task, resource, message, resp_body)
    elif resp_body.get("code") in (143, 404, "143", "404") or "文件不存在" in raw_text:
        await _fail_final(db, task, resource, message, resp_body)
    else:
        await mark_account_error(db, account, message)
        await _fail_retryable(db, task, resource, message, resp_body)


async def _handle_share_error(
    db: AsyncSession, task: Task, resource: Resource,
    account: GuangyaAccount, error: httpx.HTTPStatusError,
):
    status_code = error.response.status_code
    try:
        resp_body = error.response.json()
    except Exception:
        resp_body = {"raw": error.response.text[:500]}

    if status_code == 404:
        await _fail_final(db, task, resource, _format_api_error("分享链接无效或已失效", resp_body), resp_body)
    elif status_code == 403:
        await _fail_final(db, task, resource, _format_api_error("提取码错误或无权访问", resp_body), resp_body)
    else:
        await _fail_retryable(db, task, resource, _format_api_error(f"分享接口错误 HTTP {status_code}", resp_body), resp_body)


async def _handle_transfer_error(
    db: AsyncSession, task: Task, resource: Resource,
    account: GuangyaAccount, error: httpx.HTTPStatusError,
):
    status_code = error.response.status_code
    try:
        resp_body = error.response.json()
    except Exception:
        resp_body = {"raw": error.response.text[:500]}

    if status_code == 401:
        await mark_account_expired(db, account)
        await _fail_retryable(db, task, resource, _format_api_error("账号登录失效", resp_body), resp_body)
    elif status_code == 429:
        await mark_account_rate_limited(db, account)
        await _fail_retryable(db, task, resource, _format_api_error("账号被风控限制", resp_body), resp_body, retry_minutes=10)
    elif status_code == 507 or "容量" in str(resp_body) or "空间不足" in str(resp_body):
        await mark_account_full(db, account)
        # 清除 checkpoint 中的 account_id，下次重试会选新账号
        checkpoint = task.checkpoint or {}
        checkpoint.pop("account_id", None)
        task.checkpoint = checkpoint
        await _fail_retryable(db, task, resource, _format_api_error("账号容量不足", resp_body), resp_body)
    else:
        await mark_account_error(db, account, f"HTTP {status_code}")
        await _fail_retryable(db, task, resource, _format_api_error(f"转存接口错误 HTTP {status_code}", resp_body), resp_body)
