#!/bin/sh
# Run both exact hierarchical and flattened V3 Magic signoff views remotely.
set -eu

project_root=${V3_REMOTE_PROJECT_ROOT:-/home/jason-stone/tinytapeout-beamformer-v2-routefix}
pdk_root=${V3_REMOTE_PDK_ROOT:-/home/jason-stone/pdk/ciel/sky130/versions/0536d02d875c8f67dd7cca3902ac457e62f20005}
magic_bin=${V3_REMOTE_MAGIC_BIN:-/usr/local/bin/magic}
submission_dir=${project_root}/build/v3/submission
gds=${submission_dir}/tt_um_jjassonn69_beamformer.gds
labels=${submission_dir}/official_magic_labels.tcl
magic_rc=${pdk_root}/sky130A/libs.tech/magic/sky130A.magicrc

hier_command="/usr/bin/env -C ${project_root} PDK_ROOT=${pdk_root} V3_SUBMISSION_GDS=${gds} V3_SUBMISSION_READBACK_DIR=${submission_dir}/magic_readback ${magic_bin} -dnull -noconsole -rcfile ${magic_rc} build/v3/submission/readback_submission_gds.tcl"
flat_command="/usr/bin/env -C ${project_root} PDK_ROOT=${pdk_root} V3_SUBMISSION_GDS=${gds} V3_SUBMISSION_FLAT_DIR=${submission_dir}/magic_flat V3_SUBMISSION_LABELS=${labels} ${magic_bin} -dnull -noconsole -rcfile ${magic_rc} build/v3/submission/readback_submission_flat.tcl"

/usr/bin/script -q -e -c "${hier_command}" "${submission_dir}/magic_readback.log"
/usr/bin/script -q -e -c "${flat_command}" "${submission_dir}/magic_flat.log"
