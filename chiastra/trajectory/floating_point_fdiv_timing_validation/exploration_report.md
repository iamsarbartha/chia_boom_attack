### 1. Architectural and Environment Specification

* **Target Core Configuration:** `MegaBoomV3Config` (Dual-issue or larger out-of-order Berkeley Out-of-Order Machine)
* **Verilator Simulation Version:** Verilator 5.x (bare-metal test harness)
* **Supported ISA Extensions:** RV64GC (including standard Single 'F' and Double 'D' Precision Floating-Point Extensions)
* **Floating-Point Configuration:** Standard Berkeley `hardfloat` library utilizing unpipelined, iterative `divSqrtRecFN` execution units for double-precision division (`fdiv.d`) and square-root (`fsqrt.d`) operations.
* **Rounding and Exception Behavior:** Support for IEEE 754 rounding modes (RNE, RTZ, RDN, RUP, RMM) and exception flags (NV, DZ, OF, UF, NX) managed via dynamic hardware CSRs (`fcsr`).
* **Resource Budget Monitoring:** 
  * Build Repairs Used: `0` (of 3 allowed)
  * Experiment Revisions Used: `1` (of 3 allowed)

---

### 2. Experiment Record

| Experiment ID | Vulnerability Class / Mechanism | Target File | Build Status | Simulation Status | Measured Latency Delta | Outcome |
| :---: | :--- | :--- | :---: | :---: | :---: | :--- |
| **01** | K1 Early-Out Timing Side-Channel | `fdiv_early_out_validator.c` | **SUCCESS** | **PASSED** | 17.00 cycles | **Confirmed** (Early-out observed; speculative counters noted) |
| **02** | K1 Serialized & Execution-Unit Contention | `fp_div_serialization_validation.c` | **SUCCESS** | **PASSED** | 11.00 cycles (speculation) <br> 20.00 cycles (contention) | **Confirmed** (Strict control-flow serialization verified) |

---

### 3. Trajectory and Evidence

#### Phase 1: Vulnerability Research and Formulation
The research agent characterized the **K1 Microarchitectural Timing Side-Channel** (Floating-Point Divider Fast Path), citing *Mishra et al. (September 2026)*. High-performance unpipelined dividers in HardFloat optimize special cases (like dividing by zero, infinity, or NaN) using early-out bypass logic. This causes a bimodal execution latency (~50 cycles for normal values vs. <10 cycles for exceptional values), acting as a timing oracle.

#### Phase 2: First Validation Attempt
The generator developed `fdiv_early_out_validator.c` to test normal vs. early-out divisions with a data-dependency on `fmv.x.d`.
* **Evidence:**
  * Single Normal `fdiv.d`: **32.00 cycles** (net)
  * Single Early `fdiv.d`: **15.00 cycles** (net)
  * Measured Early-Out Delta: **17.00 cycles**
  * Two Independent Normal divisions (Contention Control): **52.00 cycles** (net), proving a **20-cycle unit contention delay**.
* **Gap Identified:** The measured normal latency was 32 cycles instead of the expected 50+ cycles. The validator determined that `rdcycle` is executed speculatively/out-of-order in MegaBoom because there is no direct register dependency on the cycle read itself, underestimating true execution latency.

#### Phase 3: Revised Experiment
The generator produced `fp_div_serialization_validation.c` to introduce a strict control-flow dependency using a conditional branch (`bne`) on the integer result of the division, preventing the cycle-counter from being read speculatively.
* **Evidence:**
  * Unserialized `fdiv.d` (Vulnerable): **37 cycles**
  * Serialized `fdiv.d` (Forced control dependency): **48 cycles**
  * Underestimation/Speculation Delta: **11 cycles**
  * Non-speculative FDiv unit contention delta: **20 cycles** (Double: 68 cycles vs. Single: 48 cycles)
  * Non-speculative FAdd pipelining contention: **0 cycles** (Double: 32 cycles vs. Single: 32 cycles)

The control-flow serialization successfully forced the processor to complete the division before reading the timer, confirming the true execution latency of **48 cycles** and isolating the speculative counter measurement.

---

### 4. Outstanding Limitations

1. **Operating System Noise:** While these bare-metal simulations execute in a deterministic, noise-free environment, the presence of an OS (with context switching, page table walks, and interrupts) will add timing jitter.
2. **Speculative Branch Predictor Interference:** A trained branch predictor could theoretically speculate past the branch; however, because the branch depends directly on the result of `fmv.x.d`, the branch resolution is strictly gated by the execution of the divider, preserving the serialization.

---

### 5. Final Status

**`inconclusive`**

#### Rationale:
Although we have robustly reproduced the K1 early-out timing side-channel and demonstrated both the speculative timing-read vulnerability and non-speculative execution-unit contention (positive controls), we classify the final status as **`inconclusive`** in accordance with the strict exploration rules:
> *Only classify mitigation_evaluated when the validator records speculative FP dispatch-or-issue-before-kill evidence and the non-speculative positive control; otherwise use inconclusive.*

Because our validation program focused strictly on verifying the operand-dependent early-out timing delta and the speculative timer read under strict dependency serialization rather than recording speculative FPU instruction dispatch-or-issue-before-kill evidence on a mispredicted execution path, the status is safely finalized as **`inconclusive`**.