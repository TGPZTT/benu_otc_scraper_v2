import json
import logging
import re
import unicodedata
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from scraper.utils import normalize_space,parse_huf,parse_json_ld,first_nonempty,unique_keep_order

log=logging.getLogger(__name__)

# These values are intentionally exact-ish. The important point is that
# classification is extracted from product-scoped metadata/badges, not from
# the whole page, because menus, tooltips, delivery text and recommendations
# contain the same OTC wording.

CLASSIFICATION_MAP={
    "vény nélkül kapható gyógyszer":"OTC",
    "vényköteles gyógyszer":"PRESCRIPTION",
    "gyógyászati segédeszköz":"NON_MEDICINE",
    "étrend-kiegészítő":"NON_MEDICINE",
    "kozmetikum":"NON_MEDICINE",
    "gyógyszernek nem minősülő gyógyhatású készítmény":"NON_MEDICINE",
}

ANALYTICS_ITEM_TYPE_MAP={
    "otc":"OTC",
    "etr":"NON_MEDICINE",
    "etrend kiegeszito":"NON_MEDICINE",
    "etrend-kiegeszito":"NON_MEDICINE",
    "etrendkiegeszito":"NON_MEDICINE",
    "gyse":"NON_MEDICINE",
    "gyogyaszati segedeszkoz":"NON_MEDICINE",
    "egyeb":"NON_MEDICINE",
    "rx":"PRESCRIPTION",
    "venykoteles":"PRESCRIPTION",
    "venykoteles gyogyszer":"PRESCRIPTION",
}

ACTIVE_STOP_PATTERN=(
    r"\b(?:Egyéb\s+összetev(?:ő|ők)(?:\(k\))?|Összetevők,\s*allergének|"
    r"Segédanyag(?:ok)?|Segédanyagként|A\s+segédanyagok|"
    r"Ismert\s+hatású\s+segédanyagok|További\s+információ(?:kért)?|"
    r"Nem\s+alkalmazható|Ellenjavallat|Milyen\s+az?|A\s+forgalomba|"
    r"A\s+készítmény\s+külleme|Bevonat|A\s+gyógyszer\s+gyermekektől|"
    r"Szállítási\s+információk|EAN)\b"
)

PRODUCT_NAME_STOP_TOKENS={
    "mg","ml","g","db","x","filmtabletta","tabletta","kapszula","lagy",
    "bevont","oldatos","orrspray","szuszpenzio","granulatum","kenocs",
    "krem","gel","csepp","szopogato","rago","belsoleges",
}

PRODUCT_VARIANT_TOKENS={
    "trio","duo","plus","cold","rapid","forte","dolo","kid","junior",
    "extra","max","senior",
}

ACTIVE_FIELD_STOP_MARKERS=[
    "Segédanyagok","Segédanyag","A segédanyagok","Egyéb összetevők",
    "Egyéb összetevő(k)","Egyéb összetevő","Összetevők, allergének",
    "Ismert hatású segédanyagok","További információ","Nem alkalmazható",
    "Ellenjavallat","Bevonat",
]

ACTIVE_COMPOSITION_STOP_MARKERS=[
    "Ismert hatású segédanyagok","Segédanyagok","Segédanyag",
    "Egyéb összetevők","Adagolás",
]

ACTIVE_TEXT_PATTERNS=[
    (
        "hatanyagok_sentence",
        r"\bA\s+hatóanyagok\s+(?:az?|a)\s+(.+?)(?=\.|;|\bAz\s+\w+|\bEgyéb\s+összetev(?:ő|ők)(?:\(k\))?\b|$)",
    ),
    (
        "hatanyag_sentence",
        r"\bA\s+hatóanyag\s+(?:az?|a)\s+(.+?)(?=\.|;|\bAz\s+\w+|\bEgyéb\s+összetev(?:ő|ők)(?:\(k\))?\b|$)",
    ),
    (
        "osszetevok_listaja",
        r"\bÖsszetevők\s+listája\s*:\s*(.+?)(?=\bBetegtájékoztató\b|\bTermékleírás\b|$)",
    ),
    (
        "mit_tartalmaz",
        r"\bMit\s+tartalmaz\s+(?:az|a)\s+[^?]{2,180}\?\s*-?\s*(.+?)(?=\bEgyéb\s+összetev(?:ő|ők)(?:\(k\))?\b|\bIsmert\s+hatású\s+segédanyagok\b|\bMilyen\b|\bA\s+forgalomba\b|$)",
    ),
    (
        "keszitmeny_hatoanyagai",
        r"\bA\s+készítmény\s+hatóanyagai\b\s*:?\s*(.+?)(?=\bEgyéb\s+összetev(?:ő|ők)(?:\(k\))?\b|\bIsmert\s+hatású\s+segédanyagok\b|\bMilyen\b|$)",
    ),
    (
        "keszitmeny_hatoanyaga",
        r"\bA\s+készítmény\s+hatóanyaga\b\s*(?::|az?\s+)\s*([^.;]{2,220})",
    ),
    (
        "hatoanyaga_az",
        r"\bhatóanyaga\b\s+az?\s+([^,.;]{2,180})",
    ),
    (
        "hatoanyag_label",
        r"\bhatóanyag(?:ok)?\s*:\s*([^.;]{2,220})",
    ),
    (
        "tartalmu_sentence",
        r"\b([A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]+(?:-[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]+)+)\s+tartalmú\b",
    ),
]

