import math
from clab_vm_startup.utils import gen_mac


class NetworkInterfaceController:

    def __init__(
        self,
        type: str,
        index: int,
        nics_per_pci_bus: int,
    ) -> None:
        self.type = type
        self.index = index
        self.device = f"p{index:02d}"
        
        # PCI bus this interface is on
        pci_bus = math.floor(index / nics_per_pci_bus) + 1
        self.bus = f"pci.{pci_bus}"

        # Address of the interface on the pci bus
        pci_addr = (index % nics_per_pci_bus) + 1
        self.addr = f"0x{pci_addr:x}"

        self.mac = gen_mac(index)
