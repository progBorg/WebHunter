import json
import logging
import requests
import sqlite3
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from huizenjacht.source import Source
from huizenjacht.config import Config

class Funda(Source):

    # Constants
    BASE_URL = "https://www.funda.nl/zoeken/"
    _allowed_property_types = {
        "woonhuis": "house",
        "house": "house",
        "appartement": "apartment",
        "apartment": "apartment",
        "parkeergelegenheid": "parking",
        "parking": "parking",
    }
    _db_table_create_stmt = '''
CREATE TABLE IF NOT EXISTS "Funda" (
	"id"	INTEGER NOT NULL UNIQUE,
	"URL"	TEXT UNIQUE,
	PRIMARY KEY("id" AUTOINCREMENT)
)'''

    # Public attributes
    logger: logging.Logger = logging.getLogger(__name__)
    conf: dict = None
    db: sqlite3.Cursor

    # Private attributes
    _required_conf_entries: set = {
        "area",
        "buy_or_rent",
    }
    _req_url: str
    _req_url_params: dict
    _req_url_headers: dict
    _ua: UserAgent
    _conn: sqlite3.Connection
    _conf_entry_name = "funda"


    def __init__(self, db: sqlite3.Connection):
        self.conf = Config().config['sources']['funda']

        self._sanity_check_conf()

        self._setup_from_conf()

        self._ua = UserAgent()

        self._conn = db
        self.db = db.cursor()

        self.db.execute(self._db_table_create_stmt)

    def get(self) -> list[str] | None:
        soup = self._do_request()

        if soup is None:
            return []

        url_list = self._parse_response(soup)

        if url_list is None:
            return []

        return url_list

    def _do_request(self) -> BeautifulSoup | None:
        # Randomize User-Agent
        headers = self._req_url_headers
        headers["User-Agent"] = self._ua.random

        # Do request
        try:
            res = requests.get(
                url=self._req_url,
                params=self._req_url_params,
                headers=headers,
            )
        except ConnectionError as exc:
            self.logger.exception("Could not connect to Funda", exc_info=exc)
            return None

        if res.status_code != 200:
            self.logger.warning("Could not reach Funda page successfully, http status code %i", res.status_code)
            return None

        return BeautifulSoup(res.text, features="html.parser")

    def _parse_response(self, soup: BeautifulSoup) -> list:
        try:
            # Get urls
            urls_json = json.loads("".join(soup.find("script", {"type": "application/ld+json"}).contents[0]))
            urls = [item["url"] for item in urls_json["itemListElement"]]
        except AttributeError as exc:
            self.logger.info(f"Failed to retrieve Funda urls from query with parameters {self._req_url_params}")
            urls = None

        return urls

    def is_new(self, house: str) -> bool:
        try:
            self.db.execute("insert into Funda (url) values (?)", [house])
        except sqlite3.IntegrityError:
            return False

        self._conn.commit()

        return True

    def _sanity_check_conf(self, conf: dict = None):
        super()
        if conf is None:
            conf = self.conf

        buy_or_rent = self.conf_value("buy_or_rent", conf=conf)
        if not buy_or_rent in ("buy", "koop", "rent", "huur"):
            raise ValueError(f'Config entry buy_or_rent must be one of [buy, rent, koop, huur], is now "{buy_or_rent}"')

        self.logger.info("Configuration sanity check successful")

    def _setup_from_conf(self):
        # Build base url
        buy_or_rent = "koop" if self.conf_value("buy_or_rent") in ("koop", "buy") else "huur"
        url = urljoin(self.BASE_URL, buy_or_rent)

        # Get values and build url parameters
        url_params = {
            "selected_area": self.conf_value("areas"),
            "sort_by": f'"{self.conf_value("sort_by", "date-down")}"',
            "offering_type": f'"{buy_or_rent}"',
            "availability": '["available"]',
        }
        min_price = self.conf_value("min_price", '')
        max_price = self.conf_value("max_price", '')
        min_rooms = self.conf_value("min_rooms", '')
        max_rooms = self.conf_value("max_rooms", '')

        # Parse search area
        if isinstance(url_params["selected_area"], str):
            url_params["selected_area"] = f'["{url_params["selected_area"]}"]'
        elif isinstance(url_params["selected_area"], list):
            url_params["selected_area"] = '[' + ','.join(f'"{city}"' for city in url_params["selected_area"]) + ']'

        # Parse property type
        property_type = self.conf_value("property_type", "woonhuis")
        try:
            property_type = [self._allowed_property_types[prop] for prop in property_type]
        except KeyError:
            raise KeyError(f"Config value 'property_type' in Funda source contains an entry that is not one of {[k for k in self._allowed_property_types.keys()]}")

        # Parse other url params
        url_params["price"] = f'"{min_price}-{"" if max_price == 0 else max_price}"'
        url_params["rooms"] = f'"{min_rooms}-{"" if max_rooms == 0 else max_rooms}"'
        url_params["object_type"] = '[' + ','.join(f'"{otype}"' for otype in property_type) + ']'

        # Filter out keys with None value
        url_params = {k: v for k, v in url_params.items() if v is not None}

        self._req_url = url
        self._req_url_params = url_params
        self._req_url_headers = {}


if __name__ == "__main__":
    # Quick functionality tests for this class
    conf_text = """
---
server:
  debug: true
  db: "huizenjacht.db"
  message_defaults:
    title: "Nieuw huis gevonden"

sources:
  funda:
    active: true
    area: "gorinchem"
    buy_or_rent: "rent"
"""

    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    Config().load_text(conf_text)
    conf = Config().config
    db = sqlite3.connect(conf["server"]["db"])
    f = Funda(db)

    houses = f.get()

    for h in houses:
        print(f"{h}: {'new' if f.is_new(h) else 'old'}")

    f._conn.commit()
