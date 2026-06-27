from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.database import engine
from app.api.router import api_router
from app.services.schema_service import initialize_database
from app.telegram_bot.runtime import start_configured_bots, stop_bots


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.auth_service import ensure_admin_exists
    from app.database import async_session

    async with engine.begin() as conn:
        await initialize_database(conn)

    async with async_session() as session:
        await ensure_admin_exists(session)

    start_configured_bots()
    try:
        yield
    finally:
        await stop_bots()
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
