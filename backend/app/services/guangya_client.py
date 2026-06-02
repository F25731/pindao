"""
光鸭云盘 API 异步客户端。
基于 guangyaclient SDK 源码重写为 async httpx 版本。
"""
import httpx
from hashlib import md5
from os import urandom
from secrets import token_hex
from time import time
from typing import Optional, List

from app.config import settings

CLIENT_ID = "aMe-8VSlkrbQXpUR"


def generate_did() -> str:
    return md5(urandom(16)).hexdigest()


def generate_traceparent() -> str:
    return f"00-{token_hex(16)}-{token_hex(8)}-01"


class GuangyaClient:
    """异步光鸭 API 客户端，每个账号实例化一个。"""

    def __init__(self, access_token: str, refresh_token: str, device_id: str):
        self.access_token = access_token
        self.refresh_token_value = refresh_token
        self.device_id = device_id
        self.token_expires_at: Optional[float] = None

    def _default_headers(self) -> dict:
        return {
            "accept": "application/json, text/plain, */*",
            "authorization": f"Bearer {self.access_token}",
            "content-type": "application/json",
            "did": self.device_id,
            "dt": "4",
            "origin": "https://www.guangyapan.com",
            "referer": "https://www.guangyapan.com/",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            "traceparent": generate_traceparent(),
        }

    def _account_headers(self) -> dict:
        return {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": "https://www.guangyapan.com",
            "referer": "https://www.guangyapan.com/",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            "x-client-id": CLIENT_ID,
            "x-client-version": "0.0.1",
            "x-device-id": self.device_id,
            "x-device-model": "chrome%2F147.0.0.0",
            "x-device-name": "PC-Chrome",
            "x-device-sign": f"wdi10.{self.device_id}{token_hex(16)}",
            "x-net-work-type": "NONE",
            "x-os-version": "MacIntel",
            "x-platform-version": "1",
            "x-protocol-version": "301",
            "x-provider-name": "NONE",
            "x-sdk-version": "9.0.2",
        }

    async def _request(self, url: str, json_data: dict = None, method: str = "POST") -> dict:
        headers = self._default_headers()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, url, headers=headers, json=json_data)

            if resp.status_code == 401 and self.refresh_token_value:
                refreshed = await self._refresh_token()
                if refreshed:
                    headers["authorization"] = f"Bearer {self.access_token}"
                    headers["traceparent"] = generate_traceparent()
                    resp = await client.request(method, url, headers=headers, json=json_data)

            resp.raise_for_status()
            return resp.json()

    async def _account_request(
        self,
        url: str,
        json_data: dict = None,
        method: str = "POST",
        timeout: int = 15,
    ) -> httpx.Response:
        headers = self._account_headers()
        headers["authorization"] = f"Bearer {self.access_token}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, headers=headers, json=json_data)

            if resp.status_code == 401 and self.refresh_token_value:
                refreshed = await self._refresh_token()
                if refreshed:
                    headers["authorization"] = f"Bearer {self.access_token}"
                    resp = await client.request(method, url, headers=headers, json=json_data)
            return resp

    async def _refresh_token(self) -> bool:
        headers = self._account_headers()
        headers["x-action"] = "401"
        body = {
            "client_id": CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token_value,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.guangya_account_base}/v1/auth/token",
                headers=headers,
                json=body,
            )
            if resp.status_code != 200:
                return False
            data = resp.json()
            if data.get("access_token"):
                self.access_token = data["access_token"]
                self.refresh_token_value = data.get("refresh_token", self.refresh_token_value)
                if data.get("expires_in"):
                    self.token_expires_at = time() + data["expires_in"]
                return True
        return False

    # ===== 分享公共接口 (不需要登录) =====

    @staticmethod
    async def share_access_token(share_id: str, code: str = "") -> dict:
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "did": generate_did(),
            "dt": "4",
            "origin": "https://www.guangyapan.com",
            "referer": "https://www.guangyapan.com/",
            "traceparent": generate_traceparent(),
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.guangya_api_base}/nd.bizuserres.s/v1/get_share_access_token",
                headers=headers,
                json={"shareId": share_id, "code": code},
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def share_files_list(access_token: str, parent_id: str = "", page: int = 1) -> dict:
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "did": generate_did(),
            "dt": "4",
            "origin": "https://www.guangyapan.com",
            "referer": "https://www.guangyapan.com/",
            "traceparent": generate_traceparent(),
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.guangya_api_base}/nd.bizuserres.s/v1/get_share_page_files_list",
                headers=headers,
                json={
                    "accessToken": access_token,
                    "parentId": parent_id,
                    "page": page,
                    "pageSize": 50,
                    "orderBy": 0,
                    "sortType": 0,
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ===== 需要登录的接口 =====

    async def restore_share(self, access_token: str, file_ids: List[str], parent_id: str = "") -> dict:
        return await self._request(
            f"{settings.guangya_api_base}/nd.bizuserres.s/v1/restore_share",
            {"accessToken": access_token, "fileIds": file_ids, "parentId": parent_id},
        )

    async def create_share(
        self,
        file_ids: List[str],
        title: str,
        code: str = "",
        validate_duration: int = 0,
    ) -> dict:
        payload = {
            "fileIds": file_ids,
            "title": title,
            "validateDuration": validate_duration,
            "shareType": 0,
            "autoFillCode": False,
            "trafficLimit": "0",
            "maxRestoreCount": 0,
            "downloadType": 1,
        }
        if code:
            payload["code"] = code
        return await self._request(
            f"{settings.guangya_api_base}/nd.bizuserres.s/v1/share_file",
            payload,
        )

    async def get_file_list(self, parent_id: str = "", page: int = 0) -> dict:
        return await self._request(
            f"{settings.guangya_api_base}/nd.bizuserres.s/v1/file/get_file_list",
            {
                "parentId": parent_id,
                "page": page,
                "pageSize": 200,
                "orderBy": 3,
                "sortType": 1,
            },
        )

    async def get_share_list(self, page: int = 0) -> dict:
        return await self._request(
            f"{settings.guangya_api_base}/nd.bizuserres.s/v1/get_share_list",
            {"page": page, "pageSize": 50, "orderType": 1, "sortType": 1},
        )

    async def user_info(self) -> dict:
        candidates = [
            ("POST", f"{settings.guangya_account_base}/v1/user/me"),
            ("GET", f"{settings.guangya_account_base}/v1/user/me"),
            ("POST", f"{settings.guangya_account_base}/v1/user/info"),
            ("GET", f"{settings.guangya_account_base}/v1/user/info"),
            ("POST", f"{settings.guangya_account_base}/v1/user/profile"),
            ("GET", f"{settings.guangya_account_base}/v1/user/profile"),
        ]
        last_resp: httpx.Response | None = None
        for method, url in candidates:
            resp = await self._account_request(url, method=method)
            last_resp = resp
            if resp.status_code in (404, 405, 501):
                continue
            resp.raise_for_status()
            return resp.json()

        return {
            "_capacity_refresh_unsupported": True,
            "message": "光鸭账号容量接口暂不可用，转存时会按光鸭实际返回自动识别满盘",
            "last_status_code": last_resp.status_code if last_resp else None,
        }
