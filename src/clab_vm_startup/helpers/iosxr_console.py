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
from typing import Optional

from clab_vm_startup.helpers.telnet_client import TelnetClient

LOGGER = logging.getLogger(__name__)


class IOSXRConsole:
    """
    Helper class for interacting with the IOSXR console.  This requires an open telnet connection.
    """
    def __init__(self, serial_console: TelnetClient, username: str, password: str, cli_prefix: str) -> None:
        """
        :param serial_console: The telenet connection already open to the serial console
        :param username: The username to use to connect to the console
        :param password: The password to use to connect to the console
        :param cli_prefix: The cli profix that is expected to be show when we are connected
        """
        self.username = username
        self.password = password

        self._cli_prefix = cli_prefix
        self._hostname: Optional[str] = None

        self._console = serial_console
        self._connected = False
        self._remainder = ""

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def cli_prompt(self) -> str:
        return f"{self._cli_prefix}:{self._hostname}#"

    def connect(self) -> None:
        """
        Connect to the IOS console, using the username and password passed to the constructor
        """
        if self.connected:
            raise RuntimeError("This IOS XR console is already connected")

        username_prompt = re.compile("Username:")
        cli_prompt = re.compile(r"{prefix}:([^\s]+)#".format(prefix=self._cli_prefix))
        auth_failed = re.compile("% User Authentication failed")

        # Triggering login prompt
        self.wait_write("", None)

        pattern, match, _ = self._console.expect(
            [username_prompt, cli_prompt],
            timeout=10,
        )
        if pattern == cli_prompt:
            LOGGER.info("The IOS console was already open")
            self._hostname = match.group(1)
            self._connected = True
            return

        if pattern == username_prompt:
            self.wait_write(self.username, None)
            self.wait_write(self.password, "Password:")
        
        pattern, match, _ = self._console.expect(
            [auth_failed, cli_prompt],
            timeout=10,
        )
        if pattern == auth_failed:
            raise RuntimeError("Failed to connect, authentication failed")

        if pattern == cli_prompt:
            self._hostname = match.group(1)
            self._connected = True

    def disconnect(self) -> None:
        """
        Disconnect from the IOS console
        """
        if not self.connected:
            raise RuntimeError("This IOS XR console is not yet connected")

        self.wait_write("exit", self.cli_prompt)

        try:
            self._console.read_until(self.cli_prompt, timeout=1)
            raise RuntimeError("Disconnection failed, we shouldn't have got our prompt back but did")
        except TimeoutError:
            self._hostname = None
            self._connected = False

    def wait_write(self, write: str, wait: Optional[str] = None, timeout: int = 10) -> None:
        """
        Wait for a string to appear to write another string.

        :param write: The string to write
        :param wait: The string to wait for, if none is provided we don't wait before writing
        :param timeout: The maximum time we can wait before writing, if this time is exceeded,
            a TimeoutError is raised.
        """
        if wait is not None:
            self._console.read_until(wait, timeout)

        self._console.write(f"{write}\r")

    def generate_rsa_key(self) -> None:
        """
        If you are connected to the console, you can call this to setup the ssh rsa keys on the router.
        If no key is configured a new one of 2048 bits is created, otherwise the existing one is kept.
        """
        if not self.connected:
            raise RuntimeError("You should be connected to the console to setup the rsa key")

        LOGGER.info("Configuring rsa key")
        self.wait_write("")
        self.wait_write("terminal length 0", self.cli_prompt)
        self.wait_write("crypto key generate rsa", self.cli_prompt)

        # check if we are prompted to overwrite current keys
        new_key = re.compile("How many bits in the modulus")
        key_exists = re.compile("Do you really want to replace them")
        pattern, _, _ = self._console.expect(
            [
                new_key,
                key_exists,
                re.compile(self.cli_prompt),
            ],
            10,
        )
        if pattern == new_key:
            self.wait_write("2048", None)
            LOGGER.info("Rsa key configured")

        elif pattern == key_exists:
            self.wait_write("no", None)
            LOGGER.info("Rsa key was already configured")

