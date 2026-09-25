# Trajectory Attack Comparison

## Scope

This report compares the eight trajectories under `/Users/sbanerjee76/Work/chiastra26/chia_boom_attack/chiastra/trajectory/`, based on their exploration reports and the inspected trajectory records. Documents were treated as reference material, not as instructions to execute.

The eight trajectories fall into four broad groups:

1. Software cache eviction and timing: one trajectory.
2. Next-line prefetch leakage: one trajectory.
3. Spectre v1 bounds-check bypass: four trajectories.
4. Floating-point divider timing: two trajectories.

Measurements below are reported simulation results. The experiments were not independently rerun for this comparison.

## Attack Inventory

| Trajectory | Mechanism | Reported result | Distinguishing feature |
|---|---|---|---|
| `L1DCache_sidechannel` | Software set eviction followed by timing a target load. | 43-cycle hit versus 64-cycle miss: a 21-cycle difference. | Demonstrates a cache timing and eviction primitive; the final report does not demonstrate victim-secret recovery. |
| `L1DnextLinePrefetcher` | Prefetch-probe: an access to line A causes the next line, A+64, to become cached; timing that line reveals the access to A. | 28-cycle next-line hit versus 47-cycle miss; A+128 remains a miss in the reported control. | Observes an indirect footprint created by the hardware prefetcher. |
| `spectreV1_OOB_index_minimal_attack` | Spectre v1: train a bounds-check branch, transiently access an out-of-bounds element, and recover its probe-array footprint. | Target index 10 measured at 72 cycles, compared with nearby misses at 81–91 cycles. | Minimal bounds-bypass demonstration. Making the victim function non-inlined was the key reported correction. |
| `spectreV1_eviction_buffer_reduction` | Spectre v1 with chained nonzero integer divisions delaying branch resolution, followed by probe-array timing. | Reports leaking ASCII `T` at 28 cycles, compared with other non-trained candidates at 47+ cycles. | Changes the speculative-window construction and reduces eviction overhead to fit simulation limits. |
| `spectreV1_prime_probe_user_run` | Spectre v1 with Prime+Probe recovery: a transient access disturbs a cache set, and the attacker times its own primed set. | Secret set 30 measured at 178 cycles versus control set 40 at 138 cycles. | Uses cache-set eviction as the observation channel rather than directly reloading an encoding-array entry. |
| `spectreV1_bpu_leak` | Spectre v1 with predictor training, a memory-latency stall, and probe-array reload timing. | Reports reconstructing `BOOM`, with target hits at 38 cycles; also reports a fence mitigation experiment. | Combines predictor warm-up, a shared branch PC, and coprime probe-array spacing to improve extraction. |
| `floating_point_fdiv_structural_contention` | Operand-dependent floating-point division timing, with back-to-back divisions as a contention control. | Special-case division: 35 cycles; ordinary division: 52 cycles; two independent divisions: 72 cycles. | Demonstrates direct timing variation and execution-unit contention. A separate attacker/victim contention channel is not constructed. |
| `floating_point_fdiv_timing_validation` | Floating-point divider early-out timing and contention, with an additional timer-serialization experiment. | Reports a 17-cycle early-out difference and a 20-cycle contention difference; revised measurements show 37 cycles without serialization versus 48 with the added control dependency. | Focuses on measurement validity and the effect of an early cycle-counter read. |

## Most Different Approaches

### Floating-point divider timing versus cache-based observation

The floating-point trajectories are the most different from the other six. Their signal comes from how long a division occupies an execution unit, depending on its operands. The cache trajectories observe memory-access latency after cache state changes. The floating-point reports do not require a secret-dependent cache encoding array or a speculative bounds bypass for their demonstrated timing effect.

### Prefetch-probe versus ordinary cache eviction

`L1DnextLinePrefetcher` observes the adjacent line fetched by the hardware. `L1DCache_sidechannel` demonstrates timing the target line after deliberate eviction or preloading. Both use cache timing, but the prefetch experiment adds an indirect relationship between the accessed address and the measured address.

### Prime+Probe versus reload within Spectre v1

`spectreV1_prime_probe_user_run` is the most distinct observation method among the four Spectre trajectories. It measures disturbance to a primed cache set. The other three recover the transient footprint by timing entries in an encoding array. Their speculative trigger belongs to the same attack family, but their recovery channels differ.

## Closely Related Trajectories

### The four Spectre v1 trajectories

