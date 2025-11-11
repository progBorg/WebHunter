import yaml
import logging
from pathlib import Path
from huizenjacht.utils.singleton import SingletonMeta

class Config(metaclass=SingletonMeta):
    # Some constants
    LOAD_TXT = "^TXT"

    # Public class attributes
    logger: logging.Logger
    config_file: str = None  # Location of default config file

    # Private class attributes
    _loaded_config_file: str = None  # Location of currently loaded config file
    _config: dict = None  # Loaded configuration

    def __init__(self, config_file: str = None):
        self.logger = logging.getLogger(__name__)

        if config_file is not None:
            self.config_file = config_file

    """Load config from config_file attribute or parameter"""
    def load(self, config_file: str = None):
        # Get desired config file location
        if config_file is None:
            config_file = self.config_file

        self._config = load_config_file(config_file)

        self._loaded_config_file = config_file

    """Alias for load()"""
    load_file = load

    """Load provided YAML string as configuration"""
    def load_text(self, text: str):
        # Attempt to load provided text as config
        try:
            self._config = yaml.safe_load(text)
        except yaml.YAMLError as e:
            self.logger.error(
                "An error occurred when attempting to parse the configuration string %s",
                text,
                exc_info=e)
            raise e

        self._loaded_config_file = self.LOAD_TXT

    """
    Main configuration getter, autoloads config file if not already loaded
    """
    @property
    def config(self) -> type(_config):
        # Don't load config if it already exists
        if self._config is not None:
            return self._config

        # Load config and return
        self.load()
        return self._config

    @property
    def loaded_config_file(self) -> str:
        return str(Path(self._loaded_config_file).resolve())

def load_config_file(config_file: str) -> dict:
    logger = logging.getLogger(__name__)

    # Set up the configuration file parser
    with open(config_file, 'r') as stream:
        try:
            config = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            logger.exception(
                "An error occurred when attempting to parse the configuration file %s",
                config_file,
                exc_info=exc
            )
            raise exc

    return config
