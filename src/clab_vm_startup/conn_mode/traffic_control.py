from typing import List, Tuple
from .connection_mode import Connection, ConnectionMode
from clab_vm_startup.host.host import Host
from pathlib import Path
from textwrap import dedent

from clab_vm_startup.host.nic import NetworkInterfaceController


class TrafficControlConnection(Connection):

    TC_TAP_IFUP_PATH = Path("/etc/tc-tap-ifup")

    def __init__(self) -> None:
        super().__init__(ConnectionMode.TC)

    def setup_host(self, host: Host) -> None:
        ifup_script = """
            #!/bin/bash

            TAP_IF=$1
            # Get interface index number, up to 3 digits
            # tap0 -> 0
            # tap123 -> 123
            INDEX=${TAP_IF:3:3}

            ip link set $TAP_IF up
            ip link set $TAP_IF mtu 65000

            # Create tc eth <-> tap redirect rules
            tc qdisc add dev eth$INDEX ingress
            tc filter add dev eth$INDEX parent ffff: protocol all u32 match u8 0 0 action mirred egress redirect dev tap$INDEX

            tc qdisc add dev $TAP_IF ingress
            tc filter add dev $TAP_IF parent ffff: protocol all u32 match u8 0 0 action mirred egress redirect dev eth$INDEX
        """
        ifup_script = dedent(ifup_script.strip("\n"))
        self.TC_TAP_IFUP_PATH.write_text(ifup_script)
        self.TC_TAP_IFUP_PATH.lchmod(0o777)

    def qemu_nic_args(self, nic: NetworkInterfaceController) -> List[Tuple[str, str]]:
        qemu_args = super().qemu_nic_args(nic)
        qemu_args.append(
            (
                "-netdev",
                f"tap,id={nic.device},ifname=tap{nic.index},script={str(self.TC_TAP_IFUP_PATH)},downscript=no",
            )
        )
        return qemu_args
