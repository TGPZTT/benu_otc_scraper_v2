import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse, urlunparse

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def normalize_space(value):
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value)).strip()

def normalize_label(value):
    return normalize_space(value).lower().rstrip(":")

def canonical_url(url, base_url):
    if not url:
        return None
    url=urljoin(base_url,url)
    p=urlparse(url)
    return urlunparse((p.scheme,p.netloc,p.path.rstrip("/"),"","",""))

def is_product_url(url):
    return bool(url) and "/products/" in urlparse(url).path

def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8",errors="ignore")).hexdigest()

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()

def parse_huf(value):
    if value is None:
        return None
    s=normalize_space(value).replace("\xa0"," ")
    m=re.search(r"(\d[\d\s.]*(?:,\d+)?)\s*(?:Ft|HUF)\b",s,re.I)
    if not m:
        return None
    raw=m.group(1).replace(" ","").replace(".","").replace(",",".")
    try:
        return int(Decimal(raw))
    except (InvalidOperation,ValueError):
        return None

def parse_decimal(value):
    if value is None:
        return None
    s=normalize_space(value).replace(",",".")
    try:
        return float(s)
    except Exception:
        return None

def json_dumps(value):
    return json.dumps(value,ensure_ascii=False)

def parse_json_ld(soup):
    result=[]
    for tag in soup.find_all("script",type=re.compile(r"ld\+json",re.I)):
        raw=tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data=json.loads(raw)
            if isinstance(data,list):
                result.extend(data)
            else:
                result.append(data)
        except Exception:
            pass
    return result

def first_nonempty(*values):
    for v in values:
        if isinstance(v,str) and normalize_space(v):
            return normalize_space(v)
        if v not in (None,"",[],{}):
            return v
    return None

def clean_text(text):
    return normalize_space(text) if text else None

def unique_keep_order(items):
    out=[]
    seen=set()
    for x in items:
        x=normalize_space(x)
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out
