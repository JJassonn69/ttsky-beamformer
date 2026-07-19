#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
: "${PDK_ROOT:?Set PDK_ROOT to the directory containing sky130A}"

magic_bin="${MAGIC_BIN:-magic}"
script="${1:-layout/pdk_smoke.tcl}"

cd "$project_root"
"$magic_bin" -dnull -noconsole \
    -rcfile "$PDK_ROOT/sky130A/libs.tech/magic/sky130A.magicrc" \
    < "$script"
