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
import datetime
import logging
import math
import os
import subprocess
import threading
import time
from abc import abstractmethod
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from telnetlib import Telnet
from typing import List, Optional, Sequence, Tuple

from clab_vm_startup.conn_mode import Connection
from clab_vm_startup.host.host import Host
from clab_vm_startup.host.nic import NetworkInterfaceController
from clab_vm_startup.host.socat import PortForwarding
from clab_vm_startup.utils import gen_mac, io_logger

LOGGER = logging.getLogger(__name__)


class VirtualRouter:

    NICS_PER_PCI_BUS = 26  # Tested to work with Xrv
    NIC_TYPE = "e1000"
    TFTP_FOLDER = Path("/tftpboot")

    def __init__(
        self,
        host: Host,
        connection: Connection,
        disk_image: str = None,
        vcpus: int = 1,
        ram: int = 4096,
        nics: int = 0,
        mgmt_nic_type: Optional[str] = None,
        forwarded_ports: Optional[List[PortForwarding]] = None,
    ) -> None:
        self.host = host
        self.connection = connection
        self.disk_image = disk_image
        self.vcpus = vcpus
        self.ram = ram
        self.nics = nics
        self.ip_address = IPv4Address("10.0.0.15")
        self.ip_network = IPv4Network("10.0.0.0/24")
        self.mgmt_nic_type = mgmt_nic_type or self.NIC_TYPE
        self.forwarded_ports = forwarded_ports or []

        self._boot_process: Optional[subprocess.Popen] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._qemu_monitor: Optional[Telnet] = None

    @property
    def running(self) -> bool:
        return self._boot_process is not None and self._boot_process.returncode is None

    @property
    def _mgmt_interface_boot_args(self) -> List[Tuple[str, str]]:
        hostfwd = ""
        for forwarded_port in self.forwarded_ports:
            hostfwd += (
                f",hostfwd={forwarded_port.protocol.lower()}::{forwarded_port.target_port}-"
                f"{str(self.ip_address)}:{forwarded_port.listen_port}"
            )

        return [
            ("-device", f"{self.mgmt_nic_type},netdev=mgmt,mac={gen_mac(0)}"),
            ("-netdev", f"user,id=mgmt,net={str(self.ip_network)}," f"tftp={str(self.TFTP_FOLDER)}{hostfwd}"),
        ]

    @property
    def _nics_boot_args(self) -> Sequence[Tuple[str, str]]:
        qemu_args = []

        for nic_index in range(1, self.nics + 1):

            nic = NetworkInterfaceController(
                type=self.NIC_TYPE,
                index=nic_index,
                nics_per_pci_bus=self.NICS_PER_PCI_BUS,
            )

            # If the matching container interface ethX doesn't exist, we don't create a nic
            if not self.host.has_interface(f"eth{nic_index}"):
                if nic_index >= self.host.highest_provisioned_nic_num:
                    continue

                # Current intf number is *under* the highest provisioned nic number, so we need
                # to allocate a "dummy" interface so that when the users data plane interface is
                # actually provisioned it is provisioned in the appropriate "slot"
                qemu_args.append(("-device", f"{self.NIC_TYPE},netdev={nic.device},bus={nic.bus},addr={nic.addr}"))
                qemu_args.append(("-netdev", f"socket,id={nic.device},listen=:{10_000 + nic_index}"))
                continue

            # Else, we extend the arguments with whatever the connection requires
            qemu_args.extend(self.connection.qemu_nic_args(nic))

        return qemu_args

    @property
    def boot_args(self) -> List[str]:
        qemu_args = [
            ("qemu-system-x96_64",),
            ("-display", "none"),
            ("-machine", "pc"),
            ("-m", str(self.ram)),
            ("-cpu", "host"),
            ("-smp", f"cores={self.vcpus},threads=1,sockets=1"),
            ("-monitor", "tcp:0.0.0.0:4000,server,nowait"),
            ("-drive", f"if=ide,file={self.disk_image}"),
        ]

        # Using KVM if it is available
        if os.path.exists("/dev/kvm"):
            qemu_args.insert(1, ("-enable-kvm",))

        # Setup PCI buses
        num_pci_buses = math.ceil(self.nics / self.NICS_PER_PCI_BUS)
        for pci in range(1, num_pci_buses + 1):
            qemu_args.append(("-device", f"pci-bridge,chassis_nr={pci},id=pci.{pci}"))

        # Setup mgmt interface args
        qemu_args.extend(self._mgmt_interface_boot_args)

        # Setup nics args
        qemu_args.extend(self._nics_boot_args)

        return [elem for arg in qemu_args for elem in arg]

    @abstractmethod
    def pre_start(self) -> None:
        """
        This method will be called before the VM is started.
        """

    def _start(self) -> None:
        # Starting vm process
        boot_args = self.boot_args
        boot_command = " ".join(boot_args)
        LOGGER.debug(f"VM boot command: {boot_command}")
        self._boot_process = subprocess.Popen(
            boot_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            shell=True,
            executable="/bin/bash",
        )

        def stop_logging() -> bool:
            return not self.running

        self._stdout_thread = threading.Thread(
            target=io_logger,
            args=(
                self._boot_process.stdout,
                f"{boot_args[0]}[{self._boot_process.pid}]-stdout",
                stop_logging,
            ),
        )
        self._stdout_thread.start()

        self._stderr_thread = threading.Thread(
            target=io_logger,
            args=(
                self._boot_process.stderr,
                f"{boot_args[0]}[{self._boot_process.pid}]-stderr",
                stop_logging,
            ),
        )
        self._stderr_thread.start()

        # Connecting to qemu monitor
        self._qemu_monitor = Telnet("127.0.0.1", 4000)
        LOGGER.debug("Successfully connected to QEMU monitor")

        LOGGER.debug("Starting port forwarding processes")
        for forwarded_port in self.forwarded_ports:
            if forwarded_port.running:
                LOGGER.warning("The following port forwarding process should not be running but " f"is: `{forwarded_port.cmd}`")
                continue

            forwarded_port.start()

    @abstractmethod
    def post_start(self) -> None:
        """
        This method will be called after the VM has been started.
        """

    def start(self) -> None:
        """
        Start the VM, if it hasn't been started before.
        """
        if self.running:
            raise RuntimeError("Can not start the vm, it is already running")

        LOGGER.debug("Ready to start VM")
        start_time = time.time()

        self.TFTP_FOLDER.mkdir(parents=True, exist_ok=True)

        # Setting up the host connections
        self.connection.setup_host(self.host)

        # Waiting for all expected nics to show on the host
        self.host.wait_provisioned_nics()

        # Running pre-start step, any vm class inheriting from this class can run extra step in there
        LOGGER.debug("Calling pre-start")
        self.pre_start()

        # Starting the vm and the qemu monitor console
        self._start()

        # Running post-start step, any vm class inheriting from this class can run extra step in there
        LOGGER.debug("Calling post-start")
        self.post_start()

        stop_time = time.time()
        startup_duration = datetime.timedelta(seconds=stop_time - start_time)
        LOGGER.info(f"VM was successfully started in {str(startup_duration)}")

    @abstractmethod
    def pre_stop(self) -> None:
        """
        This method will be called before the VM is stopped.
        """

    def _stop(self) -> None:
        """
        Stops the VM and close the telnet connection
        """
        LOGGER.debug("Stopping port forwarding processes")
        for forwarded_port in self.forwarded_ports:
            if not forwarded_port.running:
                LOGGER.warning("The following port forwarding process should be running but " f"isn't: `{forwarded_port.cmd}`")
                continue

            forwarded_port.stop()

        if self._qemu_monitor is not None:
            # TODO graceful shutdown with `system_powerdown`
            self._qemu_monitor.close()

        if self._boot_process:
            self._boot_process.kill()
            self._boot_process.wait(5)
            self._boot_process = None

        if self._stdout_thread:
            self._stdout_thread.join(5)
            if self._stdout_thread.is_alive():
                LOGGER.warning("Failed to join the stdout io logging thread")

        if self._stderr_thread:
            self._stderr_thread.join(5)
            if self._stderr_thread.is_alive():
                LOGGER.warning("Failed to join the stderr io logging thread")

    @abstractmethod
    def post_stop(self) -> None:
        """
        This method will be called after the VM has been stopped.
        """

    def stop(self) -> None:
        """
        Stop the VM, if it is running.
        """
        if not self.running:
            raise RuntimeError("Can not stop the vm, it is not running")

        LOGGER.debug("Ready to stop VM")
        start_time = time.time()

        # Running pre-stop step, any vm class inheriting from this class can run extra step in there
        LOGGER.debug("Calling pre-stop")
        self.pre_stop()

        # Stopping the vm and the qemu monitor console
        self._stop()

        # Running post-stop step, any vm class inheriting from this class can run extra step in there
        LOGGER.debug("Calling post-stop")
        self.post_stop()

        stop_time = time.time()
        shutdown_duration = datetime.timedelta(seconds=stop_time - start_time)
        LOGGER.info(f"VM was successfully shutdown in {str(shutdown_duration)}")
