import os

from celery import Celery

# Placeholder Celery app; tasks are added in later steps
celery_app = Celery("short_video", broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
