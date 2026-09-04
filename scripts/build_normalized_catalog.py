import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.db import Product, SessionLocal, init_db  # noqa: E402
from scraper.utils import normalize_space  # noqa: E402


OUT = ROOT / "data" / "exports"
HYPHENS_RE = re.compile(r"[‐‑‒–—−]")

STRENGTH_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*"
    r"(?:mg/ml|mg/g|mg|g|µg|mcg|NE|IU|%)"
    r"(?:\s*/\s*\d+(?:[.,]\d+)?\s*(?:mg/ml|mg/g|mg|g|ml|µg|mcg|NE|IU|%))*\b",
    re.I,
)

PACKAGE_X_RE = re.compile(
    r"\b(?P<count>\d+(?:[.,]\d+)?)\s*x\s*"
    r"(?P<size>\d+(?:[.,]\d+)?)\s*(?P<unit>db|ml|g|l|kg|tasak)\b",
    re.I,
)
PACKAGE_TRAILING_X_RE = re.compile(r"\b(?P<size>\d+(?:[.,]\d+)?)\s*x\b", re.I)
PACKAGE_SIMPLE_RE = re.compile(
    r"\b(?P<size>\d+(?:[.,]\d+)?)\s*(?P<unit>db|ml|g|l|kg|tasak)\b",
    re.I,
)
UNIT_PRICE_RE = re.compile(
    r"(?P<amount>\d[\d\s]*(?:[.,]\d+)?)\s*Ft\s*/\s*(?P<unit>[\wÁÉÍÓÖŐÚÜŰáéíóöőúüű/-]+)",
    re.I,
)

CANONICAL_INGREDIENT_ALIASES = {
    "acetylsalicylic acid": "acetilszalicilsav",
    "ambroxol hydrochloride": "ambroxol",
    "ambroxol-hidroklorid": "ambroxol",
    "benfotiamine": "benfotiamin",
    "benzalkonium chloride": "benzalkónium-klorid",
    "benzidamin-hidroklorid": "benzidamin",
    "benzydamine": "benzidamin",
    "benzydamine hydrochloride": "benzidamin",
    "calcium carbonate": "kalcium-karbonát",
    "caffeine": "koffein",
    "chlorhexidine hydrochloride": "klórhexidin",
    "cianokobalamin": "cianokobalamin",
    "cyanocobalamin": "cianokobalamin",
    "drotaverin-hidroklorid": "drotaverin",
    "drotaverine": "drotaverin",
    "drotaverine hydrochloride": "drotaverin",
    "dextrometorfan-hidrobromid": "dextrometorfán",
    "fenilefrin-hidroklorid": "fenilefrin",
    "fentikonazol-nitrat": "fentikonazol",
    "gynoxin fentikonazol-nitrat": "fentikonazol",
    "ibuprofen": "ibuprofén",
    "kalcium-karbonat": "kalcium-karbonát",
    "karbocisztein-natrium": "karbocisztein",
    "klorhexidin-dihidroklorid": "klórhexidin",
    "lidocaine hydrochloride": "lidokain",
    "lidokain-hidroklorid": "lidokain",
    "lidokain-hidroklorid-monohidrat": "lidokain",
    "magnesium carbonate": "magnézium-karbonát",
    "magnesium hydroxide": "magnézium-hidroxid",
    "metamizol-natrium": "metamizol-nátrium",
    "metamizol-natrium-monohidrat": "metamizol-nátrium",
    "metamizole sodium monohydrate": "metamizol-nátrium",
    "naproxen sodium": "naproxén-nátrium",
    "natrium-alginat": "nátrium-alginát",
    "natrium-hidrogen-karbonat": "nátrium-hidrogén-karbonát",
    "paracetamolum": "paracetamol",
    "paraffin": "paraffin",
    "pankreatin frogalmazza berlin-chemie": "pankreatin",
    "piridoxin-hidroklorid": "piridoxin",
    "pseudoephedrine hydrochloride": "pszeudoefedrin",
    "pszeudoefedrin-hidroklorid": "pszeudoefedrin",
    "pyridoxine hydrochloride": "piridoxin",
    "rez": "réz",
    "simeticone": "szimetikon",
    "sodium alginate": "nátrium-alginát",
    "sodium hydrogen carbonate": "nátrium-hidrogén-karbonát",
    "szimetikon": "szimetikon",
    "tiamin-hidroklorid": "tiamin",
    "tisztitott": "",
    "elolt e coli bakteriumkultura": "elölt E. coli baktériumkultúra",
    "elolt bakteriumkultura-szuszpenzio": "elölt E. coli baktériumkultúra",
    "elolt bakterium kultura szuszpenzio": "elölt E. coli baktériumkultúra",
    "vakcina e coli": "elölt E. coli baktériumkultúra",
    "bakterium liofilizatum": "elölt E. coli baktériumkultúra",
    "pafranyfenyolevel szaraz kivonat": "páfrányfenyőlevél száraz kivonat",
    "mikronizalt flavonoid frakcio": "mikronizált flavonoid frakció",
    "mikronizalt flavonoid frakciot": "mikronizált flavonoid frakció",
    "tisztitott es mikronizalt flavonoid frakcio": "mikronizált flavonoid frakció",
    "tisztitott es mikronizalt flavonoid frakciot": "mikronizált flavonoid frakció",
    "tyrothricin": "tirotricin",
}


