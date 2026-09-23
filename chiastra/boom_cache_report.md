# Technical Report: Cache Architecture of the BOOM Processor

This technical report details the microarchitecture of the cache hierarchy of the BOOM (Berkeley Out-of-Order Machine) processor configuration implemented in the provided Verilator RTL. The report is built on a direct, bottom-up analysis of the generated Verilog/SystemVerilog collateral.

---

## 1. Executive Summary & Processor Identification

Based on the generated Verilator build files and memory configuration metadata, the processor under review is the **MegaBoomV3Config** configuration of the RISC-V BOOM processor:
* **Target Build Configuration:** `chipyard.harness.TestHarness.MegaBoomV3Config` (observed in the naming of memory configuration files, e.g., `chipyard.harness.TestHarness.MegaBoomV3Config.mems.conf` and `chipyard.harness.TestHarness.MegaBoomV3Config.top.mems.conf`).
* **Cache Hierarchy:** The memory hierarchy comprises a 2-level cache organization:
  1. **L1 Instruction Cache (ICache):** Private, multi-banked, multi-way set-associative cache.
  2. **L1 Data Cache (DCache):** Private, non-blocking, fully duplicated multi-way set-associative cache supporting parallel load ports.
  3. **L2 Shared/Outer Cache (Inclusive Cache):** A multi-banked, highly concurrent coherence manager acting as an inclusive last-level cache (LLC).
* **System Address Space Configuration:** 40-bit Virtual/Physical Address Bus [Observed: `gen-collateral/BoomMSHRFile.sv:161` (`io_req_0_bits_addr[39:0]`)]. However, the cache tag arrays restrict the active physical tag comparisons to a 32-bit physical address space [Derived/Observed: `gen-collateral/BoomNonBlockingDCache.sv:1572`].

---

## 2. Tool Evidence & Search Log

The findings in this report were gathered by examining the generated hardware collateral. The key search vectors and their corresponding structural targets are listed below:

| Target Query | Primary RTL Source File | Structural Discovery |
| :--- | :--- | :--- |
| `chipyard.harness.TestHarness.MegaBoomV3Config.mems.conf` | `chipyard.harness.TestHarness.MegaBoomV3Config.mems.conf` | Raw SRAM depth, width, and mask parameters for all caches |
| `tag_array_0_ext` / `dataArrayB0Way_0_ext` | `gen-collateral/ICache.sv` | Private L1 Instruction Cache tag/data layouts and indexing |
| `tag_array_ext` / `array_0_0_ext` | `gen-collateral/BoomDuplicatedDataArray.sv` | Private L1 Data Cache duplicated multi-port bank structures |
| `BoomMSHRFile` | `gen-collateral/BoomMSHRFile.sv` | 8 cacheable MSHRs and 1 MMIO IOMSHR configuration |
| `NLPrefetcher` | `gen-collateral/NLPrefetcher.sv` | L1 Data Cache next-line hardware prefetcher (+64B) |
| `cc_dir_ext` / `cc_banks_0_ext` | `gen-collateral/Directory.sv` & `gen-collateral/BankedStore.sv` | Shared L2 Inclusive Cache directory and banked memory store |

---

## 3. L1 Instruction Cache (ICache)

The L1 ICache is designed to maximize fetch bandwidth for the high-issue-width MegaBoom front-end, retrieving up to 128 bits of instruction data per cycle.

### A. ICache Configuration Parameters
* **SRAM Configuration:**
  * **Tag Array (`tag_array_0_ext`):** Depth 64, Width 160 bits, Mask Granularity 20 bits [Observed: `top.mems.conf:5`].
  * **Data Array (`dataArrayB0Way_0_ext`):** Depth 256, Width 64 bits [Observed: `top.mems.conf:6`].
