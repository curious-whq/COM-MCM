# XiangShan current model

This directory contains the source-pinned XiangShan Kunminghu-v3 memory µMCM under construction.

Current status: **stage 8 complete — aligned scalar store STA/STD and VirtualStoreQueue lifecycle executable**.

- `events.yaml` defines architectural, public hierarchy and reserved private event vocabulary.
- `model/**/boundary.yaml` contains behavior-free module contracts.
- `composition/baseline.yaml` connects every required internal input through explicit public ports with strict encapsulation.
- `hierarchy/interfaces.yaml` is generated from that composition and is the canonical stage-1 public/private inventory.
- `model/core/lifecycle.yaml` implements dispatch allocation, issue, ROB writeback/commit, precise memory exception and redirect squash.
- `composition/core_lifecycle.yaml` and `hierarchy/core_lifecycle_interfaces.yaml` are the executable Stage 2 slice and its audited interface inventory.
- `coverage/stage2.yaml` checks the four required lifecycle paths; negative traces reject ghost commit and post-redirect writeback.
- `model/mmu/l1_dtlb.yaml` derives L1 hit/miss, replay, PTW request/refill, explicit LSU retry, SFENCE invalidation, and stale-response drop from private state.
- `composition/dtlb_l1.yaml` and `hierarchy/dtlb_l1_interfaces.yaml` are the executable Stage 3 slice and its audited public/private surface.
- `coverage/stage3.yaml` checks five required DTLB paths; negative traces reject a retry without refill and prevent `ldtlb` state from leaking into `sttlb`.
- `model/mmu/translation_backend.yaml` derives L2 hits/misses, S1 and G-stage walks, page/guest-page/access faults, protection checks, refill, and SFENCE/HFENCE invalidation.
- `composition/translation_backend.yaml` and `hierarchy/translation_backend_interfaces.yaml` are the executable Stage 4 slice and audited interface surface.
- `composition/translation_path.yaml` connects the Stage 3 L1 DTLB to the Stage 4 backend and proves miss-to-refill-to-retry closure.
- `coverage/stage4.yaml` checks ten required paths; its negative trace rejects a public PTW response with the wrong physical address.
- `model/load/scalar_pipeline.yaml` derives scalar S0-S3 progress, parallel TLB/L1D/forward requests, full forwarding or cache-data selection, replay causes, faults, LQ update, and writeback.
- `composition/scalar_load.yaml` and `hierarchy/scalar_load_interfaces.yaml` are the executable Stage 5 slice and audited interface surface.
- `composition/load_translation.yaml` connects the Stage 5 load pipeline to the Stage 3 L1 DTLB and proves a generated translation request can drive an end-to-end load writeback.
- `coverage/stage5.yaml` checks eleven required paths; negative traces reject writeback after nack and a writeback value inconsistent with full store forwarding.
- `model/load/queue_lifecycle.yaml` derives virtual-LQ allocation/completion/replay/redirect lifetime, in-order reclamation, RAR release tracking, and RAW overlap detection.
- `composition/load_queue.yaml` and `hierarchy/load_queue_interfaces.yaml` are the executable Stage 6 slice and audited interface surface.
- `composition/scalar_load_queue.yaml` connects the Stage 5 S2 order query and S3 pipeline update to the Stage 6 queue model.
- `coverage/stage6.yaml` checks ten required paths; negative traces reject RAR without release, RAW recovery for disjoint byte masks, and updates after redirect reclamation.
- `model/load/replay_queue.yaml` preserves replay cause, cause-specific blocking/wakeup, high/low entrance selection, one retry epoch, feedback reuse/free, and redirect cancellation.
- `model/core/memory_dependency_predictor.yaml` implements all five SSIT training outcomes and the active LFST pending-store wait/release path; the uninstantiated WaitTable is explicitly excluded.
- `composition/load_replay.yaml`, `composition/scalar_load_replay.yaml`, and `composition/memory_dependency_predictor.yaml` are the executable Stage 7 slices with generated interface inventories.
- `coverage/stage7.yaml` covers all fifteen required replay/SSIT/LFST paths; negative traces reject wrong replay wakeup and predicted loads issuing ahead of their store.
- `model/store/scalar_pipeline.yaml` independently derives aligned scalar STA S0-S3 and STD data flow, preserves translated address/data identity, and permits store writeback only after both SQ payloads exist.
- `model/store/virtual_queue.yaml` implements the selected 128-entry VSQ's bounded allocation, in-order ROB retirement, and two-cycle redirect recovery boundary without stealing PSQ responsibilities from Stage 9.
- `composition/scalar_store.yaml`, `composition/virtual_store_queue.yaml`, `composition/scalar_store_queue.yaml`, and `composition/store_translation.yaml` are the executable Stage 8 slices and integrations.
- `coverage/stage8.yaml` covers all fourteen required store/VSQ paths; negative traces reject wrong address/data, premature writeback, out-of-order retirement, and post-redirect completion.
- `SOURCE_MAP.md` pins source revisions, parameters, file hashes and line anchors.
- `PLAN.md` defines the remaining implementation stages and their acceptance gates.