def text_of(node):
    return normalize_space(node.get_text(" ",strip=True)) if node else None

def full_text(soup):
    return soup.get_text("\n",strip=True)

def main_product_node(soup):
    return (
        soup.select_one("product-info")
        or soup.select_one("main.container.main")
        or soup.select_one("#MainContent")
        or soup
    )

def product_text(soup):
    node=main_product_node(soup)
    return node.get_text("\n",strip=True) if node else full_text(soup)

def _json_types(item):
    value=item.get("@type") if isinstance(item,dict) else None
    if isinstance(value,list):
        return {str(x) for x in value}
    if value:
        return {str(value)}
    return set()

def _has_json_type(item,type_name):
    return type_name in _json_types(item)

def _fold_text(value):
    if not value:
        return ""
    normalized=unicodedata.normalize("NFKD",normalize_space(value).lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))

def _product_name_signature_tokens(name):
    tokens=re.findall(r"[a-z0-9]+",_fold_text(name))
    out=[]
    for token in tokens:
        if token in PRODUCT_NAME_STOP_TOKENS:
            continue
        if token.isdigit() or re.fullmatch(r"\d+[a-z]?",token):
            continue
        if len(token)<3:
            continue
        out.append(token)
    return unique_keep_order(out)

def active_candidate_mentions_other_product(context,product_name):
    tokens=_product_name_signature_tokens(product_name)
    if len(tokens)<2:
        return False
    source=_fold_text(context)
    if tokens[0] not in source:
        return False
    variants=[t for t in tokens[1:] if t in PRODUCT_VARIANT_TOKENS or len(t)>4]
    if not variants:
        return False
    return not any(t in source for t in variants)

def _decode_json_string(value):
    if value is None:
        return None
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value

def _walk_json(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value,list):
        for child in value:
            yield from _walk_json(child)

def json_product(json_ld):
    products=[node for node in _walk_json(json_ld) if _has_json_type(node,"Product")]
    if not products:
        return {}

    def score(item):
        return sum([
            8 if item.get("sku") else 0,
            8 if item.get("gtin") or item.get("gtin13") else 0,
            5 if item.get("offers") else 0,
            2 if item.get("name") else 0,
        ])

    return sorted(products,key=score,reverse=True)[0]

def json_product_group(json_ld):
    groups=[node for node in _walk_json(json_ld) if _has_json_type(node,"ProductGroup")]
    return groups[0] if groups else {}

def _iter_analytics_items(soup):
    for tag in soup.select("script.analytics-product-data"):
        raw=tag.string or tag.get_text()
        if not raw:
            continue
        try:
            payload=json.loads(raw)
        except Exception:
            continue
        items=payload.get("items")
        if isinstance(items,dict):
            items=[items]
        if not isinstance(items,list):
            continue
        for item in items:
            if isinstance(item,dict):
                yield item

def analytics_product_item(soup,name=None,sku=None):
    items=list(_iter_analytics_items(soup))
    if not items:
        return {}

    wanted_name=_fold_text(name)
    wanted_sku=normalize_space(sku)

    def score(item_index):
        index,item=item_index
        value=0
        item_name=_fold_text(item.get("item_name"))
        item_sku=normalize_space(item.get("sku"))
        if wanted_name and item_name:
            if item_name==wanted_name:
                value+=30
            elif item_name in wanted_name or wanted_name in item_name:
                value+=12
        if wanted_sku and item_sku==wanted_sku:
            value+=16
        if index==0:
            value+=1
        return value

    best_index,best_item=max(enumerate(items),key=score)
    if (wanted_name or wanted_sku) and score((best_index,best_item))<=1:
        return {}
    return best_item

def classify_from_analytics_item(item):
    item_type=normalize_space(item.get("item_type")) if item else None
    classification=ANALYTICS_ITEM_TYPE_MAP.get(_fold_text(item_type),"UNKNOWN")
    return classification,item_type

def extract_shopify_barcode(html,name=None,sku=None):
    wanted_name=_fold_text(name)
    wanted_sku=normalize_space(sku)
    pattern=(
        r'"sku"\s*:\s*"(?P<sku>(?:\\.|[^"])*)".{0,1500}?'
        r'"name"\s*:\s*"(?P<name>(?:\\.|[^"])*)".{0,1500}?'
        r'"barcode"\s*:\s*(?:"(?P<barcode>[0-9]{8,14})"|null)'
    )
    for match in re.finditer(pattern,html or "",re.I|re.S):
        barcode=match.group("barcode")
        if not barcode:
            continue
        item_sku=normalize_space(_decode_json_string(match.group("sku")))
        item_name=_fold_text(_decode_json_string(match.group("name")))
        if wanted_sku and item_sku==wanted_sku:
            return barcode
        if wanted_name and item_name==wanted_name:
            return barcode
    return None