* **Associativity (Ways):** **8** [Derived: `160 bits (total tag width) / 20 bits (mask granularity) = 8 ways`].
* **Sets:** **64** [Observed: `tag_array_0_ext` depth of 64].
* **Cache Line Size:** **64 Bytes (512 bits)** [Derived]:
  $$\frac{256 \text{ (SRAM Depth)}}{64 \text{ (Cache Sets)}} = 4 \text{ sub-words per cache line per way}$$
  $$\text{Sub-word width} = 2 \text{ Banks (B0 and B1)} \times 64 \text{ bits} = 128 \text{ bits (16 Bytes)}$$
  $$\text{Line Size} = 4 \text{ sub-words} \times 16 \text{ Bytes} = 64 \text{ Bytes (512 bits)}$$
* **Total Capacity:** **32 KB** [Derived]:
  $$\text{Capacity} = 64 \text{ sets} \times 8 \text{ ways} \times 64 \text{ Bytes/line} = 32,768 \text{ Bytes (32 KB)}$$

### B. Microarchitectural Implementation & Refill Mechanics
* **Bank Organization:** The data store is organized into two physical banks: `B0` and `B1` [Observed: `gen-collateral/ICache.sv:252`]. 
* **Fetch Bus Width:** On a cache hit, data from `B0` and `B1` of the hit way are concatenated to form a 128-bit wide fetch packet:
  ```verilog
  s2_dout_0_REG <= {_dataArrayB1Way_0_RW0_rdata, _dataArrayB0Way_0_RW0_rdata};
  ```
  [Observed: `gen-collateral/ICache.sv:252-259`].
* **Set Indexing & Offset:** 
  * The byte offset within the 64-Byte line is determined by address bits `addr[5:0]`.
  * The set index is determined by address bits `addr[11:6]` (mapping to 64 sets, $2^6 = 64$) [Observed: `gen-collateral/ICache.sv:242`].
  * The combined index + offset is exactly 12 bits, matching the standard RISC-V 4 KB virtual page size. This ensures the cache can operate as a Virtually Indexed, Physically Tagged (VIPT) cache without aliasing.
* **Valid Bits Storage:** Unlike the tags, which reside in SRAM, the valid bits are maintained in a 512-bit register array `vb_array` [Observed: `gen-collateral/ICache.sv:272`]:
  $$\text{Total Valid Bits} = 64 \text{ sets} \times 8 \text{ ways} = 512 \text{ bits}$$
  This register-based design allows a single-cycle flash invalidation on a pipeline fence or `fence.i` instruction by clearing `vb_array <= 512'h0;` [Observed: `gen-collateral/ICache.sv:278-279`].
* **Replacement Policy:** Pseudo-random replacement using a Fibonacci Linear Feedback Shift Register (LFSR) [Observed: `gen-collateral/ICache.sv:242` and `gen-collateral/ICache.sv:330` (`MaxPeriodFibonacciLFSR repl_way_prng`)].
* **Outbound Interface:** Refills are performed directly over a TileLink Master interface [Observed: `gen-collateral/ICache.sv:67-73` (TileLink Master Port A and D signals)].

---

## 4. L1 Data Cache (DCache)

The L1 DCache is a high-performance, non-blocking, out-of-order L1 cache designed to support the dual load-issue capabilities of the MegaBoom core.

### A. DCache Configuration Parameters
* **SRAM Configuration:**
  * **Tag Array (`tag_array_ext`):** Depth 64, Width 176 bits, Mask Granularity 22 bits [Observed: `top.mems.conf:3`].
  * **Data Array (`array_0_0_ext`):** Depth 256, Width 128 bits, Mask Granularity 64 bits [Observed: `top.mems.conf:4`].
* **Associativity (Ways):** **8** [Derived: `176 bits (total tag width) / 22 bits (mask granularity) = 8 ways`].
* **Sets:** **64** [Observed: `tag_array_ext` depth of 64].
* **Cache Line Size:** **64 Bytes (512 bits)** [Derived]:
  $$\frac{256 \text{ (SRAM Depth)}}{64 \text{ (Cache Sets)}} = 4 \text{ sub-words per cache line per way}$$
  $$\text{Sub-word width} = 128 \text{ bits (16 Bytes)}$$
  $$\text{Line Size} = 4 \text{ sub-words} \times 16 \text{ Bytes} = 64 \text{ Bytes (512 bits)}$$
