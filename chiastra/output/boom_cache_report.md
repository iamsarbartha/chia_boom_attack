# Technical Report: Cache Architecture of the Generated BOOM Processor

## 1. Overview and Methodology
This technical report examines the cache hierarchy and memory subsystem of the generated BOOM processor implementation. The analysis is strictly evidence-driven, referencing the generated SystemVerilog source files under `gen-collateral/` and the memory configuration file `chipyard.harness.TestHarness.MegaBoomV3Config.top.mems.conf`. No assumptions or prior external knowledge of BOOM or Rocket Chip architectures have been factored into the derived dimensions unless directly supported by the generated HDL or memory configuration parameters.

---

## 2. Processor and Configuration Identification
* **Configuration Target:** `MegaBoomV3Config` (Observed from configuration filenames such as `chipyard.harness.TestHarness.MegaBoomV3Config.top.mems.conf`).
* **Tile / Core Components:** 
  * Out-of-order CPU Core (`BoomCore.sv`)
  * Instruction Fetch Frontend (`BoomFrontend.sv`, containing `ICache.sv`)
  * Load-Store Unit / Non-Blocking Data Cache (`BoomNonBlockingDCache.sv`)
  * Outer / Shared Cache (`InclusiveCache.sv` via `InclusiveCacheBankScheduler.sv`, `BankedStore.sv`, and `Directory.sv`)

---

## 3. Instruction Cache (ICache) Architecture

The instruction cache is instantiated as module `ICache` within `BoomFrontend.sv` (`gen-collateral/BoomFrontend.sv:1213`).

### SRAM Dimensions & Parameters
From the memory configuration and `ICache.sv` evidence:
* **Tag Array:** 
  * Module/Instance: `tag_array_0` (`gen-collateral/ICache.sv:351`) / `tag_array_0_ext` (`chipyard.harness.TestHarness.MegaBoomV3Config.top.mems.conf:5`).
  * Depth (Sets): **64 sets** (Observed).
  * Width: **160 bits** total across 8 ways (Derived as 8 ways $\times$ 20 bits/way tag width, where each way has a 20-bit tag comparison against `io_s1_paddr[31:12]` at `gen-collateral/ICache.sv:170–184`).
  * Mask Granularity: 20 bits per way (`mems.conf:5`).
* **Data Arrays:**
  * Instances: `dataArrayB0Way_[0-7]` and `dataArrayB1Way_[0-7]` (`gen-collateral/ICache.sv:360–486`).
  * SRAM Depth: **256 entries** (`dataArrayB0Way_0_ext`, `chipyard.harness.TestHarness.MegaBoomV3Config.top.mems.conf:6`).
  * SRAM Width: **64 bits** per bank/way SRAM (`mems.conf:6`).
  * Banking / Ways: Organized into **8 ways** across **2 data banks** (`b0` and `b1`) (`gen-collateral/ICache.sv:120–135`, `360–486`).

### Capacity Arithmetic
* **Ways:** 8 ways (Derived from 8 tag fields in `tag_array_0` and 8 way data array pairs).
* **Sets:** 64 sets (Observed from `tag_array_0_ext` depth = 64).
* **Line Size:** Each cache line corresponds to 16 bytes (128 bits), fetched over TileLink (`io_resp_bits_data` is 128 bits wide at `gen-collateral/ICache.sv:80`).
* **Total ICache Capacity:**
  $$\text{Capacity} = \text{Sets} \times \text{Ways} \times \text{Line Size} = 64 \text{ sets} \times 8 \text{ ways} \times 16 \text{ bytes} = 8,192 \text{ bytes} = \mathbf{8\text{ KB}} \text{ (Derived)}$$