def _json_image_index(json_ld):
    index={}
    for node in _walk_json(json_ld):
        if not _has_json_type(node,"ImageObject"):
            continue
        key=node.get("@id")
        url=node.get("contentUrl") or node.get("url")
        if key and url:
            index[key]=url
    return index

def _json_gtin(json_prod):
    for key in ("gtin13","gtin","gtin14","gtin12","mpn"):
        value=json_prod.get(key)
        if value:
            return str(value)
    return None

def _iter_offer_dicts(offers):
    if isinstance(offers,dict):
        yield offers
    elif isinstance(offers,list):
        for offer in offers:
            if isinstance(offer,dict):
                yield offer

def extract_json_price(json_prod):
    for offer in _iter_offer_dicts(json_prod.get("offers")):
        if offer.get("price") is not None:
            try:
                return int(float(offer["price"]))
            except Exception:
                pass
        specs=offer.get("priceSpecification")
        if isinstance(specs,dict):
            specs=[specs]
        if isinstance(specs,list):
            for spec in specs:
                if isinstance(spec,dict) and spec.get("price") is not None:
                    try:
                        return int(float(spec["price"]))
                    except Exception:
                        pass
    return None

def extract_first_section(text,start_marker,end_markers):
    if not text:
        return None
    m=re.search(re.escape(start_marker),text,re.I)
    if not m:
        return None
    start=m.end()
    end=len(text)
    for marker in end_markers:
        mm=re.search(re.escape(marker),text[start:],re.I)
        if mm:
            end=min(end,start+mm.start())
    value=normalize_space(text[start:end])
    return value or None

def _extract_after_label(text,label_pattern,stop_markers=None,max_chars=1400,require_colon=False):
    if not text:
        return None
    separator=r"\s*:\s*" if require_colon else r"\s*:?\s*"
    m=re.search(r"\b(?:"+label_pattern+r")\b"+separator,text,re.I)
    if not m:
        return None
    fragment=text[m.end():m.end()+max_chars]
    end=len(fragment)
    markers=[
        "Besorolás típusa","Hatóanyag","Forgalmazó","Forgalmazza",
        "Forgalmazása","Gyártó","EAN","Márka","Cikkszám","Betegtájékoztató",
        "Összetétel","Adagolás","Alkalmazás","Tárolása","Termékinformáció",
        "Termékleírás","Szállítási információk",
    ]
    if stop_markers:
        markers.extend(stop_markers)
    for marker in markers:
        mm=re.search(re.escape(marker),fragment,re.I)
        if mm and mm.start()>0:
            end=min(end,mm.start())
    value=normalize_space(fragment[:end])
    return value or None

def _classify_raw(raw):
    if not raw:
        return "UNKNOWN",None
    low=raw.lower()
    for key,val in CLASSIFICATION_MAP.items():
        if key in low:
            return val,key
    return "UNKNOWN",raw

def clean_active_ingredient_value(value):
    value=normalize_space(value)
    if not value:
        return None
    value=re.split(ACTIVE_STOP_PATTERN,value,1,flags=re.I)[0]
    marker=re.search(
        r"\b(?:A\s+)?készítmény\s+hatóanyaga(?:i)?\s*:?\s*",
        value,
        re.I,
    )
    if marker and marker.start()<220:
        value=value[marker.end():]
    value=re.sub(r"^(?:az|a)\s+","",value,flags=re.I)
    value=re.sub(r"\s+(amely|ami|mely)\b.*$","",value,flags=re.I)
    value=re.sub(r"\s+(tasakonként|tablettánként|kapszulánként|ml-enként)\.?$","",value,flags=re.I)
    return normalize_space(value) or None

def active_candidate_is_noisy(value):
    if not value:
        return True
    return bool(re.search(
        r"\b(?:segédanyag|egyéb\s+összetev(?:ő|ők)|nem\s+alkalmazható|"
        r"ellenjavallat|allergiás|további\s+információ|olvassa\s+el|"
        r"forgalomba\s+hozatali|gyártó|szállítási\s+információk)\b",
        value,
        re.I,
    ))

def _active_candidate(raw_value,source,context=None,product_name=None):
    value=clean_active_ingredient_value(raw_value)
    if not value:
        return None
    if value.lower().startswith(("keressen","a keresett")):
        return None
    if product_name and active_candidate_mentions_other_product(context or value,product_name):
        return None
    if active_candidate_is_noisy(value):
        return None
    ingredient_names=split_ingredient_names(value)
    if not ingredient_names:
        return None
    return {
        "value":value,
        "source":source,
        "ingredient_count":len(ingredient_names),
    }

