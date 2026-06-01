from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.models import Base
from app.api.router import api_router


async def ensure_runtime_indexes(conn):
    statements = [
        "CREATE EXTENSION IF NOT EXISTS pg_trgm",
        "CREATE INDEX IF NOT EXISTS idx_resources_status_created_at ON resources (status, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_resources_transferred_at ON resources (transferred_at)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_status_created_at ON tasks (status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_push_records_resource_status ON telegram_push_records (resource_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_resources_name_trgm ON resources USING gin (name gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS idx_resources_tags_trgm ON resources USING gin (tags gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS idx_resources_original_link_trgm ON resources USING gin (original_link gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS idx_resources_new_share_link_trgm ON resources USING gin (new_share_link gin_trgm_ops)",
    ]
    for statement in statements:
        await conn.execute(text(statement))


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.auth_service import ensure_admin_exists
    from app.database import async_session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_indexes(conn)

    async with async_session() as session:
        await ensure_admin_exists(session)
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
