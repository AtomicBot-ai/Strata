#!/bin/sh
set -eu
base=.work/final-sprint
# S03 measures device-wide SSD traffic; compilation must wait for its last sample.
while [ ! -f research/final-sprint/runs/S03-exit.json ]; do sleep 4; done
sdk=/Users/aleksejkalina/.cache/uv/archive-v0/fHMh9zLX3EJMpyIELxJjk/mlx/include/metal_cpp
build_ink() {
    dir="$1"
    shift
    cmake -S Atomic-Turbine/engine/src/inkling2 -B "$base/$dir" -DCMAKE_BUILD_TYPE=Release "$@"
    cmake --build "$base/$dir" --target strata-inkling --parallel 4
}
build_ink ink-release > "$base/ink-release.log" 2>&1
build_ink ink-check -DCMAKE_CXX_FLAGS=-DTURBINE_TEST_LOGITS > "$base/ink-check.log" 2>&1
cmake -S Atomic-Turbine/engine/metal -B "$base/qwen-release" -DCMAKE_BUILD_TYPE=Release -DMETAL_CPP_DIR="$sdk" > "$base/qwen-release.log" 2>&1
cmake --build "$base/qwen-release" --target strata --parallel 4 >> "$base/qwen-release.log" 2>&1
