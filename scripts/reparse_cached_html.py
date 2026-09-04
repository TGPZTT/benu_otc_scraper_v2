import gzip
import json
import sys
import time
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings
from scraper.db import (
    Ingredient,
    Product,
    ProductIngredient,
    SessionLocal,
    init_db,
)
from scraper.parser import parse_product
from scraper.utils import sha256_bytes, utcnow


DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw_html"
INCOMPLETE_DIR = DATA_DIR / "incomplete_html"


PRODUCT_FIELDS = [
    "name",
    "brand",
    "sku",
    "ean",
    "classification",
    "classification_raw",
    "classification_source",
    "price_huf",
    "unit_price",
    "lowest_30d_price_huf",
    "original_price_huf",
    "sale_price_huf",
    "active_ingredient_raw",
    "active_ingredient_source",
    "strength",
    "pharmaceutical_form",
    "package_size",
    "product_information",
    "description",
    "leaflet_text",
    "distributor",
    "manufacturer",
    "registration_number",
    "json_ld",
    "raw_text",
    "raw_html_hash",
    "is_incomplete",
]


def cached_html_path(url):
    return RAW_DIR / f"{sha256_bytes(url.encode('utf-8'))}.html.gz"


def incomplete_html_path(url):
    return INCOMPLETE_DIR / f"{sha256_bytes(url.encode('utf-8'))}.html.gz"


def write_gzip_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(text)


def reset_incomplete_html_dir():
    data_root = DATA_DIR.resolve()
    target = INCOMPLETE_DIR.resolve()
    if data_root not in target.parents:
        raise RuntimeError(f"Refusing to clear unexpected path: {target}")
    INCOMPLETE_DIR.mkdir(parents=True, exist_ok=True)
    for path in INCOMPLETE_DIR.glob("*.html.gz"):
        path.unlink()


def update_cached_product(session, product, data):
    now = utcnow()
    old_snapshot = {
        field: getattr(product, field)
        for field in PRODUCT_FIELDS
        if hasattr(product, field)
    }

    data["classification"] = data.get("classification") or "UNKNOWN"
    data["name"] = (
        data.get("name")
        or data["url"].rstrip("/").split("/")[-1]
        or "Ismeretlen termék"
    )

    for field in PRODUCT_FIELDS:
        if field in data and hasattr(product, field):
            setattr(product, field, data[field])

    product.breadcrumbs_json = json.dumps(data.get("breadcrumbs", []), ensure_ascii=False)
    product.images_json = json.dumps(data.get("images", []), ensure_ascii=False)
    product.statuses_json = json.dumps(data.get("statuses", []), ensure_ascii=False)
    product.parse_warnings_json = json.dumps(
        data.get("parse_warnings", []),
        ensure_ascii=False,
    )

    changed = any(
        getattr(product, field) != old_snapshot[field]
        for field in old_snapshot
    )
    if changed:
        product.last_changed_at = now

    for rel in list(product.ingredients):
        session.delete(rel)
    session.flush()

    for ingredient_name in data.get("ingredient_names", []):
        ing = session.query(Ingredient).filter_by(name=ingredient_name).one_or_none()
        if ing is None:
            ing = Ingredient(name=ingredient_name)
            session.add(ing)
            session.flush()
        session.add(
            ProductIngredient(
                product=product,
                ingredient=ing,
                raw_amount=data.get("active_ingredient_raw"),
            )
        )

    return changed


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Reparse cached BENU raw HTML into the local database."
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Reparse only the given product URL. Can be passed multiple times.",
    )
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument(
        "--commit-every",
        type=int,
        default=0,
        help="Commit every N processed rows. Default 0 keeps one transaction.",
    )
    parser.add_argument(
        "--sync-incomplete-html",
        action="store_true",
        help="Rewrite data/incomplete_html from the newly parsed quality flags.",
    )
    args = parser.parse_args()

    init_db()
    settings = Settings()
    processed = missing_cache = changed = errors = synced_incomplete_html = 0
    deleted_orphan_ingredients = 0
    started_at = time.monotonic()
    if args.sync_incomplete_html:
        reset_incomplete_html_dir()

    with SessionLocal() as session:
        query = session.query(Product).order_by(Product.url)
        if args.url:
            query = query.filter(Product.url.in_(args.url))
        if args.limit:
            query = query.limit(args.limit)
        products = query.all()
        total = len(products)
        for product in products:
            path = cached_html_path(product.url)
            if not path.exists():
                missing_cache += 1
                continue
            try:
                html = gzip.open(path, "rt", encoding="utf-8", errors="ignore").read()
                data = parse_product(html, product.url, settings.base_url)
                if update_cached_product(session, product, data):
                    changed += 1
                if args.sync_incomplete_html and data.get("is_incomplete"):
                    write_gzip_text(incomplete_html_path(product.url), html)
                    synced_incomplete_html += 1
                processed += 1
            except Exception as exc:
                errors += 1
                print(f"ERROR {product.url}: {type(exc).__name__}: {exc}")
            if args.commit_every and processed and processed % args.commit_every == 0:
                session.commit()
            if args.progress_every and (processed + missing_cache + errors) % args.progress_every == 0:
                elapsed = max(time.monotonic() - started_at, 0.001)
                print(
                    json.dumps(
                        {
                            "progress": processed + missing_cache + errors,
                            "total": total,
                            "processed": processed,
                            "changed": changed,
                            "missing_cache": missing_cache,
                            "errors": errors,
                            "synced_incomplete_html": synced_incomplete_html,
                            "rows_per_second": round(processed / elapsed, 2),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

        orphan_ingredients = (
            session.query(Ingredient)
            .outerjoin(ProductIngredient)
            .filter(ProductIngredient.id.is_(None))
            .all()
        )
        for ingredient in orphan_ingredients:
            session.delete(ingredient)
            deleted_orphan_ingredients += 1

        session.commit()

    print(
        json.dumps(
            {
                "processed": processed,
                "changed": changed,
                "missing_cache": missing_cache,
                "deleted_orphan_ingredients": deleted_orphan_ingredients,
                "synced_incomplete_html": synced_incomplete_html,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
