FROM ubuntu:20.04
MAINTAINER Inmanta <code@inmanta.com>

ARG DEBIAN_FRONTEND=noninteractive

# Install required apt packages
RUN apt-get update -qy && \
    apt-get upgrade -qy && \
    apt-get install -y \
        iproute2 \
        python3-venv \
        socat \
        qemu-kvm \
        telnet \
        mkisofs && \
    rm -rf /var/lib/apt/lists/*

# Copying the source of this project
COPY poetry.lock /root/containerlab-vms/poetry.lock
COPY pyproject.toml /root/containerlab-vms/pyproject.toml
COPY src/ /root/containerlab-vms/src

# Installing the project in the virtual environment
RUN python3 -m venv /root/env && \
    . /root/env/bin/activate && \
    pip install -U pip poetry && \
    cd /root/containerlab-vms && \
    poetry install --no-dev

ENTRYPOINT ["/root/env/bin/python"]
