import random
import logging
from typing import Callable, IO


def gen_mac(last_octet: int = 0):
    """
        Generate a random MAC address that is in the qemu OUI space and that
        has the given last octet.
    """
    return "52:54:00:%02x:%02x:%02x" % (
        random.randint(0x00, 0xFF),
        random.randint(0x00, 0xFF),
        last_octet,
    )


def io_logger(stream: IO[str], logger_name: str, stop: Callable[[],bool]) -> None:
    logger = logging.getLogger(logger_name)

    while not stop():
        line = stream.readline().strip()
        if not line:
            continue

        logger.debug(line)