def load_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def fold_text(value):
    value = normalize_space(str(value or ""))
    value = HYPHENS_RE.sub("-", value)
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def slugify(value):
    folded = fold_text(value)
    folded = re.sub(r"[^a-z0-9]+", "-", folded)
    return folded.strip("-") or "unknown"


def parse_decimal(value):
    if value is None:
        return None
    text = str(value).replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def format_amount(value):
    if value is None:
        return None
    if abs(value - round(value)) < 0.0001:
        return str(int(round(value)))
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def parse_unit_price(value):
    match = UNIT_PRICE_RE.search(value or "")
    if not match:
        return None, None
    amount = parse_decimal(match.group("amount"))
    unit = normalize_unit(match.group("unit"))
    return amount, unit


def normalize_unit(unit):
    folded = fold_text(unit)
    if folded in {"darab", "tabletta", "filmtabletta", "kapszula", "ragotabletta"}:
        return "db"
    if folded in {"gramm"}:
        return "g"
    if folded in {"liter"}:
        return "l"
    return folded or None


def parse_package_amount(package_size, name):
    source = normalize_space(" ".join(part for part in [package_size, name] if part))
    match = PACKAGE_X_RE.search(source)
    if match:
        count = parse_decimal(match.group("count"))
        size = parse_decimal(match.group("size"))
        unit = normalize_unit(match.group("unit"))
        if count is not None and size is not None:
            amount = count * size
            if unit == "l":
                return amount * 1000, "ml", f"{format_amount(count)}x{format_amount(size)} l"
            if unit == "kg":
                return amount * 1000, "g", f"{format_amount(count)}x{format_amount(size)} kg"
            return amount, unit, f"{format_amount(count)}x{format_amount(size)} {unit}"

    match = PACKAGE_TRAILING_X_RE.search(source)
    if match:
        amount = parse_decimal(match.group("size"))
        if amount is not None:
            return amount, "db", f"{format_amount(amount)} db"

    match = PACKAGE_SIMPLE_RE.search(source)
    if not match:
        return None, None, None
    amount = parse_decimal(match.group("size"))
    unit = normalize_unit(match.group("unit"))
    if amount is None:
        return None, None, None
    if unit == "l":
        return amount * 1000, "ml", f"{format_amount(amount)} l"
    if unit == "kg":
        return amount * 1000, "g", f"{format_amount(amount)} kg"
    return amount, unit, f"{format_amount(amount)} {unit}"


