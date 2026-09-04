import csv
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path


DB_PATH = Path("data/benu_otc.db")
EXPORT_DIR = Path("data/exports")
RAW_HTML_DIR = Path("data/raw_html")
INCOMPLETE_HTML_DIR = Path("data/incomplete_html")
FAILED_HTML_DIR = Path("data/failed_html")


def rows(cur, sql, params=()):
    return [dict(row) for row in cur.execute(sql, params)]


def count_csv(path):
    if not path.exists():
        return None
    try:
        csv.field_size_limit(sys.maxsize)
    except OverflowError:
        csv.field_size_limit(2_147_483_647)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def count_gzip_html(path):
    if not path.exists():
        return 0
    return sum(1 for _ in path.glob("*.html.gz"))


def load_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def contains_any(value, needles):
    folded = (value or "").casefold()
    return any(needle in folded for needle in needles)


def fold_text(value):
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def has_medicine_signal(value):
    folded = fold_text(value)
    signals = [
        "ez a gyogyszer orvosi rendelveny nelkul kaphato",
        "ezt a gyogyszert mindig pontosan",
        "mielott elkezdi szedni ezt a gyogyszert",
        "mielott elkezdi alkalmazni ezt a gyogyszert",
    ]
    return any(signal in folded for signal in signals)


def preview(value, limit=180):
    value = (value or "").strip()
    if len(value) <= limit:
        return value or None
    return value[: limit - 3].rstrip() + "..."


