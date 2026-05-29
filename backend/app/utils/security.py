from hashlib import md5, sha256
from os import urandom
from secrets import token_hex, token_urlsafe


def generate_device_id() -> str:
    return md5(urandom(16)).hexdigest()


def generate_api_key() -> str:
    return f"gyrb_{token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    return sha256(key.encode()).hexdigest()


def mask_token(token: str, show_chars: int = 4) -> str:
    if not token or len(token) <= show_chars * 2:
        return "***"
    return f"{token[:show_chars]}...{token[-show_chars:]}"
