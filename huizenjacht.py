#!/usr/bin/env python3
# huizenjacht.py
# author: Tom Veldman
# (c) 2024
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

from huizenjacht.source import Source, Funda
from huizenjacht.comm import Comm
from huizenjacht.config import Config, load_config_file

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
    hj = Huizenjacht(db)

    # Implement reloading via SIGHUP if supported by system
    try:
        signal.signal(signal.SIGHUP, hj.reload)
    except AttributeError:
        logger.info("SIGHUP not supported by system, support for configuration reloading disabled")


    # Handle seeding of database
    if args.reseed:
        logger.info("Reseeding database")
        hj.seed()

    min_waiting_time = conf["server"].get("poll_time_min", 240)  # seconds
    max_waiting_time = conf["server"].get("poll_time_max", 360)  # seconds
    if min_waiting_time > max_waiting_time:
        max_waiting_time = min_waiting_time + 5
    logger.info(f"Running Huizenjacht at an interval of {min_waiting_time}s to {max_waiting_time}s")

    s = sched.scheduler()

    # Let systemd know we've successfully initialized
    systemd_notify('READY=1')

    try:
        run_periodic(
            scheduler=s,
            interval=(min_waiting_time, max_waiting_time),
            action=hj.run,
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
            for c in hj.comms:
                hj.send_msg(c, msg=msg, title=title)

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


class Huizenjacht:
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
        self.logger.debug("Running Huizenjacht")

        # Get new houses
        new_houses = {}
        for source in self.sources:
            for house in source.get():
                if source.is_new(house):
                    key = type(source).__name__
                    if key in new_houses:
                        new_houses[key].append(house)
                    else:
                        new_houses[key] = [house]

        # Return if no new houses
        if len(new_houses) == 0:
            self.logger.debug("No new houses found")
            return

        # Parse some information
        new_houses_count = sum([len(new_houses[h]) for h in new_houses])
        new_houses_sources = new_houses.keys()
        new_houses_sources = ', '.join(new_houses_sources)
        self.logger.info(f"Found {new_houses_count} new houses on {new_houses_sources}")

        # Create message strings
        if new_houses_count == 1:  # use singular if only one house available
            title = self.DEFAULT_MSG_TITLE
            msg = f"Er is 1 nieuw huis gevonden op {new_houses_sources}"
        else:  # else use plural
            title = self.DEFAULT_MSG_TITLE_PLURAL
            msg = f"Er zijn {new_houses_count} nieuwe huizen gevonden op {new_houses_sources}"

        try:  # Funda has high priority
            url = new_houses['Funda'][0]
        except KeyError:  # If no funda house, just get the first one available
            url = next(iter(new_houses.values()))[0]

        # Send message to all active comms
        for c in self.comms:
            self.send_msg(c, msg, title, url)

    """Load all source objects into a list and return that list"""

    def load_sources(self, sources: list, db: sqlite3.Connection) -> list[Source]:
        return self._load_classes_from_module(db, module_list=sources, module_location="huizenjacht.source")

    """Load all comm objects into a list and return that list"""

    def load_comms(self, comms: list) -> list[Comm]:
        return self._load_classes_from_module(module_list=comms, module_location="huizenjacht.comm")

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
        prog="Huizenjacht housing website scraper",
        description="Scrape housing websites and push new results to the user",
        epilog="(C) Tom Veldman 2024"
    )
    parser.add_argument("--configfile", "-c", type=str, default="/etc/huizenjacht.yaml", help='Configuration file')
    parser.add_argument("-v", "--verbose", action="store_true", help="Log debug information")
    parser.add_argument("--version", action="version", version=f"%(prog)s v{PROGRAM_VERSION}")
    parser.add_argument("--reseed", action="store_true",
                        help="Pull all currently available houses into database without notifying user")
    parser.add_argument("--oneshot", "-1", action="store_true", help="Run all sources and comms once, then exit")
    return parser.parse_args()


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
