# syntax=docker/dockerfile:1

# Build environment for instl: Python 3.12, all Python dependencies, and the
# PyInstaller (one-folder) build described by instl.spec.
#
# The build context is the project root, so build with:
#   docker build -f .oss-scanner/Dockerfile -t instl .

FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# build-essential, libyaml-dev: compile source-only wheels (PyYAML with its libyaml extension, ...)
# binutils:                      PyInstaller needs objdump on Linux
# subversion, curl:              external tools instl invokes at runtime (svn, curl)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        binutils \
        build-essential \
        ca-certificates \
        curl \
        libyaml-dev \
        subversion \
    && rm -rf /var/lib/apt/lists/*

# Same approach as create_venv.sh: an isolated virtual env. The instl script's
# "#!/usr/bin/env python3.12" shebang resolves to this env's interpreter.
RUN python3.12 -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /opt/instl

# Python dependencies (copied first so this layer is cached until they change).
#   requirements.txt       - runtime + PyInstaller
#   requirements_admin.txt - extra modules used by the instl "admin" commands (boto3, redis, ...)
#   psutil                 - imported by pybatch, but listed only in the platform specific
#                            requirements_mac_only.txt / requirements_win_only.txt
COPY requirements.txt requirements_admin.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install \
        -r requirements.txt \
        -r requirements_admin.txt \
        psutil

# Project sources
COPY . .

# Build the frozen executable -> dist/instl/instl
RUN pyinstaller --noconfirm --distpath dist --workpath build instl.spec

# The frozen executable looks for its data folders in <dist>/Resources
RUN mkdir -p dist/Resources \
    && cp -R defaults help dist/Resources/

# Smoke test: run both from source and the frozen build
RUN ./instl version \
    && ./instl test-import \
    && dist/instl/instl version \
    && dist/instl/instl test-import

CMD ["/opt/instl/dist/instl/instl", "version"]
