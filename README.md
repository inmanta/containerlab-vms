# containerlab-vms

This project is meant to help building containerlab compatible containers, running virtual routers inside of them.  This has been highly inspired by the vrntelab project.  The working principle is the same as the aforementioned project, but the inner structure of the code has been revised to fix stability issues we have encountered.

## Supported vendors

 1. `Cisco`
    1. [`xrv`](vms/xrv)
    2. [`xrv9k`](vms/xrv9k)

## Package structure
```
src/clab_vm_startup/
├── conn_mode
│   ├── connection_mode.py
│   ├── __init__.py
│   └── traffic_control.py
├── helpers
│   ├── iosxr_console.py
│   ├── telnet_client.py
│   └── utils.py
├── host
│   ├── host.py
│   ├── __init__.py
│   ├── nic.py
│   └── socat.py
├── __init__.py
└── vms
    ├── __init__.py
    ├── vr.py
    ├── xrv9k.py
    └── xrv.py
```

## Build containers

### Base image: inmantaci/containerlab-vms

This is the base container for all the virtual router ones.  Its base image is ubuntu:20.04.  It installs some common dependencies to all the virtual routers, create a python virtual environment and installs this package source in it.

```console
~/containerlab-vms$ make
...
Successfully tagged inmantaci/containerlab-vms:tmp
docker tag inmantaci/containerlab-vms:tmp inmantaci/containerlab-vms:$(docker run --rm inmantaci/containerlab-vms:tmp -c "import pkg_resources; v = pkg_resources.get_distribution('containerlab-vms').version; print(v)")
docker rmi inmantaci/containerlab-vms:tmp
Untagged: inmantaci/containerlab-vms:tmp
~/containerlab-vms$ docker images
REPOSITORY                      TAG       IMAGE ID       CREATED          SIZE
inmantaci/containerlab-vms      0.0.1     1f20d50aaa08   2 minutes ago    454MB
ubuntu                          20.04     1318b700e415   3 weeks ago      72.8MB
```

### Virtual router images

Each of the supported virtual router container can be build from its own folder, by running the make command.  For this to work, you need to place your vm image in that same folder before running the command.

```console
~/containerlab-vms$ cd vms/xrv
~/containerlab-vms/vms/xrv$ make
...
Successfully tagged containerlab/vr-xrv:6.3.1
~/containerlab-vms/vms/xrv$ docker images
REPOSITORY                      TAG       IMAGE ID       CREATED          SIZE
containerlab/vr-xrv             6.3.1     e006d956bb22   30 seconds ago   911MB
inmantaci/containerlab-vms      0.0.1     1f20d50aaa08   7 minutes ago    454MB
ubuntu                          20.04     1318b700e415   3 weeks ago      72.8MB
```
