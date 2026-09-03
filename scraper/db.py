import json
import shutil
from pathlib import Path
from sqlalchemy import (
    create_engine,Column,Integer,String,Boolean,Text,DateTime,ForeignKey,
    UniqueConstraint
)
from sqlalchemy.orm import declarative_base,sessionmaker,relationship
from scraper.utils import utcnow

DB_PATH=Path("data/benu_otc.db")
DB_PATH.parent.mkdir(parents=True,exist_ok=True)

Base=declarative_base()

class Product(Base):
    __tablename__="products"
    id=Column(Integer,primary_key=True)
    url=Column(String(1200),unique=True,nullable=False,index=True)
    name=Column(String(1000),nullable=False,index=True)
    brand=Column(String(500),index=True)
    sku=Column(String(100))
    ean=Column(String(32),index=True)

    classification=Column(String(40),nullable=False,index=True)
    classification_raw=Column(String(500))
    classification_source=Column(String(100),default="unknown")

    price_huf=Column(Integer)
    unit_price=Column(String(200))
    lowest_30d_price_huf=Column(Integer)
    original_price_huf=Column(Integer)
    sale_price_huf=Column(Integer)

    active_ingredient_raw=Column(Text)
    strength=Column(String(500))
    pharmaceutical_form=Column(String(300))
    package_size=Column(String(200))

    product_information=Column(Text)
    description=Column(Text)
    leaflet_text=Column(Text)

    distributor=Column(String(1000))
    manufacturer=Column(String(1000))
    registration_number=Column(String(300))

    breadcrumbs_json=Column(Text)
    images_json=Column(Text)
    statuses_json=Column(Text)
    parse_warnings_json=Column(Text)
    json_ld=Column(Text)
    raw_text=Column(Text)
    raw_html_hash=Column(String(64))
    is_incomplete=Column(Boolean,nullable=False,default=False,index=True)

    first_seen_at=Column(DateTime,nullable=False,default=utcnow)
    last_seen_at=Column(DateTime,nullable=False,default=utcnow)
    last_changed_at=Column(DateTime)

    ingredients=relationship("ProductIngredient",back_populates="product",cascade="all, delete-orphan")
    prices=relationship("PriceHistory",back_populates="product",cascade="all, delete-orphan")

class Ingredient(Base):
    __tablename__="ingredients"
    id=Column(Integer,primary_key=True)
    name=Column(String(500),unique=True,nullable=False,index=True)
    products=relationship("ProductIngredient",back_populates="ingredient",cascade="all, delete-orphan")

class ProductIngredient(Base):
    __tablename__="product_ingredients"
    id=Column(Integer,primary_key=True)
    product_id=Column(Integer,ForeignKey("products.id"),nullable=False,index=True)
    ingredient_id=Column(Integer,ForeignKey("ingredients.id"),nullable=False,index=True)
    raw_amount=Column(String(300))
    __table_args__=(UniqueConstraint("product_id","ingredient_id",name="uq_product_ingredient"),)
    product=relationship("Product",back_populates="ingredients")
    ingredient=relationship("Ingredient",back_populates="products")

class PriceHistory(Base):
    __tablename__="price_history"
    id=Column(Integer,primary_key=True)
    product_id=Column(Integer,ForeignKey("products.id"),nullable=False,index=True)
    observed_at=Column(DateTime,nullable=False,default=utcnow,index=True)
    price_huf=Column(Integer)
    unit_price=Column(String(200))
    lowest_30d_price_huf=Column(Integer)
    original_price_huf=Column(Integer)
    sale_price_huf=Column(Integer)
    product=relationship("Product",back_populates="prices")

class ScrapeRun(Base):
    __tablename__="scrape_runs"
    id=Column(Integer,primary_key=True)
    started_at=Column(DateTime,nullable=False)
    finished_at=Column(DateTime)
    discovered_urls=Column(Integer,default=0)
    processed=Column(Integer,default=0)
    otc_count=Column(Integer,default=0)
    non_otc_count=Column(Integer,default=0)
    unknown_count=Column(Integer,default=0)
    incomplete_count=Column(Integer,default=0)
    errors=Column(Integer,default=0)

class ScrapeError(Base):
    __tablename__="scrape_errors"
    id=Column(Integer,primary_key=True)
    run_id=Column(Integer,ForeignKey("scrape_runs.id"),index=True)
    url=Column(String(1200),nullable=False)
    error_type=Column(String(300))
    error_message=Column(Text)
    occurred_at=Column(DateTime,nullable=False,default=utcnow)

