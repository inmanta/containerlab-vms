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
import enum
import logging
import subprocess
import threading
from ipaddress import IPv4Address
from typing import List, Optional

from clab_vm_startup.helpers.utils import io_logger

LOGGER = logging.getLogger(__name__)


class Port(int, enum.Enum):
    SSH = 22
    HTTP = 80
    SNMP = 161
    HTTPS = 443
    NETCONF = 830
    GNMI = 57_400


class PortForwarding:
    """
    This class represents a port forwarding process running on the host.

    This port forwarding is done using socat, which has to be installed on the host.
    """

    def __init__(self, listen_port: int, target_addr: IPv4Address, target_port: int, protocol: str = "TCP") -> None:
        """
        :param listen_port: The port on the host to listen to
        :param target_addr: The address on the host to redirect the traffic to
        :param target_port: The port at the target address to redirect the traffic to
        :param protocol: The communication protocol to use (UDP/TCP)
        """
        self.listen_port = listen_port
        self.target_addr = target_addr
        self.target_port = target_port
        self.protocol = protocol

        self._process: Optional[subprocess.Popen] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None

    @property
    def started(self) -> bool:
        """
        Whether the port forwarding has been started and not stopped
        """
        return self._process is not None

    @property
    def cmd(self) -> List[str]:
        """
        The command to run to start the port forwarding
        """
        return [
            "/usr/bin/socat",
            f"{self.protocol.upper()}-LISTEN:{self.listen_port},fork",
            f"{self.protocol}:{str(self.target_addr)}:{self.target_port}",
        ]

    def start(self) -> None:
        """
        Start the port forwarding
        """
        if self.started:
            raise RuntimeError("This port forwarding process has already been started")

        # Starting the port forwarding process
        self._process = subprocess.Popen(
            self.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        # Starting logging threads
        self._stdout_thread = threading.Thread(
            target=io_logger,
            args=(
                self._process.stdout,
                f"socat-{self.listen_port}[{self._process.pid}]-stdout",
            ),
        )
        self._stdout_thread.start()

        self._stderr_thread = threading.Thread(
            target=io_logger,
            args=(
                self._process.stderr,
                f"socat-{self.listen_port}[{self._process.pid}]-stderr",
            ),
        )
        self._stderr_thread.start()

        LOGGER.info(f"Fort forwarding started successfully with command `{self.cmd}`")

    def stop(self) -> None:
        """
        Stop the port forwarding
        """
        if not self.started:
            raise RuntimeError("This port forwarding process has not been started")

        if self._process:
            self._process.kill()

            # Closing streams manually to let logging thread finish
            assert self._process.stdout is not None
            self._process.stdout.close()

            assert self._process.stderr is not None
            self._process.stderr.close()

            self._process.wait(5)
            self._process = None

        if self._stdout_thread:
            self._stdout_thread.join(5)
            if self._stdout_thread.is_alive():
                LOGGER.warning("Failed to join the stdout io logging thread")

        if self._stderr_thread:
            self._stderr_thread.join(5)
            if self._stderr_thread.is_alive():
                LOGGER.warning("Failed to join the stderr io logging thread")

        LOGGER.info(f"Stopped port forwarding `{self.cmd}`")
