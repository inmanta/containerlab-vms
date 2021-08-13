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
import time
from pathlib import Path
from telnetlib import Telnet
from textwrap import dedent
from typing import List, Match, Optional, Pattern, Sequence, Tuple, Union

from clab_vm_startup.conn_mode.connection_mode import Connection
from clab_vm_startup.host.host import Host
from clab_vm_startup.host.socat import Port, PortForwarding
from clab_vm_startup.utils import gen_mac
from clab_vm_startup.vms.vr import VirtualRouter

LOGGER = logging.getLogger(__name__)


class IOSXRConsole:
    def __init__(self, serial_console: Telnet, username: str, password: str) -> None:
        self.username = username
        self.password = password

        self._hostname: Optional[str] = None

        self._console = serial_console
        self._connected = False
        self.logger = logging.getLogger(f"iosxr[{self._console.host}:{self._console.port}]")
        self._remainder = ""

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def cli_prompt(self) -> str:
        return f"RP/0/RP0/CPU0:{self._hostname}#"

    def _log(self, data: str) -> str:
        lines = (self._remainder + data).split("\n")
        if lines:
            self._remainder = lines[-1]
            lines = lines[:-1]
        else:
            self._remainder = ""

        for line in lines:
            self.logger.debug(line.strip())

    def connect(self) -> None:
        if self.connected:
            raise RuntimeError("This IOS XR console is already connected")

        # Triggering login prompt
        self.wait_write("", None)
        self.wait_write(self.username, "Username:")
        self.wait_write(self.password, "Password:")

        ridx, match, res = self._console.expect(
            [b"% User Authentication failed", re.compile(r"RP\/0\/RP0\/CPU0\:(.*)\#".encode())],
            timeout=10,
        )
        self._log(res.decode())
        if not match:
            raise TimeoutError("Didn't match any of the expected value")

        if ridx == 0:
            raise RuntimeError("Failed to connect, authentication failed")

        if ridx == 1:
            self._hostname = match.group(1).decode()
            self._connected = True

    def disconnect(self) -> None:
        if not self.connected:
            raise RuntimeError("This IOS XR console is not yet connected")

        self.wait_write("", None)
        self.wait_write("exit", self.cli_prompt)

        try:
            self.wait_write("", self.cli_prompt, timeout=1)
            raise RuntimeError("Disconnection failed")
        except TimeoutError:
            self._hostname = None
            self._connected = False

    def wait_show(self, wait: str, timeout: int = 10) -> None:
        res = self._console.read_until(wait.encode(), timeout=timeout).decode()
        self._log(res)

        if wait not in res:
            raise TimeoutError(f"Timeout while waiting for '{wait}'")

    def wait_write(self, write: str, wait: Optional[str] = None, timeout: int = 10) -> None:
        if wait is not None:
            self.wait_show(wait, timeout)

        self._console.write(f"{write}\r".encode())

    def expect(
        self, list: Sequence[Union[Pattern[str], str]], timeout: Optional[float] = None
    ) -> Tuple[int, Optional[Match[bytes]], str]:
        # We accept str in input but telnetlib takes bytes, we should convert our strings to bytes
        byte_list = []
        for elem in list:
            if isinstance(elem, str):
                byte_list.append(elem.encode())
                continue

            if isinstance(elem, Pattern):
                byte_list.append(re.compile(elem.pattern.encode()))
                continue

        ridx, match, res = self._console.expect(byte_list, timeout)
        data = res.decode()
        self._log(data)
        return ridx, match, data


