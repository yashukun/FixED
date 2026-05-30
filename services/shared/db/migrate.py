"""One-shot schema migration entrypoint.

Run as the dedicated migration job (ECS task, ``docker compose run migrate``,
or in CI before deploying services)::

    python -m db.migrate

Applies all Alembic migrations up to head. This is the ONLY place schema/DDL is
applied — application services never run DDL on startup. The database URL is
read from POSTGRES_URL by the Alembic env; point it at a privileged role so the
``CREATE EXTENSION vector`` in the baseline migration can run.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent


def run_migrations() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = Config(str(HERE / "alembic.ini"))
    cfg.set_main_option("script_location", str(HERE / "migrations"))
    logger.info("Applying Alembic migrations to head...")
    command.upgrade(cfg, "head")
    logger.info("Migrations complete.")


if __name__ == "__main__":
    run_migrations()
