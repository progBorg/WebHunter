from abc import ABC, abstractmethod

class Comm(ABC):
    """
    Communication interface to update user.
    """

    """
    Send a message to the user
    """
    @abstractmethod
    def send(self, msg: str, title: str, url: str) -> int:
        pass

    """
    Retrieve the readiness of this communication channel
    """
    @abstractmethod
    def is_ready(self) -> bool:
        pass

    """
    Test and reload from provided configuration
    :returns True if conf is accepted, False otherwise
    """
    @abstractmethod
    def reload(self, config: dict) -> bool:
        pass
