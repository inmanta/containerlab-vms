# containerlab-vms

This project is meant to help building [containerlab](https://containerlab.srlinux.dev/) compatible containers, running virtual routers inside of them.  This has been highly inspired by the vrntelab project.  The working principle is the same as the aforementioned project, but the inner structure of the code has been revised to fix stability issues we have encountered.

## Supported vendors

 1. `Cisco`
    1. [`xrv`](vms/xrv)
    2. [`xrv9k`](vms/xrv9k)

You can find some examples of labs using the above vendors in [examples/](examples/).

## Getting started

Follow the following steps to quickly get a lab started.  This assumes you already have [Docker](https://docs.docker.com/get-docker/) and [Containerlab](https://containerlab.srlinux.dev/install/) installed on your system.

> *Example*: In each step, in addition to te generic explanation, all the actions described are reproduced as an example for a specific lab.

### 1. Get a router image

In order to build your container, you will need a router image from the vendor.  For copyright and licensing reason, we can not distribute those ourself, you will have to get them from the vendor.

> *Example*: We will use starting from now the image `iosxrv-k9-demo-6.3.1.qcow2` for Cisco `xrv`.

Place the image in the folder of the corresponding VM type.

> *Example*: The image should now be located in `vms/xrv`
> ```console
> ~/containerlab-vms$ ls -l vms/xrv
> total 446168
> -rw-rw-r-- 1 guillaume guillaume       130 aug 19 14:41 Dockerfile
> -rw-rw-r-- 1 guillaume guillaume 456857600 okt 22  2020 iosxrv-k9-demo-6.3.1.qcow2
> -rw-rw-r-- 1 guillaume guillaume      4084 aug 19 14:41 launch.py
> -rw-rw-r-- 1 guillaume guillaume       300 aug 19 14:41 Makefile 
> ```

### 2. Build the base image: inmantaci/containerlab-vms

This is the base container for all the virtual router ones.  Its base image is ubuntu:20.04.  It installs some common dependencies to all the virtual routers, create a python virtual environment and installs this package source in it.  To build the container, you can simply run the command `make` in the main folder.

> *Example*: Let's build the base image
> ```console
> ~/containerlab-vms$ make
> ...
> Successfully tagged inmantaci/containerlab-vms:tmp
> docker tag inmantaci/containerlab-vms:tmp inmantaci/containerlab-vms:$(docker run --rm inmantaci/containerlab-vms:tmp -c "import pkg_resources; v = pkg_resources.get_distribution>('containerlab-vms').version; print(v)")
> docker rmi inmantaci/containerlab-vms:tmp
> Untagged: inmantaci/containerlab-vms:tmp
> ~/containerlab-vms$ docker images
> REPOSITORY                      TAG       IMAGE ID       CREATED          SIZE
> inmantaci/containerlab-vms      0.0.1     1f20d50aaa08   2 minutes ago    454MB
> ubuntu                          20.04     1318b700e415   3 weeks ago      72.8MB
> ```

### 3. Build the virtual router images

Each virtual router can be build by simply running the `make` command in the folder of the virtual router type (the same folder in which you previously placed the router image).

> *Example*: Let's build cisco xrv virtual router image
> ```console
> ~/containerlab-vms$ cd vms/xrv
> ~/containerlab-vms/vms/xrv$ make
> ...
> Successfully tagged containerlab/vr-xrv:6.3.1
> ~/containerlab-vms/vms/xrv$ docker images
> REPOSITORY                      TAG       IMAGE ID       CREATED          SIZE
> containerlab/vr-xrv             6.3.1     e006d956bb22   30 seconds ago   911MB
> inmantaci/containerlab-vms      0.0.1     1f20d50aaa08   7 minutes ago    454MB
> ubuntu                          20.04     1318b700e415   3 weeks ago      72.8MB
> ```

### 4. Start the lab

Once your virtual router image is ready, you can simply start the lab using `clab deploy`.  
You can find some examples of labs in [examples/](examples/).

> *Example*: Let's start our xrv lab
> ```console
> ~/containerlab-vms$ cd examples/
> ~/containerlab-vms/examples$ sudo clab deploy --topo xrv.clab.yml 
> INFO[0000] Parsing & checking topology file: xrv.clab.yml 
> INFO[0000] Creating lab directory: /home/guillaume/Documents/containerlab-vms/examples/clab-xrv 
> INFO[0000] Creating container: subscriber-west-2        
> INFO[0000] Creating container: router-east              
> INFO[0000] Creating container: subscriber-east-2        
> INFO[0000] Creating container: subscriber-west-1        
> INFO[0000] Creating container: router-west              
> INFO[0000] Creating container: subscriber-east-1        
> INFO[0001] Creating virtual wire: router-west:eth2 <--> subscriber-west-1:eth1 
> INFO[0001] Creating virtual wire: router-east:eth3 <--> subscriber-east-2:eth1 
> INFO[0001] Creating virtual wire: router-east:eth2 <--> subscriber-east-1:eth1 
> INFO[0001] Creating virtual wire: router-east:eth1 <--> router-west:eth1 
> INFO[0001] Creating virtual wire: router-west:eth3 <--> subscriber-west-2:eth1 
> INFO[0001] Adding containerlab host entries to /etc/hosts file 
> +---+----------------------------+--------------+------------------------------+--------+-------> +---------+-----------------+----------------------+
> | # |            Name            | Container ID |            Image             |  Kind  | Group |  State  |  IPv4 Address   |     IPv6 Address     |
> +---+----------------------------+--------------+------------------------------+--------+-------+---------+-----------------+----------------------+
> | 1 | clab-xrv-router-east       | dcb5f1243cce | containerlab/vr-xrv:6.3.1    | vr-xrv |       | running | 172.20.20.21/24 | 2001:172:20:20::2/64 |
> | 2 | clab-xrv-router-west       | eaeb093a20f0 | containerlab/vr-xrv:6.3.1    | vr-xrv |       | running | 172.20.20.31/24 | 2001:172:20:20::3/64 |
> | 3 | clab-xrv-subscriber-east-1 | 0f1f5ed83c9d | inmantaci/nfv-test-api:0.6.1 | linux  |       | running | 172.20.20.22/24 | 2001:172:20:20::7/64 |
> | 4 | clab-xrv-subscriber-east-2 | 47bc6e74feb1 | inmantaci/nfv-test-api:0.6.1 | linux  |       | running | 172.20.20.23/24 | 2001:172:20:20::5/64 |
> | 5 | clab-xrv-subscriber-west-1 | 4773353dcdb4 | inmantaci/nfv-test-api:0.6.1 | linux  |       | running | 172.20.20.32/24 | 2001:172:20:20::6/64 |
> | 6 | clab-xrv-subscriber-west-2 | b0e1d6540d48 | inmantaci/nfv-test-api:0.6.1 | linux  |       | running | 172.20.20.33/24 | 2001:172:20:20::4/64 |
> +---+----------------------------+--------------+------------------------------+--------+-------+---------+-----------------+----------------------+
> ~/containerlab-vms/examples$ docker ps
> CONTAINER ID   IMAGE                          COMMAND                  CREATED         STATUS         PORTS                                                                                NAMES
> 0f1f5ed83c9d   inmantaci/nfv-test-api:0.6.1   "sh -c '/bin/sleep 5…"   3 minutes ago   Up 3 minutes   0.0.0.0:2001->8080/tcp, :::2001->8080/tcp                                            clab-xrv-subscriber-east-1
> b0e1d6540d48   inmantaci/nfv-test-api:0.6.1   "sh -c '/bin/sleep 5…"   3 minutes ago   Up 3 minutes   0.0.0.0:2004->8080/tcp, :::2004->8080/tcp                                            clab-xrv-subscriber-west-2
> 4773353dcdb4   inmantaci/nfv-test-api:0.6.1   "sh -c '/bin/sleep 5…"   3 minutes ago   Up 3 minutes   0.0.0.0:2003->8080/tcp, :::2003->8080/tcp                                            clab-xrv-subscriber-west-1
> 47bc6e74feb1   inmantaci/nfv-test-api:0.6.1   "sh -c '/bin/sleep 5…"   3 minutes ago   Up 3 minutes   0.0.0.0:2002->8080/tcp, :::2002->8080/tcp                                            clab-xrv-subscriber-east-2
> eaeb093a20f0   containerlab/vr-xrv:6.3.1      "/root/env/bin/pytho…"   3 minutes ago   Up 3 minutes   0.0.0.0:21022->22/tcp, :::21022->22/tcp, 0.0.0.0:21830->830/tcp, :::21830->830/tcp   clab-xrv-router-west
> dcb5f1243cce   containerlab/vr-xrv:6.3.1      "/root/env/bin/pytho…"   3 minutes ago   Up 3 minutes   0.0.0.0:20022->22/tcp, :::20022->22/tcp, 0.0.0.0:20830->830/tcp, :::20830->830/tcp   clab-xrv-router-east
> ```

### 5. Check that the router is up

If the router is up, you should be able to connect to it over ssh.  Containerlab updates the `hosts` file with the container names, so you can simple connect to your router using `ssh <username>@<container-name>`.  The username to use has been chosen by containerlab based on the kind of the router we deployed.  You can find the one you need [here](https://containerlab.srlinux.dev/manual/kinds/kinds/).

> *Example*: To check that the router is working, we can connect to it after a few minutes.  In our case, the username is `clab` and the password is `clab@123`.
> ```console
> ~/containerlab-vms/examples$ ssh clab@clab-xrv-router-east 
> The authenticity of host 'clab-xrv-router-east (172.20.20.21)' can't be established.
> RSA key fingerprint is SHA256:pleLnCixoa/QKSTTn0YNgIgVwZwzbGggEfESgnIB61s.
> Are you sure you want to continue connecting (yes/no/[fingerprint])? yes
> 
> 
>
> IMPORTANT:  READ CAREFULLY
> Welcome to the Demo Version of Cisco IOS XRv (the "Software").
> The Software is subject to and governed by the terms and conditions
> of the End User License Agreement and the Supplemental End User
> License Agreement accompanying the product, made available at the
> time of your order, or posted on the Cisco website at
> www.cisco.com/go/terms (collectively, the "Agreement").
> As set forth more fully in the Agreement, use of the Software is
> strictly limited to internal use in a non-production environment
> solely for demonstration and evaluation purposes.  Downloading,
> installing, or using the Software constitutes acceptance of the
> Agreement, and you are binding yourself and the business entity
> that you represent to the Agreement.  If you do not agree to all
> of the terms of the Agreement, then Cisco is unwilling to license
> the Software to you and (a) you may not download, install or use the
> Software, and (b) you may return the Software as more fully set forth
> in the Agreement.
> 
> 
> Please login with any configured user/password, or cisco/cisco
> 
> 
> Password: 
> 
>
> RP/0/0/CPU0:router-east#
> ```

### 5bis. Troubleshooting

If it looks like the routers are not coming up, or if you want to follow to boot process more closely, you can check the container's logs.  This is as simple as running:
```
docker logs -f <container-name>
```
When the container is ready, it should display the following line in its logs:
```
2021-08-25 08:24:47,165 clab_vm_startup.vms.vr   INFO     VM was successfully started in 0:03:10.046256
```
The time it will take for your container to boot highly depends on how powerful your host machine is and the kind of virtual router your are running.  `xrv9k` images take much longer to boot than `xrv` images.

### 6. Destroy the lab
Once your are done with your lab, you can destroy it easily using `clab destroy` command.  Pay attention that you need to run this command in the same folder as the one in which you ran `clab deploy`.

> *Example*: Let's destroy our lab
> ```console
> ~/containerlab-vms/examples$ sudo clab destroy --topo xrv.clab.yml 
> INFO[0000] Parsing & checking topology file: xrv.clab.yml 
> INFO[0000] Destroying lab: xrv                          
> INFO[0000] Removed container: clab-xrv-subscriber-west-2 
> INFO[0001] Removed container: clab-xrv-subscriber-east-2 
> INFO[0001] Removed container: clab-xrv-subscriber-east-1 
> INFO[0001] Removed container: clab-xrv-router-west      
> INFO[0001] Removed container: clab-xrv-subscriber-west-1 
> INFO[0001] Removed container: clab-xrv-router-east      
> INFO[0001] Removing containerlab host entries from /etc/hosts file
> ```
