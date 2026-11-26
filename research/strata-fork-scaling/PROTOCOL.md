# Inkling/Metal scaling v1

Primary population: model-warm fixed wide trees, P=1024,4096,16384,32768,
N=2,4,8, S=128, C=2. New process per measured tree, short unrelated warm-up,
then BCO on both slots. Context P+S+32 or larger where stated. A repeated
prefix starts cold. Warm-up, file writes and diagnostics are outside makespan.
Completion includes the final native sampled token after all 128 forced IDs
have been consumed, all branches and releasing the checkpoint. Identical
forced IDs are sampled over (native sampling still runs) then fed back on
individual decode steps. The final native token is an independent output.
All branches are ready at submission, dispatched in waves of at most two.

The lab toggle preserves native reads, prompt checkpoints and batching.
B3 uses per-slot prompt-end reuse. Compare sequential and two-slot admission
on development data; use the faster applicable policy from development.
A terminal wave need not save an unused checkpoint. B4 saves committed P-1
tokens once, replays the common final token on each slot, then consumes each
suffix. This matches upstream's checkpoint boundary. N=1 and unrelated
histories take the ordinary path. B7 is exactly B3 at the same admission
width on the same instrumented binary. Stock unmodified binary is checked
against the instrumented native path with unforced greedy decode.

G0 requires historical state equivalence, equal completion, finite endpoint
logits, and exact equality for same-shape restore. For comparisons of
different batch shapes, calibrate on native execution of the same workload
with repeat, one- and two-slot admission and prompt-end split. Require no
larger max absolute / RMS error than the measured native envelope (float32
rounding allowance 1e-6). Require exact sampled endpoint when native argmax
agrees across all calibration paths. Record all outcomes. A failure stops
timing until diagnosed. Forced token echo alone cannot establish correctness.

Screen 5 seed-paired blocks per supported cell, with alternated/randomized mode
order (seed 1125). Controls N=1 and no shared prefix at the same P. Retain
timeout/OOM/error and stop on correctness failure. Screening cells represent
development, never independent confirmation. Rank classes by median paired
B3/B4 speedup, confirm the highest eligible class (median >=1.3), tie by
smaller P then N. Holdout uses 10 independent new trees, two paired blocks
per tree, untouched seed range >=100000. Report paired median and ratio of
total times separately. Percentile 95% bootstrap resamples trees with nested
paired blocks (10000 resamples, seed 1125). Speed gate >=1.3 median and
lower bound >1 at equal two-slot limit and comparable measured footprint.
Memory headroom is observed; absent an enforced memory cap no capacity claim.
No validation if screening has no candidate. Boundary, load and telemetry
failures are explicit. No extrapolation to tools or live agents.
