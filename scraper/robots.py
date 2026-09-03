import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

log=logging.getLogger(__name__)

class RobotsGuard:
    def __init__(self,base_url,user_agent):
        self.base_url=base_url.rstrip("/")
        self.user_agent=user_agent
        self.rp=RobotFileParser()
        self.available=False

    def load(self,client):
        url=self.base_url+"/robots.txt"
        try:
            response=client.get(url)
            self.rp.parse(response.text.splitlines())
            self.available=True
            log.info("robots.txt loaded.")
        except Exception as exc:
            log.warning("Could not load robots.txt: %s",exc)

    def allowed(self,url):
        if not self.available:
            return True
        return self.rp.can_fetch(self.user_agent,url)
