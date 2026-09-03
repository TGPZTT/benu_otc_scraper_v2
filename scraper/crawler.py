import logging
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from scraper.utils import canonical_url,is_product_url

log=logging.getLogger(__name__)

class BenuCrawler:
    def __init__(self,client,base_url):
        self.client=client
        self.base_url=base_url.rstrip("/")

    def _xml_urls(self,url):
        response=self.client.get(url)
        root=ET.fromstring(response.content)
        urls=[]
        for elem in root.iter():
            if elem.tag.lower().endswith("loc") and elem.text:
                urls.append(elem.text.strip())
        return urls

    def discover_from_sitemaps(self):
        candidates=[
            f"{self.base_url}/sitemap.xml",
            f"{self.base_url}/sitemap_index.xml",
            f"{self.base_url}/sitemap_products_1.xml?from=0&to=999999999999",
        ]
        seen=set()
        product_urls=set()
        queue=[]

        for candidate in candidates:
            try:
                queue.extend(self._xml_urls(candidate))
            except Exception as exc:
                log.debug("Sitemap unavailable %s: %s",candidate,exc)

        while queue:
            url=queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if is_product_url(url):
                product_urls.add(canonical_url(url,self.base_url))
                continue
            low=url.lower()
            if low.endswith(".xml") or "sitemap" in low:
                try:
                    queue.extend(self._xml_urls(url))
                except Exception as exc:
                    log.debug("Nested sitemap failed %s: %s",url,exc)
        return sorted(product_urls)

    def discover_from_collection(self):
        collection=f"{self.base_url}/collections/minden-termek"
        urls=set()
        previous_page_urls=None

        for page in range(1,501):
            url=f"{collection}?page={page}"
            try:
                response=self.client.get(url)
            except Exception as exc:
                log.warning("Collection page %s failed: %s",page,exc)
                break

            soup=BeautifulSoup(response.text,"lxml")
            page_urls=set()
            for a in soup.select('a[href*="/products/"]'):
                c=canonical_url(a.get("href"),self.base_url)
                if c:
                    page_urls.add(c)

            if not page_urls:
                break
            if page_urls==previous_page_urls:
                break

            before=len(urls)
            urls.update(page_urls)
            log.info("Collection page %d: +%d",page,len(urls)-before)
            previous_page_urls=page_urls

        return sorted(urls)

    def discover_product_urls(self):
        urls=set(self.discover_from_sitemaps())
        log.info("Sitemap discovery: %d product URLs",len(urls))
        if not urls:
            urls.update(self.discover_from_collection())
            log.info("Collection discovery: %d product URLs",len(urls))
        return sorted(urls)
