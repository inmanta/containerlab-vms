import subprocess
import sys
from textwrap import dedent


def print_usage() -> None:
    msg: str
    msg = f"[-] Invalid argument\nRun like: {sys.argv[0]} <site_name>"
    raise IndexError(msg)


def get_site_name() -> str:
    if len(sys.argv) != 2:
        print_usage()

    site_name: str
    site_name = sys.argv[1]

    return site_name


def change_config(site_name: str) -> None:
    command: list
    command = ["ip", "link", "show", "dev", "eth1"]

    mac: str
    mac = subprocess.check_output(command).decode()
    mac = mac.split("ether")[1].split()[0]

    template = f"""
        namespaces:
          - name: {site_name}
            interfaces:
              - name: eth1
                mac: "{mac}"
        server:
          host: 0.0.0.0
          port: 8080
    """

    with open("/home/user/nfv-test-api/config.yaml", "w") as file:
        file.write(dedent(template.strip("\n")))


if __name__ == "__main__":
    site_name = get_site_name()
    change_config(site_name)
