from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.database import engine
from app.models import Base
from app.api.router import api_router
from app.services.schema_service import ensure_runtime_indexes, ensure_runtime_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.auth_service import ensure_admin_exists
    from app.database import async_session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_schema(conn)
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
