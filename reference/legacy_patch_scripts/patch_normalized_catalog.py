# -*- coding: utf-8 -*-
"""Egyszeri javítás a scripts/build_normalized_catalog.py fájlon.

Négy hibát javít:
  A) parse_package_amount az erősség nevezőjét kiszerelésnek olvasta
  B) félszilárd készítménynél az "1 g + 50 mg" alak valójában 50 mg/g
  C) az egységár a BENU mezőjéből jött, nem a listaár / kiszerelés hányadosából
  D) a megtakarítás nem különböztette meg a másik gyártót a nagyobb doboztól

Futtatás a projekt gyökeréből:  python scripts/patch_normalized_catalog.py
A módosítás előtt .bak másolatot készít.
"""
import re
import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "build_normalized_catalog.py"


def sub_once(src, old, new, label):
    if old not in src:
        raise SystemExit(f"NEM TALÁLHATÓ a javítandó rész: {label}")
    if src.count(old) != 1:
        raise SystemExit(f"TÖBBSZÖR SZEREPEL: {label}")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


def main():
    src = TARGET.read_text(encoding="utf-8")
    if "PACKAGE_STRENGTH_STRIP_RE" in src:
        raise SystemExit("A javítás már alkalmazva van.")

    bak = TARGET.with_suffix(f".py.{datetime.now():%Y%m%d_%H%M%S}.bak")
    shutil.copy2(TARGET, bak)
    print(f"biztonsági másolat: {bak.name}")

    # ---------------------------------------------------------------- A)
    src = sub_once(
        src,
        "PACKAGE_TRAILING_X_RE = re.compile(r\"\\b(?P<size>\\d+(?:[.,]\\d+)?)\\s*x\\b\", re.I)",
        "PACKAGE_TRAILING_X_RE = re.compile(r\"\\b(?P<size>\\d+(?:[.,]\\d+)?)\\s*x\\b\", re.I)\n"
        "# A kiszerelés-felismerés előtt le kell vágni az erősség-kifejezéseket, különben\n"
        "# a \"Panactiv 100 mg/5 ml belsőleges szuszpenzió 100ml\" 5 ml-nek olvasódik.\n"
        "PACKAGE_STRENGTH_STRIP_RE = re.compile(\n"
        "    r\"\\d+(?:[.,]\\d+)?\\s*(?:mg|µg|mcg|NE|IU)\\s*/\\s*\\d+(?:[.,]\\d+)?\\s*(?:ml|g|adag)|\"\n"
        "    r\"\\d+(?:[.,]\\d+)?\\s*(?:mg|µg|mcg|NE|IU)\\s*/\\s*(?:ml|g|adag)|\"\n"
        "    r\"\\d+(?:[.,]\\d+)?\\s*(?:mg|µg|mcg)\\b|\"\n"
        "    r\"\\d+(?:[.,]\\d+)?\\s*%\",\n"
        "    re.I,\n"
        ")",
        "A) PACKAGE_STRENGTH_STRIP_RE hozzáadása",
    )

    src = sub_once(
        src,
        "def parse_package_amount(package_size, name):\n"
        "    source = normalize_space(\" \".join(part for part in [package_size, name] if part))\n",
        "def parse_package_amount(package_size, name):\n"
        "    source = normalize_space(\" \".join(part for part in [package_size, name] if part))\n"
        "    source = normalize_space(PACKAGE_STRENGTH_STRIP_RE.sub(\" \", source))\n",
        "A) parse_package_amount erősség-levágás",
    )

    # ---------------------------------------------------------------- B)
    src = sub_once(
        src,
        "def normalize_strength(name, active_raw):\n"
        "    tokens = extract_strength_tokens(name, active_raw)\n"
        "    display = \" + \".join(tokens)\n",
        "SEMISOLID_FORMS = {\"gél\", \"krém\", \"kenőcs\", \"szemgél\", \"hüvelykrém\", \"paszta\"}\n"
        "\n"
        "\n"
        "def semisolid_ratio_tokens(tokens, form_display):\n"
        "    \"\"\"Az \"1 g + 50 mg\" félszilárd készítménynél 50 mg/g-ot jelent.\n"
        "\n"
        "    A magyar alkalmazási előírás így fogalmaz: \"1 g krém 50 mg ibuprofént\n"
        "    tartalmaz\". Enélkül a Dolgit gél 1000 mg-os erősségűnek látszik.\n"
        "    \"\"\"\n"
        "    if form_display not in SEMISOLID_FORMS or len(tokens) < 2:\n"
        "        return tokens\n"
        "    base_match = re.fullmatch(r\"(\\d+(?:[.,]\\d+)?)\\s*g\", tokens[0], re.I)\n"
        "    value_match = re.fullmatch(r\"(\\d+(?:[.,]\\d+)?)\\s*(mg|µg|mcg)\", tokens[1], re.I)\n"
        "    if not (base_match and value_match):\n"
        "        return tokens\n"
        "    base = parse_decimal(base_match.group(1))\n"
        "    value = parse_decimal(value_match.group(1))\n"
        "    if not base or value is None:\n"
        "        return tokens\n"
        "    factor = {\"mg\": 1.0, \"µg\": 0.001, \"mcg\": 0.001}[value_match.group(2).lower()]\n"
        "    return [f\"{format_amount(value * factor / base)} mg/g\"] + list(tokens[2:])\n"
        "\n"
        "\n"
        "def normalize_strength(name, active_raw, form_display=None):\n"
        "    tokens = extract_strength_tokens(name, active_raw)\n"
        "    tokens = semisolid_ratio_tokens(tokens, form_display)\n"
        "    display = \" + \".join(tokens)\n",
        "B) félszilárd erősség mg/g-ra",
    )

    # ---------------------------------------------------------------- C)
    src = sub_once(
        src,
        "    strength_display, strength_key = normalize_strength(product.name, product.active_ingredient_raw)\n"
        "    form_display, form_key = normalize_form(product.name, product.pharmaceutical_form)\n"
        "    package_amount, package_unit, package_label = parse_package_amount(product.package_size, product.name)\n"
        "    unit_price_huf, unit_price_unit = parse_unit_price(product.unit_price)\n"
        "    if unit_price_huf is None and product.price_huf is not None and package_amount and package_unit:\n"
        "        unit_price_huf = round(product.price_huf / package_amount, 4)\n"
        "        unit_price_unit = package_unit\n",
        "    form_display, form_key = normalize_form(product.name, product.pharmaceutical_form)\n"
        "    strength_display, strength_key = normalize_strength(\n"
        "        product.name, product.active_ingredient_raw, form_display\n"
        "    )\n"
        "    package_amount, package_unit, package_label = parse_package_amount(product.package_size, product.name)\n"
        "\n"
        "    # Az egységár elsődlegesen SAJÁT számítás: listaár / kiszerelés.\n"
        "    # A BENU unit_price mezője több terméknél téves (pl. a Strepfen 24 db-os\n"
        "    # dobozánál 4 849 Ft/db szerepel 202 Ft/db helyett), ezért csak akkor\n"
        "    # használjuk, ha nincs értelmezhető kiszerelés — egyébként ellenőrzés.\n"
        "    benu_unit_price_huf, benu_unit_price_unit = parse_unit_price(product.unit_price)\n"
        "    unit_price_huf = unit_price_unit = None\n"
        "    unit_price_source = None\n"
        "    if product.price_huf is not None and package_amount and package_unit:\n"
        "        unit_price_huf = round(product.price_huf / package_amount, 4)\n"
        "        unit_price_unit = package_unit\n"
        "        unit_price_source = \"computed_price_per_package\"\n"
        "    elif benu_unit_price_huf is not None:\n"
        "        unit_price_huf = benu_unit_price_huf\n"
        "        unit_price_unit = benu_unit_price_unit\n"
        "        unit_price_source = \"benu_unit_price\"\n"
        "    unit_price_mismatch = bool(\n"
        "        unit_price_source == \"computed_price_per_package\"\n"
        "        and benu_unit_price_huf\n"
        "        and unit_price_huf\n"
        "        and not (0.74 <= benu_unit_price_huf / unit_price_huf <= 1.35)\n"
        "    )\n",
        "C) egységár saját számításból",
    )

    src = sub_once(
        src,
        "    if unit_price_huf is None:\n"
        "        quality_flags.append(\"missing_unit_price\")\n",
        "    if unit_price_huf is None:\n"
        "        quality_flags.append(\"missing_unit_price\")\n"
        "    if unit_price_mismatch:\n"
        "        quality_flags.append(\"unit_price_mismatch_vs_benu\")\n",
        "C) minőségi jelzés az eltérésre",
    )

    src = sub_once(
        src,
        "        \"unit_price_huf\": unit_price_huf,\n",
        "        \"unit_price_huf\": unit_price_huf,\n"
        "        \"unit_price_source\": unit_price_source,\n"
        "        \"unit_price_benu_huf\": benu_unit_price_huf,\n"
        "        \"unit_price_mismatch\": unit_price_mismatch,\n",
        "C) új mezők a sorban",
    )

    # ---------------------------------------------------------------- D)
    src = sub_once(
        src,
        "        savings_pct = None\n"
        "        if max_unit and min_unit is not None and max_unit > 0 and len(unit_values) > 1:\n"
        "            savings_pct = round((max_unit - min_unit) / max_unit * 100, 1)\n",
        "        savings_pct = None\n"
        "        if max_unit and min_unit is not None and max_unit > 0 and len(unit_values) > 1:\n"
        "            savings_pct = round((max_unit - min_unit) / max_unit * 100, 1)\n"
        "\n"
        "        # A savings_vs_max_unit_pct önmagában félrevezető: a csoportok\n"
        "        # többségénél ugyanannak a készítménynek a nagy és kis doboza áll a\n"
        "        # két végén. Ezért külön mérjük a MÁSIK készítménnyel szembeni\n"
        "        # különbséget és a saját nagyobb kiszerelés előnyét.\n"
        "        other_brand_pct = None\n"
        "        other_brand_reference = None\n"
        "        pack_size_pct = None\n"
        "        pack_size_reference = None\n"
        "        if unit_rows and cheapest[\"unit_price_huf\"]:\n"
        "            base = brand_token(cheapest[\"name\"])\n"
        "            others = [r for r in unit_rows if brand_token(r[\"name\"]) != base]\n"
        "            if others:\n"
        "                worst = max(others, key=lambda r: r[\"unit_price_huf\"])\n"
        "                if worst[\"unit_price_huf\"] > 0:\n"
        "                    ratio = cheapest[\"unit_price_huf\"] / worst[\"unit_price_huf\"]\n"
        "                    # tízszeresnél nagyobb szórás azonos erősségen belül\n"
        "                    # adathiba, nem árkülönbség\n"
        "                    if ratio >= 0.1:\n"
        "                        other_brand_pct = round((1 - ratio) * 100, 1)\n"
        "                        other_brand_reference = worst[\"name\"]\n"
        "            same = [\n"
        "                r for r in unit_rows\n"
        "                if brand_token(r[\"name\"]) == base and r is not cheapest\n"
        "            ]\n"
        "            if same:\n"
        "                worst_same = max(same, key=lambda r: r[\"unit_price_huf\"])\n"
        "                if worst_same[\"unit_price_huf\"] > 0:\n"
        "                    pack_size_pct = round(\n"
        "                        (1 - cheapest[\"unit_price_huf\"] / worst_same[\"unit_price_huf\"]) * 100, 1\n"
        "                    )\n"
        "                    pack_size_reference = worst_same[\"name\"]\n",
        "D) márkafüggő megtakarítás számítása",
    )

    src = sub_once(
        src,
        "            \"savings_vs_max_unit_pct\": savings_pct,\n",
        "            \"savings_vs_max_unit_pct\": savings_pct,\n"
        "            \"savings_vs_other_brand_pct\": other_brand_pct,\n"
        "            \"savings_vs_other_brand_reference\": other_brand_reference,\n"
        "            \"pack_size_saving_pct\": pack_size_pct,\n"
        "            \"pack_size_saving_reference\": pack_size_reference,\n",
        "D) új csoportmezők",
    )

    src = sub_once(
        src,
        "def build_group_rows(product_rows):\n",
        "def brand_token(name):\n"
        "    \"\"\"A készítménynév első szava — ez azonosítja a terméklinet.\n"
        "\n"
        "    Nem a gyártó, mert egy gyártó több önálló márkát is forgalmaz, és nem is\n"
        "    a teljes név, mert a kiszerelés a végén különbözik.\n"
        "    \"\"\"\n"
        "    parts = fold_text(name or \"\").split()\n"
        "    return re.sub(r\"[^a-z0-9]\", \"\", parts[0]) if parts else \"\"\n"
        "\n"
        "\n"
        "def build_group_rows(product_rows):\n",
        "D) brand_token segédfüggvény",
    )

    TARGET.write_text(src, encoding="utf-8")
    print("kész — a build_normalized_catalog.py frissítve")


if __name__ == "__main__":
    main()