def normalized_quality_candidates(path):
    if not path.exists():
        return []
    bad_terms = {
        "nem adható": "contraindication_text",
        "túlérzékenység": "contraindication_text",
        "fájdalom": "effect_text",
        "lázcsillapító": "effect_text",
        "forgalmazza": "distributor_text",
        "frogalmazza": "distributor_text",
        "berlin-chemie": "distributor_text",
        "csaknem fehér": "appearance_text",
        "szabadon folyó": "appearance_text",
        "aggregátum": "appearance_text",
        "fehér vazelin": "excipient_text",
        "kivonószer": "extraction_solvent_text",
    }
    try:
        csv.field_size_limit(sys.maxsize)
    except OverflowError:
        csv.field_size_limit(2_147_483_647)
    candidates = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            display = row.get("ingredient_display") or ""
            raw = row.get("active_ingredient_raw") or ""
            haystack = display.casefold()
            reasons = []
            for term, reason in bad_terms.items():
                if term in haystack and reason not in reasons:
                    reasons.append(reason)
            if reasons:
                candidates.append(
                    {
                        "name": row.get("name"),
                        "ingredient_display": display,
                        "strength_display": row.get("strength_display"),
                        "active_ingredient_source": row.get("active_ingredient_source"),
                        "active_ingredient_preview": preview(raw),
                        "reasons": reasons,
                        "url": row.get("url"),
                    }
                )
    return candidates


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * pct)
    return ordered[index]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not DB_PATH.exists():
        raise SystemExit(f"Missing database: {DB_PATH}")

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    products = rows(cur, "select * from products order by name")
    has_active_source = bool(products) and "active_ingredient_source" in products[0]
    for p in products:
        p.setdefault("active_ingredient_source", None)
    otc = [p for p in products if p["classification"] == "OTC"]
    prices = [p["price_huf"] for p in products if p["price_huf"] is not None]
    high_cutoff = percentile(prices, 0.95)

    missing = {
        "all": {
            "price": sum(p["price_huf"] is None for p in products),
            "ean": sum(not (p["ean"] or "").strip() for p in products),
            "sku": sum(not (p["sku"] or "").strip() for p in products),
            "active_ingredient": sum(
                not (p["active_ingredient_raw"] or "").strip() for p in products
            ),
        },
        "otc": {
            "price": sum(p["price_huf"] is None for p in otc),
            "ean": sum(not (p["ean"] or "").strip() for p in otc),
            "sku": sum(not (p["sku"] or "").strip() for p in otc),
            "active_ingredient": sum(
                not (p["active_ingredient_raw"] or "").strip() for p in otc
            ),
        },
    }

    incomplete = [
        {
            "name": p["name"],
            "url": p["url"],
            "classification": p["classification"],
            "source": p["classification_source"],
            "price_huf": p["price_huf"],
            "sku": p["sku"],
            "ean": p["ean"],
            "active_ingredient_source": p["active_ingredient_source"],
            "warnings": load_json(p["parse_warnings_json"], []),
        }
        for p in products
        if p["is_incomplete"]
    ]

    invalid_price_rows = []
    for p in products:
        reasons = []
        if p["price_huf"] is None:
            reasons.append("missing_price")
        elif p["price_huf"] <= 0:
            reasons.append("non_positive_price")
        if (
            p["sale_price_huf"] is not None
            and p["price_huf"] is not None
            and p["sale_price_huf"] > p["price_huf"]
        ):
            reasons.append("sale_gt_list")
        if (
            p["original_price_huf"] is not None
            and p["price_huf"] is not None
            and p["original_price_huf"] != p["price_huf"]
        ):
            reasons.append("original_ne_list")
        if reasons:
            invalid_price_rows.append(
                {
                    "name": p["name"],
                    "classification": p["classification"],
                    "price_huf": p["price_huf"],
                    "sale_price_huf": p["sale_price_huf"],
                    "original_price_huf": p["original_price_huf"],
                    "reasons": reasons,
                    "url": p["url"],
                }
            )

    high_price_rows = [
        {
            "name": p["name"],
            "classification": p["classification"],
            "price_huf": p["price_huf"],
            "unit_price": p["unit_price"],
            "url": p["url"],
        }
        for p in products
        if high_cutoff is not None and p["price_huf"] is not None and p["price_huf"] >= high_cutoff
    ]
    high_price_rows.sort(key=lambda item: item["price_huf"], reverse=True)

    non_medicine_needles = [
        "homeop",
        "etrend",
        "étrend",
        "kozmet",
        "diagnoszt",
        "vercukor",
        "vércukor",
        "tesztcsik",
        "tesztcsík",
        "merő",
        "mérő",
        "tapszer",
        "tápszer",
        "anyatej",
        "tejalapu",
        "tejalapú",
        "italpor",
    ]
    review_needles = ["vitamin", "gumivitamin"]
    otc_false_positive_candidates = []
    otc_data_quality_candidates = []
    for p in otc:
        breadcrumbs = " > ".join(load_json(p["breadcrumbs_json"], []))
        detail_text = " ".join(
            [
                p["product_information"] or "",
                p["description"] or "",
            ]
        )
        detail_folded = fold_text(detail_text)
        haystack = " ".join(
            [
                p["name"] or "",
                breadcrumbs,
                p["classification_raw"] or "",
                p["classification_source"] or "",
            ]
        )
        classification_reasons = []
        quality_reasons = []
        medicine_confirmed = has_medicine_signal(p["raw_text"])
        if contains_any(haystack, non_medicine_needles) and not medicine_confirmed:
            classification_reasons.append("non_medicine_keyword")
        if (
            "homeopatias gyogyszer" in detail_folded
            or "homeopatias keszitmeny" in detail_folded
        ):
            classification_reasons.append("homeopathic_product_text")
        if (
            p["classification_source"] != "metadata"
            and contains_any(haystack, review_needles)
            and not medicine_confirmed
        ):
            classification_reasons.append("vitamin_category_review")
        if not (p["active_ingredient_raw"] or "").strip():
            quality_reasons.append("missing_active_ingredient")
        if p["classification_source"] == "analytics_item_type" and not medicine_confirmed:
            classification_reasons.append("analytics_only_otc")
        if classification_reasons:
            otc_false_positive_candidates.append(
                {
                    "name": p["name"],
                    "source": p["classification_source"],
                    "raw": p["classification_raw"],
                    "breadcrumbs": breadcrumbs,
                    "active_ingredient_source": p["active_ingredient_source"],
                    "active_ingredient_preview": preview(p["active_ingredient_raw"]),
                    "reasons": classification_reasons,
                    "url": p["url"],
                }
            )
        if quality_reasons:
            otc_data_quality_candidates.append(
                {
                    "name": p["name"],
                    "source": p["classification_source"],
                    "raw": p["classification_raw"],
                    "breadcrumbs": breadcrumbs,
                    "active_ingredient_source": p["active_ingredient_source"],
                    "active_ingredient_preview": preview(p["active_ingredient_raw"]),
                    "reasons": quality_reasons,
                    "url": p["url"],
                }
            )

    warning_counts = Counter()
    for p in products:
        warning_counts.update(load_json(p["parse_warnings_json"], []))

    bad_ingredients = rows(
        cur,
        """
        select p.name as product, i.name as ingredient, p.url
        from products p
        join product_ingredients pi on pi.product_id = p.id
        join ingredients i on i.id = pi.ingredient_id
        where length(i.name) > 70
           or lower(i.name) in ('tiszta', 'ill', 'ké', 'két', 'nevű', 'nevu')
           or lower(i.name) like 'ha %'
           or lower(i.name) like 'minden %'
           or lower(i.name) like '%egyéb összetevő%'
           or lower(i.name) like '%segédanyag%'
           or lower(i.name) like '%további információ%'
           or lower(i.name) like '%nem alkalmazható%'
           or lower(i.name) like '%nem adható%'
           or lower(i.name) like '%túlérzékenység%'
           or lower(i.name) like '%hagyományos növényi%'
           or lower(i.name) like '%javallat%'
           or lower(i.name) like '%fájdalom%'
           or lower(i.name) like '%lázcsillapító%'
           or lower(i.name) like '%forgalmazza%'
           or lower(i.name) like '%frogalmazza%'
           or lower(i.name) like '%berlin-chemie%'
           or lower(i.name) like '%csaknem fehér%'
           or lower(i.name) like '%szabadon folyó%'
           or lower(i.name) like '%aggregátum%'
           or lower(i.name) like '%fehér vazelin%'
           or lower(i.name) like '%kivonószer%'
           or lower(i.name) like '%azon összetevője%'
           or lower(i.name) like '%szopogató%'
           or lower(i.name) like '%szájnyálkahártyán%'
           or lower(i.name) like '%alkalmazott%'
           or lower(i.name) like '%alkalmazható%'
           or lower(i.name) like '%spray-ben%'
           or lower(i.name) like '%színű%'
           or lower(i.name) like '%szagú%'
           or lower(i.name) like '%vérszin%'
           or lower(i.name) like '%kalciumürítés%'
           or lower(i.name) like '%atrtalmaz%'
           or lower(i.name) like '%frakciót%'
           or lower(i.name) like '%a következő növényi kivonatok%'
        order by length(i.name) desc, p.name
        """,
    )

    export_counts = {
        "products.csv": count_csv(EXPORT_DIR / "products.csv"),
        "otc_products.csv": count_csv(EXPORT_DIR / "otc_products.csv"),
        "ingredients.csv": count_csv(EXPORT_DIR / "ingredients.csv"),
        "normalized_otc_products.csv": count_csv(
            EXPORT_DIR / "normalized_otc_products.csv"
        ),
        "comparison_groups.csv": count_csv(EXPORT_DIR / "comparison_groups.csv"),
    }
    normalized_candidates = normalized_quality_candidates(
        EXPORT_DIR / "normalized_otc_products.csv"
    )

    html_cache_counts = {
        "raw_html": count_gzip_html(RAW_HTML_DIR),
        "incomplete_html": count_gzip_html(INCOMPLETE_HTML_DIR),
        "failed_html": count_gzip_html(FAILED_HTML_DIR),
    }

    quality_gates = {
        "unknown_zero": Counter(p["classification"] for p in products).get("UNKNOWN", 0) == 0,
        "failed_html_zero": html_cache_counts["failed_html"] == 0,
        "otc_false_positive_zero": len(otc_false_positive_candidates) == 0,
        "bad_ingredient_zero": len(bad_ingredients) == 0,
        "otc_missing_price_zero": missing["otc"]["price"] == 0,
        "otc_missing_sku_zero": missing["otc"]["sku"] == 0,
        "otc_missing_active_zero": missing["otc"]["active_ingredient"] == 0,
        "normalized_bad_ingredient_zero": len(normalized_candidates) == 0,
    }

    report = {
        "total_products": len(products),
        "classification": dict(
            Counter(p["classification"] for p in products).most_common()
        ),
        "classification_source": dict(
            Counter(p["classification_source"] for p in products).most_common()
        ),
        "active_ingredient_source_available": has_active_source,
        "active_ingredient_source": {
            "all": dict(
                Counter(
                    (p["active_ingredient_source"] or "legacy_unknown")
                    for p in products
                    if (p["active_ingredient_raw"] or "").strip()
                ).most_common()
            ),
            "otc": dict(
                Counter(
                    (p["active_ingredient_source"] or "legacy_unknown")
                    for p in otc
                    if (p["active_ingredient_raw"] or "").strip()
                ).most_common()
            ),
        },
        "exports": export_counts,
        "html_cache": html_cache_counts,
        "quality_gates": quality_gates,
        "missing": missing,
        "warning_counts": dict(warning_counts.most_common()),
        "incomplete": incomplete,
        "ingredient_quality": {
            "bad_ingredient_count": len(bad_ingredients),
            "bad_ingredients": bad_ingredients[:20],
        },
        "normalized_quality": {
            "suspicious_count": len(normalized_candidates),
            "suspicious_rows": normalized_candidates[:20],
        },
        "suspicious_prices": {
            "invalid_rules": invalid_price_rows,
            "p95_cutoff_huf": high_cutoff,
            "high_outliers": high_price_rows[:10],
        },
        "otc_false_positive_candidates": otc_false_positive_candidates,
        "otc_data_quality_candidates": otc_data_quality_candidates,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