The Stage 1 composition intentionally remains behavior-free so its structural baseline is stable. Behavioral slices are added beside it and composed progressively.

```bash
PYTHONPATH=src python3 -m umcm compose \
  --schema examples/xiangshan/events.yaml \
  --composition examples/xiangshan/composition/baseline.yaml \
  --output /tmp/xiangshan-stage1-composed.yaml

PYTHONPATH=src python3 -m umcm interfaces \
  --schema examples/xiangshan/events.yaml \
  --composition examples/xiangshan/composition/baseline.yaml \
  --output /tmp/xiangshan-stage1-interfaces.yaml

PYTHONPATH=src python3 -m umcm complete \
  --schema examples/xiangshan/events.yaml \
  --trace examples/xiangshan/traces/core/normal_commit.yaml \
  --composition examples/xiangshan/composition/core_lifecycle.yaml \
  --backend z3 --output /tmp/xiangshan-stage2-normal.yaml

PYTHONPATH=src python3 -m umcm complete \
  --schema examples/xiangshan/events.yaml \
  --trace examples/xiangshan/traces/mmu/miss_refill_retry.yaml \
  --composition examples/xiangshan/composition/dtlb_l1.yaml \
  --backend z3 --output /tmp/xiangshan-stage3-dtlb.yaml

PYTHONPATH=src python3 -m umcm complete \
  --schema examples/xiangshan/events.yaml \
  --trace examples/xiangshan/traces/mmu/two_stage_translation.yaml \
  --composition examples/xiangshan/composition/translation_backend.yaml \
  --backend z3 --output /tmp/xiangshan-stage4-translation.yaml

PYTHONPATH=src python3 -m umcm complete \
  --schema examples/xiangshan/events.yaml \
  --trace examples/xiangshan/traces/load/cache_hit.yaml \
  --composition examples/xiangshan/composition/scalar_load.yaml \
  --backend z3 --output /tmp/xiangshan-stage5-load.yaml

PYTHONPATH=src python3 -m umcm complete \
  --schema examples/xiangshan/events.yaml \
  --trace examples/xiangshan/traces/load_queue/rar_violation.yaml \
  --composition examples/xiangshan/composition/load_queue.yaml \
  --backend z3 --output /tmp/xiangshan-stage6-rar.yaml

PYTHONPATH=src python3 -m umcm complete \
  --schema examples/xiangshan/events.yaml \
  --trace examples/xiangshan/traces/replay/blocked_refill.yaml \
  --composition examples/xiangshan/composition/load_replay.yaml \
  --backend z3 --output /tmp/xiangshan-stage7-replay.yaml

PYTHONPATH=src python3 -m umcm complete \
  --schema examples/xiangshan/events.yaml \
  --trace examples/xiangshan/traces/mdp/trained_wait.yaml \
  --composition examples/xiangshan/composition/memory_dependency_predictor.yaml \
  --backend z3 --output /tmp/xiangshan-stage7-mdp.yaml

PYTHONPATH=src python3 -m umcm complete \
  --schema examples/xiangshan/events.yaml \
  --trace examples/xiangshan/traces/store/cacheable_success.yaml \
  --composition examples/xiangshan/composition/scalar_store.yaml \
  --backend z3 --output /tmp/xiangshan-stage8-store.yaml

PYTHONPATH=src python3 -m umcm complete \
  --schema examples/xiangshan/events.yaml \
  --trace examples/xiangshan/traces/store_queue/in_order_retire.yaml \
  --composition examples/xiangshan/composition/virtual_store_queue.yaml \
  --backend z3 --output /tmp/xiangshan-stage8-vsq.yaml
```

The hardware S4 is not an ordinary aligned-load stage: it feeds an unaligned head back to S3 for head/tail concatenation. That path stays grouped with scalar-unaligned/vector semantics in Stage 12 rather than being approximated as an aligned S4 hop.

Next: Stage 9, physical StoreQueue, byte forwarding, unaligned splitting, and drain selection.
