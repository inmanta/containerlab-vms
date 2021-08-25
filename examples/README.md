# Starting containerlab labs

## Example labs topologies
Those example labs all have the same topology, but with different vendors.  We have two routers, east and west, connected to each other, and with two subscribers each.

```
 ┌──────────────────────┐                    ┌──────────────────────┐
 │                      │eth1            eth1│                      │
 │     router-west      ├────────────────────┤     router-east      │
 │                      │                    │                      │
 │ mgmt-ip:172.20.20.31 │                    │ mgmt-ip:172.20.20.21 │
 └───┬──────────────┬───┘                    └───┬──────────────┬───┘
     │  eth2    eth3│                            │eth3    eth2  │
     │              └──────────┐      ┌──────────┘              │
     │                         │      │                         │
     │  eth1                   │      │                   eth1  │
 ┌───┴──────────────────┐      │      │      ┌──────────────────┴───┐
 │                      │      │      │      │                      │
 │  subscriber-west-1   │      │      │      │  subscriber-east-1   │
 │                      │      │      │      │                      │
 │ mgmt-ip:172.20.20.32 │      │      │      │ mgmt-ip:172.20.20.22 │
 └──────────────────────┘      │      │      └──────────────────────┘
                               │      │
 ┌──────────────────────┐      │      │      ┌──────────────────────┐
 │                      │eth1  │      │  eth1│                      │
 │  subscriber-west-2   ├──────┘      └──────┤  subscriber-east-2   │
 │                      │                    │                      │
 │ mgmt-ip:172.20.20.33 │                    │ mgmt-ip:172.20.20.23 │
 └──────────────────────┘                    └──────────────────────┘
```

## Prerequisites
You will need to install `containerlab` to start any of those labs: https://containerlab.srlinux.dev/install/.

## Start the lab
To startup the lab, simply run
```
sudo clab deploy --topo <lab-file>
```  
Where `<lab-file>` is any of the files in this folder ending in `.clab.yml`.
