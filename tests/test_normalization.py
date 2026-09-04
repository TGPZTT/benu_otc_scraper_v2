from scripts.build_normalized_catalog import (
    canonical_ingredient,
    normalize_ingredients,
    normalize_form,
    normalize_strength,
    parse_package_amount,
    parse_unit_price,
)


def test_parse_unit_price():
    assert parse_unit_price("1 213 Ft / ml") == (1213.0, "ml")
    assert parse_unit_price("66 Ft / tabletta") == (66.0, "db")


def test_parse_package_amount():
    assert parse_package_amount("24x10ml", "") == (240.0, "ml", "24x10 ml")
    assert parse_package_amount("3x20 db", "") == (60.0, "db", "3x20 db")
    assert parse_package_amount(None, "Béres Actival Extra filmtabletta 90x") == (90.0, "db", "90 db")
    assert parse_package_amount("100g", "") == (100.0, "g", "100 g")


def test_canonical_ingredient_aliases():
    assert canonical_ingredient("ibuprofen") == "ibuprofén"
    assert canonical_ingredient("benzidamin-hidroklorid szopogató") == "benzidamin"
    assert canonical_ingredient("lidokain-hidroklorid-monohidrát") == "lidokain"
    assert canonical_ingredient("metamizole sodium monohydrate") == "metamizol-nátrium"
    assert canonical_ingredient("nátrium-hidrogén-karbonát") == "nátrium-hidrogén-karbonát"
    assert canonical_ingredient("tisztított és mikronizált flavonoid frakciót") == "mikronizált flavonoid frakció"
    assert normalize_ingredients(["tisztított", "mikronizált flavonoid frakciót"])[0] == ["mikronizált flavonoid frakció"]
    assert canonical_ingredient("Gynoxin fentikonazol-nitrát") == "fentikonazol"
    assert canonical_ingredient("pankreatin Frogalmazza:BERLIN-CHEMIE/ A. MENARINI Kft.") == "pankreatin"
    assert canonical_ingredient("elölt baktériumkultúra-szuszpenziót") == "elölt E. coli baktériumkultúra"
    assert canonical_ingredient("omega‑3‑sav‑etilészterek omega‑3‑sav‑etilészter") == "omega-3-sav-etilészterek"
    assert canonical_ingredient("Ginkgo biloba L folium száraz beállított kivonata") == "páfrányfenyőlevél száraz kivonat"
    assert canonical_ingredient("Cetirizin HEXAL cseppek a cetirizin-dihidroklorid") == "cetirizin"
    assert canonical_ingredient("cetirizin-dihidroklorid") == "cetirizin"
    assert canonical_ingredient("levocetirizin-dihidroklorid") == "levocetirizin"
    assert canonical_ingredient("azelasztin-hidroklorid") == "azelasztin"
    assert canonical_ingredient("• A fülcsepp fenazon") == "fenazon"


def test_normalize_form():
    assert normalize_form("Ibumax 400 mg filmtabletta 100 db", "filmtabletta") == ("tabletta", "tabletta")
    assert normalize_form("Tantum Verde 3 mg szopogató tabletta 20 db", "tabletta") == ("szopogató tabletta", "szopogato-tabletta")
    assert normalize_form("Nurofen Rapid 400 mg lágy kapszula 20 db", "lágy kapszula") == ("lágy kapszula", "lagy-kapszula")


def test_normalize_strength():
    assert normalize_strength(
        "Ibumax 400 mg filmtabletta 100 db",
        "400 mg ibuprofén filmtablettánként",
    ) == ("400 mg", "400-mg")
    assert normalize_strength(
        "Tantum Verde 1,5mg/ml spray 30ml",
        "benzidamin. 1,50 mg benzidamin-hidrokloridot tartalmaz 1 ml oldatban.",
    ) == ("1,5 mg/ml", "1-5-mg-per-ml")
    assert normalize_strength(
        "Neurogerlon Neo 40 mg/90 mg/0,25 mg filmtabletta 20 db",
        None,
    ) == ("40 mg/90 mg/0,25 mg", "40-mg-per-90-mg-per-0-25-mg")
    assert normalize_strength(
        "Deep Relief gél 50g",
        "0,05 g ibuprofén és 0,03 g levomentol 1 g gélben",
    ) == ("0,05 g + 0,03 g", "0-05-g+0-03-g")
    assert normalize_strength(
        "Dolgit krém 50g",
        "50 mg ibuprofént tartalmaz 1 g krémben",
    ) == ("50 mg", "50-mg")
    assert normalize_strength(
        "Paramax Forte 1 g tabletta 100 db",
        "PARAMAX Junior 250 mg tabletta: 250 mg paracetamolt tartalmaz tablettánként. "
        "PARAMAX Forte 1 g tabletta: 1 g paracetamol tablettánként.",
    ) == ("1 g", "1-g")
