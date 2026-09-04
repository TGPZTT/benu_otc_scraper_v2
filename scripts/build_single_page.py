# -*- coding: utf-8 -*-
"""
Egyetlen, önmagában futó HTML oldalt épít a BENU OTC katalógusból.

Bemenet:
    data/exports/normalized_otc_products.json   – a normalizált OTC katalógus
    reference/ingredient_aliases.json           – hatóanyag-kulcs kanonizálás
    reference/knowledge_base.json               – tünet -> hatóanyag tudásréteg
Kimenet:
    data/exports/benu_otc.html                  – minden adat beágyazva, nincs fetch

Három nézet:
    Panasz szerint   – tünetből indul, kurált hatóanyag-ajánlással
    Hatóanyag szerint – a teljes katalógus, kategória-navigációval
    Hol spórolhat    – csak a valódi, márkák közti árkülönbségek, rangsorolva

Árlogika (a build_normalized_catalog.py-vel összhangban):
  - az egységár a listaár és a kiszerelés hányadosa, nem a BENU mezője
  - ahol az erősség egyértelmű, az összehasonlítás Ft / gramm hatóanyag
  - százalék csak azonos erősség, azonos forma és MÁSIK készítménynév esetén
  - az azonos márka nagyobb doboza külön "kiszerelés-tipp"
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict, Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "exports" / "normalized_otc_products.json"
OUT = ROOT / "data" / "exports" / "benu_otc.html"
PRODUCTS_SRC = ROOT / "data" / "exports" / "products.json"
ALIAS_SRC = ROOT / "reference" / "ingredient_aliases.json"
KB_SRC = ROOT / "reference" / "knowledge_base.json"


# ---------------------------------------------------------------- segédfüggvények

def fold(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def brand_key(name: str) -> str:
    """A készítménynév első szava — ez azonosítja a terméklinet."""
    first = fold(name).split()
    return re.sub(r"[^a-z0-9]", "", first[0]) if first else ""


def num(s):
    try:
        return float(str(s).replace(" ", "").replace(" ", "").replace(",", "."))
    except Exception:
        return None


def grouped_int(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


# ---------------------------------------------------------------- erősség -> mg

UNIT_MG = {"mg": 1.0, "g": 1000.0, "µg": 0.001, "ug": 0.001, "mcg": 0.001}
STRENGTH_RX = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mg|µg|ug|mcg|g)\s*(?:/\s*(\d+(?:[.,]\d+)?)?\s*(ml|g|adag|db))?",
    re.I,
)
PCT_RX = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def strength_mg(strength_display: str):
    """(mg hatóanyag egységenként, az egység típusa) — az ELSŐ hatóanyagra."""
    s = (strength_display or "").strip()
    if not s:
        return None, None
    m = STRENGTH_RX.search(s)
    if m:
        val = num(m.group(1))
        unit = (m.group(2) or "mg").lower()
        if val is None:
            return None, None
        mg = val * UNIT_MG.get(unit, 1.0)
        denom_n, denom_u = num(m.group(3)), (m.group(4) or "").lower()
        if denom_u in ("ml", "g"):
            return (mg / denom_n if denom_n else mg), denom_u
        return mg, "db"
    m = PCT_RX.search(s)
    if m:
        val = num(m.group(1))
        return (val * 10.0, "g") if val is not None else (None, None)
    return None, None


TOPICAL = {"gél", "krém", "kenőcs", "hüvelykrém", "szemgél", "paszta"}


def topical_mg_per_g(strength_display, form):
    """'1 g + 50 mg' vagy csupasz '50 mg' félszilárd készítménynél = mg / g."""
    if (form or "").strip() not in TOPICAL:
        return None
    s = strength_display or ""
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*g\s*\+\s*(\d+(?:[.,]\d+)?)\s*(mg|µg|ug)\b", s, re.I)
    if m:
        base, val, unit = num(m.group(1)), num(m.group(2)), m.group(3).lower()
        if base and val:
            return val * UNIT_MG.get(unit, 1.0) / base
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(mg|µg|ug)\s*", s, re.I)
    if m:
        val = num(m.group(1))
        return val * UNIT_MG.get(m.group(2).lower(), 1.0) if val else None
    return None


PACK_STRIP = re.compile(
    r"\d+(?:[.,]\d+)?\s*mg\s*/\s*\d+(?:[.,]\d+)?\s*(?:ml|g)|"
    r"\d+(?:[.,]\d+)?\s*(?:mg|µg|ug|ne|iu)\s*/\s*(?:ml|g|adag)|"
    r"\d+(?:[.,]\d+)?\s*(?:mg|µg|ug)\b|\d+(?:[.,]\d+)?\s*%", re.I)


def pack_from_name(name):
    """Kiszerelés a névből, az erősség-kifejezések levágása után."""
    n = PACK_STRIP.sub(" ", name or "")
    m = re.search(r"(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(ml|g)\b", n, re.I)
    if m:
        return num(m.group(1)) * num(m.group(2)), m.group(3).lower()
    m = re.search(r"(\d+)\s*[x×]\s*(\d+)\s*db", n, re.I)
    if m:
        return num(m.group(1)) * num(m.group(2)), "db"
    m = re.search(r"(\d+)\s*db\s*\+\s*(\d+)\s*db", n, re.I)
    if m:
        return num(m.group(1)) + num(m.group(2)), "db"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*ml\b", n, re.I)
    if m:
        return num(m.group(1)), "ml"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*g\b(?!\w)", n, re.I)
    if m:
        return num(m.group(1)), "g"
    m = re.search(r"(\d+)\s*(?:db|tasak|darab)\b", n, re.I)
    if m:
        return num(m.group(1)), "db"
    return None, None


# ------------------------------------------------- összetevő + mennyiség párok

COMPONENT_RX = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mg|µg|ug|mcg|g|NE|IU)\b"        # mennyiség
    r"(?:\s*\([^)]*\))?"                                    # zárójeles átváltás
    r"\s*([A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű][^,;()]{1,48}?)"        # név
    r"(?=\s*[,;(]|\s+és\b|$)",
    re.I,
)
NAME_TAIL_RX = re.compile(r"\s*(?:-?ot|-?et|-?öt|-?at|-?t)\b\s*$", re.I)


def component_pairs(active_raw, ingredient_names):
    """[(név, mennyiség)] a betegtájékoztató mondatából.

    A multivitaminoknál az erősség önmagában csak számok sorozata
    ("0,5 mg + 1666 NE + 1,8 mg + ..."), ami olvashatatlan. Itt a
    mennyiséget a hozzá tartozó komponens nevével párosítjuk.
    """
    raw = re.sub(r"\s+", " ", (active_raw or "")).strip()
    if not raw:
        return []
    known = {fold(n)[:6] for n in (ingredient_names or []) if n}
    out, seen = [], set()
    for m in COMPONENT_RX.finditer(raw):
        amount = f"{m.group(1)} {m.group(2)}"
        name = NAME_TAIL_RX.sub("", m.group(3).strip(" -–")).strip()
        if len(name) < 3:
            continue
        key = fold(name)[:6]
        if known and key not in known:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append([name[0].upper() + name[1:], amount])
    return out if len(out) > 1 else []


# ---------------------------------------------------------------- gyógyszerforma

FORM_GROUP = {
    "tabletta": "tabletta",
    "filmtabletta": "tabletta",
    "bevont tabletta": "tabletta",
    "kapszula": "kapszula",
    "lágy kapszula": "kapszula",
    "kemény kapszula": "kapszula",
    "belsőleges oldatos csepp": "belsőleges cseppek",
    "belsőleges szuszpenzió": "szirup / belsőleges oldat",
    "szirup": "szirup / belsőleges oldat",
}


def form_group(form: str) -> str:
    f = (form or "").strip()
    return FORM_GROUP.get(f, f or "nem jelölt forma")


# ---------------------------------------------------------------- hatóanyagnév

STOP = {"és", "valamint", "illetve"}


def nice_ingredient(display, names, alias_display, key):
    if key in alias_display:
        return alias_display[key]
    parts = [p.strip() for p in (display or "").split("+") if p.strip()]
    if not parts and names:
        parts = [str(n).strip() for n in names if str(n).strip()]
    seen, out = set(), []
    for p in parts:
        k = fold(p)
        if k in seen or k in STOP or len(k) < 2:
            continue
        seen.add(k)
        out.append(p[0].upper() + p[1:] if p else p)
    if not out:
        return "Nem azonosított hatóanyag"
    if len(out) > 4:
        return " + ".join(out[:3]) + f" és {len(out) - 3} további összetevő"
    return " + ".join(out)


# ---------------------------------------------------------------- kategóriák

CAT_ICON = {
    "Megfázás": "cold",
    "Fájdalomcsillapítás, lázcsillapítás": "pain",
    "Vitaminok, immunerősítés": "pill",
    "Bélflóra, emésztés, probiotikumok": "gut",
    "Szív- és érrendszer": "vein",
    "Mozgás, sport": "joint",
    "Életmód": "smoke",
    "Bőrgyógyászat": "skin",
    "Fül, orr, szájápolás": "nose",
    "Allergia": "pollen",
    "Intim": "gyn",
    "Kiválasztás, húgyúti problémákra": "drop",
    "Stresszoldás, memória": "sleep",
    "Baba-mama": "drop",
    "Szemápolás": "eye",
    "Szépségápolás, dermokozmetika": "skin",
    "Kiegészítő eszközök": "pill",
    "LIVSANE termékek": "pill",
}

ICONS = {
    # 24x24 rács, csak vonal. A glifák szándékosan egyszerűek: színezett
    # csempében ülnek (lásd .ic), így 14 px-en is olvashatók, és a csempe
    # színe a terápiás családot kódolja — nem dísz, hanem gyors szűrés.
    "pain": '<path d="M13.6 2.8 6.4 12.9h4.1l-1 8.3 7.1-10.1h-4.1l1.1-8.3z"/>',
    "joint": '<circle cx="7.6" cy="7.6" r="3.5"/><circle cx="16.4" cy="16.4" r="3.5"/><path d="M10 10l4 4"/>',
    "cold": '<path d="M14 14.9V5.4a2 2 0 1 0-4 0v9.5a4.1 4.1 0 1 0 4 0z"/><path d="M12 8.6v6.6"/><path d="M16.6 7.2h2.6M16.6 10.6h1.8"/>',
    "nose": '<path d="M10 8.6h4a2.1 2.1 0 0 1 2.1 2.1v8.2a2.1 2.1 0 0 1-2.1 2.1h-4a2.1 2.1 0 0 1-2.1-2.1v-8.2A2.1 2.1 0 0 1 10 8.6z"/><path d="M11 8.6V5.9h2.6"/><path d="M18 4.6h2M18 7.6h2.6M19 10.6h1.6"/>',
    "lung": '<path d="M12 3.2v8.2"/><path d="M12 11.4c-1.2-2.1-3-2.5-4.3-1.5-1.7 1.2-2.2 3.5-1.8 6.6.3 2.2 1.6 3.5 3.1 3.2 1.6-.3 2.6-1.6 2.7-3.5l.3-4.8"/><path d="M12 11.4c1.2-2.1 3-2.5 4.3-1.5 1.7 1.2 2.2 3.5 1.8 6.6-.3 2.2-1.6 3.5-3.1 3.2-1.6-.3-2.6-1.6-2.7-3.5l-.3-4.8"/>',
    "throat": '<path d="M9.4 3v3.9c0 2.4-3 3.4-3 6.9a5.6 5.6 0 0 0 5.6 5.6 5.6 5.6 0 0 0 5.6-5.6c0-3.5-3-4.5-3-6.9V3"/><circle cx="12" cy="13.5" r="1.7"/>',
    "pollen": '<circle cx="12" cy="12" r="2.9"/><path d="M12 3.2v2.9M12 17.9v2.9M3.2 12h2.9M17.9 12h2.9M6.1 6.1l2 2M15.9 15.9l2 2M17.9 6.1l-2 2M8.1 15.9l-2 2"/>',
    "stomach": '<path d="M8.8 3.2v4.4c0 2.2 1.5 3 3.5 3.4 2.8.5 4.8 2.3 4.8 5.2a4.4 4.4 0 0 1-8.3 1.9"/><path d="M6.2 12c1.4-.7 2.6-.6 2.6-.6"/>',
    "gut": '<path d="M6 3.2v4a3.3 3.3 0 0 0 3.3 3.3h1.4a3.3 3.3 0 0 1 0 6.6H9.3A3.3 3.3 0 0 0 6 20.4"/><path d="M18 3.2v4a3.3 3.3 0 0 1-3.3 3.3"/>',
    "liver": '<path d="M3.9 8.3c4.1-3.1 12.2-3.1 16.2 0 .2 5.1-2.8 9.2-6.9 10.1-3.5.8-7.1-1.2-9.3-5.1"/>',
    "vein": '<path d="M12 20.3C8.8 18.3 4.3 14.9 4.3 10.8A4.35 4.35 0 0 1 12 8.1a4.35 4.35 0 0 1 7.7 2.7c0 4.1-4.5 7.5-7.7 9.5z"/>',
    "drop": '<path d="M12 3.2c0 0 5.7 6.3 5.7 10a5.7 5.7 0 1 1-11.4 0c0-3.7 5.7-10 5.7-10z"/>',
    "gyn": '<circle cx="12" cy="8.6" r="4.6"/><path d="M12 13.2v7.4M9 17.9h6"/>',
    "skin": '<rect x="2.4" y="9" width="19.2" height="6" rx="3" transform="rotate(-35 12 12)"/><path d="M9.3 9.3l5.4 5.4"/>',
    "nail": '<path d="M8.5 20.2h7a1.8 1.8 0 0 0 1.8-1.8V9.7c0-3-2.4-5.5-5.3-5.5S6.7 6.7 6.7 9.7v8.7a1.8 1.8 0 0 0 1.8 1.8z"/><path d="M6.7 12.5h10.6"/>',
    "eye": '<path d="M2.6 12S6.2 5.8 12 5.8 21.4 12 21.4 12 17.8 18.2 12 18.2 2.6 12 2.6 12z"/><circle cx="12" cy="12" r="2.9"/>',
    "sleep": '<path d="M20.2 14.6A8.4 8.4 0 0 1 9.4 3.8 8.4 8.4 0 1 0 20.2 14.6z"/>',
    "smoke": '<rect x="3" y="14.6" width="12.6" height="4.2" rx="1.4"/><path d="M18.2 14.6H21v4.2h-2.8"/><path d="M8.4 11.4c0-1.7-2-1.7-2-3.5s2-1.7 2-3.5"/><path d="M13.2 11.4c0-1.4-1.6-1.4-1.6-2.9"/><path d="M3.8 20.8 20.2 4"/>',
    "pill": '<rect x="2.6" y="8.6" width="18.8" height="6.8" rx="3.4" transform="rotate(-40 12 12)"/><path d="M9.5 9.5l5 5"/>',
}

# A csempe színe a terápiás családot kódolja: a bal oldali listát így
# színnel is lehet pásztázni, nem csak olvasni.
ICON_HUE = {
    "pain": 0, "joint": 0,
    "cold": 1, "nose": 1, "lung": 1, "throat": 1,
    "pollen": 2,
    "stomach": 3, "gut": 3, "liver": 3,
    "vein": 4, "drop": 4, "gyn": 4,
    "skin": 5, "nail": 5, "eye": 5, "sleep": 5, "smoke": 5, "pill": 5,
}
# ---------------------------------------------------------------- adatelőkészítés

def build_rows(products, alias, alias_display):
    prepared = []
    for p in products:
        ar = p.get("price_huf")
        if not ar:
            continue
        qty = p.get("package_amount")
        qunit = (p.get("package_unit") or "").lower() or None

        nq, nu = pack_from_name(p.get("name"))
        pack_fixed = False
        if nq and nu and qunit == nu and qty and abs(nq - qty) > 0.01:
            qty, pack_fixed = nq, True
        elif nq and nu and not qty:
            qty, qunit, pack_fixed = nq, nu, True

        ft_per_pack_unit = round(ar / qty, 1) if qty else None
        benu_unit = p.get("unit_price_huf")
        unit_mismatch = bool(
            ft_per_pack_unit and benu_unit
            and (benu_unit / ft_per_pack_unit > 1.35 or benu_unit / ft_per_pack_unit < 0.74)
        )

        mg_unit, mg_kind = strength_mg(p.get("strength_display"))
        t = topical_mg_per_g(p.get("strength_display"), p.get("form"))
        if t:
            mg_unit, mg_kind = t, "g"
        elif mg_kind == "db" and qunit in ("ml", "g"):
            mg_unit, mg_kind = None, None

        total_mg = None
        if mg_unit and qty:
            if (mg_kind == "db" and qunit == "db") or (mg_kind in ("ml", "g") and qunit in ("ml", "g")):
                total_mg = mg_unit * qty
        ft_per_g = round(ar / (total_mg / 1000.0), 1) if total_mg else None

        if ft_per_pack_unit:
            u = {"db": "db", "ml": "ml", "g": "g", "tasak": "tasak"}.get(qunit, qunit or "egység")
            cmp_val = ft_per_pack_unit
            cmp_txt = f"{ft_per_pack_unit:,.0f} Ft / {u}".replace(",", " ")
            cmp_kind = ("mg-" if ft_per_g else "") + (qunit or "?")
        else:
            cmp_val, cmp_txt, cmp_kind = None, "—", "none"

        raw_key = p.get("ingredient_key") or "?"
        key = alias.get(raw_key, raw_key)
        comps = component_pairs(p.get("active_ingredient_raw"), p.get("ingredient_names"))

        prepared.append({
            "nev": p.get("name"), "url": p.get("url"), "gyarto": p.get("brand"),
            "ar": ar,
            "kisz": p.get("package_label") or (f"{qty:g} {qunit}" if qty and qunit else None),
            "kisz_egyseg": qunit,
            "kiszn": qty,
            "eross": p.get("strength_display"), "forma": p.get("form"),
            "ear": cmp_txt, "earv": cmp_val, "earkind": cmp_kind,
            "mismatch": unit_mismatch, "pack_fixed": pack_fixed,
            "hakey": key, "raw_key": raw_key,
            "hadisp": nice_ingredient(p.get("ingredient_display"), p.get("ingredient_names"), alias_display, key),
            "kat": p.get("primary_category") or "Egyéb",
            "alkat": p.get("secondary_category") or "Egyéb",
            "fgroup": form_group(p.get("form")),
            "sdisp": p.get("strength_display") or "nem jelölt erősség",
            "raw_skey": p.get("strength_key") or "no-strength",
            "one_ing": len(p.get("canonical_ingredients") or []) == 1,
            "komp": comps,
            "mg_unit": mg_unit, "mg_kind": mg_kind, "skey": None,
        })

    for x in prepared:
        if x["one_ing"] and x["mg_unit"]:
            x["skey"] = f'{round(x["mg_unit"], 4):g}|{x["mg_kind"]}'
            x["sdisp"] = {"db": f'{round(x["mg_unit"], 4):g} mg',
                          "ml": f'{round(x["mg_unit"], 4):g} mg/ml',
                          "g": f'{round(x["mg_unit"], 4):g} mg/g'}[x["mg_kind"]]
        else:
            x["skey"] = x["raw_skey"]
            if x["komp"]:
                x["sdisp"] = f'{len(x["komp"])} összetevő'
            elif not x["eross"]:
                x["sdisp"] = "erősség nincs feltüntetve"

    by_ing = defaultdict(list)
    for x in prepared:
        by_ing[x["hakey"]].append(x)

    rows = []
    for key, plist in by_ing.items():
        blocks = defaultdict(list)
        for x in plist:
            blocks[(x["skey"], x["sdisp"], x["fgroup"])].append(x)

        bl = []
        for (skey, sdisp, fg), prods in blocks.items():
            prods.sort(key=lambda z: (z["earv"] is None, z["earv"] or 0))
            olcso = prods[0]
            megt = tipp = None
            if len(prods) > 1 and olcso["earv"]:
                komb = lambda z: "+" in (z["eross"] or "")
                mas = [z for z in prods if z["earv"] and z["earkind"] == olcso["earkind"]
                       and brand_key(z["nev"]) != brand_key(olcso["nev"])
                       and komb(z) == komb(olcso)]
                if mas:
                    draga = max(mas, key=lambda z: z["earv"])
                    pct = round(100 * (1 - olcso["earv"] / draga["earv"]))
                    if pct >= 5 and draga["earv"] / olcso["earv"] <= 10:
                        megt = {"pct": pct, "olcso": olcso["nev"], "olcso_ar": olcso["ar"],
                                "olcso_ear": olcso["ear"], "olcso_url": olcso["url"],
                                "olcso_earv": olcso["earv"], "olcso_kiszn": olcso["kiszn"],
                                "egyseg": olcso["kisz_egyseg"],
                                "draga": draga["nev"], "draga_ar": draga["ar"],
                                "draga_ear": draga["ear"], "draga_earv": draga["earv"],
                                "draga_url": draga["url"]}
                azonos = [z for z in prods if z["earv"] and z["earkind"] == olcso["earkind"]
                          and brand_key(z["nev"]) == brand_key(olcso["nev"]) and z is not olcso]
                if azonos:
                    d2 = max(azonos, key=lambda z: z["earv"])
                    p2 = round(100 * (1 - olcso["earv"] / d2["earv"]))
                    if p2 >= 15:
                        tipp = {"pct": p2, "nagy": olcso["nev"], "kicsi": d2["nev"]}
            bl.append({"eross": sdisp, "forma": fg, "db": len(prods),
                       "megt": megt, "tipp": tipp, "termekek": prods})

        def order(b):
            m = re.search(r"(\d+(?:[.,]\d+)?)", b["eross"] or "")
            return (-num(m.group(1)) if m else 0, b["forma"])

        bl.sort(key=order)
        allp = [z for b in bl for z in b["termekek"]]
        kat = Counter(z["kat"] for z in allp).most_common(1)[0][0]
        alkat = Counter(z["alkat"] for z in allp).most_common(1)[0][0]
        best = max((b["megt"]["pct"] for b in bl if b["megt"]), default=None)
        besthit = None
        for b in bl:
            if b["megt"] and b["megt"]["pct"] == best:
                besthit = dict(b["megt"], eross=b["eross"], forma=b["forma"])
                break
        olcsobb = min((z for z in allp if z["earv"]), key=lambda z: z["earv"], default=allp[0])
        rows.append({
            "key": key, "ha": allp[0]["hadisp"],
            "kat": kat, "alkat": alkat, "ikon": CAT_ICON.get(kat, "pill"),
            "blokkok": bl, "db": len(allp), "blokk_db": len(bl),
            "ar_min": min(z["ar"] for z in allp), "ar_max": max(z["ar"] for z in allp),
            "megt_pct": best, "megt": besthit,
            "gyartok": len({brand_key(z["nev"]) for z in allp}),
            "olcso_nev": olcsobb["nev"], "olcso_ar": olcsobb["ar"],
            "olcso_url": olcsobb["url"], "olcso_ear": olcsobb["ear"],
        })

    rows.sort(key=lambda r: (r["kat"], r["alkat"], -r["db"], r["ha"]))
    return rows, prepared


# ---------------------------------------------------------------- panasz-opciók

SOLID_DEFAULT = ["tabletta", "kapszula", "szopogató", "rágótabletta",
                 "pezsgő", "granulátum", "por"]


def form_matches(forma, tokens):
    f = fold(forma or "")
    return any(fold(t) in f for t in tokens)


def option_view(row, opt, prefer):
    """Egy panasz-opció nézete: formaszűrés, ajánlott forma, többi forma.

    A KEMÉNY `forms` szűrő nélkül a hatóanyag minden készítménye szóba jönne —
    így került az orrdugulás alá a dexpanthenol BŐRKENŐCS. Ha a szűrés után nem
    marad készítmény, az opció kimarad, és a generátor figyelmeztet.
    """
    blocks = row["blokkok"]
    hard = opt.get("forms")
    if hard:
        blocks = [b for b in blocks if form_matches(b["forma"], hard)]
        if not blocks:
            return None
    order = opt.get("prefer_forms") or prefer or SOLID_DEFAULT

    def rank(b):
        f = fold(b["forma"] or "")
        for i, t in enumerate(order):
            if fold(t) in f:
                return (i, -b["db"])
        return (len(order), -b["db"])

    blocks = sorted(blocks, key=rank)
    # Az ajánlás EGY blokk: azonos erősség és azonos forma. Enélkül a felnőtt
    # 1 mg/ml és a gyermek 0,5 mg/ml orrspray egy listába kerülne, és az
    # egységáruk összevetése félrevezetne.
    top_forma = blocks[0]["forma"]
    same_form = [b for b in blocks if b["forma"] == top_forma]
    rec = max(same_form, key=lambda b: (b["db"], b["megt"]["pct"] if b["megt"] else 0))
    prods = list(rec["termekek"])
    megt = rec["megt"]

    egyeb = []
    for b in blocks:
        if b is rec:
            continue
        c = min(b["termekek"], key=lambda z: (z["earv"] is None, z["earv"] or 0))
        cimke = b["forma"] if b["forma"] != top_forma else b["eross"]
        egyeb.append({"forma": cimke, "nev": c["nev"], "url": c["url"],
                      "ar": c["ar"], "ear": c["ear"]})

    egyseg = {"db": "tabletta / darab", "ml": "ml", "g": "g"}.get(
        (prods[0].get("kisz_egyseg") if prods else None) or "", "egység")
    return {
        "rec_forma": rec["eross"] + " · " + rec["forma"],
        "rec_egyseg": egyseg,
        "rec_termekek": [{"nev": p["nev"], "url": p["url"], "ar": p["ar"],
                          "kisz": p["kisz"], "eross": p["eross"], "ear": p["ear"]}
                         for p in prods[:4]],
        "rec_db": len(prods),
        "egyeb": egyeb[:4],
        "megt": megt,
        "szurve": bool(hard),
    }



TPL = r"""<!doctype html>
<html lang="hu"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vény nélküli gyógyszer adatbázis</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root{
 --bg:#F0F5F1;--bg-top:#FBFDFB;--bg-bottom:#EDF3F0;--card:#FFF;--card2:#F7FAF7;--card3:#E4EBE4;
 --ink:#101714;--ink2:#55615B;--ink3:#858F88;--line:#DDE4DD;--line2:#BFC9C0;
 --brand:#0E6B4F;--brand-deep:#164C3B;--brand-bg:#E0F1E8;--brand-line:#8DC7AA;--on-brand:#FFF;
 --hot:#A04552;--hot-bg:#FCF1F3;--hot-line:#E6BEC5;
 --flag:#8A5B13;--flag-bg:#FAEFD9;--flag-line:#E0BD79;
 --alt:#235D8D;--alt-bg:#E0EBF5;--alt-line:#9ABADA;
 --glass:rgba(255,255,255,.82);--glass-strong:#FFFFFF;
 --fb:"Archivo",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 --fm:"IBM Plex Mono",ui-monospace,SFMono-Regular,Consolas,monospace;
 --fs:"Archivo",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 --c0:#2F7D5C;--c0b:#E4F0EA;--c1:#2C5E8F;--c1b:#E3ECF6;--c2:#8A5A1F;--c2b:#F6EDDF;
 --c3:#6B4C8F;--c3b:#EEE9F6;--c4:#1F6E77;--c4b:#E1EFF1;--c5:#8C3F52;--c5b:#F6E8EB;
 --i0:#8A5A1F;--i0b:#F5EADA;--i1:#2C5E8F;--i1b:#E1EAF5;--i2:#1F6E77;--i2b:#DFEDF0;
 --i3:#2F7D5C;--i3b:#E1EFE8;--i4:#8C3F52;--i4b:#F5E6E9;--i5:#6B4C8F;--i5b:#ECE7F4;
 --lad0:#BFE2CF;--lad1:#E8E0CB;--lad2:#EBCBD1;
 --atmo:linear-gradient(112deg,rgba(14,107,79,.14) 0%,rgba(14,107,79,0) 34%),
  linear-gradient(78deg,rgba(35,93,141,0) 18%,rgba(35,93,141,.11) 51%,rgba(35,93,141,0) 78%),
  linear-gradient(180deg,var(--bg-top) 0%,var(--bg) 42%,var(--bg-bottom) 100%);
 --shadow:0 18px 48px rgba(16,23,20,.12),0 1px 2px rgba(16,23,20,.06);
 --shadow-panel:0 26px 70px rgba(16,23,20,.10),0 2px 5px rgba(16,23,20,.05);
 --shadow-soft:0 1px 0 rgba(255,255,255,.75) inset}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#0E1211;--bg-top:#121A17;--bg-bottom:#0B100F;--card:#171B19;--card2:#1C211F;--card3:#212724;
 --ink:#E7EAE7;--ink2:#9EA6A1;--ink3:#767E79;--line:#292F2C;--line2:#38403B;
 --brand:#6FC79B;--brand-deep:#2F9C72;--brand-bg:#122A20;--brand-line:#2D5B43;--on-brand:#0E1211;
 --hot:#D08496;--hot-bg:#241519;--hot-line:#4A2B32;
 --flag:#D9AC5C;--flag-bg:#292013;--flag-line:#56441F;
 --alt:#7DA6D6;--alt-bg:#131F2B;--alt-line:#2B415A;
 --glass:rgba(23,27,25,.86);--glass-strong:#171B19;
 --c0:#5FB98F;--c0b:#122720;--c1:#7DA6D6;--c1b:#131F2B;--c2:#C9964E;--c2b:#231D12;
 --c3:#A489CC;--c3b:#1D1928;--c4:#5FAAB2;--c4b:#112324;--c5:#C5798C;--c5b:#25171B;
 --i0:#C9964E;--i0b:#231C11;--i1:#7DA6D6;--i1b:#131E2A;--i2:#5FAAB2;--i2b:#102223;
 --i3:#5FB98F;--i3b:#112620;--i4:#C5798C;--i4b:#241619;--i5:#A489CC;--i5b:#1C1826;
 --lad0:#2D5B43;--lad1:#3E3A2C;--lad2:#4A2B32;
 --atmo:linear-gradient(112deg,rgba(111,199,155,.10) 0%,rgba(111,199,155,0) 34%),
  linear-gradient(78deg,rgba(125,166,214,0) 18%,rgba(125,166,214,.08) 51%,rgba(125,166,214,0) 78%),
  linear-gradient(180deg,var(--bg-top) 0%,var(--bg) 42%,var(--bg-bottom) 100%);
 --shadow:0 16px 42px rgba(0,0,0,.34),0 1px 2px rgba(0,0,0,.35);
 --shadow-panel:0 24px 60px rgba(0,0,0,.30),0 2px 5px rgba(0,0,0,.28);
 --shadow-soft:0 1px 0 rgba(255,255,255,.06) inset}}
