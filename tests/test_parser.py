from scraper.parser import (
    extract_product_metadata,extract_main_prices,extract_product_info,
    json_product,extract_json_price,parse_product,split_ingredient_names
)

def test_otc_metadata_does_not_use_footer():
    text="""
    Besorolás típusa: vény nélkül kapható gyógyszer
    EAN: 5999528941535
    Betegtájékoztató
    Vény nélkül kapható gyógyszerek és egyéb termékek
    """
    m=extract_product_metadata(text)
    assert m["classification"]=="OTC"
    assert m["ean"]=="5999528941535"

def test_non_medicine_metadata():
    text="Besorolás típusa: gyógyászati segédeszköz\nEAN: 9990000143016"
    m=extract_product_metadata(text)
    assert m["classification"]=="NON_MEDICINE"

def test_price_block():
    text="""
    Internetes ár törzsvásárlóknak Az ár BENU Hűségkártyával érvényes. 3 000 Ft
    Internetes ár
    A feltüntetett ár maximált fogyasztói ár.
    5 099 Ft
    Egységár:
    170 Ft / ml
    Az elmúlt 30 nap legalacsonyabb ára:
    4 999 Ft
    """
    p=extract_main_prices(text)
    assert p["price_huf"]==5099
    assert p["unit_price"]=="170 Ft / ml"
    assert p["lowest_30d_price_huf"]==4999

def test_sale_price():
    text="Internetes ár 4 499 Ft Eredeti ár 5 649 Ft helyett 4 499 Ft"
    p=extract_main_prices(text)
    assert p["price_huf"]==5649
    assert p["original_price_huf"]==5649
    assert p["sale_price_huf"]==4499

def test_nested_json_ld_price():
    data=[{
        "@context":"https://schema.org",
        "@graph":[{
            "@type":"ProductGroup",
            "name":"Teszt",
            "hasVariant":[{
                "@type":"Product",
                "name":"Teszt",
                "sku":"123",
                "gtin":"5999999999999",
                "offers":{
                    "@type":"Offer",
                    "priceSpecification":[{
                        "@type":"UnitPriceSpecification",
                        "price":3049,
                        "priceCurrency":"HUF",
                    }],
                },
            }],
        }],
    }]
    product=json_product(data)
    assert product["sku"]=="123"
    assert extract_json_price(product)==3049

def test_product_badge_classification_fallback():
    html="""
    <html><head><title>ACC teszt</title></head><body>
    <product-info>
      <h1>ACC teszt 20 db</h1>
      <div class="price__container">Internetes ár 1 999 Ft Egységár: 100 Ft / db</div>
      <div id="product-infos">
        <div class="product-badges">
          <div class="badge stripe">Vény nélkül kapható gyógyszer</div>
        </div>
        <div>Termékinformáció A készítmény hatóanyaga az acetilcisztein. Termékleírás EAN: 5999999999999</div>
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/acc-teszt","https://benu.hu")
    assert data["classification"]=="OTC"
    assert data["classification_source"]=="product_badge"
    assert data["active_ingredient_raw"]=="acetilcisztein"
    assert data["active_ingredient_source"]=="product_information_keszitmeny_hatoanyaga"

def test_non_product_otc_text_is_not_classification():
    html="""
    <html><head><title>Kozmetikum teszt</title></head><body>
    <product-info>
      <h1>Kozmetikum teszt 100 ml</h1>
      <div class="price__container">Internetes ár 3 299 Ft Egységár: 33 Ft / ml</div>
      <div id="product-infos">
        <div class="product-badges"><div class="badge stripe">Szállítással elérhető</div></div>
      </div>
    </product-info>
    <footer>Vény nélkül kapható gyógyszerek és egyéb termékek</footer>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/kozmetikum-teszt","https://benu.hu")
    assert data["classification"]=="UNKNOWN"

