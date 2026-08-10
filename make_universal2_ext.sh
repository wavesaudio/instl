#!/bin/bash
# Make a package's installed Mach-O extensions universal2 by lipo-merging
# the host install with a same-version wheel for the other macOS arch.
#
# Usage: make_universal2_ext.sh <package_name>
# Example: make_universal2_ext.sh cffi
set -euo pipefail

PKG_NAME="${1:-}"
if [[ -z "${PKG_NAME}" ]]; then
    echo "Usage: $0 <package_name>" >&2
    exit 2
fi

PYTHON_BIN="${PYTHON_EXE_BINARY_NAME:-python3.12}"

META_FILE="$(mktemp -t make_universal2_ext_meta.XXXXXX)"
"${PYTHON_BIN}" - <<PY > "${META_FILE}"
import importlib.metadata
import pathlib
import sys

dist = importlib.metadata.distribution("${PKG_NAME}")
print(dist.version)
locate = dist.locate_file
machos = []
for rec in dist.files or []:
    path = pathlib.Path(locate(rec))
    if not path.is_file():
        continue
    if path.suffix in {".so", ".dylib"} or ".so." in path.name:
        machos.append(str(path.resolve()))
if not machos:
    import ${PKG_NAME} as pkg
    pkg_dir = pathlib.Path(pkg.__file__).resolve().parent
    site = pkg_dir.parent
    candidates = list(pkg_dir.rglob("*.so")) + list(pkg_dir.rglob("*.dylib"))
    candidates += list(site.glob("_cffi_backend*.so"))
    machos = [str(p) for p in candidates if p.is_file()]
for p in machos:
    print(p)
if not machos:
    sys.exit("ERROR: no native extensions found for ${PKG_NAME}")
PY

PKG_VERSION="$(sed -n '1p' "${META_FILE}")"
NATIVE_FILES=()
while IFS= read -r line; do
    [[ -n "${line}" ]] && NATIVE_FILES+=("${line}")
done < <(sed '1d' "${META_FILE}")
rm -f "${META_FILE}"

echo ---* make_universal2_ext: ${PKG_NAME}==${PKG_VERSION} *---

is_universal2() {
    local f="$1"
    local archs
    archs="$(lipo -archs "${f}" 2>/dev/null || true)"
    echo " ${archs} " | grep -q ' x86_64 ' && echo " ${archs} " | grep -q ' arm64 '
}

THIN_FILES=()
for f in "${NATIVE_FILES[@]}"; do
    if ! file -b "${f}" | grep -q 'Mach-O'; then
        continue
    fi
    archs="$(lipo -archs "${f}")"
    echo ---* ${f}: ${archs} *---
    if ! is_universal2 "${f}"; then
        THIN_FILES+=("${f}")
    fi
done

if [[ ${#THIN_FILES[@]} -eq 0 ]]; then
    echo ---* ${PKG_NAME}: all native extensions already universal2 *---
    exit 0
fi

echo "---* ${PKG_NAME}: fattening ${#THIN_FILES[@]} thin extension(s) *---"

HOST_ARCH="$(uname -m)"
case "${HOST_ARCH}" in
    arm64|aarch64) OTHER_ARCH="x86_64" ;;
    x86_64) OTHER_ARCH="arm64" ;;
    *)
        echo "ERROR: unsupported host arch ${HOST_ARCH}" >&2
        exit 1
        ;;
esac

if [[ "${OTHER_ARCH}" == "arm64" ]]; then
    OTHER_PLATFORMS="macosx_11_0_arm64"
else
    OTHER_PLATFORMS="macosx_10_15_x86_64 macosx_11_0_x86_64 macosx_10_13_x86_64 macosx_10_9_x86_64"
fi

TMPDIR_MERGE="$(mktemp -d -t make_universal2_ext.XXXXXX)"
cleanup() { rm -rf "${TMPDIR_MERGE}"; }
trap cleanup EXIT

WHEEL_PATH=""
for plat in ${OTHER_PLATFORMS}; do
    rm -f "${TMPDIR_MERGE}"/*.whl
    echo ---* downloading ${PKG_NAME}==${PKG_VERSION} for ${plat} *---
    for abi in cp312 abi3; do
        if "${PYTHON_BIN}" -m pip download \
                "${PKG_NAME}==${PKG_VERSION}" \
                --only-binary=:all: \
                --no-deps \
                --python-version 312 \
                --implementation cp \
                --abi "${abi}" \
                --platform "${plat}" \
                -d "${TMPDIR_MERGE}"; then
            WHEEL_PATH="$(find "${TMPDIR_MERGE}" -maxdepth 1 -name '*.whl' | head -n 1 || true)"
            if [[ -n "${WHEEL_PATH}" ]]; then
                break 2
            fi
        fi
    done
done

if [[ -z "${WHEEL_PATH}" ]]; then
    echo "ERROR: could not download ${PKG_NAME}==${PKG_VERSION} wheel for ${OTHER_ARCH}" >&2
    exit 1
fi

echo ---* unpacking $(basename "${WHEEL_PATH}") *---
EXTRACT_DIR="${TMPDIR_MERGE}/extracted"
mkdir -p "${EXTRACT_DIR}"
unzip -q "${WHEEL_PATH}" -d "${EXTRACT_DIR}"

SITE_PACKAGES="$("${PYTHON_BIN}" -c 'import site; print(site.getsitepackages()[0])')"

for host_so in "${THIN_FILES[@]}"; do
    base="$(basename "${host_so}")"
    other_so="$(find "${EXTRACT_DIR}" -type f -name "${base}" | head -n 1 || true)"
    if [[ -z "${other_so}" ]]; then
        rel="${host_so#${SITE_PACKAGES}/}"
        other_so="$(find "${EXTRACT_DIR}" -type f -path "*/${rel}" | head -n 1 || true)"
    fi
    if [[ -z "${other_so}" ]]; then
        echo "ERROR: no matching ${base} in foreign wheel $(basename "${WHEEL_PATH}")" >&2
        exit 1
    fi

    host_archs="$(lipo -archs "${host_so}")"
    other_archs="$(lipo -archs "${other_so}")"
    echo ---* lipo ${base}: host[${host_archs}] + other[${other_archs}] *---

    if is_universal2 "${other_so}"; then
        cp -f "${other_so}" "${host_so}"
    else
        OUT="${TMPDIR_MERGE}/${base}.universal2"
        lipo -create "${host_so}" "${other_so}" -output "${OUT}"
        cp -f "${OUT}" "${host_so}"
    fi

    final_archs="$(lipo -archs "${host_so}")"
    if ! is_universal2 "${host_so}"; then
        echo "ERROR: ${host_so} still not universal2 after lipo (archs: ${final_archs})" >&2
        exit 1
    fi
    echo "---* ${base} => ${final_archs} *---"
done

echo "---* make_universal2_ext: ${PKG_NAME} done *---"
