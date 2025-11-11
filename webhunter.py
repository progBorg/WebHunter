#!/usr/bin/env python3
# webhunter.py
# author: Tom Veldman
# (c) 2024 - 2025
# MIT license

import argparse
import logging
import importlib
import sqlite3
import sys
import traceback
import signal
import inflection
import time
import random
import sched

try:  # Will fail if not on Linux
    import systemd.daemon
except ImportError:
    pass  # Fail silently and log later

from webhunter.source import Source, Funda
from webhunter.comm import Comm
from webhunter.config import Config, load_config_file

# Some constants
PROGRAM_VERSION: str = "0.1"


def main():
    # Set up logging, include systemd Journal support
    logging.basicConfig()
    logger = logging.getLogger()

    # Parse command-line arguments
    args = parse_arguments()

    try:
        systemd.daemon
    except NameError:
        logger.info("Could not import systemd daemon interface, skipping...")

    # set up global configuration
    conf = Config(config_file=args.configfile).config

    # Parse verbosity
    if args.verbose or conf['server']['debug']:
        logger.setLevel(logging.DEBUG)
        logger.debug("Running in verbose mode")
    else:
        logger.setLevel(logging.INFO)

    if conf["server"]["simulate"]:
        logger.info("Server is in simulation mode, NO MESSAGES WILL BE SENT")

    # Load database
    db = sqlite3.connect(conf["server"]["db"])

    # Create main house hunting object
    wh = WebHunter(db)

    # Implement reloading via SIGHUP if supported by system
    try:
        signal.signal(signal.SIGHUP, wh.reload)
    except AttributeError:
        logger.info("SIGHUP not supported by system, support for configuration reloading disabled")


    # Handle seeding of database
    if args.reseed:
        logger.info("Reseeding database")
        wh.seed()

    min_waiting_time = conf["server"].get("poll_time_min", 240)  # seconds
    max_waiting_time = conf["server"].get("poll_time_max", 360)  # seconds
    if min_waiting_time > max_waiting_time:
        max_waiting_time = min_waiting_time + 5
    logger.info(f"Running WebHunter at an interval of {min_waiting_time}s to {max_waiting_time}s")

    s = sched.scheduler()

    # Let systemd know we've successfully initialized
    systemd_notify('READY=1')

    try:
        run_periodic(
            scheduler=s,
            interval=(min_waiting_time, max_waiting_time),
            action=wh.run,
        )
    finally:
        systemd_notify('STOPPING=1')

        exc_type, exc_instance, _ = sys.exc_info()
        if not (exc_type, exc_instance) == (None, None):
            # An exception exists, notify all comms
            msg = f"""{conf["server"]["message_strings"]["server_shutdown_msg_text"]}

{exc_type.__name__}:
{traceback.format_exc(limit=3)}"""
            title = conf["server"]["message_strings"]["server_info_msg_title"]
            for c in wh.comms:
                wh.send_msg(c, msg=msg, title=title)

    return 0


def systemd_notify(message: str):
    try:
        systemd.daemon.notify(message)
    except NameError:
        # Silently ignore if systemd is not on this system
        pass


def run_periodic(scheduler: sched.scheduler, interval, action, actionargs=(), actionkwargs={}):
    if isinstance(interval, tuple) and len(interval) >= 2:
        rerun_interval = random.randint(interval[0], interval[1])
    else:
        rerun_interval = interval

    # Reschedule same event to happen again after rerun_interval time has passed
    scheduler.enter(rerun_interval, 1, run_periodic, (scheduler, interval, action, actionargs, actionkwargs))

    # Run action
    action(*actionargs, **actionkwargs)