def test_analytics_item_type_fallback_matches_current_product():
    html="""
    <html><head><title>Vitaday teszt</title></head><body>
    <product-info>
      <h1>Vitaday teszt 17 db</h1>
      <div class="price__container">Internetes ár 599 Ft</div>
    </product-info>
    <script type="application/json" class="analytics-product-data">
    {"items":[{"item_name":"Advil ajánló","sku":"999","item_type":"OTC"}]}
    </script>
    <script type="application/json" class="analytics-product-data">
    {"items":[{
      "item_name":"Vitaday teszt 17 db",
      "item_brand":"Vitaday",
      "sku":"127815",
      "product_breadcrumbs":"Vitaminok > C-vitamin",
      "distributor":"InnoPharm Kft.",
      "item_type":"ETR"
    }]}
    </script>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/vitaday-teszt","https://benu.hu")
    assert data["classification"]=="NON_MEDICINE"
    assert data["classification_source"]=="analytics_item_type"
    assert data["classification_raw"]=="ETR"
    assert data["brand"]=="Vitaday"
    assert data["sku"]=="127815"
    assert data["breadcrumbs"]==["Vitaminok","C-vitamin"]
    assert data["distributor"]=="InnoPharm Kft."

def test_homeopathic_category_overrides_otc_item_type():
    html="""
    <html><head><title>Acidum teszt</title></head><body>
    <product-info>
      <h1>Acidum Arsenicosum Anhydricum golyócskák 15 Ch 4g</h1>
      <div class="price__container">Internetes ár 1 499 Ft</div>
    </product-info>
    <script type="application/json" class="analytics-product-data">
    {"items":[{
      "item_name":"Acidum Arsenicosum Anhydricum golyócskák 15 Ch 4g",
      "sku":"123456",
      "product_breadcrumbs":"Homeopátiás készítmények",
      "item_type":"OTC"
    }]}
    </script>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/acidum-teszt","https://benu.hu")
    assert data["classification"]=="NON_MEDICINE"
    assert data["classification_source"]=="homeopathic_category"
    assert data["classification_raw"]=="Homeopátiás készítmények"

def test_homeopathic_non_medicine_source_is_preserved():
    html="""
    <html><head><title>Füldugó teszt</title></head><body>
    <product-info>
      <h1>ALPINE Pluggies Kids füldugó 1pár</h1>
      <div class="price__container">Internetes ár 7 716 Ft</div>
    </product-info>
    <script type="application/json" class="analytics-product-data">
    {"items":[{
      "item_name":"ALPINE Pluggies Kids füldugó 1pár",
      "sku":"254677",
      "product_breadcrumbs":"Homeopátiás készítmények",
      "item_type":"GYSE"
    }]}
    </script>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/alpine-teszt","https://benu.hu")
    assert data["classification"]=="NON_MEDICINE"
    assert data["classification_source"]=="analytics_item_type"
    assert data["classification_raw"]=="GYSE"

def test_shopify_barcode_is_product_bound_ean_fallback():
    html="""
    <html><head><title>Barcode teszt</title></head><body>
    <product-info>
      <h1>Barcode teszt 20 db</h1>
      <div class="price__container">Internetes ár 1 999 Ft</div>
    </product-info>
    <script>
    var product={"variants":[{"sku":"123456","name":"Barcode teszt 20 db","barcode":"5997207711028"}]};
    var recommendation={"variants":[{"sku":"999999","name":"Másik termék","barcode":"1111111111111"}]};
    </script>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/barcode-teszt","https://benu.hu")
    assert data["ean"]=="5997207711028"

def test_shopify_barcode_fallback_ignores_unmatched_product():
    html="""
    <html><head><title>Barcode teszt</title></head><body>
    <product-info>
      <h1>Barcode teszt 20 db</h1>
      <div class="price__container">Internetes ár 1 999 Ft</div>
    </product-info>
    <script>
    var recommendation={"variants":[{"sku":"999999","name":"Másik termék","barcode":"1111111111111"}]};
    </script>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/barcode-teszt","https://benu.hu")
    assert data["ean"] is None

def test_vitamin_category_without_medicine_signal_is_not_public_otc():
    html="""
    <html><head><title>Vitamin badge teszt</title></head><body>
    <product-info>
      <h1>Vitamin badge teszt 30 db</h1>
      <div class="price__container">Internetes ár 2 999 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>Termékinformáció Vitamin készítmény mindennapi használatra.</div>
    </product-info>
    <script type="application/json" class="analytics-product-data">
    {"items":[{
      "item_name":"Vitamin badge teszt 30 db",
      "sku":"123456",
      "product_breadcrumbs":"Vitaminok, immunerősítés > Multivitaminok",
      "item_type":"OTC"
    }]}
    </script>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/vitamin-badge-teszt","https://benu.hu")
    assert data["classification"]=="NON_MEDICINE"
    assert data["classification_source"]=="vitamin_category_without_medicine_signal"