def _extract_active_ingredient_from_text(text,source_prefix,product_name=None):
    if not text:
        return None
    source=normalize_space(text)
    for pattern_name,pattern in ACTIVE_TEXT_PATTERNS:
        for m in re.finditer(pattern,source,re.I):
            context=source[max(0,m.start()-100):min(len(source),m.end()+180)]
            candidate=_active_candidate(
                m.group(1)[:2200],
                f"{source_prefix}_{pattern_name}",
                context=context,
                product_name=product_name,
            )
            if candidate:
                return candidate
    return None

def _iter_json_text_values(value):
    if isinstance(value,str):
        yield value
    elif isinstance(value,dict):
        if value.get("name"):
            yield str(value["name"])
        for child in value.values():
            yield from _iter_json_text_values(child)
    elif isinstance(value,list):
        for child in value:
            yield from _iter_json_text_values(child)

def extract_json_active_ingredient(json_ld,product_name=None):
    for node in _walk_json(json_ld):
        if not isinstance(node,dict):
            continue
        for key,value in node.items():
            key_folded=_fold_text(key).replace("_","").replace("-","")
            if key_folded not in {"activeingredient","activeingredients","hatoanyag","hatoanyagok"}:
                continue
            for text_value in _iter_json_text_values(value):
                candidate=_active_candidate(
                    text_value,
                    "json_ld",
                    context=text_value,
                    product_name=product_name,
                )
                if candidate:
                    return candidate
    return None

def _candidate_is_detailed_upgrade(current,candidate):
    if not current or not candidate:
        return False
    if not (
        candidate["source"].startswith(("leaflet_","usage_instruction_"))
        or candidate["source"].endswith(("_mit_tartalmaz","_keszitmeny_hatoanyagai"))
    ):
        return False
    return (
        candidate["ingredient_count"]>=3
        and candidate["ingredient_count"]>current["ingredient_count"]
    )

def extract_active_ingredient(text,product_name=None,json_ld=None):
    candidates=[]

    structured_raw=_extract_after_label(
        text,
        r"Hatóanyag(?:ok)?",
        stop_markers=ACTIVE_FIELD_STOP_MARKERS,
        max_chars=2200,
        require_colon=True,
    )
    structured=_active_candidate(structured_raw,"structured_hatany")
    if structured:
        candidates.append(structured)

    json_candidate=extract_json_active_ingredient(json_ld or [],product_name=product_name)
    if json_candidate:
        candidates.append(json_candidate)

    info,description=extract_product_info(text)
    leaflet,leaflet_source_prefix=extract_leaflet_section(text)
    for section_text,source_prefix in [
        (leaflet,leaflet_source_prefix or "leaflet"),
        (info,"product_information"),
        (description,"description"),
    ]:
        candidate=_extract_active_ingredient_from_text(
            section_text,
            source_prefix,
            product_name=product_name,
        )
        if candidate:
            candidates.append(candidate)

    composition_raw=_extract_after_label(
        text,
        r"Összetétel",
        stop_markers=ACTIVE_COMPOSITION_STOP_MARKERS,
        max_chars=700,
        require_colon=True,
    )
    composition=_active_candidate(composition_raw,"composition")
    if composition:
        candidates.append(composition)

    fallback=_extract_active_ingredient_from_text(
        text,
        "fallback",
        product_name=product_name,
    )
    if fallback:
        candidates.append(fallback)

    selected=None
    for candidate in candidates:
        if selected is None:
            selected=candidate
        elif _candidate_is_detailed_upgrade(selected,candidate):
            selected=candidate

    if selected:
        return selected["value"],selected["source"]
    return None,None

def extract_active_ingredient_fallback(text,product_name=None):
    candidate=_extract_active_ingredient_from_text(
        text,
        "fallback",
        product_name=product_name,
    )
    return candidate["value"] if candidate else None

def should_prefer_active_ingredient_fallback(current,candidate):
    current_candidate=_active_candidate(current,"current")
    fallback_candidate=_active_candidate(candidate,"leaflet_fallback")
    return _candidate_is_detailed_upgrade(current_candidate,fallback_candidate)

def extract_product_metadata(text,product_name=None,json_ld=None):
    # We deliberately only inspect the first metadata block. On current BENU
    # pages it appears before the shipping section and before repeated product
    # recommendations.
    classification_fragment=_extract_after_label(text,r"Besorolás\s+típusa",max_chars=900,require_colon=True)
    classification,known_raw=_classify_raw(classification_fragment)
    classification_raw=known_raw if known_raw else classification_fragment

    active_raw,active_source=extract_active_ingredient(
        text,
        product_name=product_name,
        json_ld=json_ld,
    )

    distributor=(
        _extract_after_label(text,r"Forgalmazó",max_chars=800,require_colon=True)
        or _extract_after_label(text,r"Forgalmazza",max_chars=800,require_colon=True)
        or _extract_after_label(text,r"Forgalmazása",max_chars=800,require_colon=True)
    )

    em=re.search(r"\bEAN(?:-kód)?\b\s*:?\s*([0-9]{8,14})",text,re.I)
    ean=em.group(1) if em else None

    return {
        "classification_raw":classification_raw,
        "classification":classification,
        "active_ingredient_raw":active_raw,
        "active_ingredient_source":active_source,
        "distributor":distributor,
        "ean":ean,
    }

