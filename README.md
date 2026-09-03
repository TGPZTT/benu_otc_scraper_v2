# BENU OTC Scraper v2

Teljesebb BENU webshop scraper, amely:

- felderíti a BENU termék URL-eket sitemapből
- fallbackként végiglapozza az "Összes termék" kollekciót
- minden felderített termékoldalt feldolgoz
- **nem a teljes oldal szövegéből dönti el az OTC státuszt**
- a termék saját "Besorolás típusa" mezőjét használja elsődlegesen
- fallbackként a fő termékblokk saját badge-eit, majd a termékhez illesztett analytics `item_type` mezőt használja
- OTC / nem OTC / ismeretlen besorolást tárol
- kinyeri a listaárat, az akciós árat és az egységárat
- kinyeri az elmúlt 30 nap legalacsonyabb árát
- kinyeri a márkát, cikkszámot, EAN-t, forgalmazót
- kinyeri és normalizálja a "Hatóanyag" mezőt
- kinyeri a termékinformációt és termékleírást
- megőrzi a betegtájékoztató szövegét, ha elérhető
- kinyeri a gyógyszerformát, hatáserősséget és kiszerelést
- kinyeri a breadcrumb/kategória-hierarchiát
- kinyeri a termék kép URL-jeit
- kinyeri a főbb elérhetőségi státuszokat
- megőrzi a teljes nyers oldal-szöveget
- opcionálisan gzip-pelve archiválja a teljes HTML-t
- árhistorikát vezet
- minden scrape futást naplóz
- hibás URL-eket külön tárol
- SQLite adatbázist használ
- CSV és JSON exportot készít

## Fontos változás v1-hez képest

A v1 egyik hibája az volt, hogy a teljes oldalból kereste a "Vény nélkül kapható gyógyszer" kifejezést. Ez hibás volt, mert a BENU footerében és szállítási információiban is szerepel ez a szöveg.

A v2 kizárólag a termékoldal saját:

    Besorolás típusa: ...

mezőjét tekinti elsődleges forrásnak. Ha ez hiányzik, a parser a fő termékblokk (`product-info` / `#product-infos`) saját badge-eiből következtethet, például a `Vény nélkül kapható gyógyszer` termékbadge alapján.

Ha badge alapján sincs megbízható besorolás, a parser a termék saját analytics JSON blokkjából választja ki a név/SKU alapján illeszkedő itemet, és annak `item_type` mezőjét használhatja fallbackként. Ez például az `OTC`, `ETR`, `GYSE` és `Egyéb` BENU-kódokat kezeli. Ajánlott termékek analytics adata nem írhatja felül az aktuális terméket, mert a parser az aktuális név/SKU alapján pontozza az itemeket.

A teljes oldalszöveg, footer, tooltip, szállítási leírás és ajánló termékek szövege nem számít besorolási forrásnak.

A `Homeopátiás készítmények` kategória külön üzleti szabályként mindig `NON_MEDICINE` besorolást kap, akkor is, ha a BENU analytics adata `OTC` item type-ot ad. Ezek a termékek tárolva maradnak, de nem kerülhetnek az OTC exportba és a későbbi publikus OTC felületre.

A vitamin/multivitamin kategóriás termékek csak akkor maradhatnak publikus OTC rekordok, ha a termék saját szövegében/betegtájékoztatójában egyértelmű gyógyszer-jel található, például az, hogy a készítmény orvosi rendelvény nélkül kapható gyógyszer. Ha ilyen jel nincs, a parser `NON_MEDICINE` besorolást ad `vitamin_category_without_medicine_signal` forrással.

Ha a felső termékmeta csak túl általános hatóanyagértéket ad (például egy multivitamin esetén csak `C-vitamin`), de a betegtájékoztatóban részletes `Mit tartalmaz...` / `A készítmény hatóanyagai...` lista szerepel, a parser a részletesebb listát részesíti előnyben. Az ingredient export közben levágja a segédanyagokat, ellenjavallati szövegeket és gyakori sóforma-részleteket.

Ezért az OTC státusz:

    OTC
    PRESCRIPTION
    NON_MEDICINE
    UNKNOWN

érték lehet.

A nem gyógyszer termékeket is eltároljuk, de az OTC export és a későbbi webapp csak az OTC rekordokat használhatja.

## Ármezők

Az összehasonlító célja miatt a `price_huf` mező a rendes/listaárat jelenti. Ha a BENU akciós árat is mutat, az külön a `sale_price_huf` mezőbe kerül, az akció előtti ár pedig az `original_price_huf` mezőbe. Így a későbbi "legolcsóbb azonos hatóanyagból" logika nem ideiglenes promóciókra épül.

