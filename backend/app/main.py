from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import SessionLocal
from app.migrate import upgrade_head
from app.routers import accounts as accounts_router
from app.routers import analytics as analytics_router
from app.routers import auth as auth_router
from app.routers import mail as mail_router
from app.routers import settings as settings_router
from app.seed import seed_if_empty

log = logging.getLogger("steward.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    upgrade_head()
    db = SessionLocal()
    try:
        seed_if_empty(db)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("seed failed")
        raise
    finally:
        db.close()
    yield


app = FastAPI(title="Steward", docs_url="/docs", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_origin, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(mail_router.router)
app.include_router(accounts_router.router)
app.include_router(settings_router.router)
app.include_router(analytics_router.router)


@app.get("/health")
def health():
    return {"ok": True, "service": "steward"}
