#!/usr/bin/env bash
# Build the property-only Libargus helper when the Jetson SDK is available.
# Failure is intentionally non-fatal: the backend will use Device Tree.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_PATH="${PROJECT_ROOT}/backend/tools/argus_mode_enumerator.cpp"
OUTPUT_PATH="${PROJECT_ROOT}/backend/tools/argus-mode-enumerator"
ARGUS_INCLUDE="/usr/src/jetson_multimedia_api/argus/include"
COMPILER="${CXX:-g++}"

if [ ! -e /etc/nv_tegra_release ]; then
    echo "Argus enumerator: non-Jetson system; using Device Tree/known-table fallback."
    exit 0
fi
if ! command -v "${COMPILER}" >/dev/null 2>&1; then
    echo "WARNING: ${COMPILER} is unavailable; using Device Tree fallback."
    exit 0
fi
if [ ! -f "${ARGUS_INCLUDE}/Argus/Argus.h" ]; then
    echo "WARNING: Libargus headers are unavailable; using Device Tree fallback."
    exit 0
fi

MULTIARCH="$(${COMPILER} -print-multiarch 2>/dev/null)"
NVIDIA_LIB_DIR="/usr/lib/${MULTIARCH}/nvidia"
if [ -z "${MULTIARCH}" ] || [ ! -f "${NVIDIA_LIB_DIR}/libnvargus.so" ]; then
    echo "WARNING: libnvargus.so is unavailable; using Device Tree fallback."
    exit 0
fi

mkdir -p "$(dirname "${OUTPUT_PATH}")"
if ! TEMP_OUTPUT="$(mktemp "${OUTPUT_PATH}.tmp.XXXXXX")"; then
    echo "WARNING: cannot create a temporary build output; using Device Tree fallback."
    exit 0
fi
trap 'rm -f "${TEMP_OUTPUT}"' EXIT

if ! "${COMPILER}" \
    -std=c++17 -O2 -Wall -Wextra -Werror \
    -I"${ARGUS_INCLUDE}" \
    "${SOURCE_PATH}" \
    -L"${NVIDIA_LIB_DIR}" \
    -Wl,-rpath,"${NVIDIA_LIB_DIR}" \
    -lnvargus \
    -o "${TEMP_OUTPUT}"; then
    echo "WARNING: Argus enumerator build failed; using Device Tree fallback."
    exit 0
fi

if ! chmod 0755 "${TEMP_OUTPUT}"; then
    echo "WARNING: cannot mark Argus enumerator executable; using Device Tree fallback."
    exit 0
fi
if ! mv -f "${TEMP_OUTPUT}" "${OUTPUT_PATH}"; then
    echo "WARNING: cannot install Argus enumerator; using Device Tree fallback."
    exit 0
fi
trap - EXIT
echo "Argus enumerator built: ${OUTPUT_PATH}"
