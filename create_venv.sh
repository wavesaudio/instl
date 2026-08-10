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

# ARCHFLAGS for C extensions built from source in requirements_mac_only.txt
# (psutil, charset-normalizer). cryptography uses a pinned universal2 wheel;
# cffi is fattened via make_universal2_ext.sh after install.
export ARCHFLAGS="-arch x86_64 -arch arm64"

# pip install mac requirements first, so universal binaries will get priority
python3.12 -m pip install --upgrade pip  --no-user
python3.12 -m pip install -r requirements_mac_only.txt  --no-user
python3.12 -m pip install -r requirements.txt  --no-user

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/make_universal2_ext.sh" cffi

require_universal2() {
    local label="$1"
    local path="$2"
    local archs
    archs="$(lipo -archs "${path}")"
    echo ---* ${label} archs: ${archs} *---
    if ! echo " ${archs} " | grep -q ' x86_64 ' || ! echo " ${archs} " | grep -q ' arm64 '; then
        echo "ERROR: ${path} is not universal2 (archs: ${archs})." >&2
        echo "Expected cryptography==48.0.1 universal2 wheel and lipo-merged cffi." >&2
        exit 1
    fi
}

CRYPTO_SO="$(python3.12 -c 'import cryptography.hazmat.bindings._rust as m; print(m.__file__)')"
require_universal2 "cryptography _rust.abi3.so" "${CRYPTO_SO}"

CFFI_SO="$(python3.12 -c 'import _cffi_backend as m; print(m.__file__)')"
require_universal2 "cffi _cffi_backend" "${CFFI_SO}"

echo ---* creating virtual env done *---