engine=create_engine(f"sqlite:///{DB_PATH}",future=True)
SessionLocal=sessionmaker(bind=engine,expire_on_commit=False,future=True)

def init_db():
    Base.metadata.create_all(engine)
    ensure_schema()

def ensure_schema():
    # create_all does not alter existing SQLite tables. Keep small additive
    # migrations here so old test databases remain readable after parser upgrades.
    if not DB_PATH.exists():
        return
    with engine.begin() as conn:
        columns={row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)")}
        additions={
            "classification_source":"ALTER TABLE products ADD COLUMN classification_source VARCHAR(100) DEFAULT 'unknown'",
            "parse_warnings_json":"ALTER TABLE products ADD COLUMN parse_warnings_json TEXT",
            "is_incomplete":"ALTER TABLE products ADD COLUMN is_incomplete BOOLEAN NOT NULL DEFAULT 0",
        }
        for column,sql in additions.items():
            if column not in columns:
                conn.exec_driver_sql(sql)

        run_columns={row[1] for row in conn.exec_driver_sql("PRAGMA table_info(scrape_runs)")}
        if "incomplete_count" not in run_columns:
            conn.exec_driver_sql("ALTER TABLE scrape_runs ADD COLUMN incomplete_count INTEGER DEFAULT 0")

def backup_db():
    if DB_PATH.exists():
        stamp=utcnow().strftime("%Y%m%d_%H%M%S")
        backup=DB_PATH.with_name(f"benu_otc_{stamp}.db.bak")
        shutil.move(DB_PATH,backup)
        return backup
    return None

def upsert_product(session,data):
    now=utcnow()
    p=session.query(Product).filter_by(url=data["url"]).one_or_none()
    is_new=p is None
    old_hash=None
    old_price=None

    if is_new:
        p=Product(
            url=data["url"],
            name=data.get("name") or data["url"].rstrip("/").split("/")[-1] or "Ismeretlen termék",
            classification=data.get("classification") or "UNKNOWN",
            first_seen_at=now,
        )
        session.add(p)
        session.flush()
    else:
        old_hash=p.raw_html_hash
        old_price=p.price_huf

    # Never allow a malformed parser response to violate the DB NOT NULL constraint.
    # UNKNOWN is a deliberate value for pages where BENU did not expose the classification.
    data["classification"] = data.get("classification") or "UNKNOWN"
    data["name"] = data.get("name") or data["url"].rstrip("/").split("/")[-1] or "Ismeretlen termék"

    for field in [
        "name","brand","sku","ean","classification","classification_raw",
        "classification_source",
        "price_huf","unit_price","lowest_30d_price_huf","original_price_huf",
        "sale_price_huf","active_ingredient_raw","strength","pharmaceutical_form",
        "package_size","product_information","description","leaflet_text",
        "distributor","manufacturer","registration_number","json_ld","raw_text",
        "raw_html_hash","is_incomplete"
    ]:
        if field in data:
            setattr(p,field,data[field])

    p.breadcrumbs_json=json.dumps(data.get("breadcrumbs",[]),ensure_ascii=False)
    p.images_json=json.dumps(data.get("images",[]),ensure_ascii=False)
    p.statuses_json=json.dumps(data.get("statuses",[]),ensure_ascii=False)
    p.parse_warnings_json=json.dumps(data.get("parse_warnings",[]),ensure_ascii=False)
    p.last_seen_at=now
    if is_new or old_hash!=p.raw_html_hash:
        p.last_changed_at=now

    # Rebuild normalized ingredient links.
    for rel in list(p.ingredients):
        session.delete(rel)
    session.flush()

    for ingredient_name in data.get("ingredient_names",[]):
        ing=session.query(Ingredient).filter_by(name=ingredient_name).one_or_none()
        if ing is None:
            ing=Ingredient(name=ingredient_name)
            session.add(ing)
            session.flush()
        session.add(ProductIngredient(
            product=p,ingredient=ing,raw_amount=data.get("active_ingredient_raw")
        ))

    # Record price on every observation, but avoid duplicate rows with the exact
    # same values on the same second.
    session.add(PriceHistory(
        product=p,
        observed_at=now,
        price_huf=p.price_huf,
        unit_price=p.unit_price,
        lowest_30d_price_huf=p.lowest_30d_price_huf,
        original_price_huf=p.original_price_huf,
        sale_price_huf=p.sale_price_huf,
    ))

    session.commit()
    return p,is_new,(old_price!=p.price_huf)
