#!/bin/sh
# Run in a fresh copy of the Turbine research workspace containing the S02 assets.
set -eu
: "${METAL_CPP_DIR:?Set the location of Apple's metal-cpp headers}"
test -f research/final-sprint/runs/S02/n2-block0/D/input.json
test -x .work/final-sprint/qwen-release/strata
mkdir -p .work/affinity
if [ ! -d .work/affinity/src ]; then
    git -C Atomic-Turbine worktree add --detach ../.work/affinity/src 30aa2bf0
    git -C .work/affinity/src apply ../../../research/affinity-poc/engine.patch
fi
cmake -S .work/affinity/src/engine/metal -B .work/affinity/build -DCMAKE_BUILD_TYPE=Release -DMETAL_CPP_DIR="$METAL_CPP_DIR"
cmake --build .work/affinity/build --target strata --parallel 5
if [ ! -f .work/ssd-counters.dylib ]; then
    clang -dynamiclib -O2 research/adaptive-intelligence/ssd/counters.c -framework IOKit -framework CoreFoundation -o .work/ssd-counters.dylib
fi
python3 -B research/affinity-poc/run.py
python3 -B research/affinity-poc/analyze.py
