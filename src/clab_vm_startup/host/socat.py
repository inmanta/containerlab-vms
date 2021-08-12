import logging
from ipaddress import IPv4Address
from typing import Optional
import subprocess
import threading
from clab_vm_startup.utils import io_logger
import enum

LOGGER = logging.getLogger(__name__)


class Port(enum.Enum, int):
    SSH = 22
    HTTP = 80
    SNMP = 161
    HTTPS = 443
    NETCONF = 830
    GNMI = 57_400

class PortForwarding:

    def __init__(self, listen_port: int, target_addr: IPv4Address, target_port: int, protocol: str = "TCP") -> None:
        self.listen_port = listen_port
        self.target_addr = target_addr
        self.target_port = target_port
        self.protocol = protocol

        self._process: Optional[subprocess.Popen] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
    
    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def cmd(self) -> str:
        return (
            f"socat {self.protocol.upper()}-LISTEN:{self.listen_port},fork "
            f"{self.protocol}:{str(self.target_addr)}:{self.target_port}"
        )
    
    def start(self) -> None:
        if self.running:
            raise RuntimeError("This port forwarding process is already running")
        
        self._process = subprocess.Popen(
            self.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        def stop_logging() -> bool:
            return not self.running

        self._stdout_thread = threading.Thread(
            target=io_logger,
            args=(
                self._process.stdout,
                f"socat-{self.listen_port}[{self._process.pid}]-stdout",
                stop_logging,
            ),
        )
        self._stdout_thread.start()

        self._stderr_thread = threading.Thread(
            target=io_logger,
            args=(
                self._process.stderr,
                f"socat-{self.listen_port}[{self._process.pid}]-stderr",
                stop_logging,
            ),
        )
        self._stderr_thread.start()

        LOGGER.info(f"Fort forwarding started successfully with command `{self.cmd}`")

    def stop(self) -> None:
        if not self.running:
            raise RuntimeError("This port forwarding process is not running")

        if self._process:
            self._process.kill()
            self._process.wait(5)
            self._process = None

        if self._stdout_thread:
            self._stdout_thread.join(5)
            if self._stdout_thread.is_alive():
                LOGGER.warning("Failed to join the stdout io logging thread")

        if self._stderr_thread:
            self._stderr_thread.join(5)
            if self._stderr_thread.is_alive():
                LOGGER.warning("Failed to join the stderr io logging thread")

        LOGGER.info(f"Stopped port forwarding `{self.cmd}`")