:root[data-theme="dark"]{
 --bg:#0E1211;--bg-top:#121A17;--bg-bottom:#0B100F;--card:#171B19;--card2:#1C211F;--card3:#212724;
 --ink:#E7EAE7;--ink2:#9EA6A1;--ink3:#767E79;--line:#292F2C;--line2:#38403B;
 --brand:#6FC79B;--brand-deep:#2F9C72;--brand-bg:#122A20;--brand-line:#2D5B43;--on-brand:#0E1211;
 --hot:#D08496;--hot-bg:#241519;--hot-line:#4A2B32;
 --flag:#D9AC5C;--flag-bg:#292013;--flag-line:#56441F;
 --alt:#7DA6D6;--alt-bg:#131F2B;--alt-line:#2B415A;
 --glass:rgba(23,27,25,.86);--glass-strong:#171B19;
 --c0:#5FB98F;--c0b:#122720;--c1:#7DA6D6;--c1b:#131F2B;--c2:#C9964E;--c2b:#231D12;
 --c3:#A489CC;--c3b:#1D1928;--c4:#5FAAB2;--c4b:#112324;--c5:#C5798C;--c5b:#25171B;
 --i0:#C9964E;--i0b:#231C11;--i1:#7DA6D6;--i1b:#131E2A;--i2:#5FAAB2;--i2b:#102223;
 --i3:#5FB98F;--i3b:#112620;--i4:#C5798C;--i4b:#241619;--i5:#A489CC;--i5b:#1C1826;
 --lad0:#2D5B43;--lad1:#3E3A2C;--lad2:#4A2B32;
 --atmo:linear-gradient(112deg,rgba(111,199,155,.10) 0%,rgba(111,199,155,0) 34%),
  linear-gradient(78deg,rgba(125,166,214,0) 18%,rgba(125,166,214,.08) 51%,rgba(125,166,214,0) 78%),
  linear-gradient(180deg,var(--bg-top) 0%,var(--bg) 42%,var(--bg-bottom) 100%);
 --shadow:0 16px 42px rgba(0,0,0,.34),0 1px 2px rgba(0,0,0,.35);
 --shadow-panel:0 24px 60px rgba(0,0,0,.30),0 2px 5px rgba(0,0,0,.28);
 --shadow-soft:0 1px 0 rgba(255,255,255,.06) inset}
