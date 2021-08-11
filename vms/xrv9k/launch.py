from pathlib import Path
from telnetlib import Telnet
from typing import List, Optional, Sequence, Tuple
from clab_vm_startup.conn_mode import Connection
from clab_vm_startup.host.host import Host
from clab_vm_startup.utils import gen_mac
from clab_vm_startup.vr import VirtualRouter
from textwrap import dedent
import time


class XRV9K(VirtualRouter):

    ROUTER_CONFIG_PATH = Path("/router-config/iosxr_config.txt")
    ROUTER_CONFIG_ISO_PATH = Path("/router-config.iso")

    GNMI_PORT = 17400
    
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
        super().__init__(host, connection, disk_image=disk_image, vcpus=vcpus, ram=ram, nics=nics)

        self.username = username
        self.password = password
        self.hostname = hostname

        self._xr_console: Optional[Telnet] = None

    @property
    def _mgmt_interface_boot_args(self) -> Sequence[Tuple[str, str]]:
        return [
            ("-device", f"virtio-net-pci,netdev=mgmt,mac={gen_mac(0)}"),
            (
                "-netdev",
                "user,id=mgmt,net=10.0.0.0/24,"
                f"tftp={str(self.TFTP_FOLDER)},"
                f"hostfwd=tcp::{self.SSH_PORT}-10.0.0.15:22,"
                f"hostfwd=udp::{self.SNMP_PORT}-10.0.0.15:161,"
                f"hostfwd=tcp::{self.NETCONF_PORT}-10.0.0.15:830,"
                f"hostfwd=tcp::{self.GNMI_PORT}-10.0.0.15:57400"
            ),
            ("-device", f"virtio-net-pci,netdev=ctrl-dummy,id=ctrl-dummy,mac={gen_mac(0)}"),
            ("-netdev", "tap,ifname=ctrl-dummy,id=ctrl-dummy,script=no,downscript=no"),
            ("-device", f"virtio-net-pci,netdev=dev-dummy,id=dev-dummy,mac={gen_mac(0)}"),
            ("-netdev", "tap,ifname=dev-dummy,id=dev-dummy,script=no,downscript=no"),
        ]

    @property
    def boot_args(self) -> List[str]:
        args = super().boot_args

        args.extend(
            [
                "-machine", "smm=off",
                "-boot", "order=c",
                "-drive", f"file={str(self.ROUTER_CONFIG_ISO_PATH)},media=cdrom,index=2",
                "-serial", "telnet:0.0.0.0:5001,server,nowait",
                "-serial", "telnet:0.0.0.0:5002,server,nowait",
                "-serial", "telnet:0.0.0.0:5003,server,nowait",
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
                ipv4 address 10.0.0.15/24
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
        self.host.run_command(["mkisofs", "-l", "-o", str(self.ROUTER_CONFIG_ISO_PATH), str(self.ROUTER_CONFIG_PATH.parent)])

    def post_start(self) -> None:
        # Connecting to qemu monitor
        max_retry = 5
        for _ in range(0, max_retry):
            try:
                connection = Telnet("127.0.0.1", 4000)
                self._xr_console = connection
                break
            except:
                pass

            time.sleep(1)

        if self._xr_console is None:
            raise RuntimeError(f"Failed to connect to xr console after {max_retry} attempts")
