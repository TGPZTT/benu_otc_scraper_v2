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

def test_info_description():
    text="Termékinformáció Ez a termékinformáció. Termékleírás Ez a részletes leírás. Betegtájékoztató"
    i,d=extract_product_info(text)
    assert i=="Ez a termékinformáció."
    assert d=="Ez a részletes leírás."

def test_ingredients():
    assert split_ingredient_names("ibuprofen + pseudoefedrin") == ["ibuprofen","pseudoefedrin"]