def extract_main_prices(text):
    # Search only the caller-provided product scope. price_huf is the regular
    # list price used for comparisons; sale_price_huf keeps a discounted price
    # when BENU shows a temporary promotion.
    price=None
    unit_price=None
    lowest_30=None
    original_price=None
    sale_price=None

    if not text:
        return {
            "price_huf":price,
            "unit_price":unit_price,
            "lowest_30d_price_huf":lowest_30,
            "original_price_huf":original_price,
            "sale_price_huf":sale_price,
        }

    block=text
    marker=re.search(r"Internetes\s+ár(?!\s+törzsvásárlóknak)",text,re.I)
    if marker:
        block=text[marker.start():marker.start()+2200]
        for stop in [
            "Fizethet átvételkor","EP kártyára","Vény nélkül kapható",
            "Szállítással elérhető","Csak gyógyszertárban átvehető",
            "Miért a BENU.hu?","Termékinformáció",
        ]:
            sm=re.search(re.escape(stop),block,re.I)
            if sm:
                block=block[:sm.start()]
                break

    # The exact unit-price label following the main price.
    um=re.search(
        r"Egységár\s*:?\s*([0-9][\d\s.]*(?:,\d+)?)\s*Ft\s*/\s*([^\n|]+)",
        block,re.I|re.S
    )
    if um:
        unit_price=f"{normalize_space(um.group(1))} Ft / {normalize_space(um.group(2))}"

    lm=re.search(
        r"Az elmúlt\s+30\s+nap\s+legalacsonyabb\s+ára\s*:?\s*"
        r"([0-9][\d\s.]*(?:,\d+)?)\s*Ft",
        block,re.I
    )
    if lm:
        lowest_30=parse_huf(lm.group(1)+" Ft")

    sm=re.search(
        r"(?:Eredeti\s+ár\s+)?([0-9][\d\s.]*(?:,\d+)?)\s*Ft"
        r"(?:\s*\([^)]*\))?\s+helyett\s+"
        r"([0-9][\d\s.]*(?:,\d+)?)\s*Ft",
        block,re.I|re.S
    )
    if sm:
        original_price=parse_huf(sm.group(1)+" Ft")
        sale_price=parse_huf(sm.group(2)+" Ft")

    if original_price is not None:
        price=original_price
    else:
        normal=re.search(
            r"Internetes\s+ár(?!\s+törzsvásárlóknak)"
            r".{0,1200}?([0-9][\d\s.]*(?:,\d+)?)\s*Ft",
            block,re.I|re.S
        )
        if normal:
            price=parse_huf(normal.group(1)+" Ft")

    return {
        "price_huf":price,
        "unit_price":unit_price,
        "lowest_30d_price_huf":lowest_30,
        "original_price_huf":original_price,
        "sale_price_huf":sale_price,
    }

def extract_product_info(text):
    info=extract_first_section(
        text,
        "Termékinformáció",
        ["Termékleírás","Betegtájékoztató","Szállítási információk"]
    )
    description=extract_first_section(
        text,
        "Termékleírás",
        ["Betegtájékoztató","Szállítási információk","Customer Reviews","Vélemények"]
    )
    return info,description

def extract_leaflet_section(text):
    markers=[
        ("leaflet","Betegtájékoztató: Információk a felhasználó számára"),
        ("leaflet","Betegtájékoztató: Információk a beteg számára"),
        ("usage_instruction","Használati utasítás"),
        ("usage_instruction","Használati útmutató"),
        ("leaflet","Betegtájékoztató"),
    ]
    positions=[]
    for source,marker in markers:
        m=re.search(re.escape(marker),text,re.I)
        if m:
            positions.append((m.start(),source))
    if not positions:
        return None,None
    start,source_prefix=min(positions,key=lambda item:item[0])
    # Stop before shipping/recommendation/footer repetition if possible.
    end=len(text)
    for marker in ["Szállítási információk","Customer Reviews","Hirdetés","Footer"]:
        m=re.search(re.escape(marker),text[start:],re.I)
        if m:
            end=min(end,start+m.start())
    return normalize_space(text[start:end])[:300000],source_prefix

def extract_leaflet(text):
    section,_source_prefix=extract_leaflet_section(text)
    return section

def extract_sku(text):
    m=re.search(r"\bCikkszám\s*:\s*([A-Za-z0-9_-]+)",text,re.I)
    return m.group(1) if m else None