def strip_strength_denominator_fragments(value):
    source = normalize_space(value or "")
    source = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:g|gramm|ml)\s*"
        r"(?:\([^)]*\)\s*)?(?:,?\s*vízzel\s+lemosható\s+)?"
        r"(?:fogászati\s+)?(?:gélben|gél|krémben|krém|hüvelykrémben|"
        r"hüvelykrém|kenőcsben|kenőcs|végbélkenőcsben|szemkenőcsben|"
        r"szirupban|szirup|hintőporban|porban|folyadékban|"
        r"szuszpenzióban|oldatban|cseppben)\b",
        " ",
        source,
        flags=re.I,
    )
    return normalize_space(source)


def clean_ingredient_name(name):
    value = normalize_space(name or "")
    value = HYPHENS_RE.sub("-", value)
    value = value.replace("_", "-")
    value = re.sub(r"\b(?:Forgalmazza|Frogalmazza|Forgalmazó|Gyártó)\b.*$", "", value, flags=re.I)
    value = re.sub(r"\bkivonatát\b", "kivonat", value, flags=re.I)
    value = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:g|gramm|ml)\s*"
        r"(?:\([^)]*\)\s*)?(?:,?\s*vízzel\s+lemosható\s+)?"
        r"(?:fogászati\s+)?(?:gélben|gél|krémben|krém|hüvelykrémben|"
        r"hüvelykrém|kenőcsben|kenőcs|végbélkenőcsben|szemkenőcsben|"
        r"szirupban|szirup|hintőporban|porban|folyadékban|"
        r"szuszpenzióban|oldatban|cseppben)\b",
        " ",
        value,
        flags=re.I,
    )
    value = re.sub(
        r"\btisztított\s+(?:,?\s*és\s+)?mikronizált\s+flavonoid\s+frakciót?\b",
        "mikronizált flavonoid frakció",
        value,
        flags=re.I,
    )
    value = re.sub(r"\bazaz\b.*$", "", value, flags=re.I)
    value = re.sub(r"\bvízzel\s+lemosható\b.*$", "", value, flags=re.I)
    value = re.sub(r"^(?:kenőcsben|krémben|gélben|szirupban|hintőporban|porban)\s+", "", value, flags=re.I)
    value = re.sub(r"\btinktúrát\b", "tinktúra", value, flags=re.I)
    value = re.sub(r"\b(?:szopogató|préselt|szájnyálkahártyán|alkalmazott|alkalmazható|spray-ben|spray|fogászati|krémben|gélben|kenőcsben|hüvelykrémben|szirupban|hintőporban|porban|oldatban|szuszpenzióban|hüvelykapszulánként|hüvelykapszula|hüvelykrém|tabletta|filmtabletta|kapszula|krém|gél|kenőcs|szirup|oldat|hatóanyag|hatóanyaga|hatóanyagai|tartalma|tartalmaz|tartalmazza)\b", "", value, flags=re.I)
    value = re.sub(r"(?:ot|et)\b", "", value, flags=re.I)
    value = re.sub(r"(?<=sav)at\b", "", value, flags=re.I)
    value = re.sub(r"(?<=ir)t\b", "", value, flags=re.I)
    value = re.sub(r"(?<=ol)t\b", "", value, flags=re.I)
    value = re.sub(r"(?<=éter)t\b", "", value, flags=re.I)
    value = re.sub(r"(?<=ió)t\b", "", value, flags=re.I)
    value = re.sub(r"(?<=[né])t\b", "", value, flags=re.I)
    value = re.sub(r"\s{2,}", " ", value).strip(" ,.;:-")
    return value


