from scraper.parser import (
    extract_product_metadata,extract_main_prices,extract_product_info,
    json_product,extract_json_price,parse_product,split_ingredient_names,
    assess_quality
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

def test_unit_price_does_not_swallow_following_discount_label():
    text="""
    Internetes ár
    19 229 Ft
    Egységár:
    641 Ft /
    Az elmúlt 30 nap legalacsonyabb ára:
    18 999 Ft
    """
    p=extract_main_prices(text)
    assert p["price_huf"]==19229
    assert p["unit_price"] is None
    assert p["lowest_30d_price_huf"]==18999

def test_unit_price_does_not_accept_discount_percent_as_unit():
    text="""
    Internetes ár
    16 799 Ft
    Egységár:
    218 Ft / 35%
    """
    p=extract_main_prices(text)
    assert p["price_huf"]==16799
    assert p["unit_price"] is None

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

def test_medicine_leaflet_signal_resolves_unknown_as_otc():
    html="""
    <html><head><title>FoNo teszt</title></head><body>
    <product-info>
      <h1>FoNo teszt 50g</h1>
      <div class="price__container">Internetes ár 1 895 Ft</div>
      <div>
        Betegtájékoztató
        Mielőtt elkezdi alkalmazni ezt a gyógyszert, olvassa el figyelmesen.
        Ezt a gyógyszert mindig pontosan a betegtájékoztatóban leírtaknak megfelelően alkalmazza.
        A készítmény hatóanyaga 50 g külsőleges oldat 1,0 g szalicilsavat tartalmaz.
        EAN: 5998794322635
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/fono-teszt","https://benu.hu")
    assert data["classification"]=="OTC"
    assert data["classification_source"]=="medicine_leaflet_signal"
    assert data["active_ingredient_raw"]=="50 g külsőleges oldat 1,0 g szalicilsavat tartalmaz"

def test_prescription_marker_blocks_medicine_leaflet_otc_fallback():
    html="""
    <html><head><title>Rx teszt</title></head><body>
    <product-info>
      <h1>Rx teszt 20 db</h1>
      <div class="price__container">Internetes ár 1 895 Ft</div>
      <div>
        Vényköteles gyógyszer.
        Mielőtt elkezdi alkalmazni ezt a gyógyszert, olvassa el figyelmesen.
        A készítmény hatóanyaga tesztanyag.
        EAN: 5998794322635
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/rx-teszt","https://benu.hu")
    assert data["classification"]=="UNKNOWN"
    assert data["classification_source"]=="unknown"

def test_special_medical_food_overrides_otc_badge():
    html="""
    <html><head><title>Tápszer teszt</title></head><body>
    <nav aria-label="breadcrumb">
      <a>Életmód</a><a>Speciális étrend, élelmiszerek</a>
    </nav>
    <product-info>
      <h1>Tápszer teszt speciális gyógyászati célra szánt élelmiszer 4x200ml</h1>
      <div class="price__container">Internetes ár 8 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>
        Speciális gyógyászati célra szánt élelmiszer betegséghez kapcsolódó
        malnutríció diétás ellátására. Kizárólagos tápanyagforrásként is alkalmazható.
        EAN: 7613035089648
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/tapszer-teszt","https://benu.hu")
    assert data["classification"]=="NON_MEDICINE"
    assert data["classification_source"]=="special_medical_food"
    assert data["ingredient_names"]==[]

def test_homeopathic_globule_name_overrides_otc_badge():
    html="""
    <html><head><title>Golyócskák teszt</title></head><body>
    <product-info>
      <h1>Golyócskák teszt 30 db</h1>
      <div class="price__container">Internetes ár 3 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>Hetente egyszer 1 adag bevétele javasolt. EAN: 3352712008032</div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/golyocskak-teszt","https://benu.hu")
    assert data["classification"]=="NON_MEDICINE"
    assert data["classification_source"]=="homeopathic_product_name"

def test_homeopathic_brand_without_medicine_signal_overrides_otc_badge():
    html="""
    <html><head>
    <title>Boiron teszt</title>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Product","name":"Boiron teszt","brand":{"@type":"Brand","name":"BOIRON Laboratories"}}
    </script>
    </head><body>
    <product-info>
      <h1>Boiron teszt bukkális tabletta 30 db</h1>
      <div class="price__container">Internetes ár 3 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>Adagolás: naponta háromszor egy tabletta. EAN: 3352712008780</div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/boiron-teszt","https://benu.hu")
    assert data["classification"]=="NON_MEDICINE"
    assert data["classification_source"]=="homeopathic_brand_without_medicine_signal"

def test_dermocosmetic_category_without_medicine_signal_overrides_otc_badge():
    html="""
    <html><head><title>Krém teszt</title></head><body>
    <nav aria-label="breadcrumb">
      <a>Szépségápolás, dermokozmetika</a><a>Testápolás</a>
      <a>Bőrápoló olajok, krémek, gélek</a>
    </nav>
    <product-info>
      <h1>Krém teszt 30ml</h1>
      <div class="price__container">Internetes ár 2 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>Gyógyhatású krém bőrirritációra. Főbb hatóanyagok: cink-oxid. EAN: 5999999999999</div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/krem-teszt","https://benu.hu")
    assert data["classification"]=="NON_MEDICINE"
    assert data["classification_source"]=="dermocosmetic_without_medicine_signal"

def test_intim_lubricant_without_medicine_signal_overrides_otc_badge():
    html="""
    <html><head><title>Lubrikáns teszt</title></head><body>
    <nav aria-label="breadcrumb">
      <a>Intim</a><a>Óvszer, sikosító, potencianövelők</a>
    </nav>
    <product-info>
      <h1>Lubrikáns teszt 20g</h1>
      <div class="price__container">Internetes ár 2 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>Alkalmazása nyálkahártya-szárazság esetén ajánlott. EAN: 5997395700064</div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/lubrikans-teszt","https://benu.hu")
    assert data["classification"]=="NON_MEDICINE"
    assert data["classification_source"]=="intim_without_medicine_signal"

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

def test_homeopathic_product_text_overrides_otc_badge():
    html="""
    <html><head><title>Calmacare teszt</title></head><body>
    <product-info>
      <h1>Calmacare belsőleges oldat 10x1ml</h1>
      <div class="price__container">Internetes ár 3 499 Ft Egységár: 349 Ft / db</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Termékinformáció
        A külföldön közkedvelt Camilia homeopátiás gyógyszer már Magyarországon is kapható,
        Calmacare néven, jóváhagyott terápiás javallat nélkül.
        EAN: 3352712007974
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/calmacare-teszt","https://benu.hu")
    assert data["classification"]=="NON_MEDICINE"
    assert data["classification_source"]=="homeopathic_product_text"
    assert data["ingredient_names"]==[]
    assert "missing_active_ingredient_for_otc" not in data["parse_warnings"]

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

def test_formula_category_overrides_otc_badge():
    html="""
    <html><head><title>BEBA teszt</title></head><body>
    <product-info>
      <h1>BEBA OPTIpro Junior 3 anyatej-kiegészítő tápszer 12 hónapos kortól 600g</h1>
      <div class="price__container">Internetes ár 5 999 Ft Egységár: 10 Ft / g</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>Termékinformáció Tejalapú anyatej-kiegészítő tápszer kisgyermekeknek.</div>
    </product-info>
    <script type="application/json" class="analytics-product-data">
    {"items":[{
      "item_name":"BEBA OPTIpro Junior 3 anyatej-kiegészítő tápszer 12 hónapos kortól 600g",
      "sku":"123456",
      "product_breadcrumbs":"Baba-mama > Tápszerek",
      "item_type":"OTC"
    }]}
    </script>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/beba-teszt","https://benu.hu")
    assert data["classification"]=="NON_MEDICINE"
    assert data["classification_source"]=="formula_category"
    assert data["ingredient_names"]==[]
    assert "missing_active_ingredient_for_otc" not in data["parse_warnings"]

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

def test_leaflet_active_ingredient_allows_missing_question_mark_and_no_article():
    html="""
    <html><head><title>Buscopan teszt</title></head><body>
    <product-info>
      <h1>Buscopan 10 mg bevont tabletta 20 db</h1>
      <div class="price__container">Internetes ár 3 999 Ft Egységár: 200 Ft / db</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Betegtájékoztató
        Mit tartalmaz a Buscopan 10 mg bevont tabletta
        A készítmény hatóanyaga 10 mg hioszcin-butilbromid bevont tablettánként.
        Egyéb összetevők: borkősav, sztearinsav.
        EAN: 5999880347129
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/buscopan-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="10 mg hioszcin-butilbromid"
    assert data["active_ingredient_source"]=="leaflet_keszitmeny_hatoanyaga"
    assert data["ingredient_names"]==["hioszcin-butilbromid"]
    assert "missing_active_ingredient_for_otc" not in data["parse_warnings"]

def test_shortened_leaflet_product_name_is_not_treated_as_other_variant():
    html="""
    <html><head><title>Amorolfin teszt</title></head><body>
    <product-info>
      <h1>Amorolfin-Teva 50 mg/ml gyógyszeres körömlakk 2,5ml</h1>
      <div class="price__container">Internetes ár 6 999 Ft Egységár: 2 800 Ft / ml</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Betegtájékoztató
        Mit tartalmaz az Amorolfin-Teva?
        A készítmény hatóanyaga az amorolfin.
        Az Amorolfin-Teva 1 millilitere 50 mg amorolfint tartalmaz.
        Egyéb összetevők: metakrilát kopolimer.
        EAN: 5999999999999
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/amorolfin-teva-teszt","https://benu.hu")
    assert data["active_ingredient_raw"].startswith("amorolfin")
    assert data["active_ingredient_source"]=="leaflet_mit_tartalmaz"
    assert data["ingredient_names"]==["amorolfin"]
    assert "missing_active_ingredient_for_otc" not in data["parse_warnings"]

def test_leaflet_mit_tartalmaz_handles_hatanyagai_list_with_form_content_prefix():
    html="""
    <html><head><title>Baby Luuf teszt</title></head><body>
    <product-info>
      <h1>Baby Luuf illóolajos kenőcs 30g</h1>
      <div class="price__container">Internetes ár 3 999 Ft Egységár: 133 Ft / g</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Betegtájékoztató
        Mit tartalmaz a Baby Luuf kenőcs?
        - A készítmény hatóanyagai: 1 g kenőcs tartalma:
        40 mg tengerparti fenyőből származó terpentinolaj,
        15 mg eukaliptuszolaj,
        10 mg kakukkfűolaj.
        - Egyéb összetevők: kemény paraffin, fehér vazelin.
        EAN: 5999999999999
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/baby-luuf-teszt","https://benu.hu")
    assert data["active_ingredient_source"]=="leaflet_mit_tartalmaz"
    assert data["ingredient_names"]==[
        "tengerparti fenyőből származó terpentinolaj",
        "eukaliptuszolaj",
        "kakukkfűolaj",
    ]
    assert "missing_active_ingredient_for_otc" not in data["parse_warnings"]

def test_active_ingredient_stops_before_herbal_medicine_boilerplate():
    html="""
    <html><head><title>Bronchostop Trio teszt</title></head><body>
    <product-info>
      <h1>Bronchostop Trio megfázás elleni belsőleges oldat 120ml</h1>
      <div class="price__container">Internetes ár 4 099 Ft Egységár: 34 Ft / ml</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Hatóanyag: orvosi ziliz gyökér, lándzsás útifű és hársvirág"Hagyományos növényi gyógyszer.
        A javallatokra való alkalmazása kizárólag a régóta fennálló használaton alapul.
        EAN: 5999999999999
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/bronchostop-trio-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="orvosi ziliz gyökér, lándzsás útifű és hársvirág"
    assert data["ingredient_names"]==["orvosi ziliz gyökér","lándzsás útifű","hársvirág"]
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
    assert data["active_ingredient_raw"]=="120 mg fexofenadin-hidroklorid"
    assert data["active_ingredient_source"]=="structured_hatany"
    assert data["ingredient_names"]==["fexofenadin-hidroklorid"]

def test_structured_active_ingredient_stops_before_directions():
    html="""
    <html><head><title>Canesten teszt</title></head><body>
    <product-info>
      <h1>Canesten 10 mg/g krém 20g</h1>
      <div class="price__container">Internetes ár 3 999 Ft Egységár: 200 Ft / g</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Besorolás típusa: vény nélkül kapható gyógyszer
        Hatóanyag: klotrimazol Az érintett bőrterületre naponta 2-3 alkalommal vigye fel vékony rétegben.
        Összetevők: 10 mg klotrimazolt tartalmaz grammonként,
        Segédanyagok: cetil-sztearil-alkohol.
        EAN: 4008500128312
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/canesten-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="klotrimazol"
    assert data["active_ingredient_source"]=="structured_hatany"
    assert data["ingredient_names"]==["klotrimazol"]

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
    assert data["active_ingredient_raw"]=="oximetazolin-hidroklorid"
    assert data["active_ingredient_source"]=="usage_instruction_mit_tartalmaz"
    assert data["ingredient_names"]==["oximetazolin-hidroklorid"]

def test_product_active_ingredient_comma_sentence():
    html="""
    <html><head><title>Melatonin teszt</title></head><body>
    <product-info>
      <h1>Melatonin teszt 3 mg tabletta 30 db</h1>
      <div class="price__container">Internetes ár 2 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>A termék hatóanyaga, a melatonin, a szervezet által termelt hormonok családjába tartozik. EAN: 5999999999999</div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/melatonin-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="melatonin"
    assert data["active_ingredient_source"]=="fallback_hatoanyaga_comma"
    assert data["ingredient_names"]==["melatonin"]

def test_high_active_content_mg_sentence():
    html="""
    <html><head><title>Melatonin 5 teszt</title></head><body>
    <product-info>
      <h1>Melatonin Vitabalans 5 mg tabletta 30 db</h1>
      <div class="price__container">Internetes ár 2 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>Magas hatóanyag-tartalmú, 5 mg-os Melatonin Vitabalans természetes módon segít. EAN: 5999999999999</div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/melatonin-5-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="Melatonin"
    assert data["active_ingredient_source"]=="fallback_hatoanyag_tartalmu_mgos"
    assert data["ingredient_names"]==["Melatonin"]

def test_medicine_contains_active_sentence():
    html="""
    <html><head><title>Ibuprofen teszt</title></head><body>
    <product-info>
      <h1>Ibuprofen teszt 100 mg szuszpenzió 20x5ml</h1>
      <div class="price__container">Internetes ár 2 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>Ez a gyógyszer ibuprofént tartalmaz, ami az NSAID-ok csoportjába tartozik. EAN: 5999999999999</div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/ibuprofen-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="ibuprofén"
    assert data["active_ingredient_source"]=="fallback_gyogyszer_tartalmaz_ami"
    assert data["ingredient_names"]==["ibuprofén"]

def test_family_leaflet_without_soft_variant_is_still_usable():
    html="""
    <html><head><title>Enterol Forte teszt</title></head><body>
    <product-info>
      <h1>Enterol Forte 500mg por 10 db</h1>
      <div class="price__container">Internetes ár 4 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>
        Betegtájékoztató: Információk a felhasználó számára
        Mit tartalmaz az Enterol?
        A készítmény hatóanyaga: 500 mg liofilizált Saccharomyces boulardii CNCM I-745 sejt tasakonként.
        Egyéb összetevők: laktóz-monohidrát.
        EAN: 5999999999999
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/enterol-forte-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="500 mg liofilizált Saccharomyces boulardii CNCM I-745 sejt"
    assert data["active_ingredient_source"]=="leaflet_mit_tartalmaz"
    assert data["ingredient_names"]==["Saccharomyces boulardii"]

def test_strict_variant_still_blocks_other_product_leaflet():
    html="""
    <html><head><title>Algopyrin Trio teszt</title></head><body>
    <product-info>
      <h1>Algopyrin Trio tabletta 20 db</h1>
      <div class="price__container">Internetes ár 4 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>
        Az Algopyrin 500 mg filmtabletta metamizol-nátrium-monohidrát tartalmú,
        vény nélkül kapható gyógyszer.
        EAN: 5999999999999
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/algopyrin-trio-teszt","https://benu.hu")
    assert data["active_ingredient_raw"] is None

def test_ingredients_allergens_tartalmaz_source():
    html="""
    <html><head><title>Movex teszt</title></head><body>
    <product-info>
      <h1>Movex 1500 mg filmtabletta 60 db</h1>
      <div class="price__container">Internetes ár 8 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>
        Termékinformáció
        Összetevők, allergének 1500 mg glükózamin-szulfátot tartalmaz
        (1884 mg glükózamin-szulfát-nátrium-klorid formájában) filmtablettánként.
        EAN: 5999999999999
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/movex-teszt","https://benu.hu")
    assert data["active_ingredient_raw"].startswith("1500 mg glükózamin-szulfátot tartalmaz")
    assert data["active_ingredient_source"]=="product_information_osszetevok_tartalmaz"
    assert data["ingredient_names"]==["glükózamin-szulfát"]

def test_explicit_active_sentence_beats_later_excipients_list():
    html="""
    <html><head><title>Meboflur teszt</title></head><body>
    <product-info>
      <h1>Meboflur cseresznye és menta ízű 16,2 mg/ml oldatos spray 15ml</h1>
      <div class="price__container">Internetes ár 4 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>
        Betegtájékoztató: Információk a felhasználó számára
        Mit tartalmaz a Meboflur?
        A készítmény hatóanyaga a flurbiprofén.
        8,75 mg flurbiprofént tartalmaz adagonként (3 befújás).
        Egyéb összetevők: betadex, hidroxipropilbetadex.
        EAN: 4011548045206
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/meboflur-teszt","https://benu.hu")
    assert data["active_ingredient_source"]=="leaflet_mit_tartalmaz"
    assert data["ingredient_names"]==["flurbiprofén"]

def test_explicit_single_active_beats_later_combination_excipients():
    html="""
    <html><head><title>Canesten Kombi teszt</title></head><body>
    <product-info>
      <h1>Canesten Kombi 200 mg hüvelytabletta és krém 3x200mg+20g</h1>
      <div class="price__container">Internetes ár 6 599 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>
        Betegtájékoztató
        Mit tartalmaz a Canesten Kombi 200 mg hüvelytabletta és krém?
        A készítmény hatóanyaga a klotrimazol.
        200 mg mikronizált klotrimazolt tartalmaz hüvelytablettánként.
        10 mg klotrimazolt tartalmaz 1 g krémben.
        Egyéb összetevők: Canesten 200 mg hüvelytabletta hipromellóz, vízmentes kolloid szilícium-dioxid.
        EAN: 5999999999999
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/canesten-kombi-teszt","https://benu.hu")
    assert data["active_ingredient_source"]=="leaflet_mit_tartalmaz"
    assert data["ingredient_names"]==["klotrimazol"]

def test_ingredients_allergens_tartalma_dry_extracts():
    html="""
    <html><head><title>Remifemin teszt</title></head><body>
    <product-info>
      <h1>Remifemin Plus tabletta 120 db</h1>
      <div class="price__container">Internetes ár 9 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>
        Termékinformáció
        Összetevők, allergének 1 db filmtabletta tartalma:,
        3,75 mg rövidágú poloskavész gyökértörzs száraz kivonat (6-11:1),
        ami 22,5-41,25 mg rövidágú poloskavész gyökértörzsnek felel meg,
        70 mg közönséges orbáncfű virágos hajtás száraz kivonat.
        EAN: 5999999999999
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/remifemin-plus-teszt","https://benu.hu")
    assert data["active_ingredient_source"]=="product_information_osszetevok_tartalma"
    assert data["ingredient_names"]==[
        "rövidágú poloskavész gyökértörzs száraz kivonat",
        "közönséges orbáncfű virágos hajtás száraz kivonat",
    ]

def test_liquid_extract_product_information_is_not_truncated():
    html="""
    <html><head><title>Iberogast teszt</title></head><body>
    <product-info>
      <h1>Iberogast Hexaherba belsőleges oldatos cseppek 100ml</h1>
      <div class="price__container">Internetes ár 9 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>
        Termékinformáció
        Összetevők, allergének 1 ml folyadék az alábbiak folyékony kivonatait tartalmazza:,
        Keserű tatárvirág [Iberis amara] - friss teljes növény 0,15 ml: kivonószer: etanol 50% (V/V),
        Kamillavirágzat 0,30 ml, Köménytermés 0,20 ml, Orvosi citromfű levél 0,15 ml,
        Borsmenta levél 0,10 ml, Igazi édesgyökér 0,10 ml,
        Kivonószer az utóbbi 5 gyógynövény esetében: etanol 30% (V/V),
        A készítmény 31% V/V etanolt tartalmaz
        EAN: 5999999999999
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/iberogast-teszt","https://benu.hu")
    assert data["active_ingredient_source"]=="product_information_osszetevok_folyekony_kivonatok"
    assert data["ingredient_names"]==[
        "Keserű tatárvirág",
        "Kamillavirágzat",
        "Köménytermés",
        "Orvosi citromfű levél",
        "Borsmenta levél",
        "Igazi édesgyökér",
    ]

def test_ingredients_allergens_tablettamag_first_component():
    html="""
    <html><head><title>Venotec teszt</title></head><body>
    <product-info>
      <h1>Venotec forte 1000 mg filmtabletta 30 db</h1>
      <div class="price__container">Internetes ár 12 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>
        Termékinformáció
        Összetevők, allergének Tablettamag: mikronizált diozmin,
        mikrokristályos cellulóz, zselatin. EAN: 5999999999999
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/venotec-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="mikronizált diozmin"
    assert data["active_ingredient_source"]=="product_information_osszetevok_tablettamag_first"
    assert data["ingredient_names"]==["mikronizált diozmin"]

def test_leaflet_title_active_source():
    html="""
    <html><head><title>Nicorette teszt</title></head><body>
    <product-info>
      <h1>Nicorette Mint 4 mg szopogató tabletta mentolos 80 db</h1>
      <div class="price__container">Internetes ár 9 999 Ft</div>
      <div class="product-badges"><div class="badge">Vény nélkül kapható gyógyszer</div></div>
      <div>
        Betegtájékoztató: Információk a felhasználó számára
        Nicorette Mint 4 mg mentolos préselt szopogató tabletta nikotin
        Mielőtt elkezdi szedni ezt a gyógyszert, olvassa el figyelmesen.
        EAN: 5999999999999
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/nicorette-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="nikotin"
    assert data["active_ingredient_source"]=="leaflet_leaflet_title_active"
    assert data["ingredient_names"]==["nikotin"]

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
    assert split_ingredient_names(
        "Egy darab kemény kapszulában: 80 mg tisztított, beállított "
        "páfrányfenyőlevél (Ginkgo biloba L., folium) száraz kivonat "
        "(gyógynövény-kivonat arány: 35-67:1) amelynek ginkgo flavon glikozid tartalma: 17,6-21,6 mg."
    ) == ["páfrányfenyőlevél száraz kivonat"]
    assert split_ingredient_names(
        "1 ml (~0,918 g) belsőleges folyadék tartalma: 1 ml etanolos kivonat "
        "(1:9,75) a következő növényekből: gyömbér gyökértörzs "
        "(zingiber officinale roscoe, rhizoma), igazi édesgyökér "
        "(glycirrhiza glabra L. radix), orvosi citromfű levél "
        "(melissa officinalis L., folium), zöld tealevél "
        "(camellia sinensis L., folium, jávai kurkuma gyökértörzs "
        "(curcuma xanthorrhiza roxb., rhizoma) 8:4:4:3:1 arányban."
    ) == [
        "gyömbér gyökértörzs",
        "igazi édesgyökér",
        "orvosi citromfű levél",
        "zöld tealevél",
        "jávai kurkuma gyökértörzs",
    ]
    assert split_ingredient_names(
        "2 milliárd többszörösen antibiotikum-rezisztens "
        "Bacillus clausii spórát tartalmaz 5 ml-es tartályonként"
    ) == ["Bacillus clausii"]
    assert split_ingredient_names(
        "100 mg ibuprofént tartalmaz rágókapszulánként"
    ) == ["ibuprofén"]
    assert split_ingredient_names(
        "tablettánként: Tárnicsgyökér porított (Gentiana lutea L., radix) 12,0 mg "
        "Fekete bodza virág porított (Sambucus nigra L., flos) 36,0 mg "
        "Kankalin virág porított (Primula veris L., flos) 36,0 mg"
    ) == ["Tárnicsgyökér","Fekete bodza virág","Kankalin virág"]
    assert split_ingredient_names(
        "Átlátszó vagy sárgás színű, kerek, 19±1 mm átmérőjű szopogató tabletták "
        "PVC/PVDC//Al buborékcsomagolásban és dobozban."
    ) == []
    assert split_ingredient_names(
        "100 ml oldat 56,15 g etanolos növényi kivonatot tartalmaz az alábbi "
        "növények megadott arányú felhasználásával: 600 mg citvor gyökértörzs "
        "(Curcuma zedoaria Christ., rhizoma), 500 mg virágos kőris "
        "(Fraxinus ornus L., manna canellata), 250 mg mirha gyanta "
        "(Commiphora molmol Engler, resina), 0,20 gyömbér gyökértörzs "
        "(Zingiber officinale Rosc., rhizoma)"
    ) == ["citvor gyökértörzs","virágos kőris","mirha gyanta","gyömbér gyökértörzs"]
    assert split_ingredient_names(
        "1 ml folyadék az alábbiak folyékony kivonatait tartalmazza:, "
        "Keserű tatárvirág [Iberis amara] - friss teljes növény 0,15 ml: "
        "kivonószer: etanol 50% (V/V), Kamillavirágzat 0,30 ml, "
        "Köménytermés 0,20 ml, Orvosi citromfű levél 0,15 ml"
    ) == ["Keserű tatárvirág","Kamillavirágzat","Köménytermés","Orvosi citromfű levél"]
    assert split_ingredient_names(
        "1 ml (18 csepp) vizes oldatban: vas (vas-szulfát-heptahidrát formájában) 2,00 mg "
        "cink (cink-szulfát-heptahidrát formájában) 1,14 mg "
        "magnézium (magnézium-szulfát-heptahidrát formájában) 0,40 mg "
        "mangán (mangán-szulfát-monohidrát formájában) 0,31 mg "
        "réz (réz-szulfát-pentahidrát formájában) 0,25 mg"
    ) == ["vas","cink","magnézium","mangán","réz"]
    assert split_ingredient_names(
        "Minden szopogató tabletta 0,6 mg amilmetakrezolt és "
        "1,2 mg 2,4‑diklór‑benzil_alkoholt tartalmaz"
    ) == ["amilmetakrezol","diklór-benzil-alkohol"]
    assert split_ingredient_names(
        "Egy szopogató tabletta 0,6 mg amilmetakrezolt, ill. "
        "1,2 mg 2,4‑diklór‑benzil‑alkoholt tartalmaz"
    ) == ["amilmetakrezol","diklór-benzil-alkohol"]
    assert split_ingredient_names(
        "Minden szopogató tabletta 0,6 mg amilmetakrezolt, "
        "1,2 mg 2,4‑diklór‑benzil‑alkoholt és 8, mg levomentolt tartalmaz"
    ) == ["amilmetakrezol","diklór-benzil-alkohol","levomentol"]
    assert split_ingredient_names(
        "Egy szopogató tabletta 0,6 mg amilmetakrezolt, ill. "
        "1,2 mg 2,4‑diklór‑benzil‑alkoholt, 33,5 mg aszkorbinsavat és "
        "74,9 mg nátrium-aszkorbátot atrtalmaz"
    ) == ["amilmetakrezol","diklór-benzil-alkohol","aszkorbinsav","nátrium-aszkorbát"]
    assert split_ingredient_names(
        "3,00 mg benzidamin-hidrokloridot tartalmaz szopogató"
    ) == ["benzidamin-hidroklorid"]
    assert split_ingredient_names(
        "1,5 mg benzidamin-hidrokloridot tartalmaz 1 ml "
        "szájnyálkahártyán alkalmazott spray-ben"
    ) == ["benzidamin-hidroklorid"]
    assert split_ingredient_names(
        "3 mg ambroxol-hidroklorid 1 ml szirupban"
    ) == ["ambroxol-hidroklorid"]
    assert split_ingredient_names(
        "muskátligyökér (Pelargonium sidoides radix) szárított folyékony "
        "kivonat (1:8-10) (EPs 7630) Kivonószer: 11 m/m% etanol."
    ) == ["muskátligyökér folyékony kivonat"]
    assert split_ingredient_names(
        "50 mg dexpantenol és 5 mg klórhexidin-dihidroklorid 1 g krémben"
    ) == ["dexpantenol","klórhexidin-dihidroklorid"]
    assert split_ingredient_names(
        "150 mg kamilla tinktúrát, 3,4 mg lidokain-hidroklorid-monohidrátot "
        "és 3,2 mg makrogol-lauril-étert tartalmaz 1 g gélben"
    ) == ["kamilla tinktúra","lidokain-hidroklorid-monohidrát","makrogol-lauril-éter"]
    assert split_ingredient_names(
        "100 mg povidon-jód 1 g, vízzel lemosható kenőcsben, azaz 2 g "
        "povidon-jódot tartalmaz 20 g vízzel lemosható kenőcsben"
    ) == ["povidon-jód"]
    assert split_ingredient_names(
        "10 mg cetirizin-dihidroklorid préselt szopogató"
    ) == ["cetirizin-dihidroklorid"]
    assert split_ingredient_names(
        "2 mg nikotinnak megfelelő mennyiségű nikotin-rezinátot "
        "tartalmaz préselt szopogató"
    ) == ["nikotin-rezinát"]
    assert split_ingredient_names(
        "1 szopogató tabletta 0,5 mg tirotricint, 1 mg "
        "benzalkónium-kloridot és 1,5 mg benzokaint tartalmaz"
    ) == ["tirotricin","benzalkónium-klorid","benzokain"]
    assert split_ingredient_names(
        "500 mg nátrium-alginát, 267 mg nátrium-hidrogén-karbonát és "
        "160 mg kalcium-karbonát 10 ml szuszpenzióban"
    ) == ["nátrium-alginát","nátrium-hidrogén-karbonát","kalcium-karbonát"]
    assert split_ingredient_names(
        "500 mg tisztított és mikronizált flavonoid frakciót tartalmaz "
        "(450 mg diozmin és 50 mg heszperidinben kifejezett egyéb flavonoid) "
        "filmtablettánként"
    ) == ["mikronizált flavonoid frakció"]
    assert split_ingredient_names(
        "680 mg kalcium-karbonát és 80 mg magnézium-karbonát rágótablettánként"
    ) == ["kalcium-karbonát","magnézium-karbonát"]
    assert split_ingredient_names(
        "kalcium- és magnézium-karbonát"
    ) == ["kalcium-karbonát","magnézium-karbonát"]
    assert split_ingredient_names(
        "Sötétbarna színű, tiszta vagy gyengén opálos, jellegzetes alkohol szagú "
        "belsőleges oldat. 20 ml, 50 ml vagy 100 ml oldat."
    ) == []
    assert split_ingredient_names("két") == []
    assert split_ingredient_names("nevű") == []
    assert split_ingredient_names(
        "Vitaminok:, A-vitamin: 3333 NE, B₁-vitamin: 20 mg, "
        "C-vitamin: 150 mg, Ásványi anyagok és nyomelemek:, "
        "Kalcium: 51,3 mg, Molibdén: 0,1 mg Nem szabad szedni a "
        "készítmény alkotórészeivel szembeni túlérzékenység, magas "
        "kalcium vérszint esetén."
    ) == ["A-vitamin","B₁-vitamin","C-vitamin","Kalcium","Molibdén"]

def test_active_ingredient_skips_count_words_and_uses_real_multi_active_text():
    text="""
    Besorolás típusa: vény nélkül kapható gyógyszer
    Ez a gyógyszer két hatóanyagot tartalmaz. Ezek az ibuprofén és a paracetamol.
    6. A csomagolás tartalma és egyéb információk
    Mit tartalmaz a Nurofen Duo?
    A készítmény hatóanyagai az ibuprofén és a paracetamol.
    Egyéb összetevők: mikrokristályos cellulóz.
    """
    metadata=extract_product_metadata(text,product_name="Nurofen Duo 200 mg/500 mg filmtabletta")
    assert metadata["active_ingredient_raw"]=="ibuprofén és a paracetamol"
    assert split_ingredient_names(metadata["active_ingredient_raw"])==["ibuprofén","paracetamol"]

def test_active_ingredient_colon_multi_active_list():
    text="""
    Besorolás típusa: vény nélkül kapható gyógyszer
    A Zovirax Duo két hatóanyagot tartalmaz: aciklovirt és hidrokortizont.
    Az aciklovir vírusellenes hatóanyag.
    """
    metadata=extract_product_metadata(text,product_name="Zovirax Duo krém")
    assert metadata["active_ingredient_raw"]=="aciklovirt és hidrokortizont"
    assert split_ingredient_names(metadata["active_ingredient_raw"])==["aciklovir","hidrokortizon"]

def test_active_ingredient_skips_colon_explanation_and_uses_composition_block():
    text="""
    Besorolás típusa: vény nélkül kapható gyógyszer
    A Deep Relief két hatóanyagot tartalmaz: Az ibuprofén a nem-szteroid
    gyulladáscsökkentő gyógyszerek csoportjába tartozó hatékony fájdalomcsillapító.
    A levomentol nyugtató hatású.
    Mit tartalmaz a Deep Relief?
    A készítmény hatóanyagai: 0,05 g ibuprofén és 0,03 g levomentol 1 g gélben.
    Egyéb összetevők: propilénglikol.
    """
    metadata=extract_product_metadata(text,product_name="Deep Relief gél 50g")
    assert metadata["active_ingredient_raw"]=="0,05 g ibuprofén és 0,03 g levomentol 1 g gélben"
    assert split_ingredient_names(metadata["active_ingredient_raw"])==["ibuprofén","levomentol"]

def test_active_ingredient_rejects_noise_and_falls_back_to_leaflet_composition():
    text="""
    Besorolás típusa: vény nélkül kapható gyógyszer
    Amennyiben csak az egyik jelentkezik, olyan gyógyszert válasszon, mely csak az egyik hatóanyagot tartalmazza.
    Mit tartalmaz az Aspirin Complex granulátum?
    Hatóanyagként (500 mg) acetilszalicilsavat és (30 mg) pszeudoefedrin-hidrokloridot tartalmaz tasakonként.
    Egyéb összetevők: citromsav.
    """
    metadata=extract_product_metadata(text,product_name="Aspirin Complex italpor 20 db")
    assert metadata["active_ingredient_raw"]=="acetilszalicilsavat és (30 mg) pszeudoefedrin-hidrokloridot"
    assert split_ingredient_names(metadata["active_ingredient_raw"])==["acetilszalicilsav","pszeudoefedrin-hidroklorid"]

def test_active_ingredient_plain_hatoanyaga_marker():
    text="""
    Besorolás típusa: vény nélkül kapható gyógyszer
    Mit tartalmaz a Jodid 100 mikrogramm tabletta - Hatóanyaga a kálium-jodid.
    Tablettánként 100 mikrogramm jóddal egyenértékű kálium-jodidot tartalmaz.
    Segédanyagok: magnézium-sztearát.
    """
    metadata=extract_product_metadata(text,product_name="Jodid 100 mikrogramm tabletta")
    assert metadata["active_ingredient_raw"]=="kálium-jodid"

def test_info_description():
    text="Termékinformáció Ez a termékinformáció. Termékleírás Ez a részletes leírás. Betegtájékoztató"
    i,d=extract_product_info(text)
    assert i=="Ez a termékinformáció."
    assert d=="Ez a részletes leírás."

def test_ingredients():
    assert split_ingredient_names("ibuprofen + pseudoefedrin") == ["ibuprofen","pseudoefedrin"]

def test_missing_ean_is_warning_but_not_incomplete():
    data={
        "price_huf":1999,
        "sku":"123456",
        "ean":None,
        "classification":"NON_MEDICINE",
        "classification_source":"metadata",
        "active_ingredient_raw":None,
        "images":["https://example.test/image.jpg"],
        "raw_text":"x"*6000,
    }
    incomplete,warnings=assess_quality(data)
    assert incomplete is False
    assert "missing_ean" in warnings

def test_otc_missing_active_ingredient_is_incomplete():
    data={
        "price_huf":1999,
        "sku":"123456",
        "ean":"5999999999999",
        "classification":"OTC",
        "classification_source":"metadata",
        "active_ingredient_raw":None,
        "images":["https://example.test/image.jpg"],
        "raw_text":"x"*6000,
    }
    incomplete,warnings=assess_quality(data)
    assert incomplete is True
    assert "missing_active_ingredient_for_otc" in warnings

def test_structured_active_ingredient_stops_before_contraindication_text():
    html="""
    <html><head><title>Saridon teszt</title></head><body>
    <product-info>
      <h1>Saridon fájdalomcsillapító tabletta 10 db</h1>
      <div class="price__container">Internetes ár 2 099 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Besorolás típusa: vény nélkül kapható gyógyszer
        Hatóanyag: 250 mg paracetamolt, 150 mg propifenazont, illetve
        50 mg koffeint tartalmaz tablettánként
        A készítmény nem adható bármely összetevőjével szembeni túlérzékenység esetén.
        EAN: 5999528941405
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/saridon-teszt","https://benu.hu")
    assert data["active_ingredient_raw"]=="250 mg paracetamolt, 150 mg propifenazont, illetve 50 mg koffeint tartalmaz"
    assert data["ingredient_names"]==["paracetamol","propifenazon","koffein"]

def test_mit_tartalmaz_ignores_packaging_content_question():
    html="""
    <html><head><title>Neo Citran Max teszt</title></head><body>
    <product-info>
      <h1>Neo Citran Max köptetővel por belsőleges oldathoz 10 db</h1>
      <div class="price__container">Internetes ár 6 999 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Betegtájékoztató
        Mit tartalmaz a Neo Citran Max köptetővel?
        A készítmény hatóanyagai: paracetamol, fenilefrin-hidroklorid és gvajfenezin.
        Tasakonként 1000 mg paracetamolt, 12,2 mg fenilefrin-hidrokloridot és 200 mg gvajfenezint tartalmaz.
        Egyéb összetevők: szacharóz.
        Milyen a Neo Citran Max köptetővel külleme és mit tartalmaz a csomagolás?
        Csaknem fehér, szabadon folyó por.
        EAN: 5999518585046
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/neo-citran-max-teszt","https://benu.hu")
    assert data["active_ingredient_source"]=="leaflet_mit_tartalmaz"
    assert data["ingredient_names"]==["paracetamol","fenilefrin-hidroklorid","gvajfenezin"]

def test_product_variant_line_is_only_late_fallback():
    html="""
    <html><head><title>Canesten teszt</title></head><body>
    <product-info>
      <h1>Canesten Kombi Uno 500 mg lágy hüvelykapszula és krém 1 db</h1>
      <div class="price__container">Internetes ár 6 799 Ft</div>
      <div class="product-badges">
        <div class="badge">Vény nélkül kapható gyógyszer</div>
      </div>
      <div>
        Betegtájékoztató
        Mit tartalmaz a Canesten Kombi Uno 500 mg lágy hüvelykapszula és krém?
        A készítmény hatóanyaga a klotrimazol.
        Egy Canesten Uno 500 mg lágy hüvelykapszula 500 mg mikronizált klotrimazolt tartalmaz.
        Egy gramm Canesten 10 mg/g krém 10 mg klotrimazolt tartalmaz.
        Egyéb összetevők:
        Canesten Uno 500 mg lágy hüvelykapszula: Fehér vazelin, folyékony paraffin.
        EAN: 5999528942174
      </div>
    </product-info>
    </body></html>
    """
    data=parse_product(html,"https://benu.hu/products/canesten-kombi-uno-teszt","https://benu.hu")
    assert data["active_ingredient_source"]=="leaflet_mit_tartalmaz"
    assert data["ingredient_names"]==["klotrimazol"]

def test_special_active_ingredient_names_are_not_split_on_noise():
    assert split_ingredient_names(
        "0,66 milliárd Vakcina E. Coli (steril) kúponként"
    )==["elölt E. coli baktériumkultúra"]
    assert split_ingredient_names(
        "omega-3-sav-etilészterek: Egy kapszula 1000 mg omega‑3‑sav‑etilészter 90-et tartalmaz"
    )==["omega-3-sav-etilészterek"]
    assert split_ingredient_names(
        "120,0 mg Ginkgo biloba L., folium (páfrányfenyőlevél) száraz, tisztított, beállított kivonata"
    )==["páfrányfenyőlevél száraz kivonat"]

def test_liquid_extract_ingredients_ignore_extraction_solvent():
    assert split_ingredient_names(
        "5 ml oldat tartalma: 770 mg kerti és spanyol kakukkfű levél és virág "
        "(Thymus vulgaris L., vagy Thymus zygis L., herba) folyékony kivonat; "
        "kivonószer: etanol; 660 mg orvosi ziliz gyökér "
        "(Althaea officinalis L., radix) folyékony kivonat, kivonószer: víz"
    )==[
        "kerti és spanyol kakukkfű levél és virág folyékony kivonat",
        "orvosi ziliz gyökér folyékony kivonat",
    ]
