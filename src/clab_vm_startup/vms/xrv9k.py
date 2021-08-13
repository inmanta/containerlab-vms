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
from typing import List, Optional, Tuple

from clab_vm_startup.conn_mode.connection_mode import Connection
from clab_vm_startup.host.host import Host
from clab_vm_startup.host.socat import Port, PortForwarding
from clab_vm_startup.utils import gen_mac
from clab_vm_startup.vms.vr import VirtualRouter

LOGGER = logging.getLogger(__name__)


class XRV9K(VirtualRouter):

    ROUTER_CONFIG_PATH = Path("/router-config/iosxr_config.txt")
    ROUTER_CONFIG_ISO_PATH = Path("/router-config.iso")
    CONFIG_TIMEOUT = 20 * 60  # 20 minutes

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

    @property
    def _mgmt_interface_boot_args(self) -> List[Tuple[str, str]]:
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
        args = super().boot_args

        args.extend(
            [
                "-machine",
                "smm=off",
                "-boot",
                "order=c",
                "-drive",
                f"file={str(self.ROUTER_CONFIG_ISO_PATH)},media=cdrom,index=2",
                "-serial",
                "telnet:0.0.0.0:5000,server,nowait",
                "-serial",
                "telnet:0.0.0.0:5001,server,nowait",
                "-serial",
                "telnet:0.0.0.0:5002,server,nowait",
                "-serial",
                "telnet:0.0.0.0:5003,server,nowait",
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
        xr_console = Telnet("127.0.0.1", 5000, timeout=5)

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
            if time.time() - start_time > self.CONFIG_TIMEOUT:
                raise TimeoutError("Timeout reached while waiting for router config to be applied")

            _, match, res = xr_console.expect([cvac_config_regex], timeout=1)

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

        xr_console.close()

    def generate_rsa_key(self) -> None:
        LOGGER.info("Configuring rsa key")
        xr_console = Telnet("127.0.0.1", 5000, timeout=5)

        def wait_write(cmd: str, wait: Optional[str] = "#") -> None:
            if wait is not None:
                xr_console.read_until(wait.encode())

            xr_console.write(f"{cmd}\r".encode())

        wait_write("", wait=None)

        wait_write(self.username, wait="Username:")
        wait_write(self.password, wait="Password:")

        wait_write("terminal length 0")
        wait_write("crypto key generate rsa")

        # check if we are prompted to overwrite current keys
        ridx, match, res = xr_console.expect(
            [b"How many bits in the modulus", b"Do you really want to replace them", b"^[^ ]+#"],
            10,
        )
        if match:  # got a match!
            if ridx == 0:
                wait_write("2048", None)
                LOGGER.info("Rsa key configured")
            elif ridx == 1:
                wait_write("no", None)
                LOGGER.info("Rsa key was already configured")

        wait_write("exit")

        xr_console.close()

    def pre_stop(self) -> None:
        pass

    def post_stop(self) -> None:
        pass
