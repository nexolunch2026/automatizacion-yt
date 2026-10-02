from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("faceless", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,  # si un worker muere, la tarea vuelve a la cola
    worker_prefetch_multiplier=1,
    task_track_started=True,
)


@celery_app.task(name="system.ping")
def ping() -> str:
    return "pong"
