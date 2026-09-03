import logging
from pathlib import Path

from config import parse_settings
from scraper.db import backup_db
from scraper.run import run

settings,args=parse_settings()

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=getattr(logging,settings.log_level,logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/scraper.log",encoding="utf-8")
    ]
)

if __name__=="__main__":
    if args.fresh:
        backup=backup_db()
        if backup:
            print(f"Existing database backed up to: {backup}")
    run(settings)
