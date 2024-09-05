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
from abc import abstractmethod
from typing import List, Tuple

from clab_vm_startup.host.host import Host
from clab_vm_startup.host.nic import NetworkInterfaceController


class ConnectionMode(str, enum.Enum):
    TC = "tc"


class Connection:
    """
    Connection class, parent class for all connection modes.
    A VM has a connection mode, which defines how it sets up its interface and how those
    are linked to the host and reachable from outside of the host.

    For each supported connection mode, a new class inheriting from this one should be created.
    """

    def __init__(self, mode: ConnectionMode) -> None:
        self.mode = mode

    @abstractmethod
    def setup_host(self, host: Host) -> None:
        """
        This has to be implemented by inheriting classes.

        This method will be called before VM startup, in case the connection mode has to configure
        the host in some way.
        """

    def qemu_nic_args(self, nic: NetworkInterfaceController) -> List[Tuple[str, str]]:
        """
        This can be extended by inheriting classes.

        This method will be called when generating the boot arguments of the VM.  If this connection
        mode requires some additional arguments, this is the place to set them.
        """
        return [
            ("-device", f"{nic.type},netdev={nic.device},mac={nic.mac},bus={nic.bus},addr={nic.addr}"),
        ]
