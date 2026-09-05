from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.migrate import upgrade_head
from app.routers import auth as auth_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    upgrade_head()
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


@app.get("/health")
def health():
    return {"ok": True, "service": "steward"}