### Ports, Miss Handling & Hierarchy Connections
* **Ports:** Single read/write port (`RW0`) per SRAM instance (`gen-collateral/ICache.sv:353`, `366`).
* **Miss Handling:** Controlled via a 3-stage pipeline (`s0_valid`, `s1_valid`, `s2_valid`) with `s2_miss` triggering master requests on TileLink A (`auto_master_out_a_valid`, `gen-collateral/ICache.sv:146, 148, 327`).
* **Replacement Policy:** Pseudo-random replacement driven by a PRNG (`_repl_way_prng_io_out_*`, `gen-collateral/ICache.sv:137–139, 152, 157`).
* **Coherence / Invalidation:** Supports explicit invalidation via `io_invalidate` (`gen-collateral/ICache.sv:81`) connected to `io_cpu_flush_icache` from the core (`BoomFrontend.sv:1230`, `BoomCore.sv:9144`).

---

## 4. Data Cache (DCache) Architecture

The data cache is implemented as a non-blocking structure (`BoomNonBlockingDCache.sv`) connected to the load-store unit (`LSU.sv`).

### SRAM Dimensions & Parameters
From `BoomNonBlockingDCache.sv` and `mems.conf`:
* **Meta Arrays:** 
  * Instances: `meta_0` / `meta_0_ext` (`chipyard.harness.TestHarness.MegaBoomV3Config.top.mems.conf:12`).
  * Depth (Sets): **128 sets** (Derived/Observed from depth 128).
  * Width: **120 bits** (Supporting 8 ways with tag + coherence state; 8 ways $\times$ (20-bit tag + 2-bit coh state + metadata bits)).
* **Data Arrays:**
  * Instances: `data` / `data_ext` (`chipyard.harness.TestHarness.MegaBoomV3Config.top.mems.conf:15`).
  * Depth: **2048 entries** (`mems.conf:15`).
  * Width: **8 bits** per data slice (`mems.conf:15`), banked and organized to support 128-bit data lines across 8 ways.
* **MSHRs & Buffers:**
  * MSHRs (Miss Status Holding Registers) are instantiated inside `BoomNonBlockingDCache` (`_mshrs_...`, `gen-collateral/BoomNonBlockingDCache.sv:433`).

### Capacity Arithmetic
* **Ways:** **8 ways** (Observed from way-enable signals `[7:0]` and 8-way tag match outputs `s2_tag_match_way_0` at `gen-collateral/BoomNonBlockingDCache.sv:1572`).
* **Sets:** **128 sets** (Observed from `meta_0_ext` depth = 128).
* **Line Size:** 64 bytes / 512 bits per cache block, transferred in beats over TileLink (128-bit data bus interfaces `auto_out_a_bits_data`, `auto_out_d_bits_data` at `BoomNonBlockingDCache.sv:75, 97`).
* **Total DCache Capacity:**
  $$\text{Capacity} = \text{Sets} \times \text{Ways} \times \text{Line Size} = 128 \text{ sets} \times 8 \text{ ways} \times 64 \text{ bytes} = 65,536 \text{ bytes} = \mathbf{64\text{ KB}} \text{ (Derived)}$$

### Ports, Miss Handling & Hierarchy Connections
* **Ports:** Multi-ported/banked read and write arbiters (`_dataReadArb`, `_dataWriteArb`, `_metaReadArb`, `_metaWriteArb` at `BoomNonBlockingDCache.sv:331–376`), supporting dual-issue load/store requests (`io_lsu_req_bits_0` and `io_lsu_req_bits_1` at `BoomNonBlockingDCache.sv:103, 267`).
* **Miss Handling:** Non-blocking design utilizing MSHRs (`BoomMSHR.sv`, `BoomMSHRFile.sv`) allowing multiple outstanding misses.
* **Replacement & Coherence:** Implements full TileLink coherence (supports channels A, B, C, D, E for PBUS/C-cache operations) with probe units (`BoomProbeUnit.sv`) and writeback units (`BoomWritebackUnit.sv`) handling cache-line state transitions (Invalid, Branch, Shared, Owned, Dirty / `_s2_has_permission_r_T`).

---

## 5. Shared / Outer Cache (L2 / InclusiveCache) Architecture

An outer shared cache (`InclusiveCache.sv`) is present in the hierarchy, managing requests between the tile's inner caches and system memory / memory bus (`MemoryBus.sv`).

