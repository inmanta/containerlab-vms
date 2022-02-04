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
from ipaddress import IPv4Address
from pathlib import Path
from textwrap import dedent
from typing import List, Optional, Tuple

from clab_vm_startup.conn_mode.connection_mode import Connection
from clab_vm_startup.helpers.iosxr_console import IOSXRConsole
from clab_vm_startup.helpers.telnet_client import TelnetClient
from clab_vm_startup.helpers.utils import gen_mac
from clab_vm_startup.host.host import Host
from clab_vm_startup.host.socat import Port, PortForwarding
from clab_vm_startup.vms.vr import VirtualRouter

LOGGER = logging.getLogger(__name__)


class XRV9K(VirtualRouter):
    """
    This class represents a Cisco XRV9K virtual router
    """

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
                ("-smbios", 'type=1,manufacturer="cisco",product="Cisco IOS XRv 9000",uuid=97fc351b-431d-4cf2-9c01-43c283faf2a3'),
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
                "once=d",
            ]
        )

        return args

    def pre_start(self) -> None:
        pass

    def post_start(self) -> None:
        if self._xr_console is None:
            self._xr_console = self.get_serial_console_connection()

        start_time = time.time()
        if self.CONFIG_TIMEOUT <= 0:
            timeout = None
        else:
            timeout = self.CONFIG_TIMEOUT

        self._xr_console.read_until("export@cisco.com.", timeout=timeout)

        LOGGER.info(f"Router {self.hostname} has finished booting, it is ready to be configured")

        self._xr_console.write("\r")
        self._xr_console.read_until("Enter root-system username:", timeout=30)
        self._xr_console.write(f"{self.username}\r")
        self._xr_console.read_until("Enter secret:", timeout=30)
        self._xr_console.write(f"{self.password}\r")
        self._xr_console.read_until("Enter secret again:", timeout=30)
        self._xr_console.write(f"{self.password}\r")

        xrv_console = IOSXRConsole(self._xr_console, self.username, self.password, "RP/0/RP0/CPU0")
        xrv_console.connect()
        xrv_console.generate_rsa_key()

        xrv_console.wait_write("configure")

        # Configuring hostname
        xrv_console.wait_write(f"hostname {self.hostname}")

        # Configuring management interface
        xrv_console.wait_write("interface MgmtEth0/RP0/CPU0/0")
        xrv_console.wait_write(f"ipv4 address {str(self.ip_address)}/{self.ip_network.prefixlen}")
        xrv_console.wait_write("no shutdown")
        xrv_console.wait_write("exit")

        # Configuring xml agent
        xrv_console.wait_write("xml agent tty")
        xrv_console.wait_write("iteration off")
        xrv_console.wait_write("exit")

        # Configuring netconf agent
        xrv_console.wait_write("netconf agent tty")
        xrv_console.wait_write("exit")

        # Configuring netconf-yang agent
        xrv_console.wait_write("netconf-yang agent")
        xrv_console.wait_write("ssh")
        xrv_console.wait_write("exit")

        # Configuring ssh
        xrv_console.wait_write("ssh server v2")
        xrv_console.wait_write("ssh server netconf port 830")
        xrv_console.wait_write("ssh server vrf default")

        # Commiting changes
        xrv_console.wait_write("commit")
        xrv_console.wait_write("exit")

        xrv_console.disconnect()

    def pre_stop(self) -> None:
        if self._xr_console is not None:
            LOGGER.debug("Closing connection to xr console")
            self._xr_console.close()
            self._xr_console = None

    def post_stop(self) -> None:
        pass
