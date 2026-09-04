"""CLI script to run the financial reconciliation benchmark and report detailed metrics."""

import argparse
import json
import os
import sys
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.evaluation import evaluate_reconciliation
from src.data_validation import audit_dataset_and_repo
from src.config import ReconciliationConfig

DIR_MAP = {
    "dev": os.path.join("data", "benchmark", "dev"),
    "holdout": os.path.join("data", "benchmark", "holdout"),
    "demo": os.path.join("data", "demo"),
    "default": "data",
}


def main():
    parser = argparse.ArgumentParser(description="Run LedgerLens financial reconciliation benchmark.")
    parser.add_argument("--data-dir", type=str, default=None, help="Directory containing dataset files (overrides --mode)")
    parser.add_argument("--mode", type=str, default="default", choices=["dev", "holdout", "demo", "default"],
                        help="Benchmark mode: dev, holdout, demo, or default (data/)")
    args = parser.parse_args()

    data_dir = args.data_dir if args.data_dir is not None else DIR_MAP.get(args.mode, "data")

    if not os.path.exists(data_dir):
        print(f"ERROR: Data directory '{data_dir}' does not exist.")
        print(f"Run: python -m scripts.generate_dataset --mode {args.mode}")
        sys.exit(1)

    print(f"Benchmark Mode: {args.mode.upper()}")
    print(f"Data Directory: {data_dir}")
    print()

    print("Running Dataset Audit...")
    t0 = time.perf_counter()
    audit = audit_dataset_and_repo(data_dir=data_dir)
    audit_time = time.perf_counter() - t0
    print(f"Audit completed in {audit_time:.2f}s")

    print("\nRunning Reconciliation Engine Benchmark...")
    t0 = time.perf_counter()
    metrics = evaluate_reconciliation(data_dir=data_dir)
    eval_time = time.perf_counter() - t0
    print(f"Evaluation completed in {eval_time:.2f}s")

    print(f"\nTotal benchmark time: {audit_time + eval_time:.2f}s")

    print("\nBenchmark Summary JSON:")
    print(json.dumps({
        "mode": args.mode,
        "data_dir": data_dir,
        "timing": {
            "audit_seconds": round(audit_time, 3),
            "evaluation_seconds": round(eval_time, 3),
            "total_seconds": round(audit_time + eval_time, 3),
        },
        "audit": audit,
        "metrics": metrics,
    }, indent=2))


if __name__ == "__main__":
    main()
