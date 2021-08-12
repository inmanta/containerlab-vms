import subprocess
from typing import List, Optional, Sequence, Tuple, Union
from pathlib import Path
import time
import re
import logging


LOGGER = logging.getLogger(__name__)


class Host:

    INTERFACES_PATH = Path("/sys/class/net")

    def __init__(self, expected_provisioned_nics_count: int) -> None:
        self._expected_provisioned_nics_count = expected_provisioned_nics_count
        self._highest_provisioned_nic_num: Optional[int] = None

    def run_command(
        self,
        cmd: Union[List[str], str],
        cwd: Optional[str] = None,
        shell: bool = False,
    ) -> Tuple[str, str]:
        LOGGER.debug(f"Running the following command on the host: {cmd}")
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            shell=shell,
            universal_newlines=True,
        )
        return process.communicate()

    def has_interface(self, name: str) -> bool:
        interface = self.INTERFACES_PATH / Path(name)
        return interface.exists()
    
    def get_interfaces(self, pattern: str = "*") -> Sequence[str]:
        return [
            interface.name
            for interface in self.INTERFACES_PATH.glob(pattern)
        ]

    def wait_provisioned_nics(self, timeout: int = 60) -> Sequence[str]:
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

            interface_num = int(interface_match.group(0))
            if interface_num > self._highest_provisioned_nic_num:
                self._highest_provisioned_nic_num = interface_num

        LOGGER.debug(f"The highest interface number in {interfaces} is {self._highest_provisioned_nic_num}")

        return self._highest_provisioned_nic_num
