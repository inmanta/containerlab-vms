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
import subprocess
import time
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

LOGGER = logging.getLogger(__name__)


class CPUVendor(str, Enum):
    INTEL = "GenuineIntel"
    AMD = "AuthenticAMD"


class Host:
    """
    This class represents the host on which the VM is running.  This host wil be in our case
    a container.

    This class contains various helper methods for actions that we might want to make when deploying
    the VM.
    """

    INTERFACES_PATH = Path("/sys/class/net")

    def __init__(self, expected_provisioned_nics_count: int) -> None:
        self._expected_provisioned_nics_count = expected_provisioned_nics_count
        self._highest_provisioned_nic_num: Optional[int] = None

    def run_command(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        shell: bool = False,
    ) -> Tuple[str, str]:
        """
        Run a command on the host and wait for its completion.

        :param cmd: The command to run
        :param cwd: The current working directory to set before running the command
        :param shell: Whether to run this command in a shell or not
        """
        LOGGER.debug(f"Running the following command on the host: {cmd}")
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            shell=shell,
            universal_newlines=True,
        )
        return process.communicate()

    def has_interface(self, name: str) -> bool:
        """
        Check if the host has the provided interface

        :param name: The name of the interface we are checking the existence of
        """
        interface = self.INTERFACES_PATH / Path(name)
        return interface.exists()

    def get_interfaces(self, pattern: str = "*") -> List[str]:
        """
        Get all the interfaces of the host matching a pattern.

        :param pattern: A pattern to match only some interfaces
        """
        return [interface.name for interface in self.INTERFACES_PATH.glob(pattern)]

    def wait_provisioned_nics(self, timeout: int = 60) -> List[str]:
        """
        The host can expect some nics to be provisioned by an external user (not this process, clab for example).
        This methods wait for those nics to appear.
        The amount of nics we expect is set in the constructor: self._expected_provisioned_nics_count

        :param timeout: Time after which we shouldn't wait for the nics anymore, and raise a TimeoutError.
        """
        start = time.time()
        while time.time() - start < timeout:
            LOGGER.debug("Waiting for provisioned nics to show up")

            # Getting all ethX interfaces
            interfaces = self.get_interfaces("eth*")

            # We exclude the mgmt interface from the count
            interfaces = list(filter(lambda interface: interface != "eth0", interfaces))

            # If we have enough interfaces we can stop waiting
            if len(interfaces) >= self._expected_provisioned_nics_count:
                LOGGER.info(f"Found all interfaces: {interfaces}")
                return interfaces

            LOGGER.debug(f"Found {len(interfaces)} out of {self._expected_provisioned_nics_count} interfaces")

            time.sleep(5)

        raise TimeoutError(
            f"Timeout of {timeout}s exceeded, not enough interfaces showed up.  "
            f"Got {len(interfaces)}, expected at least {self._expected_provisioned_nics_count}.  "
            f"Current list of interfaces (mgmt excluded) is: {interfaces}"
        )

    @property
    def highest_provisioned_nic_num(self) -> int:
        """
        Get the highest interface number from all the provisoned one.  The interface number
        is X in ethX.

        To get the highest interface number, this property first waits for all the expected
        provisoned interfaces to show up.
        """
        if self._highest_provisioned_nic_num is not None:
            return self._highest_provisioned_nic_num

        # Waiting for all expected interfaces to show
        interfaces = self.wait_provisioned_nics()

        # Regex to extract the interface number
        interface_regex = re.compile(r"eth(\d+)")

        self._highest_provisioned_nic_num = 0
        for interface in interfaces:
            interface_match = interface_regex.match(interface)
            if interface_match is None:
                raise RuntimeError(f"Failed to extract interface number from {interface}")

            interface_num = int(interface_match.group(1))
            if interface_num > self._highest_provisioned_nic_num:
                self._highest_provisioned_nic_num = interface_num

        LOGGER.debug(f"The highest interface number in {interfaces} is {self._highest_provisioned_nic_num}")

        return self._highest_provisioned_nic_num

    def get_cpu_vendor(self) -> CPUVendor:
        """
        Get the cpu vendor of the host by reading the /proc/cpuinfo file.
        """
        vendor_id_regex = re.compile(r"vendor_id(\t+| +): (\w+)")

        with open("/proc/cpuinfo", "r") as f:
            for line in f.readlines():
                match = vendor_id_regex.match(line)
                if match is not None:
                    vendor = match.group(2)
                    return CPUVendor(vendor)

        raise LookupError("Failed to find the cpu vendor id in /proc/cpuinfo")