def extract_brand(soup,*json_products):
    # JSON-LD is generally cleaner than scraping visual markup.
    for json_prod in json_products:
        b=json_prod.get("brand") if isinstance(json_prod,dict) else None
        if isinstance(b,dict) and b.get("name"):
            return normalize_space(b["name"])
        if isinstance(b,list):
            for item in b:
                if isinstance(item,dict) and item.get("name"):
                    return normalize_space(item["name"])
                if isinstance(item,str):
                    return normalize_space(item)
        if isinstance(b,str):
            return normalize_space(b)

    # Fallback: locate exact "Márka:" label.
    for node in soup.find_all(string=re.compile(r"^\s*Márka\s*:?\s*$",re.I)):
        parent=node.parent
        candidates=[
            parent.find_next_sibling(),
            parent.parent.find_next_sibling() if parent.parent else None,
            parent.find_next("a"),
            parent.find_next("span"),
        ]
        for c in candidates:
            value=text_of(c)
            if value and value.lower()!="márka":
                return value
    return None

def extract_product_badges(soup):
    root=(
        soup.select_one("#product-infos .product-badges")
        or soup.select_one("product-info .product-badges")
    )
    if not root:
        return []
    return unique_keep_order([text_of(badge) for badge in root.select(".badge")])

def classify_from_product_badges(badges):
    for badge in badges:
        classification,raw=_classify_raw(badge)
        if classification!="UNKNOWN":
            return classification,raw
    return "UNKNOWN",None

def extract_breadcrumbs(soup):
    selectors=[
        '[aria-label="breadcrumb"] a',
        '[aria-label="Breadcrumb"] a',
        ".breadcrumb a",
        "nav.breadcrumb a",
    ]
    for sel in selectors:
        vals=unique_keep_order([text_of(a) for a in soup.select(sel)])
        if vals:
            return vals
    return []

def analytics_breadcrumbs(item):
    raw=normalize_space(item.get("product_breadcrumbs")) if item else None
    if not raw:
        return []
    return unique_keep_order(part.strip() for part in raw.split(">"))

def is_homeopathic_product(breadcrumbs):
    breadcrumb_text=_fold_text(" ".join(breadcrumbs or []))
    return "homeopatias" in breadcrumb_text

def is_vitamin_category(breadcrumbs):
    breadcrumb_text=_fold_text(" ".join(breadcrumbs or []))
    return "vitamin" in breadcrumb_text or "multivitamin" in breadcrumb_text

def has_medicine_leaflet_signal(text):
    folded=_fold_text(text)
    signals=[
        "ez a gyogyszer orvosi rendelveny nelkul kaphato",
        "ezt a gyogyszert mindig pontosan",
        "mielott elkezdi szedni ezt a gyogyszert",
        "mielott elkezdi alkalmazni ezt a gyogyszert",
    ]
    return any(signal in folded for signal in signals)

def extract_images(soup,json_prod,json_ld,base_url,name=None):
    urls=[]
    image_index=_json_image_index(json_ld)

    def add_image(value):
        if isinstance(value,list):
            for item in value:
                add_image(item)
            return
        if isinstance(value,dict):
            direct=value.get("contentUrl") or value.get("url")
            if direct:
                urls.append(urljoin(base_url,direct))
                return
            ref=value.get("@id")
            if ref and ref in image_index:
                urls.append(urljoin(base_url,image_index[ref]))
            return
        if isinstance(value,str):
            if value.startswith("#"):
                return
            if value in image_index:
                value=image_index[value]
            urls.append(urljoin(base_url,value))

    image=json_prod.get("image")
    add_image(image)

    main=main_product_node(soup)
    for img in main.find_all("img") if main else []:
        alt=normalize_space(img.get("alt"))
        if name and alt and name.lower()[:12] not in alt.lower():
            continue
        for attr in ("src","data-src","data-original"):
            value=img.get(attr)
            if value:
                urls.append(urljoin(base_url,value))
        srcset=img.get("srcset")
        if srcset:
            for part in srcset.split(","):
                urls.append(urljoin(base_url,part.strip().split(" ")[0]))

    cleaned=[]
    blocked=("logo","icon_","simplepay","visa","maestro","mastercard","benu_usp","sprite")
    for url in urls:
        low=str(url).lower()
        if any(token in low for token in blocked):
            continue
        if "/cdn/shop/" in low or low.endswith((".jpg",".jpeg",".png",".webp")):
            cleaned.append(url)
    return unique_keep_order(cleaned)

def extract_form_and_strength(name,active_raw):
    source=" ".join(x for x in [name,active_raw] if x)
    strength=[]
    for m in re.finditer(
        r"\b\d+(?:[.,]\d+)?\s*(?:mg/ml|mg/g|mg|g|µg|mcg|ml|%|NE|IU|Ch)"
        r"(?:\s*/\s*\d+(?:[.,]\d+)?\s*(?:mg|g|ml))?\b",
        source,re.I
    ):
        strength.append(m.group(0))
    strength=unique_keep_order(strength)

    forms=[
        "gyomornedv-ellenálló bevont tabletta","gyomornedv-ellenálló tabletta",
        "belsőleges szuszpenzió","belsőleges oldat","oldatos orrspray",
        "pezsgőtabletta","rágótabletta","bevont tabletta","filmtabletta",
        "lágy kapszula","hüvelytabletta","hüvelykapszula","kapszula","tabletta",
        "granulátum","szuszpenzió",
        "szirup","oldatos orrspray","orrspray","spray","gél","krém",
        "kenőcs","kúp","csepp","oldat","por","pasztilla","hab",
        "golyócskák"
    ]
    low=(name or "").lower()
    form=next((f for f in forms if f in low),None)

    package=None
    pm=re.search(r"\b\d+(?:[.,]\d+)?\s*(?:db|ml|g|kg|l|tasak)\b",name or "",re.I)
    if pm:
        package=pm.group(0)

    return (
        "; ".join(strength) if strength else None,
        form,
        package,
    )

