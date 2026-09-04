import argparse
import gzip
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.db import (  # noqa: E402
    Ingredient,
    Product,
    ProductIngredient,
    SessionLocal,
    init_db,
)
from scraper.utils import sha256_bytes, utcnow  # noqa: E402


DEFAULT_REFERENCE = ROOT / "reference" / "curated_product_enrichment.json"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw_html"
INCOMPLETE_DIR = DATA_DIR / "incomplete_html"

CRITICAL_WARNINGS = {
    "missing_price",
    "missing_sku",
    "unknown_classification",
    "missing_active_ingredient_for_otc",
    "short_raw_text",
}


def load_json_value(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def load_reference(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    products = payload.get("products")
    if not isinstance(products, list):
        raise ValueError(f"Reference file has no products list: {path}")
    return products


def validate_entry(entry):
    required = [
        "url",
        "active_ingredient_raw",
        "ingredient_names",
        "active_ingredient_source",
        "evidence_urls",
    ]
    missing = [field for field in required if not entry.get(field)]
    if missing:
        raise ValueError(f"Curated entry is missing {missing}: {entry.get('url')}")
    if not isinstance(entry["ingredient_names"], list):
        raise ValueError(f"ingredient_names must be a list: {entry.get('url')}")
    if not isinstance(entry["evidence_urls"], list):
        raise ValueError(f"evidence_urls must be a list: {entry.get('url')}")


def cached_html_path(url):
    return RAW_DIR / f"{sha256_bytes(url.encode('utf-8'))}.html.gz"


def incomplete_html_path(url):
    return INCOMPLETE_DIR / f"{sha256_bytes(url.encode('utf-8'))}.html.gz"


def reset_incomplete_html_dir():
    data_root = DATA_DIR.resolve()
    target = INCOMPLETE_DIR.resolve()
    if data_root not in target.parents:
        raise RuntimeError(f"Refusing to clear unexpected path: {target}")
    INCOMPLETE_DIR.mkdir(parents=True, exist_ok=True)
    for path in INCOMPLETE_DIR.glob("*.html.gz"):
        path.unlink()


def copy_incomplete_html(product):
    source = cached_html_path(product.url)
    if not source.exists():
        return False
    target = incomplete_html_path(product.url)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def remove_resolved_warnings(product, removed_warning_names):
    warnings = load_json_value(product.parse_warnings_json, [])
    warnings = [w for w in warnings if w not in removed_warning_names]
    product.parse_warnings_json = json.dumps(warnings, ensure_ascii=False)
    product.is_incomplete = any(w in CRITICAL_WARNINGS for w in warnings)
    return warnings


def snapshot_product(product):
    return {
        "active_ingredient_raw": product.active_ingredient_raw,
        "active_ingredient_source": product.active_ingredient_source,
        "registration_number": product.registration_number,
        "ingredients": [rel.ingredient.name for rel in product.ingredients],
        "warnings": load_json_value(product.parse_warnings_json, []),
        "is_incomplete": product.is_incomplete,
    }


def ensure_ingredient(session, name):
    ingredient = session.query(Ingredient).filter_by(name=name).one_or_none()
    if ingredient is None:
        ingredient = Ingredient(name=name)
        session.add(ingredient)
        session.flush()
    return ingredient


def apply_entry(session, product, entry):
    before = snapshot_product(product)
    now = utcnow()

    product.active_ingredient_raw = entry["active_ingredient_raw"]
    product.active_ingredient_source = entry["active_ingredient_source"]
    if entry.get("registration_number"):
        product.registration_number = entry["registration_number"]
    remove_resolved_warnings(product, {"missing_active_ingredient_for_otc"})

    for rel in list(product.ingredients):
        session.delete(rel)
    session.flush()

    for ingredient_name in entry["ingredient_names"]:
        ingredient = ensure_ingredient(session, ingredient_name)
        session.add(
            ProductIngredient(
                product=product,
                ingredient=ingredient,
                raw_amount=product.active_ingredient_raw,
            )
        )

    after = snapshot_product(product)
    if before != after:
        product.last_changed_at = now

    return {
        "url": product.url,
        "name": product.name,
        "match_name": entry.get("match_name"),
        "name_mismatch": (
            bool(entry.get("match_name"))
            and entry["match_name"].casefold() != product.name.casefold()
        ),
        "before": before,
        "after": after,
    }


def delete_orphan_ingredients(session):
    deleted = 0
    orphan_ingredients = (
        session.query(Ingredient)
        .outerjoin(ProductIngredient)
        .filter(ProductIngredient.id.is_(None))
        .all()
    )
    for ingredient in orphan_ingredients:
        session.delete(ingredient)
        deleted += 1
    return deleted


def sync_incomplete_html(session):
    reset_incomplete_html_dir()
    synced = 0
    missing_cache = 0
    for product in session.query(Product).filter_by(is_incomplete=True):
        if copy_incomplete_html(product):
            synced += 1
        else:
            missing_cache += 1
    return {"synced": synced, "missing_cache": missing_cache}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Apply source-backed curated product enrichments to the local DB."
    )
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--sync-incomplete-html",
        action="store_true",
        help="Rewrite data/incomplete_html after curated fixes are applied.",
    )
    args = parser.parse_args()

    entries = load_reference(args.reference)
    for entry in entries:
        validate_entry(entry)

    init_db()
    applied = []
    missing_products = []
    deleted_orphan_ingredients = 0
    incomplete_html = None

    with SessionLocal() as session:
        for entry in entries:
            product = session.query(Product).filter_by(url=entry["url"]).one_or_none()
            if product is None:
                missing_products.append(
                    {
                        "url": entry["url"],
                        "match_name": entry.get("match_name"),
                    }
                )
                continue
            applied.append(apply_entry(session, product, entry))

        deleted_orphan_ingredients = delete_orphan_ingredients(session)

        if args.sync_incomplete_html and args.dry_run:
            incomplete_html = {
                "would_sync": session.query(Product).filter_by(is_incomplete=True).count()
            }
        elif args.sync_incomplete_html:
            session.flush()
            incomplete_html = sync_incomplete_html(session)

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    print(
        json.dumps(
            {
                "dry_run": args.dry_run,
                "reference": str(args.reference),
                "entries": len(entries),
                "applied": len(applied),
                "missing_products": missing_products,
                "name_mismatches": [
                    item
                    for item in applied
                    if item["name_mismatch"]
                ],
                "deleted_orphan_ingredients": deleted_orphan_ingredients,
                "incomplete_html": incomplete_html,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if missing_products:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
