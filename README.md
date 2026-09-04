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

Ha a felső termékmeta csak túl általános hatóanyagértéket ad (például egy multivitamin esetén csak `C-vitamin`), de a betegtájékoztatóban vagy használati utasításban részletes `Mit tartalmaz...` / `A készítmény hatóanyagai...` lista szerepel, a parser a részletesebb listát részesíti előnyben. Az ingredient export közben levágja a segédanyagokat, ellenjavallati szövegeket és gyakori sóforma-részleteket.

A hatóanyag mellé az `active_ingredient_source` mező is mentésre kerül. Ez jelzi, hogy a találat például `structured_hatany`, `leaflet_mit_tartalmaz`, `usage_instruction_mit_tartalmaz`, `product_information_tartalmu_sentence`, `description_tartalmu_sentence` vagy `json_ld` forrásból jött.

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

Ez nem indít scrapinget, csak a meglévő `data/benu_otc.db`, `data/exports` és HTML cache mappákat olvassa. Összesíti a besorolásokat, forrásokat, hiányzó mezőket, incomplete rekordokat, gyanús árakat, HTML cache darabszámokat, quality gate státuszokat és OTC false positive jelölteket.

## Cache-ből újraparszolás

Ha a parseren javítasz, nem kell újra letölteni a BENU oldalait. A mentett HTML cache-ből újra lehet építeni a DB termékmezőit és az ingredient kapcsolatokat:

```powershell
python scripts/reparse_cached_html.py --progress-every 250 --sync-incomplete-html
python export.py
python scripts/analyze_quality.py
```

A `--sync-incomplete-html` újragenerálja a `data/incomplete_html/` mappát az aktuális minőségi szabályok szerint, így nem maradnak benne korábbi parserverzióból származó téves incomplete HTML-ek.

## Kurált adatpótlás

Néhány BENU termékoldal nem tartalmaz saját hatóanyagblokkot, vagy a mentett HTML-ben félrevezető betegtájékoztató-részlet szerepel. Ezeket nem parser-kivétellel, hanem auditálható referenciafájlból pótoljuk:

```powershell
python scripts/apply_curated_enrichment.py --dry-run
python scripts/apply_curated_enrichment.py --sync-incomplete-html
```

A forrásfájl:

```text
reference/curated_product_enrichment.json
```

Ez URL alapján tölti fel a kurált `active_ingredient_raw`, `active_ingredient_source`, `registration_number` és ingredient kapcsolatokat, majd eltávolítja a megoldott `missing_active_ingredient_for_otc` figyelmeztetést. A dry-run nem írja át a DB-t.

## Normalizált összehasonlító katalógus

A webapp nem közvetlenül a nyers scraper exportból dolgozik, hanem egy normalizált OTC katalógusból:

```powershell
python scripts/build_normalized_catalog.py
```

Létrejön:

```text
data/exports/normalized_otc_products.csv
data/exports/normalized_otc_products.json
data/exports/comparison_groups.csv
data/exports/comparison_groups.json
data/exports/grouped_catalog.json
```

A csoportosítás kulcsa: normalizált hatóanyag-kombináció + erősség + gyógyszerforma + összehasonlítási egység. A listaárból vagy BENU egységárból számolt egységár alapján jelöli a legolcsóbb terméket az azonos csoporton belül.

## Lokális webapp

Az első összehasonlító felület a `webapp/` mappában van. Nem igényel Node/npm telepítést, a meglévő exportot olvassa:

```text
data/exports/grouped_catalog.json
```

Indítás a projekt gyökeréből:

```powershell
.\.venv\Scripts\python.exe -m http.server 8000
```

Megnyitás böngészőben:

```text
http://localhost:8000/webapp/
```

Ha foglalt a 8000-es port, használj másikat, például:

```powershell
.\.venv\Scripts\python.exe -m http.server 8010
```

## Adatlezárás scrape nélkül

