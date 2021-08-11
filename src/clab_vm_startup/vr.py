from pathlib import Path
from typing import List, Optional, Sequence, Tuple
import subprocess
from telnetlib import Telnet
import math
import os
import time
from clab_vm_startup.conn_mode import Connection
from clab_vm_startup.host.host import Host
from clab_vm_startup.host.nic import NetworkInterfaceController

from clab_vm_startup.utils import gen_mac


class VirtualRouter:

    NICS_PER_PCI_BUS = 26  # Tested to work with Xrv
    NIC_TYPE = "e1000"
    TFTP_FOLDER = Path("/tftpboot")

    # Those are the ports to do the forwarding to
    SSH_PORT = 2022
    SNMP_PORT = 2161
    NETCONF_PORT = 2830
    HTTP_PORT = 2080
    HTTPS_PORT = 2443

    def __init__(
        self,
        host: Host,
        connection: Connection,
        disk_image: str = None,
        vcpus: int = 1,
        ram: int = 4096,
        nics: int = 0,
    ) -> None:
        self.host = host
        self.connection = connection
        self.disk_image = disk_image
        self.vcpus = vcpus
        self.ram = ram
        self.nics = nics

        self._boot_process: Optional[subprocess.Popen] = None
        self._qemu_monitor: Optional[Telnet] = None

    @property
    def running(self) -> bool:
        return self._boot_process is not None

    @property
    def _mgmt_interface_boot_args(self) -> Sequence[Tuple[str, str]]:
        return [
            ("-device", f"{self.NIC_TYPE},netdev=p00,mac={gen_mac(0)}"),
            (
                "-netdev",
                "user,id=p00,net=10.0.0.0/24,"
                f"tftp={str(self.TFTP_FOLDER)},"
                f"hostfwd=tcp::{self.SSH_PORT}-10.0.0.15:22,"
                f"hostfwd=udp::{self.SNMP_PORT}-10.0.0.15:161,"
                f"hostfwd=tcp::{self.NETCONF_PORT}-10.0.0.15:830,"
                f"hostfwd=tcp::{self.HTTP_PORT}-10.0.0.15:80,"
                f"hostfwd=tcp::{self.HTTPS_PORT}-10.0.0.15:443"
            ),
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
                qemu_args.append(
                    ("-device", f"{self.NIC_TYPE},netdev={nic.device},bus={nic.bus},addr={nic.addr}")
                )
                qemu_args.append(
                    ("-netdev", f"socket,id={nic.device},listen=:{10_000 + nic_index}")
                )
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
            ("-serial", "telnet:0.0.0.0:5000,server,nowait"),
            ("-drive", f"if=ide,file={self.disk_image}"),
        ]

        # Using KVM if it is available
        if os.path.exists("/dev/kvm"):
            qemu_args.insert(1, ("-enable-kvm",))

        # Setup PCI buses
        num_pci_buses = math.ceil(self.nics / self.NICS_PER_PCI_BUS)
        for pci in range(1, num_pci_buses + 1):
            qemu_args.append(
                ("-device", f"pci-bridge,chassis_nr={pci},id=pci.{pci}")
            )

        # Setup mgmt interface args
        qemu_args.extend(self._mgmt_interface_boot_args)

        # Setup nics args
        qemu_args.extend(self._nics_boot_args)

        return [
            elem
            for arg in qemu_args
            for elem in arg
        ]

    def pre_start(self) -> None:
        """
            Overwrite this in inheriting classes
        """

    def _start(self) -> None:
        # Starting vm process
        boot_command = " ".join(self.boot_args)
        self._boot_process = subprocess.Popen(
            boot_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            shell=True,
            executable="/bin/bash",
        )

        # Connecting to qemu monitor
        max_retry = 5
        for _ in range(0, max_retry):
            try:
                connection = Telnet("127.0.0.1", 4000)
                self._qemu_monitor = connection
                break
            except:
                pass

            time.sleep(1)

        if self._qemu_monitor is None:
            raise RuntimeError(f"Failed to connect to qemu monitor after {max_retry} attempts")


    def post_start(self) -> None:
        """
            Overwrite this in inheriting classes
        """

    def start(self) -> None:
        """
            Start the VM, if it hasn't been started before.
        """
        if self.running:
            raise RuntimeError("Can not start the vm, it is already running")

        self.TFTP_FOLDER.mkdir(parents=True, exist_ok=True)

        # Setting up the host connections
        self.connection.setup_host(self.host)

        # Waiting for all expected nics to show on the host
        self.host.wait_provisioned_nics()

        # Running pre-start step, any vm class inheriting from this class can run extra step in there
        self.pre_start()

        # Starting the vm and the qemu monitor console
        self._start()

        # Running post-start step, any vm class inheriting from this class can run extra step in there
        self.post_start()

    def pre_stop(self) -> None:
        """
            Overwrite this in inheriting classes
        """

    def _stop(self) -> None:
        """
            Stops the VM and close the telnet connection
        """
        if self._qemu_monitor is not None:
            # TODO graceful shutdown with `system_powerdown`
            self._qemu_monitor.close()

    def post_stop(self) -> None:
        """
            Overwrite this in inheriting classes
        """

    def stop(self) -> None:
        """
            Stop the VM, if it is running.
        """
        if not self.running:
            raise RuntimeError("Can not stop the vm, it is not running")

        # Running pre-stop step, any vm class inheriting from this class can run extra step in there
        self.pre_stop()

        # Stopping the vm and the qemu monitor console
        self._stop()

        # Running post-stop step, any vm class inheriting from this class can run extra step in there
        self.post_stop()