def canonical_ingredient(name):
    cleaned = clean_ingredient_name(name)
    key = fold_text(cleaned)
    key = re.sub(r"\s+", " ", key).strip()
    if "omega-3-sav-etileszter" in key:
        return "omega-3-sav-etilészterek"
    if (
        "ginkgo biloba" in key
        and ("pafranyfenyolevel" in key or "folium" in key)
        and "kivon" in key
    ):
        return "páfrányfenyőlevél száraz kivonat"
    if (
        "escherichia coli" in key
        or "vakcina e coli" in key
        or "bakteriumkultura" in key
        or "bakterium kultura" in key
    ):
        return "elölt E. coli baktériumkultúra"
    return CANONICAL_INGREDIENT_ALIASES.get(key, cleaned.casefold())


def normalize_ingredients(ingredient_names):
    canonical = [canonical_ingredient(name) for name in ingredient_names if name]
    canonical = [name for name in canonical if name]
    display = []
    for name in canonical:
        if name not in display:
            display.append(name)
    key = "+".join(sorted(slugify(name) for name in display)) or "missing-active"
    return display, key


def strip_package_fragments(name):
    value = normalize_space(name or "")
    value = PACKAGE_X_RE.sub(" ", value)
    def replace_simple(match):
        amount = parse_decimal(match.group("size"))
        unit = normalize_unit(match.group("unit"))
        following = value[match.end():match.end() + 40]
        if (
            unit == "g"
            and amount is not None
            and amount <= 2
            and re.match(
                r"\s*(?:tabletta|rágótabletta|pezsgőtabletta|kapszula|granulátum)\b",
                following,
                re.I,
            )
        ):
            return match.group(0)
        return " "

    value = PACKAGE_SIMPLE_RE.sub(replace_simple, value)
    return normalize_space(value)


def normalize_strength_token(token):
    token = HYPHENS_RE.sub("-", normalize_space(token or ""))
    token = re.sub(r"(\d)(?=(?:mg|g|µg|mcg|NE|IU|%))", r"\1 ", token, flags=re.I)
    token = re.sub(r"\s*/\s*", "/", token)
    token = re.sub(r"\s+", " ", token)
    return token.strip()


def extract_strength_tokens(name, active_raw):
    sources = [
        strip_package_fragments(name),
        strip_strength_denominator_fragments(active_raw or ""),
    ]
    for source in sources:
        tokens = [normalize_strength_token(match.group(0)) for match in STRENGTH_RE.finditer(source)]
        tokens = unique_keep_order(tokens)
        if tokens:
            return tokens
    return []


def normalize_strength(name, active_raw):
    tokens = extract_strength_tokens(name, active_raw)
    display = " + ".join(tokens)
    key = "+".join(slugify(token.replace("/", "-per-")) for token in tokens) or "no-strength"
    return display or None, key


def normalize_form(name, pharmaceutical_form):
    source = fold_text(" ".join(part for part in [pharmaceutical_form, name] if part))
    rules = [
        ("préselt szopogató tabletta", ["preselt szopogato"]),
        ("szopogató tabletta", ["szopogato"]),
        ("gyógyszeres rágógumi", ["gyogyszeres ragogumi"]),
        ("rágótabletta", ["ragotabletta"]),
        ("pezsgőtabletta", ["pezsgotabletta"]),
        ("hüvelytabletta", ["huvelytabletta"]),
        ("hüvelykapszula", ["huvelykapszula"]),
        ("lágy kapszula", ["lagy kapszula"]),
        ("kapszula", ["kapszula"]),
        ("granulátum", ["granulatum"]),
        ("belsőleges szuszpenzió", ["belsoleges szuszpenzio", "szuszpenzio"]),
        ("belsőleges oldatos csepp", ["oldatos cseppek", "csepp"]),
        ("orrspray", ["orrspray"]),
        ("szemcsepp", ["szemcsepp"]),
        ("spray", ["spray"]),
        ("gél", ["gel"]),
        ("krém", ["krem"]),
        ("kenőcs", ["kenocs"]),
        ("kúp", ["kup"]),
        ("oldat", ["oldat"]),
        ("por", ["por"]),
        ("tabletta", ["filmtabletta", "bevont tabletta", "tabletta"]),
    ]
    for display, needles in rules:
        if any(needle in source for needle in needles):
            return display, slugify(display)
    return pharmaceutical_form or None, slugify(pharmaceutical_form or "unknown-form")