Ha már megvan a teljes `data/raw_html/` cache és nem akarsz új BENU letöltést indítani, ezt a sorrendet futtasd:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\reparse_cached_html.py --progress-every 500 --commit-every 500 --sync-incomplete-html
.\.venv\Scripts\python.exe scripts\apply_curated_enrichment.py --sync-incomplete-html
.\.venv\Scripts\python.exe export.py
.\.venv\Scripts\python.exe scripts\build_normalized_catalog.py
.\.venv\Scripts\python.exe scripts\build_single_page.py
.\.venv\Scripts\python.exe scripts\analyze_quality.py > data\exports\quality_report.json
Get-Content data\exports\quality_report.json -Raw
```

Ez csak lokális fájlokból dolgozik: meglévő HTML-cache, SQLite DB, exportok és referenciafájl. Nem hívja meg a BENU oldalt.

Future refresh ellenőrzőlista:

- legyen Git checkpoint a futás előtt
- kis mintán futtasd: `python main.py --fresh --limit 50`
- ha tiszta: teljes frissítés csak saját gépen: `python main.py --fresh --all`
- utána cache reparse + kurált adatpótlás + export + quality riport + normalizált katalógus
- elvárt kapuk: `processed == discovered`, `errors == 0`, `failed_html == 0`, `UNKNOWN == 0`, OTC false positive `0`, bad ingredient `0`, OTC ár/SKU hiány `0`
- EAN-hiány maradhat figyelmeztetés, ha a BENU oldalon nincs termék-EAN / JSON-LD `gtin` / illeszkedő Shopify `barcode`

## Hibakezelés

A `classification` mező adatbázis-szinten kötelező, de a scraper mindig `UNKNOWN` értéket használ, ha a BENU oldalon nem található megbízható besorolás. Így egyetlen atipikus oldal sem okoz `NOT NULL constraint failed` hibát.

A futás végén az összesítő tartalmazza az `incomplete` darabszámot is. Ez olyan oldalt jelent, ahol a név megvan, de legalább egy kritikus mező hiányzik vagy a parser rövid/gyanús oldalt kapott. Kritikus hiány az ár, SKU, ismeretlen besorolás, OTC rekordnál hiányzó hatóanyag, illetve a gyanúsan rövid nyers oldal-szöveg. A hiányzó EAN külön figyelmeztetés, de önmagában nem teszi inkompletté a rekordot, mert a BENU több termékoldalon nem ad termék-EAN-t. A hiányossági jelzések a `parse_warnings` exportmezőben is látszanak. Az ilyen oldalak HTML-je `data/incomplete_html/` alá is bekerül, a tényleges feldolgozási kivételek HTML-je pedig `data/failed_html/` alatt kerül mentésre.

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


## Egyfájlos HTML kimenet

```powershell
.\.venv\Scripts\python.exe scripts\build_single_page.py
```

Létrejön:

```text
data/exports/benu_otc.html
```

Ez egyetlen, önmagában megnyitható fájl: az adat be van ágyazva, nincs `fetch`,
nem kell hozzá `http.server`. Duplakattintásra megnyílik, e-mailben elküldhető.
A `webapp/` mappa megmarad a fejlesztéshez, de a megosztható kimenet ez a fájl.

### Miben tér el a `webapp/` logikájától

1. **Egységár újraszámolva.** A BENU saját `unit_price` mezője 34 terméknél
   ellentmond a listaár / kiszerelés hányadosnak. A legdurvább eset a
   `Strepfen 8,75 mg szopogató tabletta 24 db`, ahol a BENU 4 849 Ft/db-ot ír
   202 Ft/db helyett — emiatt a régi csoportosításban a Dorifen 97,5%-kal
   olcsóbbnak látszott, holott a valós különbség kb. 29%. Az oldal mindig a
   listaár / kiszerelés értéket használja, a BENU-ét csak ellenőrzésre, és a
   táblázatban jelöli, ahol a kettő eltér.

2. **Márkafüggő megtakarítás.** A `savings_vs_max_unit_pct` 174 csoportjából
   124-nél ugyanannak a készítménynek a nagy és a kis doboza állt a százalék
   két végén (Octenisept 1000 ml vs 50 ml, Laevolac 1000 ml vs 100 ml). Az nem
   generikus alternatíva. Az oldalon százalék csak akkor jelenik meg, ha a két
   készítmény neve is más; az azonos márka nagyobb doboza külön
   „kiszerelés-tipp".

3. **Kiszerelés a névből.** A `Panactiv 100 mg/5 ml belsőleges szuszpenzió
   100ml` kiszerelése 5 ml-nek olvasódott 100 ml helyett, mert a parser az
   erősség nevezőjét vette kiszerelésnek. Az oldal az erősség-kifejezések
   levágása után újraolvassa a nevet, és eltérés esetén a névből számol.

4. **Félszilárd készítmények erőssége.** A `Dolgit gél 50g` erőssége
   `1 g + 50 mg` formában jött, ami valójában 50 mg/g. A magyar alkalmazási
   előírás így fogalmaz: „1 g krém 50 mg ibuprofént tartalmaz". Az oldal a
   gél / krém / kenőcs formáknál ezt mg/g-ként értelmezi.

5. **Bioekvivalens formák összevonva.** A tabletta, a filmtabletta és a bevont
   tabletta egy blokk. A kapszula külön marad, mert a hatáskezdet más.

6. **Kanonikus erősség-kulcs.** Egyhatóanyagú készítménynél a mg-érték a
   csoportkulcs, így az `1%` és a `10 mg/g` nem esik szét két blokkra.

7. **Épeszűségi korlát.** Ha egy blokkon belül a legolcsóbb és a legdrágább
   egységár között több mint tízszeres a különbség, az oldal nem ír ki
   százalékot — az ilyen szórás azonos erősségen belül adathibát jelez.

### Visszavezetett normalizálási szabályok

Ezek már nem csak az egyfájlos HTML-ben élnek, hanem a normál
`scripts/build_normalized_catalog.py` exportfolyamat részei:

- az egységár elsődlegesen `listaár / kiszerelés`; a BENU `unit_price` mezője
  ellenőrző adatként marad meg
- eltérés esetén a termék `unit_price_mismatch_vs_benu` quality flaget kap
- a kiszerelés a `package_size` mezőből és a terméknévből is olvasódik; az
  erősség nevezője nem írhatja felül a valódi dobozméretet
- félszilárd készítményeknél az `1 g + 50 mg` jellegű erősség `50 mg/g`
  formára normalizálódik
- a csoportokban külön mező jelzi a más készítménynévvel szembeni megtakarítást
  (`savings_vs_other_brand_pct`) és a saját nagyobb kiszerelés előnyét
  (`pack_size_saving_pct`)
- a tabletta, filmtabletta és bevont tabletta összevont forma, a kapszula külön
  marad


## Tudásréteg és a három nézet

A `scripts/build_single_page.py` két kézzel karbantartott referenciafájlt is beolvas.
Egyik sem a scraperből jön, ezért szerkeszthetők és auditálhatók:

```text
reference/ingredient_aliases.json    hatóanyag-kulcs kanonizálás + megjelenítendő nevek
reference/knowledge_base.json        tünet -> hatóanyag ajánlás, indoklással és figyelmeztetéssel
```

### ingredient_aliases.json

A parser néha a mondat körüli szavakat is bevonja a kulcsba
(`ibuprofen-vegbelkuponken`), vagy ugyanazt a hatóanyagot két néven adja vissza
(`diozmin` és `mikronizalt-diozmin`). Emiatt egy hatóanyag több csoportra esik
szét, és nem talál rá a generikus alternatívára. Az alias-tábla ezt vezeti vissza
a kanonikus kulcsra: jelenleg 92 terméknél, aminek nyomán 314 hatóanyag-kulcsból
282 lett. A `display` szakasz adja a megjelenítendő nevet, ahol a nyers kulcs nem
olvasható.

Kizárólag azonos hatóanyagot szabad összevonni. Eltérő sóformát csak akkor, ha az
adagolás egyenértékű.

### knowledge_base.json

26 panasz, panaszonként 1–6 hatóanyag-ajánlással. Minden ajánlás mezői:

- `key` – a kanonizált `ingredient_key`
- `role` – `first` (első választás), `alt` (alternatíva), `note` (jó tudni)
- `why` – miért ez, egy-két mondatban
- `caution` – mire kell figyelni

A generátor kihagyja azt az ajánlást, aminek a kulcsa nincs meg az adatban, és a
futás végén kiírja a hiányzó kulcsokat. Így a tudásréteg nem tud olyan
hatóanyagra hivatkozni, ami nincs a katalógusban.

### A három nézet

- **Panasz szerint** – csempékből induló, tünet-alapú belépés. Panaszonként az
  ajánlott hatóanyagok, mindegyiknél a legjobb egységárú készítmény, és lenyitva
  az összes erősség és ár.
- **Hatóanyag szerint** – a teljes katalógus, kategória- és alkategória-navigációval.
- **Hol spórolhat** – csak a valódi, márkák közti árkülönbségek, csökkenő sorrendben.

### Megjelenítési döntések

- Az egységár a doboz egységére vonatkozik (Ft/db, Ft/ml, Ft/g). A mg-alapú
  normalizálás a háttérben marad: egy blokkon belül az erősség azonos, ezért a
  Ft/db sorrend ugyanaz, viszont a szám olvasható. A `Ft / g hatóanyag` szopogató
  tablettánál 300 000 fölötti értékeket adott.
- A sok komponensű készítményeknél az erősség nem a nyers
  `0,5 mg + 1666 NE + 1,8 mg + ...` sorozat, hanem összetevőnként név + mennyiség
  párokban jelenik meg. Ez 149 terméket érint.
- Kombinációs készítmény nem áll szembe egyhatóanyagúval a megtakarítás-számításban.
