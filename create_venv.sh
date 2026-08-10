#!/bin/bash

echo ---* python is: $(which python3.12) *---

echo ---* creating virtual env in: $(pwd)/venv *---

python3.12 -m venv venv
source venv/bin/activate
echo ---* after "source venv/bin/activate" VIRTUAL_ENV is:
echo    $VIRTUAL_ENV  *---

echo ---* activated virtual env in: $(pwd)/venv *---
echo ---* now python is: $(which python3.12) *---

echo ---* pip installing *---

# Build native extensions as universal2 so PyInstaller target_arch=universal2 succeeds.
# cryptography (and cffi) ship only thin macOS wheels; --no-binary + ARCHFLAGS rebuilds fat .so files.
# Requires Rust (rustc/cargo) on the Mac build agent.
export ARCHFLAGS="-arch x86_64 -arch arm64"

# pip install mac requirements first, so universal binaries will get priority
python3.12 -m pip install --upgrade pip  --no-user
python3.12 -m pip install -r requirements_mac_only.txt  --no-user
python3.12 -m pip install -r requirements.txt  --no-user

CRYPTO_SO="$(python3.12 -c 'import cryptography.hazmat.bindings._rust as m; print(m.__file__)')"
CRYPTO_ARCHS="$(lipo -archs "${CRYPTO_SO}")"
echo ---* cryptography native extension archs: ${CRYPTO_ARCHS} *---
if ! echo " ${CRYPTO_ARCHS} " | grep -q ' x86_64 ' || ! echo " ${CRYPTO_ARCHS} " | grep -q ' arm64 '; then
    echo "ERROR: ${CRYPTO_SO} is not universal2 (archs: ${CRYPTO_ARCHS})." >&2
    echo "Install Rust and use a universal2 Python (python.org), then re-run." >&2
    exit 1
fi

echo ---* creating virtual env done *---