## Telepítés Windows / PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Ha a PowerShell tiltja a `.ps1` futtatását:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

A tesztet nem is kell `.ps1`-ből futtatni.

## 20 termékes teszt

```powershell
$env:MAX_PRODUCTS="20"
$env:FORCE_RESCRAPE="1"
python main.py
```

Vagy közvetlenül:

```powershell
python main.py --fresh --limit 20
```

## Teljes futtatás

```powershell
$env:MAX_PRODUCTS="0"
$env:FORCE_RESCRAPE="0"
python main.py
```

Vagy:

```powershell
python main.py --all
```

## Tiszta új adatbázis

A korábbi v1 adatbázisod hibás OTC rekordokat tartalmazhat. A v2 előtt ajánlott:

```powershell
python main.py --fresh --limit 20
```

Ez a meglévő `data/benu_otc.db` fájlt dátumozott `.bak` fájlba menti, majd új adatbázist készít.

Teljesen friss adatbázissal:

```powershell
python main.py --fresh --all
```

## Export

```powershell
python export.py
```

Létrejön:

```text
data/exports/products.csv
data/exports/otc_products.csv
data/exports/products.json
data/exports/otc_products.json
data/exports/ingredients.csv
```

## Adatminőségi riport

```powershell
python scripts/analyze_quality.py
```

Ez nem indít scrapinget, csak a meglévő `data/benu_otc.db` és `data/exports` fájlokat olvassa. Összesíti a besorolásokat, forrásokat, hiányzó mezőket, incomplete rekordokat, gyanús árakat és OTC false positive jelölteket.

## Hibakezelés

A `classification` mező adatbázis-szinten kötelező, de a scraper mindig `UNKNOWN` értéket használ, ha a BENU oldalon nem található megbízható besorolás. Így egyetlen atipikus oldal sem okoz `NOT NULL constraint failed` hibát.

A futás végén az összesítő tartalmazza az `incomplete` darabszámot is. Ez olyan oldalt jelent, ahol a név megvan, de legalább egy kritikus mező hiányzik vagy a parser rövid/gyanús oldalt kapott. A hiányossági jelzések a `parse_warnings` exportmezőben is látszanak. Az ilyen oldalak HTML-je `data/incomplete_html/` alá is bekerül, a tényleges feldolgozási kivételek HTML-je pedig `data/failed_html/` alatt kerül mentésre.

## EAN források

Az EAN elsődlegesen a termék saját `EAN` mezőjéből vagy JSON-LD `gtin` mezőjéből jön. Fallbackként a parser a Shopify termék-variáns `barcode` mezőjét is használhatja, de csak akkor, ha a variáns név/SKU alapján az aktuális termékhez illeszkedik. Analytics `product_id` vagy `item_id` értékből nem készít EAN-t.

## Adatbázis

```text
data/benu_otc.db
```

Fő táblák:

- `products`
- `ingredients`
- `product_ingredients`
- `price_history`
- `scrape_runs`
- `scrape_errors`

A `products` táblában minden felderített BENU-termék szerepel. Az OTC szűrés az `classification` mezőn történik. A `classification_source` mutatja, hogy a besorolás `metadata`, `product_badge`, `analytics_item_type`, `homeopathic_category`, `vitamin_category_without_medicine_signal` vagy `unknown` forrásból jött-e.

## Raw HTML

Alapból:

```text
SAVE_RAW_HTML=1
```

A HTML gzip formában kerül ide:

```text
data/raw_html/
```

Ha nem akarod megtartani:

```text
SAVE_RAW_HTML=0
```

## Megjegyzés a "minden adat" kifejezéshez

A scraper a BENU termékoldalán található, programból megbízhatóan kinyerhető adatokat célozza. A parser-hibák és hiányos/atipikus oldalak nem állítják le a futást: a besorolás hiánya `UNKNOWN`, a hibás válaszok HTML-je pedig a `data/failed_html/` könyvtárba kerül diagnosztikához. A teljes HTML és a teljes látható szöveg is archiválható, ezért később új parserrel további mezők is kinyerhetők.

A BENU oldal szerkezete változhat. Ha a BENU módosítja a HTML-t, a `scraper/parser.py` az a fájl, amelyet elsősorban módosítani kell.

## Jogi / üzemeltetési megjegyzés

A futtatás előtt ellenőrizd a BENU aktuális robots.txt-jét, felhasználási feltételeit és az alkalmazandó jogszabályokat. A scraper szándékosan lassított, szekvenciális kéréseket használ, és alapból tiszteletben tartja a robots.txt tiltásait.
