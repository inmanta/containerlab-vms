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
import re
from typing import List, Match, Optional, Pattern, Tuple

from clab_vm_startup.helpers.telnet_client import TelnetClient

LOGGER = logging.getLogger(__name__)


class IOSXRConsole:
    def __init__(self, serial_console: TelnetClient, username: str, password: str) -> None:
        self.username = username
        self.password = password

        self._hostname: Optional[str] = None

        self._console = serial_console
        self._connected = False
        self._remainder = ""

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def cli_prompt(self) -> str:
        return f"RP/0/RP0/CPU0:{self._hostname}#"

    def connect(self) -> None:
        if self.connected:
            raise RuntimeError("This IOS XR console is already connected")

        # Triggering login prompt
        self.wait_write("", None)
        self.wait_write(self.username, "Username:")
        self.wait_write(self.password, "Password:")

        auth_failed = re.compile("% User Authentication failed")
        cli_prompt = re.compile(r"RP\/0\/RP0\/CPU0\:(.*)\#")
        pattern, match, res = self._console.expect(
            [auth_failed, cli_prompt],
            timeout=10,
        )
        if pattern == auth_failed:
            raise RuntimeError("Failed to connect, authentication failed")

        if pattern == cli_prompt:
            self._hostname = match.group(1)
            self._connected = True

    def disconnect(self) -> None:
        if not self.connected:
            raise RuntimeError("This IOS XR console is not yet connected")

        self.wait_write("", None)
        self.wait_write("exit", self.cli_prompt)

        try:
            self._console.read_until(self.cli_prompt, timeout=1)
            raise RuntimeError("Disconnection failed")
        except TimeoutError:
            self._hostname = None
            self._connected = False

    def wait_write(self, write: str, wait: Optional[str] = None, timeout: int = 10) -> None:
        if wait is not None:
            self._console.read_until(wait, timeout)

        self._console.write(f"{write}\r")

    def expect(self, expressions: List[Pattern], timeout: Optional[int] = None) -> Tuple[Pattern, Match, str]:
        return self._console.expect(expressions, timeout)
