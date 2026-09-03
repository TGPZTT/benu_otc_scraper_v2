import argparse
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    base_url: str = os.getenv("BENU_BASE_URL", "https://benu.hu").rstrip("/")
    request_delay_min: float = float(os.getenv("REQUEST_DELAY_MIN", "0.8"))
    request_delay_max: float = float(os.getenv("REQUEST_DELAY_MAX", "1.8"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "4"))
    respect_robots: bool = os.getenv("RESPECT_ROBOTS", "1").lower() in {"1","true","yes"}
    max_products: int = int(os.getenv("MAX_PRODUCTS", "0"))
    force_rescrape: bool = os.getenv("FORCE_RESCRAPE", "0").lower() in {"1","true","yes"}
    save_raw_html: bool = os.getenv("SAVE_RAW_HTML", "1").lower() in {"1","true","yes"}
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

def parse_settings():
    parser=argparse.ArgumentParser(description="BENU OTC scraper")
    parser.add_argument("--all", action="store_true", help="scrape all discovered products")
    parser.add_argument("--limit", type=int, default=None, help="limit number of products")
    parser.add_argument("--fresh", action="store_true", help="backup existing DB and create a fresh DB")
    parser.add_argument("--force", action="store_true", help="force re-scrape")
    args=parser.parse_args()

    s=Settings()
    if args.all:
        s.max_products=0
    if args.limit is not None:
        s.max_products=args.limit
    if args.force:
        s.force_rescrape=True
    return s,args
