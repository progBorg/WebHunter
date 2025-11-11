from huizenjacht.comm import Comm
from huizenjacht.config import Config

import time
import logging
import chump
from urllib.parse import urlparse

class Pushover(Comm):
    # Public class attributes
    logger: logging.Logger
    conf: dict

    # Private class attributes
    _pushover: chump.Application
    _rcpt: chump.User
    _default_title: str

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        conf = Config().config
        self._default_title = conf['server']['message_strings']['default_title']
        self.conf = conf['comm']['pushover']
        self._sanity_check_conf()

        self._pushover = chump.Application(token=self.conf['api_key'])
        self._rcpt = self._pushover.get_user(self.rcpt)

    def send(self, msg: str, title: str = None, url: str = None) -> chump.Message | None:
        msg = str(msg)

        if len(msg) == 0:
            return None

        # Truncate msg size if necessary
        msg = msg[:1020] + '...' if len(msg) >= 1024 else msg  # Limit msg length

        if title is None:
            title = self._default_title

        url_title = urlparse(url).netloc if url is not None else None
        message = self._rcpt.create_message(message=msg, title=title, url=url, url_title=url_title)
        message.send()
        return message

    """Check whether app and recipient are authenticated"""
    def is_ready(self) -> bool:
        return self._pushover.is_authenticated and self._rcpt.is_authenticated

    """Get recipient string
    Returns the string containing one or more user or group keys"""
    @property
    def rcpt(self) -> str:
        return self.conf['user_key']

    def reload(self, config: dict) -> bool:
        if 'comm' in config:
            if 'pushover' in config['comm']:
                config = config['comm']['pushover']
            else:
                self.logger.error("Could not find Pushover entry in config")
                return False
        try:
            self._sanity_check_conf(config)
        except KeyError:
            return False

        #TODO Implement actual reload
        return True

    """Perform a simple sanity check on the configuration keys"""
    def _sanity_check_conf(self, conf: dict = None):
        entries = {
            "api_key": None,
            "user_key": None,
        }

        if conf is None:
            conf = self.conf

        for name in entries.keys():
            try:
                value = conf[name]
            except KeyError as e:
                logging.error(f"{name} not found in Pushover configuration")
                raise e

            entries[name] = value
            if value is not None:
                self.logger.debug(f"{name}: {value}")

        self.logger.info("Configuration sanity check successful")

if __name__ == "__main__":
    # Quick functionality tests for this class
    conf_text = """
---
server:
  debug: true
  message_defaults:
    title: "Nieuw huis gevonden"

comm:
  pushover:
    active: true
    api_key: "API_KEY"
    user_key: "USER_KEY"
    """

    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    Config().load_text(conf_text)
    po = Pushover()

    while not po.is_ready():
        time.sleep(1)

    po.send(msg=input(": "), url="https://home.hetverreoosten.com/")
