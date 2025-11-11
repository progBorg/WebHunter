import logging
from typing import Any

from webhunter.source import Source

class RentAHouse(Source):
    @property
    def logger(self) -> logging.Logger:
        pass

    @property
    def conf(self) -> dict:
        pass

    @property
    def _required_conf_entries(self) -> set:
        pass

    def __init__(self):
        pass

    def get(self):
        pass

    def is_new(self, house: Any) -> bool:
        pass

