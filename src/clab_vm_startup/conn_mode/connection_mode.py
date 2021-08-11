from abc import abstractmethod
import enum
from typing import List, Tuple

from clab_vm_startup.host.host import Host
from clab_vm_startup.host.nic import NetworkInterfaceController


class ConnectionMode(enum.Enum, str):
    TC = "tc"


class Connection:

    def __init__(self, mode: ConnectionMode) -> None:
        self.mode = mode
    
    @abstractmethod
    def setup_host(self, host: Host) -> None:
        pass

    def qemu_nic_args(self, nic: NetworkInterfaceController) -> List[Tuple[str, str]]:
        return [
            (
                "-device",
                f"{nic.type},netdev={nic.device},mac={nic.mac},bus={nic.bus},addr={nic.addr}"
            ),
        ]
