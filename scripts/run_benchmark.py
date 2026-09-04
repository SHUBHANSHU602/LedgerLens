"""CLI script to run the financial reconciliation benchmark and report detailed metrics."""

import argparse
import json
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.evaluation import evaluate_reconciliation
from src.data_validation import audit_dataset_and_repo


def main():
    parser = argparse.ArgumentParser(description="Run LedgerLens financial reconciliation benchmark.")
    parser.add_argument("--data-dir", type=str, default="data", help="Directory containing dataset files")
    args = parser.parse_args()

    print("Running Dataset Audit...")
    audit = audit_dataset_and_repo(data_dir=args.data_dir)

    print("\nRunning Reconciliation Engine Benchmark...")
    metrics = evaluate_reconciliation(data_dir=args.data_dir)

    print("\nBenchmark Summary JSON:")
    print(json.dumps({
        "audit": audit,
        "metrics": metrics,
    }, indent=2))


if __name__ == "__main__":
    main()
