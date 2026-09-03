import logging
import random
import time
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import Settings

log=logging.getLogger(__name__)

class BenuHttpClient:
    def __init__(self, settings: Settings):
        self.settings=settings
        self.session=requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/139.0 Safari/537.36"
            ),
            "Accept-Language":"hu-HU,hu;q=0.9,en;q=0.6",
            "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def _sleep(self):
        time.sleep(random.uniform(self.settings.request_delay_min,self.settings.request_delay_max))

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1,min=2,max=30),
        retry=retry_if_exception_type((requests.RequestException, requests.HTTPError)),
        reraise=True,
    )
    def get(self,url,**kwargs):
        self._sleep()
        response=self.session.get(
            url,
            timeout=self.settings.request_timeout,
            allow_redirects=True,
            **kwargs
        )
        if response.status_code in (429,500,502,503,504):
            response.raise_for_status()
        response.raise_for_status()
        return response