* **Total Capacity:** **32 KB** [Derived]:
  $$\text{Capacity} = 64 \text{ sets} \times 8 \text{ ways} \times 64 \text{ Bytes/line} = 32 \text{ KB}$$

### B. Dual-Port Duplicated Data & Tag Architecture
To support two concurrent, fully independent load operations per clock cycle without the area and wire-congestion penalties of multi-ported SRAM cells, the MegaBoom L1 DCache implements a **fully duplicated** structure:
* **Duplicated Data Array:** The data arrays are replicated into two identical copies: Bank 0 (`array_X_0`) and Bank 1 (`array_X_1`) [Observed: `gen-collateral/BoomDuplicatedDataArray.sv:77-92`].
  * **Parallel Reads:** Load Port 0 accesses Bank 0 using `io_read_0_bits_addr[11:4]`, while Load Port 1 simultaneously accesses Bank 1 using `io_read_1_bits_addr[11:4]` [Observed: `gen-collateral/BoomDuplicatedDataArray.sv:171, 259`].
  * **Coherent Writes:** All write operations (stores or cache refills) broadcast the same address and data to both banks simultaneously (`array_0_0_MPORT_en` drives both Bank 0 and Bank 1 write enables) [Observed: `gen-collateral/BoomDuplicatedDataArray.sv:263-264`].
* **Duplicated Tag Array:** To match the dual load ports, the metadata tag arrays are also fully duplicated into two parallel instances: `meta_0` and `meta_1` [Observed: `gen-collateral/BoomNonBlockingDCache.sv:2540, 2569`]. Both copies perform simultaneous, independent tag-lookup and hit evaluation for Load Port 0 and Load Port 1 [Observed: `gen-collateral/BoomNonBlockingDCache.sv:1572-1573`].

### C. Physical Address Space Constraint
The outer system bus defines physical addresses as 40-bit values (`addr[39:0]`) [Observed: `gen-collateral/BoomMSHRFile.sv:161`]. However, the L1 data cache tag array metadata only allocates 20 bits for the physical tag [Observed: `top.mems.conf:3` width 176 / 8 ways = 22 bits metadata per way, of which 20 bits are the tag and 2 bits represent the coherence state]. 

Because the tag array stores only 20 bits, the physical tag match logic pads the tag with 8 leading zeros:
```verilog
s2_tag_match_way_0 <= ... {{8'h0, _meta_0_io_resp_7_tag} == s1_req_0_addr[39:12] & (|_meta_0_io_resp_7_coh_state), ...};
```
[Observed: `gen-collateral/BoomNonBlockingDCache.sv:1572`]. 

This microarchitectural optimization indicates that **the processor physical address space supported by the L1 cache is limited to $20 \text{ tag bits} + 12 \text{ index/offset bits} = 32$ bits (4 GB)**. Physical addresses exceeding `0x00_FFFF_FFFF` will mismatch since the top 8 physical address bits are hardwired to zero in the comparison.

