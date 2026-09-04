"""CLI script to generate synthetic reconciliation benchmark datasets with holdout split."""

import argparse
import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data_generator import generate_synthetic_data

SEED_MAP = {
    "dev": 123,
    "holdout": 456,
    "demo": 789,
}

DIR_MAP = {
    "dev": os.path.join("data", "benchmark", "dev"),
    "holdout": os.path.join("data", "benchmark", "holdout"),
    "demo": os.path.join("data", "demo"),
}


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic financial reconciliation benchmark dataset.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility (overrides --mode seed)")
    parser.add_argument("--ledger-count", type=int, default=200, help="Number of target ledger records")
    parser.add_argument("--bank-count", type=int, default=200, help="Number of target bank statement records")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory (overrides --mode directory)")
    parser.add_argument("--mode", type=str, default="dev", choices=["dev", "holdout", "demo", "all"],
                        help="Dataset mode: dev (seed 123), holdout (seed 456), demo (seed 789), or all")

    args = parser.parse_args()

    if args.mode == "all":
        for mode_name in ("dev", "holdout", "demo"):
            seed = SEED_MAP[mode_name]
            out_dir = DIR_MAP[mode_name]
            count = 50 if mode_name == "demo" else args.ledger_count
            print(f"\n{'='*50}")
            print(f"Generating {mode_name.upper()} dataset (seed={seed}) → {out_dir}")
            print(f"{'='*50}")
            generate_synthetic_data(seed=seed, output_dir=out_dir, ledger_count=count, bank_count=count)
    else:
        seed = args.seed if args.seed is not None else SEED_MAP.get(args.mode, 123)
        out_dir = args.output_dir if args.output_dir is not None else DIR_MAP.get(args.mode, "data")
        generate_synthetic_data(
            seed=seed,
            output_dir=out_dir,
            ledger_count=args.ledger_count,
            bank_count=args.bank_count,
        )


if __name__ == "__main__":
    main()
