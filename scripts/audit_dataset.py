"""CLI script to audit benchmark dataset quality, leakage metrics, and repo boundaries."""

import argparse
import json
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data_validation import audit_dataset_and_repo


def main():
    parser = argparse.ArgumentParser(description="Audit LedgerLens dataset quality, difficulty metrics, and leakage.")
    parser.add_argument("--data-dir", type=str, default="data", help="Directory containing benchmark dataset files")
    args = parser.parse_args()

    report = audit_dataset_and_repo(data_dir=args.data_dir)
    print("=" * 65)
    print("LEDGERLENS DATASET QUALITY & LEAKAGE AUDIT REPORT")
    print("=" * 65)
    print(json.dumps(report, indent=2))
    print("=" * 65)


if __name__ == "__main__":
    main()
