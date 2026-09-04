"""Throughput benchmark — measures reconciliation performance across varying dataset sizes.

Reports:
  - Preprocessing time
  - Deterministic reconciliation time (AI disabled)
  - Total batch time
  - Records/second
  - Status counts per scale

Uses time.perf_counter() for high-resolution timing.
AI is disabled for large-scale runs to isolate deterministic throughput.
"""

import sys
import os
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data_generator import generate_synthetic_data
from src.reconciliation import reconcile
from src.config import ReconciliationConfig


SCALES = [250, 1000, 5000, 10000]


def run_throughput_benchmark():
    """Run throughput benchmark across multiple dataset scales."""
    print("=" * 75)
    print("LEDGERLENS THROUGHPUT BENCHMARK")
    print("=" * 75)
    print(f"Scales: {SCALES}")
    print(f"AI: Disabled (deterministic-only throughput)")
    print(f"Timer: time.perf_counter() (high-resolution)")
    print()

    config = ReconciliationConfig(ENABLE_AI_ASSIST=False)
    results = []

    for scale in SCALES:
        print(f"--- Scale: {scale} records ---")

        # Generate dataset
        t_gen_start = time.perf_counter()
        tmpdir = os.path.join("data", "_throughput_tmp")
        df_ledger, df_bank, _ = generate_synthetic_data(
            seed=42 + scale,
            output_dir=tmpdir,
            ledger_count=scale,
            bank_count=scale,
        )
        t_gen_end = time.perf_counter()
        gen_time = t_gen_end - t_gen_start

        actual_ledger = len(df_ledger)
        actual_bank = len(df_bank)

        # Reconcile
        t_recon_start = time.perf_counter()
        df_results = reconcile(df_ledger, df_bank, config=config)
        t_recon_end = time.perf_counter()
        recon_time = t_recon_end - t_recon_start

        total_time = gen_time + recon_time
        records_per_sec = actual_ledger / recon_time if recon_time > 0 else 0

        status_counts = df_results["status"].value_counts().to_dict()
        matched = status_counts.get("MATCHED", 0)
        review = status_counts.get("REVIEW", 0)
        unmatched = status_counts.get("UNMATCHED", 0)

        result = {
            "target_scale": scale,
            "actual_ledger": actual_ledger,
            "actual_bank": actual_bank,
            "total_results": len(df_results),
            "gen_time_s": round(gen_time, 3),
            "recon_time_s": round(recon_time, 3),
            "total_time_s": round(total_time, 3),
            "records_per_sec": round(records_per_sec, 1),
            "matched": matched,
            "review": review,
            "unmatched": unmatched,
        }
        results.append(result)

        print(f"  Ledger: {actual_ledger}  Bank: {actual_bank}  Results: {len(df_results)}")
        print(f"  Gen: {gen_time:.3f}s  Recon: {recon_time:.3f}s  Total: {total_time:.3f}s")
        print(f"  Throughput: {records_per_sec:.1f} records/sec (deterministic)")
        print(f"  MATCHED={matched}  REVIEW={review}  UNMATCHED={unmatched}")
        print()

    # Cleanup temp dir
    import shutil
    tmpdir_path = os.path.join("data", "_throughput_tmp")
    if os.path.exists(tmpdir_path):
        shutil.rmtree(tmpdir_path, ignore_errors=True)

    # Summary table
    print("=" * 75)
    print(f"{'Records':>10} | {'Recon Time':>12} | {'Rec/sec':>10} | {'MATCHED':>8} | {'REVIEW':>8} | {'UNMATCHED':>10}")
    print("-" * 75)
    for r in results:
        print(f"{r['actual_ledger']:>10} | {r['recon_time_s']:>10.3f}s | {r['records_per_sec']:>10.1f} | {r['matched']:>8} | {r['review']:>8} | {r['unmatched']:>10}")
    print("=" * 75)

    return results


if __name__ == "__main__":
    run_throughput_benchmark()
