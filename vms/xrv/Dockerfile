FROM inmantaci/containerlab-vms:0.0.1

ARG IMAGE
COPY $IMAGE /
COPY launch.py /

ENTRYPOINT ["/root/env/bin/python", "launch.py"]
