import logging
import os
from clab_vm_startup.conn_mode import ConnectionMode
from clab_vm_startup.conn_mode import TrafficControlConnection
from clab_vm_startup.host import Host
from clab_vm_startup.vms.xrv9k import XRV9K
import click
import sys
import time
from pathlib import Path


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
    logger = logging.getLogger()
    if trace:
        logger.setLevel(logging.DEBUG)

    # Containerlab will setup some interfaces on its own
    expected_provisioned_nics_count = int(os.getenv("CLAB_INTFS", default=0))

    # User can ask for a delay before booting the vm
    delay = int(os.getenv("BOOT_DELAY", default=0))
    if delay:
        logger.info(f"Delaying VM boot of by {delay} seconds")
        time.sleep(delay)

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

    # Genrating overlay copy of the disk image
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
    xrv9k.start()
    xrv9k.generate_rsa_key()

    sys.exit(0)


if __name__ == "__main__":
    main()
