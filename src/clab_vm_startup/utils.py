"""
       Copyright 2021 Inmanta

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""
import colorlog
import logging
import random
import sys
from typing import IO, Callable


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


def io_logger(stream: IO[str], logger_name: str, stop: Callable[[], bool]) -> None:
    logger = logging.getLogger(logger_name)

    while not stop():
        line = stream.readline().strip()
        if not line:
            continue

        logger.debug(line)


def is_on_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def get_log_formatter_for_stream_handler(timed: bool) -> logging.Formatter:
    """
        Copied from 
        https://github.com/inmanta/inmanta-core/blob/2d18cc42c8b64b603e84453a7776bebdda3ade48/src/inmanta/app.py#L614
    """
    log_format = "%(asctime)s " if timed else ""
    if is_on_tty():
        log_format += "%(log_color)s%(name)-25s%(levelname)-8s%(reset)s %(message)s"
        formatter = colorlog.ColoredFormatter(
            log_format,
            datefmt=None,
            reset=True,
            log_colors={"DEBUG": "cyan", "INFO": "green", "WARNING": "yellow", "ERROR": "red", "CRITICAL": "red"},
        )
    else:
        log_format += "%(name)-25s%(levelname)-8s%(message)s"
        formatter = logging.Formatter(fmt=log_format)
    return formatter


def get_default_stream_handler() -> logging.StreamHandler:
    """
        Copied from 
        https://github.com/inmanta/inmanta-core/blob/2d18cc42c8b64b603e84453a7776bebdda3ade48/src/inmanta/app.py#L586
    """
    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setLevel(logging.INFO)

    formatter = get_log_formatter_for_stream_handler(timed=False)
    stream_handler.setFormatter(formatter)

    return stream_handler


def setup_logging(trace: bool) -> None:
    stream_handler = get_default_stream_handler()
    logging.root.handlers = []
    logging.root.addHandler(stream_handler)
    logging.root.setLevel(0)

    formatter = get_log_formatter_for_stream_handler(timed=True)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.DEBUG if trace else logging.INFO)