def test_vitamin_category_with_medicine_signal_stays_otc():
    html="""
    <html><head><title>Actival teszt</title></head><body>
    <product-info>
      <h1>Actival EXTRA filmtabletta 30 db</h1>
      <div class="price__container">Internetes ár 4 999 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>Betegtájékoztató Ez a gyógyszer orvosi rendelvény nélkül kapható.</div>
    </product-info>
    <script type="application/json" class="analytics-product-data">
    {"items":[{
      "item_name":"Actival EXTRA filmtabletta 30 db",
      "sku":"123456",
      "product_breadcrumbs":"Vitaminok, immunerősítés > Multivitaminok",
      "item_type":"OTC"
    }]}
    </script>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/actival-extra-teszt","https://benu.hu")
    assert data["classification"]=="OTC"
    assert data["classification_source"]=="product_badge"

def test_active_ingredients_from_leaflet_hatanyagok_sentence():
    html="""
    <html><head><title>Actifed teszt</title></head><body>
    <product-info>
      <h1>Actifed 1 mg/ml + 50 mg/ml oldatos orrspray 10ml</h1>
      <div class="price__container">Internetes ár 4 099 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Termékleírás
        Betegtájékoztató
        Mit tartalmaz az Actifed orrspray?
        A hatóanyagok a xilometazolin-hidroklorid és a dexpantenol.
        Az oldatos orrspray 1 mg xilometazolin-hidrokloridot és 50 mg dexpantenolt tartalmaz milliliterenként.
        EAN: 3574661762562
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/actifed-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="xilometazolin-hidroklorid és a dexpantenol"
    assert data["active_ingredient_source"]=="leaflet_hatanyagok_sentence"
    assert data["ingredient_names"]==["xilometazolin-hidroklorid","dexpantenol"]
    assert "missing_active_ingredient_for_otc" not in data["parse_warnings"]

def test_active_ingredients_from_mit_tartalmaz_section():
    html="""
    <html><head><title>Actival Junior teszt</title></head><body>
    <product-info>
      <h1>Actival JUNIOR rágótabletta 60 db</h1>
      <div class="price__container">Internetes ár 3 499 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Betegtájékoztató
        Mit tartalmaz az Actival Junior rágótabletta?
        - 417 NE A-vitamint, 30 mg aszkorbinsavat (C-vitamin), 50 mg kalciumot.
        Egyéb összetevők: szorbit, xilit.
        EAN: 5997207713954
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/actival-junior-teszt","https://benu.hu")
    assert data["active_ingredient_raw"].startswith("417 NE A-vitamint")
    assert data["active_ingredient_source"]=="leaflet_mit_tartalmaz"
    assert "Egyéb összetevők" not in data["active_ingredient_raw"]
    assert "missing_active_ingredient_for_otc" not in data["parse_warnings"]

def test_tartalmu_fallback_ignores_mismatched_product_info():
    html="""
    <html><head><title>Algopyrin Trio teszt</title></head><body>
    <product-info>
      <h1>Algopyrin Trio tabletta 20 db</h1>
      <div class="price__container">Internetes ár 2 999 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Termékinformáció
        Az Algopyrin 500 mg filmtabletta metamizol-nátrium-monohidrát tartalmú, vény nélkül kapható gyógyszer.
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/algopyrin-trio-tabletta-quarelin","https://benu.hu")
    assert data["active_ingredient_raw"] is None
    assert data["active_ingredient_source"] is None
    assert data["ingredient_names"]==[]
    assert "missing_active_ingredient_for_otc" in data["parse_warnings"]

def test_active_ingredient_from_matching_tartalmu_sentence():
    html="""
    <html><head><title>Algopyrin 500 mg filmtabletta teszt</title></head><body>
    <product-info>
      <h1>Algopyrin 500 mg filmtabletta 20 db</h1>
      <div class="price__container">Internetes ár 2 999 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Termékinformáció
        Az Algopyrin 500 mg filmtabletta metamizol-nátrium-monohidrát tartalmú, vény nélkül kapható gyógyszer.
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/algopyrin-500-mg-filmtabletta-20-db","https://benu.hu")
    assert data["active_ingredient_raw"]=="metamizol-nátrium-monohidrát"
    assert data["active_ingredient_source"]=="product_information_tartalmu_sentence"
    assert data["ingredient_names"]==["metamizol-nátrium-monohidrát"]
    assert "missing_active_ingredient_for_otc" not in data["parse_warnings"]

def test_detailed_leaflet_ingredients_override_generic_vitamin_metadata():
    html="""
    <html><head><title>Actival Extra teszt</title></head><body>
    <product-info>
      <h1>Actival Extra filmtabletta 30 db</h1>
      <div class="price__container">Internetes ár 4 999 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Termékinformáció
        Hatóanyag: C-vitamin
        Betegtájékoztató
        Mit tartalmaz az Actival Extra filmtabletta?
        A készítmény hatóanyagai 1 filmtablettában:
        0,5 mg (1666 NE) all-(E)-retinol (A-vitamin),
        1,8 mg bétakarotin,
        125 mg aszkorbinsav (C-vitamin).
        Segédanyagként szorbitot is tartalmaz.
        EAN: 5997207710069
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/actival-extra-teszt","https://benu.hu")
    assert data["active_ingredient_raw"].startswith("1 filmtablettában")
    assert data["active_ingredient_source"]=="leaflet_mit_tartalmaz"
    assert data["ingredient_names"]==["all-E-retinol","bétakarotin","aszkorbinsav"]
    assert "Segédanyag" not in data["active_ingredient_raw"]

