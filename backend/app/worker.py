from time import sleep
import logging
import os

from app.db import SessionLocal
from app.migrate import upgrade_head
from app.pipeline import after_new_mail
from app.sync import sync_all

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("steward.worker")

INTERVAL = int(os.environ.get("SYNC_INTERVAL_SEC", "45"))


def main():
    upgrade_head()
    log.info("worker up, interval=%ss", INTERVAL)
    while True:
        db = SessionLocal()
        try:
            n = sync_all(db, on_new=after_new_mail)
            db.commit()
            if n:
                log.info("synced %s new messages", n)
        except Exception:
            db.rollback()
            log.exception("sync loop crashed")
        finally:
            db.close()
        sleep(INTERVAL)


if __name__ == "__main__":
    main()
