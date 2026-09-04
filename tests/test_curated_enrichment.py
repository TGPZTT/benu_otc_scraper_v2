import json
from pathlib import Path


REFERENCE = Path("reference/curated_product_enrichment.json")


def test_curated_enrichment_reference_is_valid():
    payload = json.loads(REFERENCE.read_text(encoding="utf-8"))
    products = payload["products"]
    urls = [item["url"] for item in products]

    assert payload["schema_version"] == 1
    assert len(urls) == len(set(urls))
    assert len(products) >= 13

    for item in products:
        assert item["url"].startswith("https://benu.hu/products/")
        assert item["active_ingredient_raw"].strip()
        assert item["active_ingredient_source"].startswith("curated_")
        assert item["ingredient_names"]
        assert all(name.strip() for name in item["ingredient_names"])
        assert item["evidence_urls"]