*{box-sizing:border-box}
html{min-height:100%}
body{margin:0;min-height:100vh;display:flex;flex-direction:column;background:var(--atmo);
 background-repeat:no-repeat;background-attachment:fixed;color:var(--ink);font-family:var(--fb);
 font-size:14.5px;line-height:1.5;-webkit-font-smoothing:antialiased}
header,.ctl,main,footer{position:relative}
a{color:inherit}
:focus-visible{outline:2px solid var(--brand);outline-offset:2px;border-radius:5px}
.w{max-width:1240px;margin:0 auto;padding:0 22px}
.m{font-family:var(--fm);font-variant-numeric:tabular-nums}
.s{font-family:var(--fb)}
.lbl{font-family:var(--fm);font-size:9.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--ink3)}

/* ---- fejléc ---- */
header{background:var(--glass-strong);border-bottom:1px solid var(--line);
 box-shadow:0 18px 48px rgba(16,23,20,.07);backdrop-filter:blur(18px)}
header::after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:2px;
 background:linear-gradient(90deg,var(--brand),var(--alt),var(--flag),var(--hot));opacity:.82}
.hd{display:flex;align-items:center;gap:14px 22px;flex-wrap:wrap;padding:20px 0 19px}
.hd h1{margin:0;font-family:var(--fb);font-size:30px;font-weight:800;letter-spacing:0;line-height:1.05}
.stats{display:flex;gap:8px;margin-left:auto;align-items:stretch;flex-wrap:wrap}
.stats .st{display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:2px;
 min-width:112px;background:linear-gradient(180deg,var(--card),var(--card2));border:1px solid var(--line);border-radius:8px;
 padding:8px 10px;box-shadow:var(--shadow-soft)}
