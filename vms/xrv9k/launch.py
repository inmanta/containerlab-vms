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
import os
import signal
from pathlib import Path
from types import FrameType

import click  # type: ignore
from clab_vm_startup.conn_mode.connection_mode import ConnectionMode
from clab_vm_startup.conn_mode.traffic_control import TrafficControlConnection
from clab_vm_startup.helpers.utils import setup_logging
from clab_vm_startup.host.host import Host
from clab_vm_startup.vms.xrv9k import XRV9K

LOGGER = logging.getLogger(__name__)


@click.command()
@click.option(
    "--trace",
    is_flag=True,
    help="Enable trace level logging",
)
@click.option(
    "--hostname",
    default="vr-xrv9k",
    show_default=True,
    help="Router hostname",
)
@click.option(
    "--username",
    default="vrnetlab",
    show_default=True,
    help="Username",
)
@click.option(
    "--password",
    default="VR-netlab9",
    show_default=True,
    help="Password",
)
@click.option(
    "--nics",
    default=128,
    show_default=True,
    help="Number of NICS",
)
@click.option(
    "--vcpu",
    default=2,
    show_default=True,
    help="Number of cpu cores to use",
)
@click.option(
    "--ram",
    default=12228,
    show_default=True,
    help="Amount of RAM (in MB) to use",
)
@click.option(
    "--connection-mode",
    default=ConnectionMode.TC.value,
    show_default=True,
    help="Connection mode to use in the datapath",
)
def main(
    trace: bool,
    hostname: str,
    username: str,
    password: str,
    nics: int,
    vcpu: int,
    ram: int,
    connection_mode: str,
) -> None:
    setup_logging(trace)

    # The user can overwrite the config timeout by setting the env variable `CONFIG_TIMEOUT`
    CONFIG_TIMEOUT_OVERWRITE = os.getenv("CONFIG_TIMEOUT")
    if CONFIG_TIMEOUT_OVERWRITE is not None:
        LOGGER.warning(f"Overwriting config timeout with new value: {CONFIG_TIMEOUT_OVERWRITE}")
        XRV9K.CONFIG_TIMEOUT = int(CONFIG_TIMEOUT_OVERWRITE)

    # Containerlab will setup some interfaces on its own
    expected_provisioned_nics_count = int(os.getenv("CLAB_INTFS", default=0))

    # Checking the connection mode entered by the user
    if connection_mode == ConnectionMode.TC:
        connection = TrafficControlConnection()
    else:
        raise ValueError(f"Unknown connection mode: {connection_mode}")

    host = Host(expected_provisioned_nics_count)

    # Finding disk image
    disk_image_folder = Path("/")
    disk_image_files = list(disk_image_folder.glob("*.qcow2"))
    if len(disk_image_files) != 1:
        raise RuntimeError("Couldn't find the router image file.")

    # Generating overlay copy of the disk image
    disk_image_file = str(disk_image_files[0])
    overlay_disk_image_file = disk_image_file.strip(".qcow2") + "-overlay.qcow2"
    host.run_command(
        [
            "qemu-img",
            "create",
            "-f",
            "qcow2",
            "-b",
            disk_image_file,
            overlay_disk_image_file,
        ]
    )

    xrv9k = XRV9K(
        host=host,
        connection=connection,
        disk_image=overlay_disk_image_file,
        vcpus=vcpu,
        ram=ram,
        nics=nics,
        username=username,
        password=password,
        hostname=hostname,
    )

    def handle_stop_signal(signum: int, frame: FrameType):
        xrv9k.stop()

    signal.signal(signal.SIGTERM, handle_stop_signal)
    signal.signal(signal.SIGINT, handle_stop_signal)

    try:
        xrv9k.start()
    except Exception as e:
        xrv9k.stop()
        raise e


if __name__ == "__main__":
    main()