### D. Miss Status Holding Registers (MSHR) & Outbound Interface
* **Cacheable MSHRs:** **8 concurrent outstanding miss registers** (`mshrs_0` to `mshrs_7`) [Observed: `gen-collateral/BoomMSHRFile.sv:4720-7037`]. This allows up to 8 outstanding cache-line refills to be tracked in parallel.
* **Non-Cacheable MMIO MSHRs:** **1 dedicated non-cacheable I/O register** (`mmios_0`) [Observed: `gen-collateral/BoomMSHRFile.sv:7372`]. Non-cacheable MMIO transactions bypass the cache array entirely.
* **Writeback Units:** **1** outstanding writeback tracker (`wb`) manages dirty line evictions to the L2 [Observed: `gen-collateral/BoomNonBlockingDCache.sv:2127`].
* **Next-Line Hardware Prefetcher:** The cache integrates a dedicated Next-Line Prefetcher (`prefetcher` of module type `NLPrefetcher`) [Observed: `gen-collateral/BoomMSHRFile.sv:2800`]. The prefetcher monitors requests and generates prefetch actions targeting the adjacent downstream cache line:
  ```verilog
  wire [39:0] _mshr_req_addr_T = io_req_addr + 40'h40;
  ```
  [Observed: `gen-collateral/NLPrefetcher.sv:63`]. Since `40'h40` is exactly 64 bytes (decimal), the prefetcher targets `current_address + 1 cache line`.

---

## 5. Shared L2 Cache (Inclusive Cache Coherence Manager)

The L2 cache acts as an inclusive shared cache and a system-level coherence manager, coordinating directory states across the core's private L1 caches using TileLink channels A, B, C, D, and E.

### A. L2 Configuration Parameters
* **SRAM Configuration:**
  * **Directory Array (`cc_dir_ext`):** Depth 1024, Width 152 bits, Mask Granularity 19 bits [Observed: `top.mems.conf:1`].
  * **Banked Data Store (`cc_banks_0_ext`):** Depth 8192, Width 64 bits [Observed: `top.mems.conf:2`].
* **Associativity (Ways):** **8** [Derived: `152 bits (total directory width) / 19 bits (mask granularity) = 8 ways`].
* **Sets:** **1024** [Observed: `cc_dir_ext` depth of 1024].
* **Cache Line Size:** **64 Bytes (512 bits)** [Derived]:
  The data store is constructed from 8 banked SRAMs (`cc_banks_0` to `cc_banks_7`) [Observed: `gen-collateral/BankedStore.sv:104-111`]:
  $$\text{Line Size} = 8 \text{ Banks} \times 64 \text{ bits/bank} = 512 \text{ bits (64 Bytes)}$$
* **Total Capacity:** **512 KB** [Derived]:
  $$\text{Capacity} = 1024 \text{ sets} \times 8 \text{ ways} \times 64 \text{ Bytes/line} = 524,288 \text{ Bytes (512 KB)}$$

### B. L2 Directory & Coherence Architecture
* **Directory Indexing:** The directory tag and state tracking SRAM `cc_dir` is indexed with a 10-bit set index (`cc_dir_MPORT_addr[9:0]`) [Observed: `gen-collateral/Directory.sv:133`].
* **Directory Entry Layout:** Each way's metadata in the directory comprises exactly **19 bits** [Observed: `top.mems.conf:1` (`mask_gran 19`)]. The entry bits are allocated as follows:
  * **Physical Tag:** **13 bits** [Observed: `gen-collateral/Directory.sv:198` (`_cc_dir_RW0_rdata[14:2]`)]. 
  * **Coherence State:** **2 bits** [Observed: `gen-collateral/Directory.sv:309` (`_cc_dir_RW0_rdata[17:16]`)]. These bits represent the standard TileLink coherence states (Invalid, Shared, Clean, Dirty).
  * **Dirty State:** **1 bit** [Observed: `gen-collateral/Directory.sv:308` (`_cc_dir_RW0_rdata[18]`)].
  * **Client Presence Bitmask:** **1 bit** [Observed: `gen-collateral/Directory.sv:310` (`_cc_dir_RW0_rdata[15]`)]. This tracks whether the single Tile core has a copy of the line in its L1.
  * **Prefetched Indicator:** **1 bit** [Observed: `gen-collateral/Directory.sv:312` (`_cc_dir_RW0_rdata[1]`)].
  * **Prefetch Brought Indicator:** **1 bit** [Observed: `gen-collateral/Directory.sv:313` (`_cc_dir_RW0_rdata[0]`)].
  * **Total Size:** $13 + 2 + 1 + 1 + 1 + 1 = 19$ bits. This aligns with the SRAM mask granularity.
