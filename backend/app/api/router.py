from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.accounts import router as accounts_router
from app.api.imports import router as imports_router
from app.api.resources import router as resources_router
from app.api.tasks import router as tasks_router
from app.api.duplicates import router as duplicates_router
from app.api.telegram import router as telegram_router
from app.api.api_keys import router as api_keys_router
from app.api.export import router as export_router
from app.api.stats import router as stats_router
from app.api.external import router as external_router
from app.api.guangya_login import router as guangya_login_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["认证"])
api_router.include_router(accounts_router, prefix="/accounts", tags=["账号池"])
api_router.include_router(guangya_login_router, prefix="/accounts/login", tags=["光鸭登录"])
api_router.include_router(imports_router, prefix="/imports", tags=["导入"])
api_router.include_router(resources_router, prefix="/resources", tags=["资源"])
api_router.include_router(tasks_router, prefix="/tasks", tags=["任务"])
api_router.include_router(duplicates_router, prefix="/duplicates", tags=["去重审核"])
api_router.include_router(telegram_router, prefix="/telegram", tags=["推送管理"])
api_router.include_router(api_keys_router, prefix="/api-keys", tags=["API密钥"])
api_router.include_router(export_router, prefix="/export", tags=["导出"])
api_router.include_router(stats_router, prefix="/stats", tags=["统计"])
api_router.include_router(external_router, prefix="/external", tags=["外部API"])