.stats .st b{font-family:var(--fm);font-size:18px;font-weight:600;letter-spacing:0;line-height:1}
.stats .st i{font-family:var(--fm);font-style:normal;font-size:9.4px;letter-spacing:.1em;
 text-transform:uppercase;color:var(--ink3)}
.stats .sep{display:none}
.stats .save b{color:var(--brand)}

/* ---- vezérlősáv ---- */
.ctl{position:sticky;top:0;z-index:30;background:transparent;border-bottom:0;
 padding:12px 0 10px;backdrop-filter:blur(14px)}
.cr{display:flex;gap:9px;flex-wrap:wrap;align-items:center;background:var(--glass);
 border:1px solid var(--line);border-radius:8px;padding:7px;box-shadow:var(--shadow-panel)}
.tabs{display:flex;gap:4px;background:var(--card3);border:1px solid var(--line);border-radius:8px;padding:3px;box-shadow:var(--shadow-soft)}
.tabs button{font:inherit;font-size:13.3px;font-weight:500;color:var(--ink2);background:none;
 border:0;border-radius:6px;padding:8px 14px;cursor:pointer;white-space:nowrap}
.tabs button:hover{color:var(--ink)}
.tabs button[aria-current="true"]{background:var(--card);color:var(--ink);font-weight:700;box-shadow:0 8px 22px rgba(16,23,20,.10),var(--shadow-soft)}
.srch{flex:1 1 250px;min-width:190px;position:relative;display:flex}
.srch input{width:100%;font:inherit;font-size:14px;color:var(--ink);background:var(--card);
 border:1px solid var(--line2);border-radius:8px;padding:10px 34px 10px 34px;box-shadow:var(--shadow-soft)}
.srch input::placeholder{color:var(--ink3)}
.srch>svg{position:absolute;left:10px;top:50%;transform:translateY(-50%);width:15px;height:15px;
 stroke:var(--ink3);fill:none;stroke-width:2;stroke-linecap:round}
.srch kbd{position:absolute;right:9px;top:50%;transform:translateY(-50%);font-family:var(--fm);
 font-size:10px;color:var(--ink3);border:1px solid var(--line2);border-radius:4px;padding:1px 5px;background:var(--card2)}
select{font:inherit;font-size:13.4px;color:var(--ink);background:var(--card);
 border:1px solid var(--line2);border-radius:8px;padding:10px 10px;cursor:pointer;box-shadow:var(--shadow-soft)}
.cnt{font-family:var(--fm);font-size:11.2px;color:var(--ink3);margin-left:auto;white-space:nowrap}

/* ---- ikoncsempe ---- */
.ic{position:relative;display:inline-flex;align-items:center;justify-content:center;width:25px;height:25px;
 border-radius:8px;flex-shrink:0;border:1px solid currentColor;overflow:hidden;box-shadow:var(--shadow-soft)}
.ic::before{content:"";position:absolute;inset:5px;border:1px solid currentColor;border-radius:6px;
 opacity:.16;transform:rotate(8deg)}
.ic::after{content:"";position:absolute;right:4px;top:4px;width:4px;height:4px;border-radius:50%;
 background:currentColor;opacity:.22}
.ic svg{position:relative;z-index:1;width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.9;
 stroke-linecap:round;stroke-linejoin:round}
.ic.big{width:42px;height:42px;border-radius:8px}
.ic.big::before{inset:7px;border-radius:7px}.ic.big::after{right:6px;top:6px;width:5px;height:5px}
.ic.big svg{width:23px;height:23px;stroke-width:1.75}
.ic.h0{background:linear-gradient(135deg,var(--i0b),var(--card));color:var(--i0)}
.ic.h1{background:linear-gradient(135deg,var(--i1b),var(--card));color:var(--i1)}
.ic.h2{background:linear-gradient(135deg,var(--i2b),var(--card));color:var(--i2)}
.ic.h3{background:linear-gradient(135deg,var(--i3b),var(--card));color:var(--i3)}
.ic.h4{background:linear-gradient(135deg,var(--i4b),var(--card));color:var(--i4)}
.ic.h5{background:linear-gradient(135deg,var(--i5b),var(--card));color:var(--i5)}

/* ---- váz ---- */
main{flex:1;padding:22px 0 58px}
.shell{display:grid;grid-template-columns:248px minmax(0,1fr);gap:28px;align-items:start}
.shell.solo{grid-template-columns:minmax(0,1fr)}
.nav{position:sticky;top:82px;max-height:calc(100vh - 104px);overflow-y:auto;
 padding:10px;background:var(--glass);border:1px solid var(--line);border-radius:8px;box-shadow:var(--shadow-soft)}
.nav h3{margin:0 0 7px;font-family:var(--fm);font-size:9.5px;letter-spacing:.11em;
 text-transform:uppercase;color:var(--ink3);font-weight:400}
.nav button{display:flex;width:100%;gap:9px;align-items:center;text-align:left;font:inherit;
 font-size:13.2px;color:var(--ink2);background:none;border:0;border-radius:8px;
 padding:5px 8px 5px 5px;cursor:pointer;line-height:1.3}
.nav button:hover{background:var(--card2);color:var(--ink)}
.nav button[aria-current="true"]{background:var(--card);color:var(--ink);font-weight:700;box-shadow:0 8px 20px rgba(16,23,20,.08),var(--shadow-soft)}
.nav button i{margin-left:auto;font-style:normal;font-family:var(--fm);font-size:10.4px;color:var(--ink3)}
.nav .sub{padding-left:38px;font-size:12.3px;color:var(--ink3)}
.nav .sub:hover{color:var(--ink);background:none;text-decoration:underline}
.nav hr{border:0;border-top:1px solid var(--line);margin:10px 0}
.lead{font-size:14px;color:var(--ink2);max-width:70ch;margin:3px 0 18px;line-height:1.65}
.lead b{color:var(--ink);font-weight:600}

