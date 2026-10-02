from collections.abc import Callable

import redis
from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.storage import get_s3
from app.db.session import engine
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/health", tags=["health"])


def _check_db() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def _check_redis() -> None:
    redis.Redis.from_url(get_settings().redis_url, socket_timeout=2).ping()


def _check_storage() -> None:
    get_s3().head_bucket(Bucket=get_settings().s3_bucket)


def _check_worker() -> None:
    if celery_app.send_task("system.ping").get(timeout=5) != "pong":
        raise RuntimeError("respuesta inesperada del worker")


CHECKS: dict[str, Callable[[], None]] = {
    "database": _check_db,
    "redis": _check_redis,
    "storage": _check_storage,
    "worker": _check_worker,
}


@router.get("")
def health() -> dict:
    services: dict[str, dict] = {}
    for name, check in CHECKS.items():
        try:
            check()
            services[name] = {"ok": True}
        except Exception as exc:  # noqa: BLE001 — se informa cualquier fallo
            services[name] = {"ok": False, "error": str(exc)[:200]}
    return {"ok": all(s["ok"] for s in services.values()), "services": services}