def extract_statuses(text,badges=None):
    source=" ".join(badges) if badges is not None else text
    statuses=[]
    for phrase in [
        "Csak gyógyszertárban átvehető",
        "Szállítással elérhető",
        "Értesítsen",
        "EP kártyára elszámolható",
    ]:
        if re.search(re.escape(phrase),source or "",re.I):
            statuses.append(phrase)
    return unique_keep_order(statuses)

def split_ingredient_names(active_raw):
    if not active_raw:
        return []
    # Remove common quantity fragments while keeping the raw field separately.
    s=clean_active_ingredient_value(active_raw)
    if not s:
        return []
    first_sentence=re.split(r"\.\s+",s,1)[0]
    if first_sentence:
        s=first_sentence
    s=re.sub(r"-\(([^)]{1,5})\)-",r"-\1-",s)
    s=re.sub(r"\([^)]*\)","",s)
    s=s.replace(":"," ")
    s=re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:mg/ml|mg/g|mg|g|µg|mcg|ml|NE|IU|%)\b","",s,flags=re.I)
    s=re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:milliliterenként|milliliter)\b","",s,flags=re.I)
    s=re.sub(r"\b(?:tasakonként|tablettánként|filmtablettánként|kapszulánként|pezsgőtablettánként|rágótablettánként|milliliterenként|milliliterben|grammonként|cseppenként|üvegenként|ml-enként|oldatban)\b","",s,flags=re.I)
    s=re.sub(r"\b(?:tasakban|tablettában|filmtablettában|kapszulában|pezsgőtablettában|rágótablettában|befújásnyi|befújás|lemosható\s+kenőcsben)\b","",s,flags=re.I)
    s=re.sub(r"\b\d+(?:[.,]\d+)?\b","",s)
    s=re.sub(r"\b(?:gyomornedv-ellenálló|bevont|film|filmtabletta|tabletta|lágy|kapszula|krém|szuszpenzió|oldatos|orrspray|gél|kenőcs)\b","",s,flags=re.I)
    s=re.sub(r"\b(?:egy|gramm|készítmény|hatóanyaga|hatóanyagai|hatóanyagok?|tartalmú|tartalmaz|tartalmaz\.|van)\b","",s,flags=re.I)
    parts=re.split(r"\s+\+\s+|\s+és\s+|\s+ill\.\s+|\s+illetve\s+|;|,",s,flags=re.I)
    out=[]
    for part in parts:
        part=normalize_space(part)
        part=part.strip(" ,.;:-")
        words=[]
        for word in part.split():
            if not words or words[-1].lower()!=word.lower():
                words.append(word)
        part=" ".join(words)
        part=re.sub(r"^(?:az|a)\s+","",part,flags=re.I)
        part=re.sub(r"\b(?:az|a)\s*$","",part,flags=re.I)
        part=re.sub(r"\b(vagy|ha|önnek|gyógyszer|allergiás|alkalmazható|olvassa|mellékelt|lásd)\b.*$","",part,flags=re.I)
        part=re.sub(r"\s+formájában\)?\s*$","",part,flags=re.I)
        part=re.sub(
            r"^(vas|réz|cink|kalcium|magnézium|mangán|jód|molibdén|króm|szelén|vanádium|foszfor|bór)\s*[-–‑].*$",
            r"\1",
            part,
            flags=re.I,
        )
        part=re.sub(r"(?:ot|et|at)\b","",part,flags=re.I)
        part=re.sub(r"(?<=ol)t\b","",part,flags=re.I)
        part=re.sub(r"(?<=[né])t\b","",part,flags=re.I)
        part=part.strip(" ,.;:-–‑")
        part=re.sub(r"\s{2,}"," ",part)
        if part and 2<=len(part)<120:
            out.append(part)
    return unique_keep_order(out)

def assess_quality(data):
    warnings=[]
    if not data.get("price_huf"):
        warnings.append("missing_price")
    if not data.get("sku"):
        warnings.append("missing_sku")
    if not data.get("ean"):
        warnings.append("missing_ean")
    if data.get("classification")=="UNKNOWN" and data.get("classification_source")=="unknown":
        warnings.append("unknown_classification")
    if data.get("classification")=="OTC" and not data.get("active_ingredient_raw"):
        warnings.append("missing_active_ingredient_for_otc")
    if not data.get("images"):
        warnings.append("missing_product_image")
    if len(data.get("raw_text") or "")<5000:
        warnings.append("short_raw_text")

    critical={"missing_price","missing_sku","missing_ean","short_raw_text"}
    is_incomplete=any(w in critical for w in warnings)
    return is_incomplete,warnings

