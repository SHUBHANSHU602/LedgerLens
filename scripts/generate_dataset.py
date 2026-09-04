"""CLI script to generate synthetic reconciliation benchmark datasets."""

import argparse
import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data_generator import generate_synthetic_data


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic financial reconciliation benchmark dataset.")
    parser.add_argument("--seed", type=int, default=123, help="Random seed for reproducibility")
    parser.add_argument("--ledger-count", type=int, default=200, help="Number of target ledger records")
    parser.add_argument("--bank-count", type=int, default=200, help="Number of target bank statement records")
    parser.add_argument("--output-dir", type=str, default="data", help="Output directory for generated datasets")

    args = parser.parse_args()
    generate_synthetic_data(
        seed=args.seed,
        output_dir=args.output_dir,
        ledger_count=args.ledger_count,
        bank_count=args.bank_count,
    )


if __name__ == "__main__":
    main()
