import csv
import json
from pathlib import Path
from scraper.db import SessionLocal,Product,Ingredient,ProductIngredient,init_db

OUT=Path("data/exports")
OUT.mkdir(parents=True,exist_ok=True)

def row(p):
    return {
        "id":p.id,
        "name":p.name,
        "brand":p.brand,
        "sku":p.sku,
        "ean":p.ean,
        "classification":p.classification,
        "classification_raw":p.classification_raw,
        "classification_source":p.classification_source,
        "price_huf":p.price_huf,
        "unit_price":p.unit_price,
        "lowest_30d_price_huf":p.lowest_30d_price_huf,
        "original_price_huf":p.original_price_huf,
        "sale_price_huf":p.sale_price_huf,
        "active_ingredient_raw":p.active_ingredient_raw,
        "active_ingredient_source":getattr(p,"active_ingredient_source",None),
        "strength":p.strength,
        "pharmaceutical_form":p.pharmaceutical_form,
        "package_size":p.package_size,
        "product_information":p.product_information,
        "description":p.description,
        "leaflet_text":p.leaflet_text,
        "distributor":p.distributor,
        "manufacturer":p.manufacturer,
        "registration_number":p.registration_number,
        "breadcrumbs":p.breadcrumbs_json,
        "images":p.images_json,
        "statuses":p.statuses_json,
        "is_incomplete":p.is_incomplete,
        "parse_warnings":p.parse_warnings_json,
        "url":p.url,
        "first_seen_at":p.first_seen_at.isoformat() if p.first_seen_at else None,
        "last_seen_at":p.last_seen_at.isoformat() if p.last_seen_at else None,
        "last_changed_at":p.last_changed_at.isoformat() if p.last_changed_at else None,
    }

init_db()

with SessionLocal() as session:
    products=session.query(Product).order_by(Product.name).all()
    otc=[p for p in products if p.classification=="OTC"]
    all_rows=[row(p) for p in products]
    otc_rows=[row(p) for p in otc]

    for filename,rows in [("products.csv",all_rows),("otc_products.csv",otc_rows)]:
        if not rows:
            continue
        with (OUT/filename).open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)

    (OUT/"products.json").write_text(json.dumps(all_rows,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"otc_products.json").write_text(json.dumps(otc_rows,ensure_ascii=False,indent=2),encoding="utf-8")

    ingredients=[]
    for ing in session.query(Ingredient).order_by(Ingredient.name):
        count=session.query(ProductIngredient).filter_by(ingredient_id=ing.id).count()
        ingredients.append({"id":ing.id,"name":ing.name,"product_count":count})
    with (OUT/"ingredients.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["id","name","product_count"])
        w.writeheader(); w.writerows(ingredients)

print(f"Products: {len(products)}")
print(f"OTC: {len(otc)}")
print(f"Exports: {OUT.resolve()}")