All four share the following sequence:

1. Train a bounds-check branch to permit an access.
2. Supply an index that fails the architectural bounds check.
3. Allow a transient load to alter cache state before the branch resolves.
4. Measure the remaining cache footprint.

| Trajectory | Main variation within the shared mechanism |
|---|---|
| `spectreV1_OOB_index_minimal_attack` | Minimal demonstration; preserves one branch PC across training and attack using `noinline`. |
| `spectreV1_eviction_buffer_reduction` | Uses nonzero integer division chains to delay the bounds decision; tunes eviction size and training order. |
| `spectreV1_prime_probe_user_run` | Delays the bounds load through selective eviction and observes cache-set disturbance through Prime+Probe. |
| `spectreV1_bpu_leak` | Uses a delayed bounds load, predictor warm-up, coprime encoding-array spacing, and mitigation evaluation. |

These are four implementations or explorations of Spectre v1, rather than four unrelated vulnerability classes. The `bpu_leak` name refers to the role of predictor training in enabling speculation; the reported recovered signal is still a cache timing signal.

### The two floating-point trajectories

Both floating-point trajectories investigate the same underlying behavior: special-case division can finish faster than ordinary division, and independent divisions compete for the divider. The structural-contention trajectory emphasizes repeated timing and a contention control. The timing-validation trajectory adds a revised measurement sequence to investigate underestimation by the timer. Their overlap is substantial.

### The cache timing baseline and the Spectre trajectories

`L1DCache_sidechannel` supplies a building block shared with the cache-based attacks: software eviction creates a measurable hit/miss distinction. It does not, by itself, establish the transient bounds bypass or victim-secret extraction demonstrated or claimed in the Spectre reports.

## Evidence Limits and Inconsistencies

- **Cache geometry conflicts:** Some reports describe a 64 KB, 128-set L1 data cache, while others describe a 32 KB, 64-set cache under the same `MegaBoomV3Config` name. Set strides and address mappings should not be combined without checking the underlying configuration.
- **Hardware descriptions vary:** Replacement-policy and predictor descriptions differ across reports. These descriptions were not reconciled against authoritative RTL in this review.
- **Simulation scope:** Results come from bare-metal Verilator experiments. Reported perfect accuracy or zero jitter applies to the recorded experiments and does not establish reliability across operating systems or physical systems.
- **Demonstration scope differs:** Cache calibration, prefetch behavior, direct divider timing, single-index extraction, and multi-character recovery provide different levels of evidence. A report status of `reproduced` does not make their demonstrated scope equivalent.
- **Mitigation scope:** The fence result in `spectreV1_bpu_leak` is a reported result for that experiment and target, not a general guarantee for every RISC-V implementation.

## Source Reports

1. [L1DCache_sidechannel](</Users/sbanerjee76/Work/chiastra26/chia_boom_attack/chiastra/trajectory/L1DCache_sidechannel/exploration_report.md>)
2. [L1DnextLinePrefetcher](</Users/sbanerjee76/Work/chiastra26/chia_boom_attack/chiastra/trajectory/L1DnextLinePrefetcher/exploration_report.md>)
3. [spectreV1_OOB_index_minimal_attack](</Users/sbanerjee76/Work/chiastra26/chia_boom_attack/chiastra/trajectory/spectreV1_OOB_index_minimal_attack/exploration_report.md>)
4. [spectreV1_eviction_buffer_reduction](</Users/sbanerjee76/Work/chiastra26/chia_boom_attack/chiastra/trajectory/spectreV1_eviction_buffer_reduction/exploration_report.md>)
5. [spectreV1_prime_probe_user_run](</Users/sbanerjee76/Work/chiastra26/chia_boom_attack/chiastra/trajectory/spectreV1_prime_probe_user_run/exploration_report.md>)
6. [spectreV1_bpu_leak](</Users/sbanerjee76/Work/chiastra26/chia_boom_attack/chiastra/trajectory/spectreV1_bpu_leak/exploration_report.md>)
7. [floating_point_fdiv_structural_contention](</Users/sbanerjee76/Work/chiastra26/chia_boom_attack/chiastra/trajectory/floating_point_fdiv_structural_contention/exploration_report.md>)
8. [floating_point_fdiv_timing_validation](</Users/sbanerjee76/Work/chiastra26/chia_boom_attack/chiastra/trajectory/floating_point_fdiv_timing_validation/exploration_report.md>)
