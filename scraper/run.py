import gzip
import logging
from pathlib import Path
from tqdm import tqdm

from scraper.http import BenuHttpClient
from scraper.crawler import BenuCrawler
from scraper.parser import parse_product
from scraper.db import (
    init_db,SessionLocal,Product,ScrapeRun,ScrapeError,upsert_product
)
from scraper.robots import RobotsGuard
from scraper.utils import utcnow,sha256_bytes
from config import Settings

log=logging.getLogger(__name__)

def save_raw_html(url,html,subdir="raw_html"):
    raw_dir=Path("data") / subdir
    raw_dir.mkdir(parents=True,exist_ok=True)
    filename=sha256_bytes(url.encode("utf-8"))+".html.gz"
    path=raw_dir/filename
    with gzip.open(path,"wt",encoding="utf-8") as f:
        f.write(html)
    return path

def run(settings: Settings):
    init_db()
    client=BenuHttpClient(settings)

    if settings.respect_robots:
        guard=RobotsGuard(settings.base_url,client.session.headers["User-Agent"])
        # Do not use the normal client for robots.txt because that would add a
        # scrape delay. A direct request is enough here.
        import requests
        try:
            r=requests.get(
                settings.base_url+"/robots.txt",
                headers={"User-Agent":client.session.headers["User-Agent"]},
                timeout=settings.request_timeout
            )
            guard.rp.parse(r.text.splitlines())
            guard.available=True
        except Exception as exc:
            log.warning("robots.txt could not be checked: %s",exc)
    else:
        guard=None

    crawler=BenuCrawler(client,settings.base_url)
    urls=crawler.discover_product_urls()

    if settings.max_products>0:
        urls=urls[:settings.max_products]

    started=utcnow()
    with SessionLocal() as session:
        run_row=ScrapeRun(started_at=started,discovered_urls=len(urls))
        session.add(run_row)
        session.commit()
        run_id=run_row.id

    log.info("Starting scrape of %d product URLs.",len(urls))

    processed=otc=non_otc=unknown=errors=incomplete=0

    for url in tqdm(urls,desc="BENU products",unit="product"):
        try:
            if guard and not guard.allowed(url):
                raise PermissionError("Blocked by robots.txt")

            response=client.get(url)
            html=response.text

            data=parse_product(html,url,settings.base_url)

            # Parser failures should never become DB constraint failures.
            # Missing classification is represented explicitly as UNKNOWN.
            data["classification"] = data.get("classification") or "UNKNOWN"
            if data.get("is_incomplete"):
                incomplete += 1
                log.warning(
                    "Incomplete product page: %s | warnings=%s | name=%r classification=%r price=%r ean=%r",
                    url, ",".join(data.get("parse_warnings",[])),
                    data.get("name"), data.get("classification_raw"),
                    data.get("price_huf"), data.get("ean")
                )
                save_raw_html(url,html,"incomplete_html")

            if settings.save_raw_html:
                save_raw_html(url,html)

            with SessionLocal() as session:
                upsert_product(session,data)

            processed+=1
            if data["classification"]=="OTC":
                otc+=1
            elif data["classification"]=="UNKNOWN":
                unknown+=1
            else:
                non_otc+=1

        except Exception as exc:
            errors+=1
            log.exception("Failed %s",url)
            # Preserve the exact response for diagnosing BENU pages that use a
            # different template, challenge page, or otherwise break parsing.
            try:
                if "html" in locals() and html:
                    save_raw_html(url,html,"failed_html")
            except Exception as debug_exc:
                log.warning("Could not save failed HTML for %s: %s",url,debug_exc)
            with SessionLocal() as session:
                session.add(ScrapeError(
                    run_id=run_id,
                    url=url,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                ))
                session.commit()

    finished=utcnow()
    with SessionLocal() as session:
        row=session.get(ScrapeRun,run_id)
        row.finished_at=finished
        row.processed=processed
        row.otc_count=otc
        row.non_otc_count=non_otc
        row.unknown_count=unknown
        row.incomplete_count=incomplete
        row.errors=errors
        session.commit()

    log.info(
        "DONE discovered=%d processed=%d OTC=%d non_OTC=%d UNKNOWN=%d incomplete=%d errors=%d",
        len(urls),processed,otc,non_otc,unknown,incomplete,errors
    )
