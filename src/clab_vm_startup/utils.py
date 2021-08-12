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
import logging
import random
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
