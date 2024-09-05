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
from typing import List, Optional, Sequence, Tuple

from clab_vm_startup.conn_mode.connection_mode import Connection
from clab_vm_startup.helpers.telnet_client import TelnetClient
from clab_vm_startup.helpers.utils import gen_mac, io_logger
from clab_vm_startup.host.host import Host
from clab_vm_startup.host.nic import NetworkInterfaceController
from clab_vm_startup.host.socat import PortForwarding

LOGGER = logging.getLogger(__name__)


class VirtualRouter:
    """
    This class represents a virtual router.
    """

    NICS_PER_PCI_BUS = 26  # Tested to work with Xrv
    NIC_TYPE = "e1000"
    TFTP_FOLDER = Path("/tftpboot")

    QEMU_MONITOR_PORT = 4000  # Port to open for the qemu monitor

    SERIAL_CONSOLE_PORT = 5000  # Port offset for the serial consoles
    SERIAL_CONSOLE_COUNT = 1  # Number of serial console to open

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
        """
        :param host: The host on which we deploy this VM
        :param connection: The type of connection to setup between the host and the vm
        :param disk_image: The path to the disk image of the vm
        :param vcpus: The number of virtual cpus to give to the vm
        :param ram: The amount of ram (MB) to give to the vm
        :param nics: The amount of network interface to attach to the vm
        :param mgmt_nic_type: The type of the mgmt interface we create and attach to the vm
        :param forwarded_ports: A list of forwarded ports going from the host to the vm
        """
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

    @property
    def started(self) -> bool:
        """
        Whether this vm has already been started and not stopped
        """
        return self._boot_process is not None

    @property
    def _mgmt_interface_boot_args(self) -> List[Tuple[str, str]]:
        """
        Qemu boot arguments to add the management interface to the vm
        """
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
        """
        Qemu boot arguments to add the interfaces to the vm
        """
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
        """
        Qemu boot arguments
        """
        qemu_args = [
            ("qemu-system-x86_64",),
            ("-display", "none"),
            ("-machine", "pc"),
            ("-m", str(self.ram)),
            ("-cpu", "host"),
            ("-smp", f"cores={self.vcpus},threads=1,sockets=1"),
            ("-monitor", f"tcp:0.0.0.0:{self.QEMU_MONITOR_PORT},server,nowait"),
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

        # Setup serial consoles
        for i in range(0, self.SERIAL_CONSOLE_COUNT):
            qemu_args.append(
                (
                    "-serial",
                    f"telnet:0.0.0.0:{self.SERIAL_CONSOLE_PORT + i},server,nowait",
                )
            )

        return [elem for arg in qemu_args for elem in arg]

    @abstractmethod
    def pre_start(self) -> None:
        """
        This method will be called before the VM is started.
        """

    def _start(self) -> None:
        """
        Start the VM and the port forwarding processes
        """
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

        # Starting logging threads
        self._stdout_thread = threading.Thread(
            target=io_logger,
            args=(
                self._boot_process.stdout,
                f"{boot_args[0]}[{self._boot_process.pid}]-stdout",
            ),
        )
        self._stdout_thread.start()

        self._stderr_thread = threading.Thread(
            target=io_logger,
            args=(
                self._boot_process.stderr,
                f"{boot_args[0]}[{self._boot_process.pid}]-stderr",
            ),
        )
        self._stderr_thread.start()

        LOGGER.debug("Starting port forwarding processes")
        for forwarded_port in self.forwarded_ports:
            if forwarded_port.started:
                LOGGER.warning(f"The following port forwarding process should not be enabled but is: `{forwarded_port.cmd}`")
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
        if self.started:
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

        # Starting the vm
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
        Stops the VM and the port forwarding processes
        """
        LOGGER.debug("Stopping port forwarding processes")
        for forwarded_port in self.forwarded_ports:
            if not forwarded_port.started:
                LOGGER.warning(f"The following port forwarding process should be running but isn't: `{forwarded_port.cmd}`")
                continue

            forwarded_port.stop()

        if self._boot_process:
            if not self._boot_process.returncode:
                self._boot_process.kill()

            # Closing streams manually to let logging thread finish
            assert self._boot_process.stdout is not None
            self._boot_process.stdout.close()

            assert self._boot_process.stderr is not None
            self._boot_process.stderr.close()

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
        if not self.started:
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

    def get_qemu_monitor_connection(self) -> TelnetClient:
        """
        Get a telnet object with an open connection to the qemu monitor.
        The caller of this method has the responsability of closing the connection.
        """
        LOGGER.debug("Opening connection to qemu monitor")
        # Connecting to qemu monitor
        max_retry = 5
        for _ in range(0, max_retry):
            try:
                qemu_monitor = TelnetClient("127.0.0.1", self.QEMU_MONITOR_PORT)
                qemu_monitor.open()
                LOGGER.debug("Successfully connected to QEMU monitor")
                return qemu_monitor
            except ConnectionRefusedError:
                pass

            time.sleep(1)

        raise RuntimeError(f"Failed to connect to QEMU monitor after {max_retry} attempts")

    def get_serial_console_connection(self, index: int = 0) -> TelnetClient:
        """
        Get a telnet object with an open connection to a serial console of the vm.
        The caller of this method has the responsability of closing the connection.
        The caller can specify an index if multiple serial console have been created.
            The index starts at zero.

        :param index: The index of the serial console to get.
        """
        if index >= self.SERIAL_CONSOLE_COUNT:
            raise ValueError(
                "The provided serial console index exceeds the highest one we created: "
                f"{index} > {self.SERIAL_CONSOLE_COUNT - 1}"
            )

        LOGGER.debug(f"Opening connection to serial console (with index={index})")
        # Connecting to qemu monitor
        max_retry = 5
        for _ in range(0, max_retry):
            try:
                xr_console = TelnetClient("127.0.0.1", self.SERIAL_CONSOLE_PORT + index)
                xr_console.open()
                LOGGER.debug("Successfully connected to serial console")
                return xr_console
            except ConnectionRefusedError:
                pass

            time.sleep(1)

        raise RuntimeError(f"Failed to connect to serial console after {max_retry} attempts")
