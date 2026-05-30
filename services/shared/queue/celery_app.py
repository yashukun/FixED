import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Document processing is long-running and idempotent enough to re-run, so the
# defaults below favour not losing work over raw throughput. Hard/soft time
# limits and result expiry are env-tunable.
_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "1800"))          # 30 min hard kill
_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "1500"))  # 25 min soft
_RESULT_EXPIRES = int(os.getenv("CELERY_RESULT_EXPIRES", "86400"))           # 1 day

celery_app = Celery(
    "fixed_queue",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks"],  # Tasks will be discovered here
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    # Reliability: ack only after the task finishes, and requeue if a worker is
    # lost mid-task (so a crashed/replaced Fargate task doesn't drop a job).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Long jobs: one at a time per worker process, no greedy prefetch.
    worker_prefetch_multiplier=1,
    # Bound runaway tasks.
    task_time_limit=_TASK_TIME_LIMIT,
    task_soft_time_limit=_TASK_SOFT_TIME_LIMIT,
    # Don't let Redis fill up with stale results.
    result_expires=_RESULT_EXPIRES,
    # Survive ElastiCache failovers / transient broker blips.
    broker_connection_retry=True,
    broker_transport_options={"visibility_timeout": _TASK_TIME_LIMIT + 60},
)