def primary_categories(product):
    breadcrumbs = load_json(product.breadcrumbs_json, [])
    meaningful = [item for item in breadcrumbs if fold_text(item) != "gyogyaszat"]
    return (
        meaningful[0] if len(meaningful) >= 1 else None,
        meaningful[1] if len(meaningful) >= 2 else None,
        breadcrumbs,
    )


def unique_keep_order(values):
    seen = set()
    out = []
    for value in values:
        key = fold_text(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def product_to_row(product):
    ingredient_names = [rel.ingredient.name for rel in product.ingredients]
    canonical_ingredients, ingredient_key = normalize_ingredients(ingredient_names)
    strength_display, strength_key = normalize_strength(product.name, product.active_ingredient_raw)
    form_display, form_key = normalize_form(product.name, product.pharmaceutical_form)
    package_amount, package_unit, package_label = parse_package_amount(product.package_size, product.name)
    unit_price_huf, unit_price_unit = parse_unit_price(product.unit_price)
    if unit_price_huf is None and product.price_huf is not None and package_amount and package_unit:
        unit_price_huf = round(product.price_huf / package_amount, 4)
        unit_price_unit = package_unit

    primary_category, secondary_category, breadcrumbs = primary_categories(product)
    warnings = load_json(product.parse_warnings_json, [])
    quality_flags = list(warnings)
    if not canonical_ingredients:
        quality_flags.append("missing_normalized_ingredient")
    if unit_price_huf is None:
        quality_flags.append("missing_unit_price")

    comparison_unit = unit_price_unit or package_unit or "unit"
    comparison_group_key = "|".join(
        [
            ingredient_key,
            strength_key,
            form_key,
            slugify(comparison_unit),
        ]
    )

    return {
        "id": product.id,
        "name": product.name,
        "brand": product.brand,
        "url": product.url,
        "sku": product.sku,
        "ean": product.ean,
        "price_huf": product.price_huf,
        "unit_price": product.unit_price,
        "unit_price_huf": unit_price_huf,
        "unit_price_unit": unit_price_unit,
        "package_amount": package_amount,
        "package_unit": package_unit,
        "package_label": package_label,
        "active_ingredient_raw": product.active_ingredient_raw,
        "active_ingredient_source": product.active_ingredient_source,
        "ingredient_names": ingredient_names,
        "canonical_ingredients": canonical_ingredients,
        "ingredient_display": " + ".join(canonical_ingredients),
        "ingredient_key": ingredient_key,
        "strength_display": strength_display,
        "strength_key": strength_key,
        "form": form_display,
        "form_key": form_key,
        "comparison_unit": comparison_unit,
        "comparison_group_key": comparison_group_key,
        "primary_category": primary_category,
        "secondary_category": secondary_category,
        "breadcrumbs": breadcrumbs,
        "images": load_json(product.images_json, []),
        "statuses": load_json(product.statuses_json, []),
        "quality_flags": unique_keep_order(quality_flags),
        "classification_source": product.classification_source,
    }


def serializable_row(row):
    out = {}
    for key, value in row.items():
        if isinstance(value, list):
            out[key] = json.dumps(value, ensure_ascii=False)
        else:
            out[key] = value
    return out


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(serializable_row(row) for row in rows)


def build_group_rows(product_rows):
    groups = defaultdict(list)
    for row in product_rows:
        groups[row["comparison_group_key"]].append(row)

    group_rows = []
    group_payloads = []
    for index, (key, rows) in enumerate(sorted(groups.items()), start=1):
        unit_rows = [row for row in rows if row["unit_price_huf"] is not None]
        price_rows = [row for row in rows if row["price_huf"] is not None]
        best_source = unit_rows or price_rows or rows
        cheapest = min(
            best_source,
            key=lambda row: (
                row["unit_price_huf"] if row["unit_price_huf"] is not None else float("inf"),
                row["price_huf"] if row["price_huf"] is not None else float("inf"),
                row["name"],
            ),
        )
        unit_values = [row["unit_price_huf"] for row in unit_rows]
        price_values = [row["price_huf"] for row in price_rows]
        max_unit = max(unit_values) if unit_values else None
        min_unit = min(unit_values) if unit_values else None
        savings_pct = None
        if max_unit and min_unit is not None and max_unit > 0 and len(unit_values) > 1:
            savings_pct = round((max_unit - min_unit) / max_unit * 100, 1)
        categories = Counter(row["primary_category"] for row in rows if row["primary_category"])
        quality_flags = unique_keep_order(flag for row in rows for flag in row["quality_flags"])

        group = {
            "group_id": index,
            "comparison_group_key": key,
            "ingredient_display": rows[0]["ingredient_display"],
            "ingredient_key": rows[0]["ingredient_key"],
            "strength_display": rows[0]["strength_display"],
            "strength_key": rows[0]["strength_key"],
            "form": rows[0]["form"],
            "form_key": rows[0]["form_key"],
            "comparison_unit": rows[0]["comparison_unit"],
            "primary_category": categories.most_common(1)[0][0] if categories else None,
            "product_count": len(rows),
            "min_price_huf": min(price_values) if price_values else None,
            "max_price_huf": max(price_values) if price_values else None,
            "min_unit_price_huf": min_unit,
            "max_unit_price_huf": max_unit,
            "savings_vs_max_unit_pct": savings_pct,
            "cheapest_product_id": cheapest["id"],
            "cheapest_product_name": cheapest["name"],
            "cheapest_product_url": cheapest["url"],
            "cheapest_price_huf": cheapest["price_huf"],
            "cheapest_unit_price_huf": cheapest["unit_price_huf"],
            "quality_flags": quality_flags,
        }
        group_rows.append(group)
        group_payload = dict(group)
        group_payload["products"] = sorted(
            rows,
            key=lambda row: (
                row["unit_price_huf"] if row["unit_price_huf"] is not None else float("inf"),
                row["price_huf"] if row["price_huf"] is not None else float("inf"),
                row["name"],
            ),
        )
        group_payloads.append(group_payload)

    return group_rows, group_payloads


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Build normalized OTC product and comparison-group exports."
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    init_db()
    args.out.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        products = (
            session.query(Product)
            .filter(Product.classification == "OTC")
            .order_by(Product.name)
            .all()
        )
        product_rows = [product_to_row(product) for product in products]

    group_rows, group_payloads = build_group_rows(product_rows)
    categories = Counter(row["primary_category"] for row in product_rows if row["primary_category"])
    quality_flags = Counter(flag for row in product_rows for flag in row["quality_flags"])

    write_csv(args.out / "normalized_otc_products.csv", product_rows)
    write_csv(args.out / "comparison_groups.csv", group_rows)
    (args.out / "normalized_otc_products.json").write_text(
        json.dumps(product_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.out / "comparison_groups.json").write_text(
        json.dumps(group_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.out / "grouped_catalog.json").write_text(
        json.dumps(
            {
                "source": "data/benu_otc.db",
                "counts": {
                    "otc_products": len(product_rows),
                    "comparison_groups": len(group_rows),
                    "multi_product_groups": sum(1 for row in group_rows if row["product_count"] > 1),
                },
                "categories": dict(categories.most_common()),
                "quality_flags": dict(quality_flags.most_common()),
                "groups": group_payloads,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "otc_products": len(product_rows),
                "comparison_groups": len(group_rows),
                "multi_product_groups": sum(1 for row in group_rows if row["product_count"] > 1),
                "quality_flags": dict(quality_flags.most_common()),
                "exports": str(args.out.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
