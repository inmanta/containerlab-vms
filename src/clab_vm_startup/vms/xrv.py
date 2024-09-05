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
import pathlib
import re
import time
from ipaddress import IPv4Address
from pathlib import Path
from textwrap import dedent
from typing import List, Optional

from clab_vm_startup.conn_mode.connection_mode import Connection
from clab_vm_startup.helpers.iosxr_console import IOSXRConsole
from clab_vm_startup.helpers.telnet_client import TelnetClient
from clab_vm_startup.host.host import Host
from clab_vm_startup.host.socat import Port, PortForwarding
from clab_vm_startup.vms.vr import VirtualRouter

LOGGER = logging.getLogger(__name__)

# https://github.com/hellt/vrnetlab/blob/1d9928a33f45ecd630604f13b21d1a52d8229e6d/xrv/docker/launch.py#L15
# The startup config will be mounted by containerlab inside the container
STARTUP_CONFIG_FILE = pathlib.Path("/config/startup-config.cfg")


class XRV(VirtualRouter):
    """
    This class represents a Cisco XRV9K virtual router
    """

    ROUTER_CONFIG_FOLDER_PATH = Path("/router-config/")
    ROUTER_CONFIG = "iosxr_config.txt"
    ROUTER_CONFIG_ADMIN = "iosxr_config_admin.txt"
    ROUTER_CONFIG_ISO_PATH = Path("/router-config.iso")
    CONFIG_TIMEOUT = 10 * 60  # 10 minutes

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
            forwarded_ports=[
                PortForwarding(
                    listen_port=Port.SSH,
                    target_addr=IPv4Address("127.0.0.1"),
                    target_port=Port.SSH + 2000,
                ),
                PortForwarding(
                    listen_port=Port.SNMP,
                    target_addr=IPv4Address("127.0.0.1"),
                    target_port=Port.SNMP + 2000,
                    protocol="UDP",
                ),
                PortForwarding(
                    listen_port=Port.NETCONF,
                    target_addr=IPv4Address("127.0.0.1"),
                    target_port=Port.NETCONF + 2000,
                ),
                PortForwarding(
                    listen_port=Port.GNMI,
                    target_addr=IPv4Address("127.0.0.1"),
                    target_port=17_400,
                ),
            ],
        )

        self.username = username
        self.password = password
        self.hostname = hostname

        self._xr_console: Optional[TelnetClient] = None

    @property
    def boot_args(self) -> List[str]:
        """
        Extending the boot args with the config disk and some options for cisco
        """
        args = super().boot_args

        args.extend(
            [
                "-drive",
                f"file={str(self.ROUTER_CONFIG_ISO_PATH)},media=cdrom,index=2",
            ]
        )

        return args

    def pre_start(self) -> None:
        self.ROUTER_CONFIG_FOLDER_PATH.mkdir(parents=True, exist_ok=True)

        # Generating config file
        router_config = f"""
            hostname {self.hostname}
            interface MgmtEth0/0/CPU0/0
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
        (self.ROUTER_CONFIG_FOLDER_PATH / Path(self.ROUTER_CONFIG)).write_text(router_config)

        # Generating admin config file
        router_admin_config = f"""
            !! IOS XR Admin Configuration
            username {self.username}
                group root-system
                secret 0 {self.password}
            !
            end
        """
        router_admin_config = dedent(router_admin_config.strip("\n"))
        (self.ROUTER_CONFIG_FOLDER_PATH / Path(self.ROUTER_CONFIG_ADMIN)).write_text(router_admin_config)

        # Building config iso
        _, stderr = self.host.run_command(
            ["mkisofs", "-l", "-o", str(self.ROUTER_CONFIG_ISO_PATH), str(self.ROUTER_CONFIG_FOLDER_PATH)]
        )
        if stderr:
            LOGGER.warning(f"Got some error while running mkisofs: {stderr}")

    def post_start(self) -> None:
        if self._xr_console is None:
            self._xr_console = self.get_serial_console_connection()

        start_time = time.time()
        if self.CONFIG_TIMEOUT <= 0:
            timeout = None
        else:
            timeout = self.CONFIG_TIMEOUT

        # This is the last line of cisco cryptographic product laws
        self._xr_console.read_until("export@cisco.com.", timeout=timeout)

        LOGGER.info(f"Router {self.hostname} has finished booting, waiting for the configuration to be applied")

        # Waiting for cvac config to complete
        # The following regex allows us to match logs from cvac on the console
        cvac_config_regex = re.compile(
            r"RP\/0\/0\/CPU0:(.*): cvac\[([0-9]+)\]: %MGBL-CVAC-4-CONFIG_([A-Z]+) : "
            r"Configuration was applied from file /cd0/([^\s]+). "
            r"See /disk0:/cvac.log for more details."
        )

        # Whether the configuration of the router is done
        cvac_config_done = False
        cvac_config_admin_done = False

        while not cvac_config_done or not cvac_config_admin_done:
            remaining_time = float(timeout) if timeout is not None else None
            if remaining_time is not None:
                remaining_time -= time.time() - start_time

            _, match, res = self._xr_console.expect([cvac_config_regex], timeout=remaining_time)

            utc, pid, stage, config_file = match.groups()
            if stage == "DONE":
                if config_file == self.ROUTER_CONFIG:
                    LOGGER.info(f"Router config applied from file {config_file}")
                    cvac_config_done = True
                    continue

                if config_file == self.ROUTER_CONFIG_ADMIN:
                    LOGGER.info(f"Router admin config applied from file {config_file}")
                    cvac_config_admin_done = True
                    continue

            raise RuntimeError(
                f"Unexpected match while waiting for cvac config to complete: {match.string} "
                f"(utc='{utc}',pid='{pid}',stage='{stage}',config_file='{config_file}')"
            )

        xrv_console = IOSXRConsole(self._xr_console, self.username, self.password, "RP/0/0/CPU0")
        xrv_console.connect()
        xrv_console.generate_rsa_key()

        # Load the startup config
        # https://github.com/hellt/vrnetlab/blob/1d9928a33f45ecd630604f13b21d1a52d8229e6d/xrv/docker/launch.py#L226-L232
        if STARTUP_CONFIG_FILE.is_file():
            LOGGER.info("Apply startup config")
            with xrv_console.exclusive_configuration():
                for line in STARTUP_CONFIG_FILE.read_text().split("\n"):
                    xrv_console.wait_write(line)
        else:
            LOGGER.info("No startup config found at %s", STARTUP_CONFIG_FILE)

        xrv_console.disconnect()

    def pre_stop(self) -> None:
        if self._xr_console is not None:
            LOGGER.debug("Closing connection to xr console")
            self._xr_console.close()
            self._xr_console = None

    def post_stop(self) -> None:
        pass
