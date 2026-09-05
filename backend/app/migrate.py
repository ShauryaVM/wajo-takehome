from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade_head() -> None:
    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini))
    command.upgrade(cfg, "head")
