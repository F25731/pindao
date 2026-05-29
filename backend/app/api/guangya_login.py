from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
import httpx
from secrets import token_hex
from hashlib import md5
from os import urandom

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AdminUser, GuangyaAccount
from app.config import settings

router = APIRouter()

CLIENT_ID = "aMe-8VSlkrbQXpUR"

# 临时存储登录流程状态
_login_sessions = {}


def _generate_did() -> str:
    return md5(urandom(16)).hexdigest()


def _generate_traceparent() -> str:
    return f"00-{token_hex(16)}-{token_hex(8)}-01"


def _account_headers(device_id: str) -> dict:
    return {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://www.guangyapan.com",
        "referer": "https://www.guangyapan.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "x-client-id": CLIENT_ID,
        "x-client-version": "0.0.1",
        "x-device-id": device_id,
        "x-device-model": "chrome%2F147.0.0.0",
        "x-device-name": "PC-Chrome",
        "x-device-sign": f"wdi10.{device_id}{token_hex(16)}",
        "x-net-work-type": "NONE",
        "x-os-version": "MacIntel",
        "x-platform-version": "1",
        "x-protocol-version": "301",
        "x-provider-name": "NONE",
        "x-sdk-version": "9.0.2",
    }


def _normalize_phone(raw: str) -> str:
    phone = raw.replace("+86 ", "").replace("+86", "").strip()
    return f"+86 {phone}" if phone else ""


class SmsInitRequest(BaseModel):
    phone: str


class SmsSendRequest(BaseModel):
    phone: str
    session_key: str


class SmsVerifyRequest(BaseModel):
    session_key: str
    code: str


class SmsSigninRequest(BaseModel):
    session_key: str
    code: str
    account_name: Optional[str] = None


@router.post("/sms/init")
async def sms_init(
    req: SmsInitRequest,
    user: AdminUser = Depends(get_current_user),
):
    """初始化短信登录，获取 captcha_token。"""
    phone_number = _normalize_phone(req.phone)
    if not phone_number:
        raise HTTPException(status_code=400, detail="手机号格式错误")

    device_id = _generate_did()
    headers = _account_headers(device_id)

    body = {
        "client_id": CLIENT_ID,
        "action": "POST:/v1/auth/verification",
        "device_id": device_id,
        "meta": {"phone_number": phone_number},
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{settings.guangya_account_base}/v1/shield/captcha/init",
            headers=headers,
            json=body,
        )

    result = resp.json()

    if result.get("url"):
        raise HTTPException(status_code=400, detail="需要人机验证，请稍后再试")

    captcha_token = result.get("captcha_token")
    if not captcha_token:
        raise HTTPException(status_code=400, detail=f"初始化失败: {result}")

    session_key = token_hex(16)
    _login_sessions[session_key] = {
        "phone": req.phone,
        "phone_number": phone_number,
        "device_id": device_id,
        "captcha_token": captcha_token,
        "step": "init",
    }

    return {"session_key": session_key, "message": "初始化成功，请发送验证码"}


@router.post("/sms/send")
async def sms_send(
    req: SmsSendRequest,
    user: AdminUser = Depends(get_current_user),
):
    """发送短信验证码。"""
    session_data = _login_sessions.get(req.session_key)
    if not session_data:
        raise HTTPException(status_code=400, detail="登录会话不存在或已过期")

    phone_number = _normalize_phone(req.phone)
    device_id = session_data["device_id"]
    captcha_token = session_data["captcha_token"]

    headers = _account_headers(device_id)
    headers["x-captcha-token"] = captcha_token

    body = {
        "phone_number": phone_number,
        "target": "ANY",
        "client_id": CLIENT_ID,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{settings.guangya_account_base}/v1/auth/verification",
            headers=headers,
            json=body,
        )

    result = resp.json()
    verification_id = result.get("verification_id")
    if not verification_id:
        raise HTTPException(status_code=400, detail=f"发送验证码失败: {result}")

    session_data["verification_id"] = verification_id
    session_data["step"] = "sent"

    return {"message": "验证码已发送", "session_key": req.session_key}


@router.post("/sms/verify")
async def sms_verify(
    req: SmsVerifyRequest,
    user: AdminUser = Depends(get_current_user),
):
    """校验验证码。"""
    session_data = _login_sessions.get(req.session_key)
    if not session_data or session_data.get("step") != "sent":
        raise HTTPException(status_code=400, detail="登录会话不存在或步骤错误")

    device_id = session_data["device_id"]
    verification_id = session_data["verification_id"]

    headers = _account_headers(device_id)
    body = {
        "verification_id": verification_id,
        "verification_code": req.code,
        "client_id": CLIENT_ID,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{settings.guangya_account_base}/v1/auth/verification/verify",
            headers=headers,
            json=body,
        )

    result = resp.json()
    verification_token = result.get("verification_token")
    if not verification_token:
        raise HTTPException(status_code=400, detail=f"验证码校验失败: {result}")

    session_data["verification_token"] = verification_token
    session_data["step"] = "verified"

    return {"message": "验证码校验成功", "session_key": req.session_key}


@router.post("/sms/signin")
async def sms_signin(
    req: SmsSigninRequest,
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """完成登录并自动添加到账号池。"""
    session_data = _login_sessions.get(req.session_key)
    if not session_data or session_data.get("step") != "verified":
        raise HTTPException(status_code=400, detail="登录会话不存在或步骤错误")

    device_id = session_data["device_id"]
    phone_number = session_data["phone_number"]
    captcha_token = session_data["captcha_token"]
    verification_token = session_data["verification_token"]

    headers = _account_headers(device_id)
    headers["x-captcha-token"] = captcha_token

    body = {
        "verification_code": req.code,
        "verification_token": verification_token,
        "username": phone_number,
        "client_id": CLIENT_ID,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{settings.guangya_account_base}/v1/auth/signin",
            headers=headers,
            json=body,
        )

    result = resp.json()
    access_token = result.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail=f"登录失败: {result}")

    refresh_token = result.get("refresh_token", "")
    expires_in = result.get("expires_in")

    # 清理登录会话
    _login_sessions.pop(req.session_key, None)

    # 添加到账号池
    from datetime import datetime, timezone, timedelta

    account_name = req.account_name or session_data["phone"]
    token_expires_at = None
    if expires_in:
        token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    account = GuangyaAccount(
        name=account_name,
        access_token=access_token,
        refresh_token=refresh_token,
        device_id=device_id,
        token_expires_at=token_expires_at,
        default_parent_id="",
        priority=0,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    return {
        "message": "登录成功，账号已添加到账号池",
        "account_id": account.id,
        "account_name": account.name,
    }