/* ---- panasz-csempék ---- */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(238px,1fr));gap:10px}
.tile{display:flex;flex-direction:column;gap:8px;text-align:left;font:inherit;color:inherit;
 background:linear-gradient(180deg,var(--card),var(--card2));border:1px solid var(--line);border-radius:8px;padding:14px;cursor:pointer;box-shadow:var(--shadow-soft)}
.tile:hover{border-color:var(--brand-line);background:var(--card2);transform:translateY(-1px);box-shadow:var(--shadow)}
.tile{transition:transform .12s,border-color .12s}
.tile .t{display:flex;align-items:center;gap:9px;font-weight:800;font-size:14.4px;letter-spacing:0}
.tile p{margin:0;font-size:12.6px;color:var(--ink2);line-height:1.5;
 display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.tile .n{font-family:var(--fm);font-size:10.2px;color:var(--ink3);margin-top:auto;padding-top:5px}
.back{display:inline-flex;align-items:center;gap:6px;font:inherit;font-size:13px;color:var(--ink2);
 background:none;border:0;padding:4px 0;cursor:pointer;margin-bottom:8px}
.back:hover{color:var(--ink)}
.back svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round}
.sym-h{display:flex;align-items:center;gap:12px;margin:0 0 6px}
.sym-h span{font-family:var(--fb);font-size:30px;font-weight:800;letter-spacing:0;line-height:1.08}

/* ---- panasz-opció ---- */
.opt{background:var(--card);border:1px solid var(--line);border-radius:8px;margin-bottom:12px;overflow:hidden;box-shadow:var(--shadow-panel)}
.opt-h{display:grid;grid-template-columns:minmax(0,1fr) 160px;gap:20px;align-items:start;
 padding:15px 17px 13px;background:linear-gradient(180deg,var(--card),var(--card2))}
.role{display:inline-block;font-family:var(--fm);font-size:9.4px;letter-spacing:.1em;
 text-transform:uppercase;border-radius:4px;padding:2px 7px;margin-bottom:6px;border:1px solid transparent}
.role.first{background:var(--brand-bg);color:var(--brand);border-color:var(--brand-line)}
.role.alt{background:var(--alt-bg);color:var(--alt);border-color:var(--alt-line)}
.role.note{background:var(--card3);color:var(--ink2);border-color:var(--line2)}
.opt h4{margin:0 0 6px;font-size:19px;font-weight:800;letter-spacing:0}
.opt .why{margin:0;font-size:13.4px;line-height:1.6;color:var(--ink2);max-width:64ch}
.opt .cau{margin:8px 0 0;font-size:12.8px;line-height:1.55;color:var(--ink);background:var(--flag-bg);
 border:1px solid var(--flag-line);border-radius:8px;padding:7px 10px;max-width:64ch}