class WebHunter:
    # Class constants
    SOURCES_KEY = "sources"
    COMMS_KEY = "comm"

    SERVER_COMM_MSG_TITLE: str
    STARTUP_COMM_MSG_TEXT: str
    AND: str

    DEFAULT_MSG_TITLE: str
    DEFAULT_MSG_TITLE_PLURAL: str

    # Public attributes
    logger: logging.Logger
    conf: dict
    db: sqlite3.Cursor

    sources: list[Source]
    comms: list[Comm]

    # Private attributes
    _conn: sqlite3.Connection

    def __init__(self, db: sqlite3.Connection):
        self.logger = logging.getLogger(type(self).__name__)
        self.conf = Config().config
        self._conn = db
        self.db = db.cursor()

        # Load active sources and active comms
        self.sources = self.load_sources(
            [key for key in self.conf[self.SOURCES_KEY].keys()
             if self.conf[self.SOURCES_KEY][key]["active"]],
            db
        )
        self.comms = self.load_comms(
            [key for key in self.conf[self.COMMS_KEY].keys()
             if self.conf[self.COMMS_KEY][key]["active"]]
        )

        # Read config values
        self.SERVER_COMM_MSG_TITLE = self.conf["server"]["message_strings"]["server_info_msg_title"]
        self.STARTUP_COMM_MSG_TEXT = self.conf["server"]["message_strings"]["server_startup_msg_text"]
        self.AND = self.conf["server"]["message_strings"]["and"]
        self.DEFAULT_MSG_TITLE = self.conf["server"]["message_strings"]["default_title"]
        self.DEFAULT_MSG_TITLE_PLURAL = self.conf["server"]["message_strings"]["default_title_plural"]

        # Send a startup message
        if self.STARTUP_COMM_MSG_TEXT not in (None, ''):
            for comm in self.comms:
                self.send_msg(comm, msg=self.STARTUP_COMM_MSG_TEXT, title=self.SERVER_COMM_MSG_TITLE)

    def run(self):
        """Go once through all sources and push new houses to all comms"""
        self.logger.debug("Running WebHunter")

        # Get new houses
        new_items = {}
        for source in self.sources:
            for item in source.get():
                if source.is_new(item):
                    key = type(source).__name__
                    if key in new_items:
                        new_items[key].append(item)
                    else:
                        new_items[key] = [item]

        # Return if no new houses
        if len(new_items) == 0:
            self.logger.debug("No new items found")
            return

        # Parse some information
        new_items_count = sum([len(new_items[h]) for h in new_items])
        new_items_sources = new_items.keys()
        new_items_sources = ', '.join(new_items_sources)
        self.logger.info(f"Found {new_items_count} new items on {new_items_sources}")

        # Create message strings
        if new_items_count == 1:  # use singular if only one item available
            title = self.DEFAULT_MSG_TITLE
            msg = f"Er is 1 nieuw item gevonden op {new_items_sources}"
        else:  # else use plural
            title = self.DEFAULT_MSG_TITLE_PLURAL
            msg = f"Er zijn {new_items_count} nieuwe items gevonden op {new_items_sources}"

        try:  # Funda has high priority
            url = new_items['Funda'][0]
        except KeyError:  # If no funda item, just get the first one available
            url = next(iter(new_items.values()))[0]

        # Send message to all active comms
        for c in self.comms:
            self.send_msg(c, msg, title, url)

    """Load all source objects into a list and return that list"""

    def load_sources(self, sources: list, db: sqlite3.Connection) -> list[Source]:
        return self._load_classes_from_module(db, module_list=sources, module_location="webhunter.source")

    """Load all comm objects into a list and return that list"""

    def load_comms(self, comms: list) -> list[Comm]:
        return self._load_classes_from_module(module_list=comms, module_location="webhunter.comm")

    def _load_classes_from_module(self, *args, module_list: list, module_location: str):
        # Collect file names and object names of modules
        file_names, object_names = self._str_to_file_and_object_names(module_list)

        # Iterate through module strings and attempt to load corresponding objects
        # The class name must be CamelCased, the filename must be snake_cased
        objects = []
        for module_file, object_name in zip(file_names, object_names):
            objects.append(
                getattr(
                    importlib.import_module(f".{module_file}", module_location),  # Module
                    object_name
                )(*args)
            )

        return objects

    """From a list of strings, generate a list of filenames and object names for Sources and Comms """

    def _str_to_file_and_object_names(self, stringlist: list[str]) -> (list[str], list[str]):
        # Make a copy of input with all inputs cast to a string and anything not alphanumeric or underscore removed
        _stringlist = [''.join(c for c in str(s) if c.isalnum() or c == '_') for s in stringlist]

        # Convert to snake_case
        file_names: list[str] = [inflection.underscore(s) for s in _stringlist]

        # Convert to CamelCase
        object_names: list[str] = [inflection.camelize(s, uppercase_first_letter=True) for s in _stringlist]

        return file_names, object_names

    def seed(self):
        for source in self.sources:
            houses = source.get()
            for h in houses:
                source.is_new(h)

    def reload(self, sig: int, frame):
        systemd_notify(f'RELOADING=1\nMONOTONIC_USEC={time.monotonic_ns() // 1000}')

        try:
            new_conf = load_config_file(str(Config().loaded_config_file))
        except FileNotFoundError as exc:
            if Config().loaded_config_file == Config.LOAD_TXT:
                self.logger.error("Attempted to reload while using textual input as config, this is not possible")
            else:
                raise exc
        else:  # Succesfully loaded
            new_conf_accepted = True
            failing_modules = []
            for s in self.sources:
                if not s.reload(new_conf):
                    failing_modules.append(type(s).__name__)
                    new_conf_accepted = False
            for c in self.comms:
                if not c.reload(new_conf):
                    failing_modules.append(type(c).__name__)
                    new_conf_accepted = False

            if not new_conf_accepted:
                self.logger.error(f"Attempted to reload configuration, but not accepted by {failing_modules}")
                self.logger.error("Retaining old config")

        systemd_notify('READY=1')

    """Send a message to specified comm object"""
    def send_msg(self, comm: Comm, msg: str, title: str = None, url: str = None) -> int:
        one_line_msg = '|\t'.join([line.strip() for line in msg.splitlines()])
        if not self.conf["server"]["simulate"]:
            self.logger.debug(f"msg to {type(comm).__name__}: t'{title}' m'{one_line_msg}' u'{url}'")
            return comm.send(msg=msg, title=title, url=url)
        else:
            self.logger.info(f"sim-msg to {type(comm).__name__}: t'{title}' m'{one_line_msg}' u'{url}'")
            return 0


def parse_arguments():
    parser = argparse.ArgumentParser(
        prog="WebHunter website scraper",
        description="Scrape websites for items and push new results to the user",
        epilog="(C) Tom Veldman 2024 - 2025"
    )
    parser.add_argument("--configfile", "-c", type=str, default="/etc/webhunter.yaml", help='Configuration file')
    parser.add_argument("-v", "--verbose", action="store_true", help="Log debug information")
    parser.add_argument("--version", action="version", version=f"%(prog)s v{PROGRAM_VERSION}")
    parser.add_argument("--reseed", action="store_true",
                        help="Pull all currently available houses into database without notifying user")
    parser.add_argument("--oneshot", "-1", action="store_true", help="Run all sources and comms once, then exit")
    return parser.parse_args()


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
