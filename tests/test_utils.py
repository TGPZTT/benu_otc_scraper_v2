from scraper.utils import parse_huf,normalize_space,is_product_url

def test_huf():
    assert parse_huf("6 599 Ft")==6599
    assert parse_huf("749 Ft")==749

def test_space():
    assert normalize_space("  alma   körte \n banán ")=="alma körte banán"

def test_url():
    assert is_product_url("https://benu.hu/products/ibumax-400-mg")