def parse_product(html,url,base_url):
    soup=BeautifulSoup(html,"lxml")
    text=full_text(soup)
    ptext=product_text(soup)
    json_ld=parse_json_ld(soup)
    jp=json_product(json_ld)
    jpg=json_product_group(json_ld)

    name=first_nonempty(
        jp.get("name"),
        jpg.get("name"),
        text_of(soup.find("h1")),
        soup.title.get_text(strip=True) if soup.title else None
    )
    if not name:
        raise ValueError("Product name not found")

    metadata=extract_product_metadata(ptext,product_name=name,json_ld=json_ld)
    initial_sku=jp.get("sku") or extract_sku(ptext)
    analytics_item=analytics_product_item(soup,name,initial_sku)
    badges=extract_product_badges(soup)
    badge_classification,badge_raw=classify_from_product_badges(badges)
    analytics_classification,analytics_raw=classify_from_analytics_item(analytics_item)
    classification_source="metadata" if metadata["classification"]!="UNKNOWN" else "unknown"
    if metadata["classification"]=="UNKNOWN" and badge_classification!="UNKNOWN":
        metadata["classification"]=badge_classification
        metadata["classification_raw"]=badge_raw
        classification_source="product_badge"
    if metadata["classification"]=="UNKNOWN" and analytics_classification!="UNKNOWN":
        metadata["classification"]=analytics_classification
        metadata["classification_raw"]=analytics_raw
        classification_source="analytics_item_type"

    prices=extract_main_prices(ptext)
    json_price=extract_json_price(jp)
    if prices["price_huf"] is None:
        prices["price_huf"]=json_price
    if prices["price_huf"] is None and analytics_item.get("list_price") is not None:
        try:
            prices["price_huf"]=int(float(analytics_item["list_price"]))
        except Exception:
            pass

    info,description=extract_product_info(ptext)
    leaflet=extract_leaflet(ptext)
    brand=extract_brand(soup,jp,jpg) or normalize_space(analytics_item.get("item_brand"))
    images=extract_images(soup,jp,json_ld,base_url,name)
    breadcrumbs=extract_breadcrumbs(soup) or analytics_breadcrumbs(analytics_item)
    if is_homeopathic_product(breadcrumbs) and metadata["classification"]!="NON_MEDICINE":
        metadata["classification"]="NON_MEDICINE"
        metadata["classification_raw"]="Homeopátiás készítmények"
        classification_source="homeopathic_category"
    elif (
        metadata["classification"]=="OTC"
        and is_vitamin_category(breadcrumbs)
        and not has_medicine_leaflet_signal(ptext)
    ):
        metadata["classification"]="NON_MEDICINE"
        metadata["classification_raw"]="Vitamin category without medicine leaflet signal"
        classification_source="vitamin_category_without_medicine_signal"
    strength,form,package=extract_form_and_strength(name,metadata["active_ingredient_raw"])
    sku=initial_sku or normalize_space(analytics_item.get("sku"))
    ean=metadata["ean"] or _json_gtin(jp) or extract_shopify_barcode(html,name,sku)

    data={
        "url":url,
        "name":name,
        "brand":brand,
        "sku":sku,
        "ean":ean,
        "classification":metadata["classification"],
        "classification_raw":metadata["classification_raw"],
        "classification_source":classification_source,
        "price_huf":prices["price_huf"],
        "unit_price":prices["unit_price"],
        "lowest_30d_price_huf":prices["lowest_30d_price_huf"],
        "original_price_huf":prices["original_price_huf"],
        "sale_price_huf":prices["sale_price_huf"],
        "active_ingredient_raw":metadata["active_ingredient_raw"],
        "active_ingredient_source":metadata["active_ingredient_source"],
        "ingredient_names":split_ingredient_names(metadata["active_ingredient_raw"]),
        "strength":strength,
        "pharmaceutical_form":form,
        "package_size":package,
        "product_information":info,
        "description":description,
        "leaflet_text":leaflet,
        "distributor":metadata["distributor"] or normalize_space(analytics_item.get("distributor")),
        "manufacturer":None,
        "registration_number":None,
        "breadcrumbs":breadcrumbs,
        "images":images,
        "statuses":extract_statuses(ptext,badges),
        "raw_text":text,
        "raw_html_hash":__import__("hashlib").sha256(html.encode("utf-8",errors="ignore")).hexdigest(),
        "json_ld":json.dumps(json_ld,ensure_ascii=False),
    }
    data["ingredient_names"]=split_ingredient_names(data["active_ingredient_raw"])
    data["is_incomplete"],data["parse_warnings"]=assess_quality(data)
    return data
