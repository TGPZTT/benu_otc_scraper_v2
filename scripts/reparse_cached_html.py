import gzip
import json
import sys
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


RAW_DIR = Path("data/raw_html")


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

    init_db()
    settings = Settings()
    processed = missing_cache = changed = errors = 0
    deleted_orphan_ingredients = 0

    with SessionLocal() as session:
        products = session.query(Product).order_by(Product.url).all()
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
                processed += 1
            except Exception as exc:
                errors += 1
                print(f"ERROR {product.url}: {type(exc).__name__}: {exc}")

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