* **L2 Physical Address Mapping:** The L2 index and tag verify a 29-bit active physical address space:
  $$\text{Physical Address} = 13 \text{ Tag bits} + 10 \text{ Index bits} + 6 \text{ Offset bits} = 29 \text{ bits}$$
* **Replacement Policy:** Monotone-checked random replacement logic driven by a PRNG [Observed: `gen-collateral/Directory.sv:182` (`_victimLFSR_prng_io_out_9`)].

---

## 6. Cache Hierarchy Summary & Parameter Table

### Cache Hierarchy Summary
```
+-------------------------------------------------------------+
|                         MegaBoom Core                       |
|   +--------------------------+   +----------------------+   |
|   |   L1 ICache (Private)    |   | L1 DCache (Private)  |   |
|   |         32 KB            |   |        32 KB         |   |
|   |  8-Way, 64-Set, 2-Bank   |   |   8-Way, 64-Set      |   |
|   |                          |   | (Duplicated Arrays   |   |
|   |                          |   |   for Dual Loads)    |   |
|   +------------+-------------+   +-----------+----------+   |
+----------------|-----------------------------|--------------+
                 | TileLink                    | TileLink
                 | Channel A/D                 | Channel A/B/C/D/E
+----------------v-----------------------------v--------------+
|                    Shared L2 Inclusive Cache                |
|                             512 KB                          |
|                     8-Way, 1024-Set, 8-Bank                 |
+-------------------------------------------------------------+
```

### Cache-Parameter Table

| Parameter | L1 Instruction Cache | L1 Data Cache | Shared L2 Cache |
| :--- | :--- | :--- | :--- |
| **Classification** | Private [Derived] | Private [Derived] | Shared / Outer LLC [Derived] |
| **Capacity** | 32 KB [Derived] | 32 KB [Derived] | 512 KB [Derived] |
| **Associativity (Ways)** | 8-way [Derived] | 8-way [Derived] | 8-way [Derived] |
| **Number of Sets** | 64 [Observed] | 64 [Observed] | 1024 [Observed] |
| **Line Size** | 64 Bytes [Derived] | 64 Bytes [Derived] | 64 Bytes [Derived] |
| **Write Policy** | Read-Only [Observed] | Write-Back, Write-Allocate [Derived] | Write-Back [Derived] |
| **Inclusivity** | Non-Inclusive [Observed] | Non-Inclusive [Observed] | Fully Inclusive [Observed] |
| **Replacement Policy** | Pseudo-Random (LFSR) [Observed] | Unknown (tracked in L1 Meta) [Unknown] | Monotone Random (LFSR) [Observed] |
| **Parallel Read Ports** | 1 (128-bit wide) [Derived] | 2 (128-bit wide each) [Observed] | 1 (64-bit wide per bank) [Observed] |
| **SRAM Bank Layout** | 2 banks (B0, B1) [Observed] | 2 banks (fully duplicated) [Observed] | 8 banks [Observed] |
| **Active Phys. Tag Size** | 20 bits [Observed] | 20 bits (padded to 28) [Observed] | 13 bits [Observed] |
| **Active Phys. Address Space** | 32 bits (4 GB) [Derived] | 32 bits (4 GB) [Derived] | 29 bits (512 MB) [Derived] |
| **MSHR File Capacity** | N/A (simple refill register) [Observed] | 8 Cacheable, 1 MMIO [Observed] | N/A (Transaction buffers) [Observed] |
| **Hardware Prefetcher** | None [Observed] | Next-Line Prefetcher (+64B) [Observed] | None [Observed] |
| **Coherence Protocol** | None (Private Read-Only) [Observed] | TileLink Coherence (Client) [Observed] | TileLink Coherence (Manager) [Observed] |