.rec{border-top:1px solid var(--line);background:var(--card2);padding:12px 17px 14px}
.rec-h{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;margin-bottom:9px}
.rec-h b{font-family:var(--fm);font-size:9.6px;letter-spacing:.1em;text-transform:uppercase;color:var(--brand)}
.rec-h em{font-style:normal;font-size:11.8px;color:var(--ink3)}
.rtw{overflow-x:auto}
.rt{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.rt th{font-family:var(--fm);font-size:9.2px;letter-spacing:.08em;text-transform:uppercase;
 color:var(--ink3);text-align:left;font-weight:400;padding:0 12px 6px 0;white-space:nowrap}
.rt th.n,.rt td.n{text-align:right;padding-right:0}
.rt td{border-top:1px solid var(--line);padding:8px 12px 8px 0;font-size:13.2px;vertical-align:baseline}
.rt tr:first-child td{border-top-color:var(--line2)}
.rt .mm{font-family:var(--fm);font-size:12.4px;white-space:nowrap}
.rt a{color:var(--brand);text-decoration:none}
.rt a:hover{text-decoration:underline}
.forms{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin-top:12px;padding-top:11px;border-top:1px solid var(--line)}
.fchip{display:inline-flex;align-items:baseline;gap:7px;background:var(--card);border:1px solid var(--line2);
 border-radius:100px;padding:5px 12px;text-decoration:none}
.fchip:hover{border-color:var(--brand-line)}
.fchip b{font-size:12.4px;font-weight:500;color:var(--ink)}
.fchip span{font-family:var(--fm);font-size:11.4px;color:var(--ink2)}
.opt details{border-top:1px solid var(--line)}
.opt details>summary{list-style:none;cursor:pointer;font-size:12.9px;color:var(--ink2);padding:9px 17px}
.opt details>summary::-webkit-details-marker{display:none}
.opt details>summary:hover{background:var(--card2);color:var(--ink)}
.opt details[open]>summary{border-bottom:1px solid var(--line)}
.opt .dt{padding:3px 15px 13px}

/* ---- katalógus ---- */
.gh{display:flex;gap:10px;align-items:center;padding:24px 2px 9px;border-bottom:2px solid var(--ink)}
.gh:first-child{padding-top:2px}
.gh b{font-family:var(--fb);font-size:21px;font-weight:800;letter-spacing:0}
.gh span{font-family:var(--fm);font-size:10.4px;color:var(--ink3);margin-left:auto}
.sh{display:flex;align-items:center;gap:9px;padding:10px 13px;background:var(--card3);
 border-bottom:1px solid var(--line);margin-top:1px;scroll-margin-top:70px}
.sh b{font-size:12.9px;font-weight:600}
.sh i{font-family:var(--fm);font-size:10.2px;color:var(--ink3);font-style:normal;margin-left:auto}
.r{background:var(--card);border-bottom:1px solid var(--line)}
.r>summary{list-style:none;display:grid;grid-template-columns:minmax(190px,1.3fr) minmax(130px,1fr) 156px 92px 18px;
 gap:16px;align-items:center;padding:11px 13px;cursor:pointer}
.r>summary::-webkit-details-marker{display:none}
.r>summary:hover{background:var(--card2)}
.ha b{font-family:var(--fb);font-size:17px;font-weight:800;letter-spacing:0}
.nb{font-family:var(--fm);font-size:10.4px;color:var(--ink3);margin-top:2px;display:block}
.ind{font-size:12.5px;color:var(--ink2);line-height:1.4}
.pr{font-family:var(--fm);font-size:12.4px;color:var(--ink3);font-variant-numeric:tabular-nums;line-height:1.45}
.pr b{color:var(--ink);font-weight:600;display:block;font-size:13px}
.bdg{display:block;font-family:var(--fm);font-size:13.4px;font-weight:600;text-align:center;
 border-radius:8px;padding:5px;border:1px solid transparent;font-variant-numeric:tabular-nums;line-height:1.15}
.bdg i{display:block;font-family:var(--fb);font-style:normal;font-weight:500;font-size:8.6px;
 letter-spacing:.05em;text-transform:uppercase;opacity:.78;margin-top:2px}
.b-save{background:var(--brand-bg);color:var(--brand);border-color:var(--brand-line)}
.b-none{color:var(--ink3);border-color:var(--line)}
.cv{width:16px;height:16px;stroke:var(--ink3);fill:none;stroke-width:2;stroke-linecap:round;transition:transform .16s}
.r[open] .cv{transform:rotate(180deg)}
.r[open]>summary{background:var(--card2);border-bottom:1px solid var(--line)}
.dt{padding:5px 13px 15px}

/* ---- erősség-blokk ---- */
.bl{margin-top:11px;border:1px solid var(--line);border-left:4px solid var(--bc);border-radius:8px;overflow:hidden}
.bl.k0{--bc:var(--c0);--bb:var(--c0b)}.bl.k1{--bc:var(--c1);--bb:var(--c1b)}
.bl.k2{--bc:var(--c2);--bb:var(--c2b)}.bl.k3{--bc:var(--c3);--bb:var(--c3b)}
.bl.k4{--bc:var(--c4);--bb:var(--c4b)}.bl.k5{--bc:var(--c5);--bb:var(--c5b)}
.bl-h{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:8px 11px;background:var(--bb);border-bottom:1px solid var(--line)}
.bl-h b{font-family:var(--fm);font-size:12.2px;font-weight:600;color:var(--bc)}
.bl-h em{font-style:normal;font-size:12.2px;color:var(--ink2)}
.bl-h .n{font-family:var(--fm);font-size:10.3px;color:var(--ink3);margin-left:auto}
.bl-h .p{font-family:var(--fm);font-size:11.5px;font-weight:600;color:var(--bc);
 background:var(--card);border:1px solid var(--bc);border-radius:5px;padding:1px 7px}

/* ---- árlétra ---- */
.lad{padding:15px 16px 8px;background:var(--card)}
.lad-t{position:relative;height:30px}
.lad-t .axis{position:absolute;left:0;right:0;top:14px;height:3px;border-radius:2px;
 background:linear-gradient(90deg,var(--lad0) 0%,var(--lad1) 52%,var(--lad2) 100%)}
.lad-t .dot{position:absolute;top:11px;width:9px;height:9px;border-radius:50%;
 background:var(--line2);margin-left:-4.5px}
.lad-t .dot.lo{top:8px;width:15px;height:15px;margin-left:-7.5px;background:var(--brand);
 border:3px solid var(--card);box-shadow:0 0 0 1px var(--brand)}
.lad-t .dot.hi{top:10px;width:11px;height:11px;margin-left:-5.5px;background:var(--hot)}
.lad-e{display:flex;justify-content:space-between;gap:12px;margin-top:2px}
.lad-e span{font-family:var(--fm);font-size:11px;font-variant-numeric:tabular-nums}
.lad-e .l{color:var(--brand);font-weight:600}
.lad-e .h{color:var(--hot);font-weight:600;text-align:right}

.tw{overflow-x:auto}
.tb{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.tb th{font-family:var(--fm);font-size:9.4px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3);
 text-align:left;font-weight:400;padding:7px 10px 5px;white-space:nowrap}
.tb th.n,.tb td.n{text-align:right}
.tb td{padding:7px 10px;border-top:1px solid var(--line);font-size:13.1px;vertical-align:top}
.tb tr.best td{background:var(--brand-bg)}
.tb a{color:var(--brand);text-decoration:none;font-weight:500}
.tb a:hover{text-decoration:underline}
.tb .mm{font-family:var(--fm);font-size:12.3px;white-space:nowrap}
.tag{font-family:var(--fm);font-size:9.2px;letter-spacing:.05em;text-transform:uppercase;
 border:1px solid var(--line2);border-radius:4px;padding:1px 5px;color:var(--ink2);margin-left:6px;white-space:nowrap}
.tag.b{border-color:var(--brand-line);color:var(--brand);background:var(--brand-bg)}
.tag.f{border-color:var(--flag-line);color:var(--flag);background:var(--flag-bg)}
.note{margin:9px 11px 11px;font-size:12.5px;line-height:1.6;color:var(--ink2);
 border-left:2px solid var(--line2);padding-left:10px}
.note b{color:var(--ink);font-weight:600}
.note.f{border-left-color:var(--flag-line)}
.komp{margin:9px 11px 11px;display:flex;flex-wrap:wrap;gap:5px 6px}
.komp span{font-family:var(--fm);font-size:11px;background:var(--card2);border:1px solid var(--line);
 border-radius:5px;padding:2px 7px;color:var(--ink2)}
.komp span b{color:var(--ink);font-weight:600}

/* ---- spórolás ---- */
.sv{display:grid;grid-template-columns:118px minmax(0,1fr) 126px;align-items:stretch;
 background:var(--card);border:1px solid var(--line);border-radius:8px;margin-bottom:12px;overflow:hidden;box-shadow:var(--shadow-panel)}
.sv .pct{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:16px 8px;
 background:linear-gradient(160deg,var(--brand),var(--brand-deep));color:var(--on-brand)}
.sv .pct b{font-family:var(--fm);font-size:29px;font-weight:600;letter-spacing:0;line-height:1}
.sv .pct i{font-family:var(--fm);font-style:normal;font-size:8.5px;letter-spacing:.09em;
 text-transform:uppercase;opacity:.72}
.sv .body{padding:14px 17px;display:flex;flex-direction:column;gap:9px;min-width:0}
.sv .ttl{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.sv .ttl b{font-family:var(--fb);font-size:18px;font-weight:800;letter-spacing:0}
.sv .ttl span{font-family:var(--fm);font-size:10.4px;color:var(--ink3)}
.sv .pair{display:grid;grid-template-columns:minmax(0,1fr) 44px minmax(0,1fr);gap:9px;align-items:stretch}
.sv .route{display:flex;align-items:center;justify-content:center;color:var(--brand)}
.sv .route svg{width:30px;height:30px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;
 stroke-linejoin:round;background:var(--card);border:1px solid var(--brand-line);border-radius:50%;padding:6px;box-shadow:0 12px 26px rgba(16,23,20,.13)}
.sv .box{border-radius:8px;padding:9px 12px;display:flex;flex-direction:column;gap:3px;min-width:0}
.sv .box.good{background:var(--brand-bg);border:1px solid var(--brand-line)}
.sv .box.bad{background:var(--hot-bg);border:1px solid var(--hot-line)}
.sv .box .k{font-family:var(--fm);font-size:9.2px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink3)}
.sv .box .n{font-size:13.6px;font-weight:600;overflow-wrap:anywhere}
.sv .box.bad .n{font-weight:400;color:var(--ink2)}
.sv .box .p{font-family:var(--fm);font-size:12.5px}
.sv .box.good .p{color:var(--brand)}.sv .box.bad .p{color:var(--hot)}
.sv .diff{font-size:12.6px;color:var(--ink2)}
.sv .diff b{color:var(--ink);font-weight:600}
.sv .go{border-left:1px solid var(--line);display:flex;align-items:center;justify-content:center;
 font-size:13px;font-weight:600;color:var(--brand);text-decoration:none}
.sv .go:hover{background:var(--card2)}
.empty{padding:44px;text-align:center;color:var(--ink2);background:var(--card);
 border:1px dashed var(--line2);border-radius:8px}

footer{margin-top:auto;border-top:1px solid var(--line);background:var(--glass-strong);
 padding:18px 0 24px;font-size:12.5px;color:var(--ink2);box-shadow:0 -16px 44px rgba(16,23,20,.05)}
.ft{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.ft p{margin:0;line-height:1.55;max-width:82ch}
.ft span{font-family:var(--fm);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3)}

@media(max-width:1000px){
 .shell{grid-template-columns:1fr;gap:8px}
 .nav{position:sticky;top:74px;z-index:20;background:var(--glass);max-height:none;border:1px solid var(--line);
  display:flex;gap:7px;overflow-x:auto;padding:8px;scrollbar-width:none;box-shadow:var(--shadow-soft)}
 .nav::-webkit-scrollbar{display:none}
 .nav h3,.nav hr,.nav .sub{display:none}
 .nav button{width:auto;flex:0 0 auto;border:1px solid var(--line2);border-radius:100px;
  padding:5px 13px 5px 5px;white-space:nowrap;background:var(--card)}}
@media(max-width:920px){
 .r>summary{grid-template-columns:minmax(0,1fr) 92px 18px;gap:10px}
 .ind{display:none}.pr{grid-column:1/-1;order:3}
 .opt-h{grid-template-columns:minmax(0,1fr)}
 .tb thead{display:none}.tb td{display:block;border:0;padding:2px 0}
 .tb td[data-l]::before{content:attr(data-l) ": ";font-family:var(--fb);font-size:11.3px;color:var(--ink3)}
 .tb tr{display:block;border-top:1px solid var(--line);padding:10px 8px}.tb td.n{text-align:left}
 .tb .mm{white-space:normal}
 .sv{grid-template-columns:96px minmax(0,1fr)}.sv .go{grid-column:1/-1;border-left:0;border-top:1px solid var(--line);padding:11px}
 .sv .pair{grid-template-columns:minmax(0,1fr);gap:7px}.sv .route{height:24px}.sv .route svg{transform:rotate(90deg)}}
@media(max-width:720px){
 .hd{padding:14px 0 12px}.hd h1{width:100%;font-size:24px}.stats{margin-left:0;width:100%;justify-content:space-between}.stats .st{flex:1 1 104px}
 .tabs{flex:1 1 100%}.tabs button{flex:1 1 0;padding:8px 4px;text-align:center}
 .srch kbd{display:none}.cnt{margin-left:0}
 .cr{padding:6px}
 main{padding-top:14px}
 .sym-h span{font-size:26px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body>
<header><div class="w hd">
 <h1>Vény nélküli gyógyszer adatbázis</h1>
 <div class="stats" aria-label="Adatbázis összefoglaló">
  <div class="st"><b>__P__</b><i>gyógyszer</i></div>
  <div class="st"><b>__N__</b><i>hatóanyag</i></div>
  <div class="st save"><b>__S__</b><i>olcsóbb változat</i></div>
 </div>
</div></header>
<div class="ctl"><div class="w cr">
 <div class="tabs" role="tablist">
  <button data-v="panasz" role="tab">Panasz szerint</button>
  <button data-v="katalogus" role="tab">Hatóanyag szerint</button>
  <button data-v="ar" role="tab">Hol spórolhat</button>
 </div>
 <label class="srch"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="M20 20l-3.5-3.5"></path></svg>
  <input type="search" id="q" placeholder="Hatóanyag, készítmény vagy panasz" aria-label="Keresés"><kbd>/</kbd></label>
 <select id="g" aria-label="Kategória"></select>
 <span class="cnt" id="cnt"></span>
</div></div>
<main class="w"><div class="shell" id="shell"><nav class="nav" id="nav" aria-label="Navigáció"></nav>
<div id="out"></div></div></main>
<footer><div class="w ft">
 <p>Listaárakból épített, tájékoztató célú adatbázis. Vásárlás vagy gyógyszerváltás előtt ellenőrizze az aktuális termékoldalt, és bizonytalan esetben kérdezzen gyógyszerészt.</p>
 <span>__P__ készítmény · __N__ hatóanyag</span>
</div></footer>
<script id="d" type="application/json">__JSON__</script>
<script id="sy" type="application/json">__SYM__</script>
<script id="ic" type="application/json">__ICONS__</script>
<script id="ih" type="application/json">__HUE__</script>
<script>
(function(){"use strict";
var D=JSON.parse(document.getElementById('d').textContent);
var SY=JSON.parse(document.getElementById('sy').textContent);
var IC=JSON.parse(document.getElementById('ic').textContent);
var IH=JSON.parse(document.getElementById('ih').textContent);
var out=document.getElementById('out'),cnt=document.getElementById('cnt');
var nav=document.getElementById('nav'),gsel=document.getElementById('g'),shell=document.getElementById('shell');
var KEY={};D.forEach(function(r){KEY[r.key]=r;});
var GS=[];D.forEach(function(r){if(GS.indexOf(r.kat)<0)GS.push(r.kat);});
GS.sort(function(a,b){return D.filter(function(r){return r.kat===b;}).length-D.filter(function(r){return r.kat===a;}).length;});
var st={v:'panasz',sym:null,q:'',g:GS[0]};
var oAll=document.createElement('option');oAll.value='__ALL__';oAll.textContent='Minden kategória ('+D.length+')';gsel.appendChild(oAll);
GS.forEach(function(g){var n=D.filter(function(r){return r.kat===g;}).length;
 var o=document.createElement('option');o.value=g;o.textContent=g+' ('+n+')';gsel.appendChild(o);});
gsel.value=st.g;
function nm(s){return (s||'').toString().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'');}
function ft(n){return n==null?'—':n.toLocaleString('hu-HU')+' Ft';}
function e(s){return (s==null?'':String(s)).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function icon(k,big){var h=IH[k]==null?5:IH[k];
 return '<span class="ic h'+h+(big?' big':'')+'"><svg viewBox="0 0 24 24" aria-hidden="true">'+(IC[k]||IC.pill)+'</svg></span>';}

/* ---------- árlétra ---------- */
function ladder(b){
 var v=b.termekek.filter(function(p){return p.earv;});
 if(v.length<2)return '';
 var lo=v[0],hi=v[v.length-1],min=lo.earv,max=hi.earv;
 if(!(max>min))return '';
 var dots=v.map(function(p){
  var x=((p.earv-min)/(max-min)*100).toFixed(2);
  var c=p===lo?' lo':(p===hi?' hi':'');
  return '<span class="dot'+c+'" style="left:'+x+'%" title="'+e(p.nev)+' — '+e(p.ear)+'"></span>';}).join('');
 return '<div class="lad"><div class="lad-t"><div class="axis"></div>'+dots+'</div>'+
  '<div class="lad-e"><span class="l">'+e(lo.ear)+' · '+e(lo.nev)+'</span>'+
  '<span class="h">'+e(hi.ear)+' · '+e(hi.nev)+'</span></div></div>';}

/* ---------- blokk ---------- */
function table(b){
 var best=b.termekek[0],multi=b.termekek.length>1;
 var rows=b.termekek.map(function(p){
  var t='';
  if(p===best&&multi)t+='<span class="tag b">legolcsóbb</span>';
  if(p.mismatch)t+='<span class="tag f">BENU egységára eltér</span>';
  if(p.pack_fixed)t+='<span class="tag f">kiszerelés javítva</span>';
  return '<tr'+(p===best&&multi?' class="best"':'')+'>'+
   '<td data-l="Készítmény"><a href="'+e(p.url)+'" target="_blank" rel="noopener">'+e(p.nev)+'</a>'+t+
   (p.gyarto?'<div class="nb">'+e(p.gyarto)+'</div>':'')+'</td>'+
   '<td class="mm" data-l="Erősség">'+(p.komp&&p.komp.length>3?p.komp.length+' összetevő':e(p.eross||'—'))+'</td>'+
   '<td class="mm" data-l="Kiszerelés">'+e(p.kisz||'—')+'</td>'+
   '<td class="n mm" data-l="Listaár"><strong>'+ft(p.ar)+'</strong></td>'+
   '<td class="n mm" data-l="Egységár">'+e(p.ear)+'</td></tr>';}).join('');
 return '<div class="tw"><table class="tb"><thead><tr><th>Készítmény (BENU-link)</th><th>Erősség</th>'+
  '<th>Kiszerelés</th><th class="n">Listaár</th><th class="n">Egységár</th></tr></thead><tbody>'+rows+'</tbody></table></div>';}
function block(b,i){
 var n='',m=b.megt,k=b.termekek[0].komp;
 if(k&&k.length)n+='<div class="komp">'+k.map(function(c){
  return '<span><b>'+e(c[0])+'</b> '+e(c[1])+'</span>';}).join('')+'</div>';
 if(m)n+='<div class="note"><b>'+e(m.olcso)+'</b> ('+e(m.olcso_ear)+') — <b>'+m.pct+
  '%-kal olcsóbb</b>, mint a '+e(m.draga)+' ('+e(m.draga_ear)+'). Azonos erősség és forma, másik készítmény.</div>';
 if(b.tipp)n+='<div class="note">Kiszerelés-tipp: a <b>'+e(b.tipp.nagy)+'</b> egységre vetítve '+b.tipp.pct+
  '%-kal kedvezőbb, mint a '+e(b.tipp.kicsi)+' — ugyanaz a készítmény, csak nagyobb doboz.</div>';
 if(b.db>1&&!m)n+='<div class="note f">Ebben a blokkban csak egyetlen készítménynév szerepel, ezért nincs generikus alternatíva.</div>';
 return '<div class="bl k'+(i%6)+'"><div class="bl-h"><b>'+e(b.eross)+'</b><em>'+e(b.forma)+'</em>'+
  (m?'<span class="p">&minus;'+m.pct+'%</span>':'')+'<span class="n">'+b.db+' készítmény</span></div>'+
  ladder(b)+table(b)+n+'</div>';}
function badge(r){
 if(r.megt_pct)return '<span class="bdg b-save">&minus;'+r.megt_pct+'%<i>olcsóbb</i></span>';
 return '<span class="bdg b-none">'+r.db+'<i>készítmény</i></span>';}
function rec(r){
 return '<details class="r"><summary>'+
  '<div><div class="ha"><b>'+e(r.ha)+'</b></div><span class="nb">'+
  (r.blokk_db>1?r.blokk_db+' erősség / forma · '+r.gyartok+' márka':e(r.blokkok[0].eross+' · '+r.blokkok[0].forma))+'</span></div>'+
  '<div class="ind">'+e(r.alkat)+'</div>'+
  '<div class="pr"><b>'+ft(r.ar_min)+(r.ar_max!==r.ar_min?' – '+ft(r.ar_max):'')+'</b>'+r.db+' készítmény</div>'+
  '<div>'+badge(r)+'</div>'+
  '<svg class="cv" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>'+
  '</summary><div class="dt">'+r.blokkok.map(block).join('')+'</div></details>';}

/* ---------- keresés ---------- */
function hay(r){
 if(r._h)return r._h;
 r._h=nm(r.ha+' '+r.kat+' '+r.alkat+' '+r.blokkok.map(function(b){
  return b.eross+' '+b.forma+' '+b.termekek.map(function(p){return p.nev+' '+(p.gyarto||'');}).join(' ');}).join(' '));
 return r._h;}
function found(){
 var t=nm(st.q).trim().split(/\s+/).filter(Boolean);
 if(!t.length)return [];
 return D.filter(function(r){var h=hay(r);return t.every(function(x){return h.indexOf(x)>=0;});});}

/* ---------- 1. panasz ---------- */
function symTiles(){
 return '<p class="lead">Válasszon panaszt. Minden panasznál jelöljük, mi az <b>első választás</b> és mi az '+
  'alternatíva, mire kell figyelni, és melyik a legjobb egységárú készítmény az adott hatóanyagból.</p>'+
  '<div class="grid">'+SY.map(function(s){
   return '<button class="tile" data-sym="'+e(s.id)+'"><span class="t">'+icon(s.icon)+e(s.label)+'</span>'+
    '<p>'+e(s.blurb)+'</p><span class="n">'+s.options.length+' hatóanyag</span></button>';}).join('')+'</div>';}
function optCard(o){
 var r=KEY[o.key];if(!r)return '';
 var roleTxt={first:'Első választás',alt:'Alternatíva',note:'Jó tudni'}[o.role]||'Alternatíva';
 var rows=o.rec_termekek.map(function(p,i){
  return '<tr><td>'+
   '<a href="'+e(p.url)+'" target="_blank" rel="noopener"'+(i===0?' style="font-weight:600"':'')+'>'+e(p.nev)+'</a>'+
   (i===0&&o.rec_termekek.length>1?'<span class="tag b">legjobb ár</span>':'')+'</td>'+
   '<td class="mm">'+e(p.eross||'—')+'</td>'+
   '<td class="mm">'+e(p.kisz||'—')+'</td>'+
   '<td class="n mm"'+(i===0?' style="font-weight:600"':'')+'>'+ft(p.ar)+'</td>'+
   '<td class="n mm"'+(i===0?' style="font-weight:600;color:var(--brand)"':' style="color:var(--ink2)"')+'>'+e(p.ear)+'</td></tr>';}).join('');
 var forms=o.egyeb.length?('<div class="forms"><span class="lbl">Ugyanez más formában vagy erősségben</span>'+
   o.egyeb.map(function(g){return '<a class="fchip" href="'+e(g.url)+'" target="_blank" rel="noopener">'+
     '<b>'+e(g.forma)+'</b><span>'+e(g.nev)+' · '+ft(g.ar)+'</span></a>';}).join('')+'</div>'):'';
 return '<article class="opt"><div class="opt-h"><div>'+
  '<span class="role '+e(o.role)+'">'+roleTxt+'</span>'+
  '<h4>'+e(r.ha)+'</h4><p class="why">'+e(o.why)+'</p>'+
  (o.caution?'<p class="cau">Figyelem: '+e(o.caution)+'</p>':'')+'</div>'+
  '<div>'+badge(r)+'</div></div>'+
  '<div class="rec"><div class="rec-h"><b>'+e(o.rec_forma)+'</b>'+
   '<em>'+(o.rec_db>1?'ár szerint, a legjobbtól — az egységár egy '+e(o.rec_egyseg)+' ára':'egyetlen kiszerelés')+'</em>'+
   (o.megt?'<span class="tag b" style="margin-left:auto">&minus;'+o.megt.pct+'% ugyanabból a hatóanyagból</span>':'')+'</div>'+
   '<div class="rtw"><table class="rt"><thead><tr><th>Készítmény</th><th>Erősség</th><th>Doboz</th>'+
   '<th class="n">Listaár</th><th class="n">Egységár</th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
   forms+'</div>'+
  '<details><summary>Mind a '+r.db+' készítmény, erősség és ár &darr;</summary>'+
  '<div class="dt">'+r.blokkok.map(block).join('')+'</div></details></article>';}
function symView(){
 var s=SY.filter(function(x){return x.id===st.sym;})[0];
 if(!s)return symTiles();
 return '<button class="back" data-back="1"><svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>Vissza a panaszokhoz</button>'+
  '<h2 class="sym-h">'+icon(s.icon,1)+'<span>'+e(s.label)+'</span></h2>'+
  '<p class="lead">'+e(s.blurb)+'</p>'+
  s.options.map(optCard).join('');}

/* ---------- 2. katalógus ---------- */
function catView(rs){
 var h='';
 GS.forEach(function(g){
  var x=rs.filter(function(r){return r.kat===g;});if(!x.length)return;
  h+='<div class="gh">'+icon(x[0].ikon)+'<b>'+e(g)+'</b><span>'+x.length+' hatóanyag · '+
   x.reduce(function(a,r){return a+r.db;},0)+' készítmény</span></div>';
  var subs=[];x.forEach(function(r){if(subs.indexOf(r.alkat)<0)subs.push(r.alkat);});
  subs.forEach(function(s){var y=x.filter(function(r){return r.alkat===s;});
   h+='<div class="sh" id="s-'+encodeURIComponent(s)+'"><b>'+e(s)+'</b><i>'+y.length+' hatóanyag</i></div>'+y.map(rec).join('');});});
 return h||'<div class="empty">Nincs találat.</div>';}

/* ---------- 3. spórolás ---------- */
function savView(){
 var x=D.filter(function(r){return r.megt&&r.megt_pct;});
 x.sort(function(a,b){return b.megt_pct-a.megt_pct;});
 return '<p class="lead">Azonos erősség és gyógyszerforma mellett, <b>másik gyártó készítményeivel</b> számolva. '+
  'A nagyobb doboz önmagában nem generikus alternatíva.</p>'+
  x.map(function(r){var m=r.megt,diff='';
   if(m.olcso_earv&&m.draga_earv&&m.olcso_kiszn){
    var d=Math.round((m.draga_earv-m.olcso_earv)*m.olcso_kiszn);
    var u={db:'darabra',ml:'millilitere',g:'grammra',tasak:'tasakra'}[m.egyseg]||'egységre';
    diff='<div class="diff">Ugyanennyi hatóanyagra — '+m.olcso_kiszn.toLocaleString('hu-HU')+' '+u+
     ' vetítve — <b>'+ft(d)+'</b> a különbség.</div>';}
   return '<div class="sv"><div class="pct"><b>&minus;'+m.pct+'%</b><i>olcsóbb</i></div>'+
    '<div class="body"><div class="ttl"><b>'+e(r.ha)+'</b><span>'+e(m.eross)+' · '+e(m.forma)+' · '+e(r.kat)+'</span></div>'+
    '<div class="pair">'+
     '<div class="box bad"><span class="k">Drágább választás</span><span class="n">'+e(m.draga)+'</span><span class="p">'+ft(m.draga_ar)+' · '+e(m.draga_ear)+'</span></div>'+
     '<span class="route" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12h14"/><path d="M13 6l6 6-6 6"/></svg></span>'+
     '<div class="box good"><span class="k">Olcsóbb alternatíva</span><span class="n">'+e(m.olcso)+'</span><span class="p">'+ft(m.olcso_ar)+' · '+e(m.olcso_ear)+'</span></div>'+
    '</div>'+diff+'</div>'+
    '<a class="go" href="'+e(m.olcso_url)+'" target="_blank" rel="noopener">Megnézem &rarr;</a></div>';}).join('');}

/* ---------- navigáció ---------- */
function navRender(){
 if(st.v==='panasz'&&!st.q){
  nav.innerHTML='<h3>Panaszok</h3>'+SY.map(function(s){
   return '<button data-sym="'+e(s.id)+'" aria-current="'+(st.sym===s.id?'true':'false')+'">'+
    icon(s.icon)+e(s.label)+'</button>';}).join('');
  return;}
 if(st.v==='katalogus'&&!st.q){
  var h='<h3>Kategóriák</h3>';
  GS.forEach(function(g){
   var x=D.filter(function(r){return r.kat===g;});
   h+='<button data-g="'+e(g)+'" aria-current="'+(st.g===g?'true':'false')+'">'+icon(x[0].ikon)+e(g)+'<i>'+x.length+'</i></button>';
   if(st.g===g){var subs=[];x.forEach(function(r){if(subs.indexOf(r.alkat)<0)subs.push(r.alkat);});
    subs.forEach(function(s2){var n=x.filter(function(r){return r.alkat===s2;}).length;
     h+='<button class="sub" data-jump="'+e(s2)+'">'+e(s2)+'<i>'+n+'</i></button>';});}});
  h+='<hr><button data-g="__ALL__" aria-current="'+(st.g==='__ALL__'?'true':'false')+'">'+
   '<span class="ic h5"><svg viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="5" rx="1.5"/>'+
   '<rect x="3.5" y="14.5" width="17" height="5" rx="1.5"/></svg></span>Minden kategória<i>'+D.length+'</i></button>';
  nav.innerHTML=h;return;}
 nav.innerHTML='';}

function render(){
 document.querySelectorAll('.tabs button').forEach(function(b){
  b.setAttribute('aria-current',b.getAttribute('data-v')===st.v?'true':'false');});
 gsel.style.display=(st.v==='katalogus'&&!st.q)?'':'none';
 navRender();
 var solo=!nav.innerHTML;
 shell.classList.toggle('solo',solo);
 nav.style.display=solo?'none':'';
 var h;
 if(st.q){
  var rs=found();
  cnt.textContent=rs.length+' hatóanyag · '+rs.reduce(function(a,r){return a+r.db;},0)+' készítmény';
  h=rs.length?('<div class="gh"><b>Keresés: '+e(st.q)+'</b><span>'+rs.length+' hatóanyag</span></div>'+rs.map(rec).join(''))
    :'<div class="empty">Nincs találat. Próbáljon más kifejezést.</div>';
 }else if(st.v==='panasz'){
  cnt.textContent=SY.length+' panasz';h=symView();
 }else if(st.v==='ar'){
  cnt.textContent=D.filter(function(r){return r.megt_pct;}).length+' valódi árkülönbség';h=savView();
 }else{
  var x=(st.g==='__ALL__')?D:D.filter(function(r){return r.kat===st.g;});
  cnt.textContent=x.length+' hatóanyag · '+x.reduce(function(a,r){return a+r.db;},0)+' készítmény';
  h=catView(x);}
 out.innerHTML=h;}

document.querySelector('.tabs').addEventListener('click',function(ev){
 var b=ev.target.closest('button');if(!b)return;
 st.v=b.getAttribute('data-v');st.sym=null;render();window.scrollTo({top:0,behavior:'smooth'});});
out.addEventListener('click',function(ev){
 var t=ev.target.closest('[data-sym],[data-back]');if(!t)return;
 st.sym=t.hasAttribute('data-back')?null:t.getAttribute('data-sym');
 render();window.scrollTo({top:0,behavior:'smooth'});});
nav.addEventListener('click',function(ev){
 var b=ev.target.closest('button');if(!b)return;
 if(b.hasAttribute('data-sym')){st.sym=b.getAttribute('data-sym');render();window.scrollTo({top:0,behavior:'smooth'});return;}
 if(b.hasAttribute('data-jump')){var el=document.getElementById('s-'+encodeURIComponent(b.getAttribute('data-jump')));
  if(el)el.scrollIntoView({behavior:'smooth',block:'start'});return;}
 st.g=b.getAttribute('data-g');gsel.value=st.g;render();window.scrollTo({top:0,behavior:'smooth'});});
gsel.addEventListener('change',function(ev){st.g=ev.target.value;render();});
var qi=document.getElementById('q'),tm;
qi.addEventListener('input',function(){clearTimeout(tm);tm=setTimeout(function(){st.q=qi.value;render();},130);});
document.addEventListener('keydown',function(ev){
 if(ev.key==='/'&&document.activeElement!==qi){ev.preventDefault();qi.focus();qi.select();}
 else if(ev.key==='Escape'&&document.activeElement===qi){qi.value='';st.q='';render();qi.blur();}});
render();})();
</script></body></html>
"""


def main():
    products = json.loads(SRC.read_text(encoding="utf-8"))
    ali = json.loads(ALIAS_SRC.read_text(encoding="utf-8")) if ALIAS_SRC.exists() else {}
    alias, alias_display = ali.get("alias", {}), ali.get("display", {})
    kb = json.loads(KB_SRC.read_text(encoding="utf-8")) if KB_SRC.exists() else {"symptoms": []}

    rows, prepared = build_rows(products, alias, alias_display)

    by_key = {r["key"]: r for r in rows}
    symptoms, missing, kiszurt = [], [], []
    for s in kb.get("symptoms", []):
        prefer = s.get("prefer_forms")
        opts = []
        for o in s.get("options", []):
            row = by_key.get(o["key"])
            if not row:
                missing.append((s["id"], o["key"], "nincs ilyen hatóanyag"))
                continue
            view = option_view(row, o, prefer)
            if not view:
                kiszurt.append((s["id"], o["key"], o.get("forms")))
                continue
            opts.append(dict(o, **view))
        if opts:
            symptoms.append(dict(s, options=opts))

    scraped = len(products)
    if PRODUCTS_SRC.exists():
        try:
            scraped = len(json.loads(PRODUCTS_SRC.read_text(encoding="utf-8")))
        except Exception:
            pass

    savings = sum(1 for r in rows if r["megt_pct"])
    page = (TPL
            .replace("__JSON__", json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
            .replace("__SYM__", json.dumps(symptoms, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
            .replace("__ICONS__", json.dumps(ICONS, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__HUE__", json.dumps(ICON_HUE, ensure_ascii=False))
            .replace("__N__", str(len(rows)))
            .replace("__S__", str(savings))
            .replace("__P__", str(len(prepared))))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")

    tips = sum(1 for r in rows for b in r["blokkok"] if b["tipp"])
    komp = sum(1 for p in prepared if p["komp"])
    merged = sum(1 for p in prepared if p["hakey"] != p["raw_key"])
    ladders = sum(1 for r in rows for b in r["blokkok"]
                  if len([p for p in b["termekek"] if p["earv"]]) > 1)
    print(f"kimenet: {OUT}  ({OUT.stat().st_size/1024:.0f} kB)")
    print(f"hatóanyag: {len(rows)} | erősség-blokk: {sum(r['blokk_db'] for r in rows)} | készítmény: {len(prepared)}")
    print(f"panasz: {len(symptoms)} | valódi megtakarítás: {savings} | kiszerelés-tipp: {tips}")
    print(f"árlétra: {ladders} blokkban | komponens-bontás: {komp} | kulcs kanonizálva: {merged}")
    print(f"scrape: {grouped_int(scraped)} termékoldal | BENU egységár-eltérés: "
          f"{sum(1 for p in prepared if p['mismatch'])} | kiszerelés névből: "
          f"{sum(1 for p in prepared if p['pack_fixed'])}")
    if missing:
        print("\nFIGYELEM — a tudásrétegben szereplő, de az adatban nem található kulcsok:")
        for sid, k, why in missing:
            print(f"  {sid}: {k} ({why})")
    if kiszurt:
        print("\nFormaszűrés miatt kihagyott ajánlás (nincs ilyen formájú készítmény):")
        for sid, k, f in kiszurt:
            print(f"  {sid}: {k} -> {f}")


if __name__ == "__main__":
    main()