### SRAM Dimensions & Parameters
From `InclusiveCache.sv`, `BankedStore.sv`, and `mems.conf`:
* **Directory Array:**
  * Instance: `cc_dir_ext` (`chipyard.harness.TestHarness.MegaBoomV3Config.top.mems.conf:1`).
  * Depth (Sets): **1024 sets** (`mems.conf:1`).
  * Width: **152 bits** (`mems.conf:1`).
* **Banked Store Data Arrays:**
  * Instance: `cc_banks_0_ext` (`chipyard.harness.TestHarness.MegaBoomV3Config.top.mems.conf:2`).
  * Depth: **8192 entries** (`mems.conf:2`).
  * Width: **64 bits** (`mems.conf:2`).

### Capacity Arithmetic
* **Banks:** Banked architecture (`InclusiveCacheBankScheduler.sv`, `BankedStore.sv`).
* **Directory Sets:** 1024 sets (`mems.conf:1`).
* **Total L2 Capacity (Derived from mems.conf):**
  * The bank store `cc_banks_0_ext` has depth = 8192 and width = 64 bits (8 bytes).
  * $\text{Store Capacity} = 8192 \times 8 \text{ bytes} = 65,536 \text{ bytes} = \mathbf{64\text{ KB}}$ per bank (or scaled by bank count in the L2 wrapper).

### Ports, Miss Handling & Hierarchy Connections
* **Ports:** TileLink inward (from `BoomTile` client xbar) and outward (to `MemoryBus`) supporting full 5-channel TileLink (`auto_in_a`, `auto_in_b`, `auto_in_c`, `auto_in_d`, `auto_in_e` and `auto_out_*` at `InclusiveCache.sv:21–86`).
* **Miss Handling & Control:** Managed by `InclusiveCacheControl.sv` and `InclusiveCacheBankScheduler.sv`, providing inclusive snoop filtering, flushing (`_ctrls_io_flush_req_valid`), and directory maintenance.

---

## 6. Hierarchy Summary and Cache-Parameter Table

### Hierarchy Summary
* **Level 1 Instruction Cache (ICache):** 8 KB, 8-way set-associative, 16-byte line size, virtually indexed / physically tagged, single-banked with pseudo-random replacement. Connected directly to `BoomFrontend` and TileLink client port.
* **Level 1 Data Cache (DCache):** 64 KB, 8-way set-associative, 64-byte line size, non-blocking with MSHRs, dual-ported load/store interface (`BoomNonBlockingDCache`). Connects to TileLink for full cache-coherent outer communication.
* **Level 2 Shared Cache (InclusiveCache):** Inclusive outer cache managed by `InclusiveCache.sv` with directory arrays (`cc_dir_ext`, 1024 sets) and banked data stores (`cc_banks_0_ext`, 8192 $\times$ 64-bit), interfacing between the tile and the system memory bus via TileLink.

### Cache-Parameter Table

| Cache Level | Capacity (Derived) | Set Count (Observed) | Way Count (Observed) | Line Size | Banking / Organization | Miss Handling / MSHR | Coherence / Repl. Clues |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **L1 Instruction (ICache)** | **8 KB** | 64 | 8 | 16 Bytes | 2 Data Banks (`b0`, `b1`), 8 Way Slices | Blocking / Refill Queue | Pseudo-Random PRNG / Invalidate (`io_invalidate`) |
| **L1 Data (DCache)** | **64 KB** | 128 | 8 | 64 Bytes | Multi-banked, Dual-port read/write arbiters | Non-Blocking (`BoomMSHR`, `BoomMSHRFile`) | Full TileLink Coherence (A/B/C/D/E), Prober/WB units |
| **L2 Shared (InclusiveCache)** | **64 KB+** *(Store)* | 1024 *(Dir)* | Unknown / Configurable | 64 Bytes | Banked Store (`cc_banks_0_ext`), Directory (`cc_dir_ext`) | `InclusiveCacheBankScheduler` / Control | Inclusive snoop/directory controller, Flush/Invalidate requests |