class XRV9K(VirtualRouter):
    """
    This class represents a Cisco XRV9K virtual router
    """

    ROUTER_CONFIG_PATH = Path("/router-config/iosxr_config.txt")
    ROUTER_CONFIG_ISO_PATH = Path("/router-config.iso")
    CONFIG_TIMEOUT = 20 * 60  # 20 minutes

    SERIAL_CONSOLE_COUNT = 4  # Number of serial console to open, cisco has 4 serial consoles

    def __init__(
        self,
        host: Host,
        connection: Connection,
        disk_image: str,
        vcpus: int,
        ram: int,
        nics: int,
        username: str,
        password: str,
        hostname: str,
    ) -> None:
        """
        :param host: The host on which we deploy this VM
        :param connection: The type of connection to setup between the host and the vm
        :param disk_image: The path to the disk image of the vm
        :param vcpus: The number of virtual cpus to give to the vm
        :param ram: The amount of ram (MB) to give to the vm
        :param nics: The amount of network interface to attach to the vm
        :param username: The username of the account to create on the router
        :param password: The password of the account to create on the router
        :param hostname: The hostname to set on the router
        """
        super().__init__(
            host,
            connection,
            disk_image=disk_image,
            vcpus=vcpus,
            ram=ram,
            nics=nics,
            mgmt_nic_type="virtio-net-pci",
            forwarded_ports=[
                PortForwarding(
                    listen_port=Port.SSH,
                    target_addr="127.0.0.1",
                    target_port=Port.SSH + 2000,
                ),
                PortForwarding(
                    listen_port=Port.SNMP,
                    target_addr="127.0.0.1",
                    target_port=Port.SNMP + 2000,
                    protocol="UDP",
                ),
                PortForwarding(
                    listen_port=Port.NETCONF,
                    target_addr="127.0.0.1",
                    target_port=Port.NETCONF + 2000,
                ),
                PortForwarding(
                    listen_port=Port.GNMI,
                    target_addr="127.0.0.1",
                    target_port=17_400,
                ),
            ],
        )

        self.username = username
        self.password = password
        self.hostname = hostname

        self._xr_console: Optional[Telnet] = None

    @property
    def _mgmt_interface_boot_args(self) -> List[Tuple[str, str]]:
        """
        Extending the mgmt interfaces config with two dummy interfaces
        """
        boot_args = super()._mgmt_interface_boot_args
        boot_args.extend(
            [
                ("-device", f"virtio-net-pci,netdev=ctrl-dummy,id=ctrl-dummy,mac={gen_mac(0)}"),
                ("-netdev", "tap,ifname=ctrl-dummy,id=ctrl-dummy,script=no,downscript=no"),
                ("-device", f"virtio-net-pci,netdev=dev-dummy,id=dev-dummy,mac={gen_mac(0)}"),
                ("-netdev", "tap,ifname=dev-dummy,id=dev-dummy,script=no,downscript=no"),
            ]
        )
        return boot_args

    @property
    def boot_args(self) -> List[str]:
        """
        Extending the boot args with the config disk and some options for cisco
        """
        args = super().boot_args

        args.extend(
            [
                "-machine",
                "smm=off",
                "-boot",
                "order=c",
                "-drive",
                f"file={str(self.ROUTER_CONFIG_ISO_PATH)},media=cdrom,index=2",
            ]
        )

        return args

    def pre_start(self) -> None:
        # Generating config file
        router_config = f"""
            hostname {self.hostname}
            username {self.username}
                group root-lr
                group cisco-support
                password {self.password}
            !
            interface MgmtEth0/RP0/CPU0/0
                ipv4 address {str(self.ip_address)}/{self.ip_network.prefixlen}
                no shutdown
            !
            !
            xml agent tty
                iteration off
            !
            netconf agent tty
            !
            netconf-yang agent
                ssh
            !
            ssh server v2
            ssh server netconf port 830
            ssh server vrf default
            end
        """
        router_config = dedent(router_config.strip("\n"))
        self.ROUTER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.ROUTER_CONFIG_PATH.write_text(router_config)

        # Building config iso
        _, stderr = self.host.run_command(
            ["mkisofs", "-l", "-o", str(self.ROUTER_CONFIG_ISO_PATH), str(self.ROUTER_CONFIG_PATH.parent)]
        )
        if stderr:
            LOGGER.warning(f"Got some error while running mkisofs: {stderr}")

    def post_start(self) -> None:
        if self._xr_console is None:
            self._xr_console = self.get_serial_console_connection()

        console_logger = logging.getLogger(self.hostname)

        # Waiting for cvac config to complete
        # The following regex allows us to match logs from cvac on the console
        cvac_config_regex = re.compile(
            r"RP\/0\/RP0\/CPU0\:(.*): cvac\[([0-9]+)\]: %MGBL-CVAC-4-CONFIG_([A-Z]+) : (.*)".encode()
        )

        # Whether the configuration of the router is done
        cvac_config_done = False

        # unfinished_line will contain any previously read data that didn't ends with an "\n".
        # This is prepended to the next batch of data we read.
        unfinished_line = ""

        start_time = time.time()
        while not cvac_config_done:
            if time.time() - start_time > self.CONFIG_TIMEOUT and self.CONFIG_TIMEOUT > 0:
                raise TimeoutError("Timeout reached while waiting for router config to be applied")

            _, match, res = self._xr_console.expect([cvac_config_regex], timeout=1)

            data = unfinished_line + res.decode("utf-8")
            if data == "":
                # Nothing got printed since last line
                continue

            lines = data.split("\n")
            if lines:
                # The last line (might be empty) is unfinished
                unfinished_line = lines[-1]

                # The lines that matter to us are all of them up to the unfinished one
                lines = lines[:-1]
            else:
                # In case we don't have any lines
                unfinished_line = ""

            for line in lines:
                # Logging the console output
                console_logger.debug(line.strip())

            if not match:
                # We didn't get any match here
                continue

            utc, pid, stage, msg = match.groups()
            if stage == b"START":
                LOGGER.info("Router configuration started")
                continue

            if stage == b"DONE":
                LOGGER.info("Router configuration completed")
                cvac_config_done = True
                continue

            raise RuntimeError(f"Unexpected match while waiting for cvac config to complete, stage is {stage}: {match.string}")

    def generate_rsa_key(self) -> None:
        LOGGER.info("Configuring rsa key")
        if self._xr_console is None:
            self._xr_console = self.get_serial_console_connection()

        console = IOSXRConsole(self._xr_console, self.username, self.password)
        console.connect()
        console.wait_write("")
        console.wait_write("terminal length 0", console.cli_prompt)
        console.wait_write("crypto key generate rsa", console.cli_prompt)

        # check if we are prompted to overwrite current keys
        ridx, match, res = console.expect(
            [
                "How many bits in the modulus",
                "Do you really want to replace them",
                console.cli_prompt,
            ],
            10,
        )
        if match:  # got a match!
            if ridx == 0:
                console.wait_write("2048", None)
                LOGGER.info("Rsa key configured")
            elif ridx == 1:
                console.wait_write("no", None)
                LOGGER.info("Rsa key was already configured")

        console.disconnect()

    def pre_stop(self) -> None:
        if self._xr_console is not None:
            LOGGER.debug("Closing connection to xr console")
            self._xr_console.close()
            self._xr_console = None

    def post_stop(self) -> None:
        pass
