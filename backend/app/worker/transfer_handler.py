"""
转存任务执行器。
单个资源的完整转存流程，带 checkpoint 断点续跑。
"""
import logging
from datetime import datetime, timezone, timedelta
from secrets import token_hex
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
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
    update_account_tokens,
)
from app.utils.link_parser import build_share_link
from app.config import settings

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
        # STEP 1: 选择账号
        if "account_id" not in checkpoint:
            account = await select_available_account(db)
            if not account:
                await _fail_retryable(db, task, resource, "没有可用账号", retry_minutes=5)
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

        client = GuangyaClient(
            access_token=account.access_token,
            refresh_token=account.refresh_token,
            device_id=account.device_id,
        )

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

            share_token = _extract_access_token(token_resp)
            if not share_token:
                await _fail_final(db, task, resource, "获取分享访问令牌失败", token_resp)
                return

            checkpoint["share_access_token"] = share_token
            task.checkpoint = checkpoint
            await db.commit()

        # STEP 3: 获取分享文件列表
        if "file_ids" not in checkpoint:
            try:
                files_resp = await GuangyaClient.share_files_list(
                    access_token=checkpoint["share_access_token"]
                )
            except httpx.HTTPStatusError as e:
                await _handle_share_error(db, task, resource, account, e)
                return

            file_ids = _extract_file_ids(files_resp)
            if not file_ids:
                await _fail_final(db, task, resource, "分享文件列表为空", files_resp)
                return

            checkpoint["file_ids"] = file_ids
            task.checkpoint = checkpoint
            await db.commit()

        # STEP 4: 转存到自己账号
        if "restore_done" not in checkpoint:
            try:
                restore_resp = await client.restore_share(
                    access_token=checkpoint["share_access_token"],
                    file_ids=checkpoint["file_ids"],
                    parent_id=account.default_parent_id or "",
                )
            except httpx.HTTPStatusError as e:
                await _handle_transfer_error(db, task, resource, account, e)
                return

            checkpoint["restore_done"] = True
            checkpoint["restore_resp"] = restore_resp
            task.checkpoint = checkpoint
            await db.commit()

        # STEP 5: 创建新分享
        if "new_share_link" not in checkpoint:
            # 获取转存后的文件 ID
            transferred_file_ids = checkpoint["file_ids"]

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

            new_share_id = _extract_new_share_id(share_resp)
            if not new_share_id:
                # 尝试从分享列表获取
                try:
                    list_resp = await client.get_share_list(page=0)
                    new_share_id = _find_share_id_from_list(list_resp, resource.name)
                except Exception:
                    pass

            if not new_share_id:
                await _fail_retryable(db, task, resource, "创建分享成功但无法获取分享ID", retry_minutes=2)
                return

            new_link = build_share_link(new_share_id, new_code)
            checkpoint["new_share_id"] = new_share_id
            checkpoint["new_extract_code"] = new_code
            checkpoint["new_share_link"] = new_link
            task.checkpoint = checkpoint
            await db.commit()

        # STEP 6: 更新资源记录，标记成功
        resource.status = "待推送"
        resource.transfer_account_id = account.id
        resource.transferred_file_id = ",".join(checkpoint.get("file_ids", []))
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

        await db.commit()
        logger.info(f"转存成功: resource_id={resource.id}, new_link={resource.new_share_link}")

    except Exception as e:
        logger.error(f"转存异常: task_id={task.id}, error={e}")
        await _fail_retryable(db, task, resource, f"未知错误: {str(e)[:500]}")


# ===== 辅助函数 =====

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


def _extract_new_share_id(resp: dict) -> Optional[str]:
    if isinstance(resp, dict):
        data = resp.get("data", resp)
        # 优先找带 _ 的完整 publicShareId
        for key in ("publicShareId", "shareId", "id"):
            val = data.get(key)
            if val and "_" in str(val):
                return str(val)
        # 退而求其次
        for key in ("publicShareId", "shareId", "id"):
            val = data.get(key)
            if val:
                return str(val)
    return None


def _find_share_id_from_list(resp: dict, title: str) -> Optional[str]:
    if isinstance(resp, dict):
        data = resp.get("data", resp)
        shares = data.get("list") or data.get("shares") or []
        for s in shares:
            sid = s.get("publicShareId") or s.get("id") or ""
            if "_" in str(sid):
                return str(sid)
    return None


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
    await db.commit()
    logger.warning(f"任务可重试失败: task_id={task.id}, attempt={task.attempt}, msg={message}")


async def _fail_final(
    db: AsyncSession, task: Task, resource: Resource,
    message: str, resp: dict = None,
):
    task.status = "failed_final"
    task.error_message = message
    task.error_response = resp
    task.completed_at = datetime.now(timezone.utc)
    resource.status = "最终失败"
    resource.error_message = message
    resource.error_response = resp
    await db.commit()
    logger.error(f"任务最终失败: task_id={task.id}, msg={message}")


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
        await _fail_final(db, task, resource, "分享链接无效或已失效", resp_body)
    elif status_code == 403:
        await _fail_final(db, task, resource, "提取码错误或无权访问", resp_body)
    else:
        await _fail_retryable(db, task, resource, f"分享接口错误 HTTP {status_code}", resp_body)


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
        await _fail_retryable(db, task, resource, "账号登录失效", resp_body)
    elif status_code == 429:
        await mark_account_rate_limited(db, account)
        await _fail_retryable(db, task, resource, "账号被风控限制", resp_body, retry_minutes=10)
    elif status_code == 507 or "容量" in str(resp_body):
        await mark_account_full(db, account)
        # 清除 checkpoint 中的 account_id，下次重试会选新账号
        checkpoint = task.checkpoint or {}
        checkpoint.pop("account_id", None)
        task.checkpoint = checkpoint
        await _fail_retryable(db, task, resource, "账号容量不足", resp_body)
    else:
        await mark_account_error(db, account, f"HTTP {status_code}")
        await _fail_retryable(db, task, resource, f"转存接口错误 HTTP {status_code}", resp_body)