def test_structured_active_ingredient_stops_before_singular_excipients():
    html="""
    <html><head><title>Allegra teszt</title></head><body>
    <product-info>
      <h1>Allegra 120 mg filmtabletta 30 db</h1>
      <div class="price__container">Internetes ár 5 999 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Besorolás típusa: vény nélkül kapható gyógyszer
        Hatóanyag: 120 mg fexofenadin-hidroklorid filmtablettánként,
        Egyéb összetevő(k): magnézium-sztearát, kroszkarmellóz-nátrium.
        EAN: 5909990994697
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/allegra-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="120 mg fexofenadin-hidroklorid filmtablettánként,"
    assert data["active_ingredient_source"]=="structured_hatany"
    assert data["ingredient_names"]==["fexofenadin-hidroklorid"]

def test_usage_instruction_active_ingredient_source():
    html="""
    <html><head><title>Orrspray teszt</title></head><body>
    <product-info>
      <h1>Orrspray teszt 15ml</h1>
      <div class="price__container">Internetes ár 2 999 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Használati utasítás
        Mit tartalmaz az Orrspray teszt?
        A készítmény hatóanyaga az oximetazolin-hidroklorid.
        Egyéb összetevő(k): benzalkónium-klorid.
        EAN: 5999528942266
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/orrspray-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="oximetazolin-hidroklorid."
    assert data["active_ingredient_source"]=="usage_instruction_mit_tartalmaz"
    assert data["ingredient_names"]==["oximetazolin-hidroklorid"]

def test_json_ld_active_ingredient_source():
    html="""
    <html><head>
    <title>JSON-LD teszt</title>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Product","name":"JSON-LD teszt","sku":"123","activeIngredient":"acetilcisztein"}
    </script>
    </head><body>
    <product-info>
      <h1>JSON-LD teszt</h1>
      <div class="price__container">Internetes ár 1 999 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>EAN: 5999999999999</div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/json-ld-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="acetilcisztein"
    assert data["active_ingredient_source"]=="json_ld"
    assert data["ingredient_names"]==["acetilcisztein"]

def test_ingredient_names_drop_excipients_and_warnings():
    assert split_ingredient_names(
        "400 mg ibuprofént tartalmaz filmtablettánként, "
        "Segédanyagok: a készítmény 60 mg laktóz-monohidrátot tartalmaz."
    ) == ["ibuprofén"]
    assert split_ingredient_names(
        "400 mg ibuprofén lágy kapszulánként, "
        "Segédanyagként szorbit-szirupot is tartalmaz."
    ) == ["ibuprofén"]
    assert split_ingredient_names(
        "400 mg ibuprofen lágy kapszulánként, "
        "Segédanyag: szorbitot (E420) tartalmaz."
    ) == ["ibuprofen"]
    assert split_ingredient_names(
        "220 mg naproxén-nátrium (megfelel 200 mg naproxénnek) filmtablettánként "
        "Nem alkalmazható: ha allergiás a naproxénre."
    ) == ["naproxén-nátrium"]
    assert split_ingredient_names(
        "1 filmtablettában: 0,5 mg (1666 NE) all-(E)-retinol "
        "(retinol-acetát formájában) (A-vitamin), 1,8 mg bétakarotin, "
        "1,4 mg tiamin (tiamin-nitrát formájában), 125 mg aszkorbinsav "
        "(C-vitamin), 0,005 mg kolekalciferolt (D-vitamin)."
    ) == ["all-E-retinol","bétakarotin","tiamin","aszkorbinsav","kolekalciferol"]
    assert split_ingredient_names(
        "A készítmény hatóanyagai filmtablettánként: "
        "0,80 mg all-E retinol, 1,4 mg tiamin."
    ) == ["all-E retinol","tiamin"]
    assert split_ingredient_names(
        "2 mg mangán ‑szulfát‑monohidrát formájában, 15 mg cink-szulfát-monohidrát formájában."
    ) == ["mangán","cink"]

def test_info_description():
    text="Termékinformáció Ez a termékinformáció. Termékleírás Ez a részletes leírás. Betegtájékoztató"
    i,d=extract_product_info(text)
    assert i=="Ez a termékinformáció."
    assert d=="Ez a részletes leírás."

def test_ingredients():
    assert split_ingredient_names("ibuprofen + pseudoefedrin") == ["ibuprofen","pseudoefedrin"]
