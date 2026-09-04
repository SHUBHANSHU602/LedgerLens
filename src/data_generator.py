"""Synthetic dataset generator for financial reconciliation benchmarking."""

import os
import random
from datetime import datetime, timedelta
import pandas as pd
try:
    from src.config import CONFIG
except ModuleNotFoundError:
    from config import CONFIG


def generate_synthetic_data(seed: int = 42, output_dir: str = "data"):
    """Generate synthetic ledger, bank statement, and answer key CSVs."""
    random.seed(seed)
    os.makedirs(output_dir, exist_ok=True)

    base_date = datetime(2026, 8, 1)
    customers = ["Acme Corp", "Beta Traders", "Gamma Tech", "Delta Retail", "Epsilon Co"]
    payment_methods = ["UPI", "NEFT", "RTGS", "CARD"]

    ledger_rows, bank_rows, answer_rows = [], [], []
    order_counter = 1000
    utr_counter = 500000

    def next_order_id():
        nonlocal order_counter
        order_counter += 1
        return f"ORD-{order_counter}"

    def next_utr():
        nonlocal utr_counter
        utr_counter += 1
        return f"UTR{utr_counter}"

    def random_date(max_days=20):
        return (base_date + timedelta(days=random.randint(0, max_days))).strftime("%Y-%m-%d")

    # 1. Exact Match (35 cases)
    for _ in range(35):
        oid, utr, dt = next_order_id(), next_utr(), random_date()
        amt = round(random.uniform(500, 15000), 2)
        ledger_rows.append((oid, random.choice(customers), amt, "INR", dt, random.choice(payment_methods)))
        bank_rows.append((utr, f"PAYMENT FOR {oid} REF {utr}", amt, "INR", dt, 0.0))
        answer_rows.append((oid, utr, "exact_match", "MATCHED", "Exact reference, amount, and date match"))

    # 2. Fee Difference (10 cases) - Bank deducts a fee
    for _ in range(10):
        oid, utr, dt = next_order_id(), next_utr(), random_date()
        amt = round(random.uniform(2000, 20000), 2)
        fee = round(random.uniform(10, 50), 2)
        net_amt = round(amt - fee, 2)
        ledger_rows.append((oid, random.choice(customers), amt, "INR", dt, random.choice(payment_methods)))
        bank_rows.append((utr, f"SETTLEMENT {oid} FEE DEDUCTED", net_amt, "INR", dt, fee))
        answer_rows.append((oid, utr, "fee_difference", "UNRESOLVED", "Amount mismatch due to bank deduction fee"))

    # 3. Settlement Date Delay (10 cases) - Bank value date is 2 days later
    for _ in range(10):
        oid, utr = next_order_id(), next_utr()
        l_date_dt = base_date + timedelta(days=random.randint(0, 15))
        b_date_str = (l_date_dt + timedelta(days=2)).strftime("%Y-%m-%d")
        l_date_str = l_date_dt.strftime("%Y-%m-%d")
        amt = round(random.uniform(1000, 8000), 2)
        ledger_rows.append((oid, random.choice(customers), amt, "INR", l_date_str, random.choice(payment_methods)))
        bank_rows.append((utr, f"CREDIT {oid} DELAYED SETTLEMENT", amt, "INR", b_date_str, 0.0))
        answer_rows.append((oid, utr, "settlement_date_delay", "MATCHED", "Match within date window delay"))

    # 4. Noisy Reference (10 cases) - Order ID embedded in complex string
    for _ in range(10):
        oid, utr, dt = next_order_id(), next_utr(), random_date()
        amt = round(random.uniform(500, 5000), 2)
        ledger_rows.append((oid, random.choice(customers), amt, "INR", dt, random.choice(payment_methods)))
        bank_rows.append((utr, f"CMS/NEFT/N123456/{oid}/CLIENTPAY/TXN99", amt, "INR", dt, 0.0))
        answer_rows.append((oid, utr, "noisy_reference", "MATCHED", "Reference extracted from noisy narration"))

    # 5. Typo in Reference (5 cases) - Reference string mutated in bank narration
    for _ in range(5):
        oid, utr, dt = next_order_id(), next_utr(), random_date()
        amt = round(random.uniform(1000, 6000), 2)
        typo_oid = oid.replace("ORD-", "ORD_ERR_")
        ledger_rows.append((oid, random.choice(customers), amt, "INR", dt, random.choice(payment_methods)))
        bank_rows.append((utr, f"PAYMENT {typo_oid}", amt, "INR", dt, 0.0))
        answer_rows.append((oid, utr, "typo", "UNRESOLVED", "Reference typo prevents exact reference match"))

    # 6. True Unmatched Ledger (10 cases)
    for _ in range(10):
        oid, dt = next_order_id(), random_date()
        amt = round(random.uniform(100, 3000), 2)
        ledger_rows.append((oid, random.choice(customers), amt, "INR", dt, random.choice(payment_methods)))
        answer_rows.append((oid, "", "true_unmatched_ledger", "UNMATCHED", "No bank statement record present"))

    # 7. True Unmatched Bank (10 cases)
    for _ in range(10):
        utr, dt = next_utr(), random_date()
        amt = round(random.uniform(100, 3000), 2)
        bank_rows.append((utr, f"DIRECT BANK DEPOSIT {utr}", amt, "INR", dt, 0.0))
        answer_rows.append(("", utr, "true_unmatched_bank", "UNMATCHED", "No ledger record present"))

    # 8. Near-duplicate Decoys (6 ledger, 6 bank) - Duplicate amounts & dates without order IDs
    for _ in range(3):
        dt = random_date()
        amt = 999.00
        for _ in range(2):
            oid_dup, utr_dup = next_order_id(), next_utr()
            ledger_rows.append((oid_dup, random.choice(customers), amt, "INR", dt, "CARD"))
            bank_rows.append((utr_dup, f"CARD SETTLEMENT BATCH {utr_dup}", amt, "INR", dt, 0.0))
            answer_rows.append((oid_dup, utr_dup, "near_duplicate_decoys", "UNRESOLVED", "Ambiguous amount/date decoy match"))

    # 9. Batch Aggregate (4 ledger, 2 bank) - 2 ledger orders combined in 1 bank transaction
    for _ in range(2):
        oid1, oid2, utr = next_order_id(), next_order_id(), next_utr()
        dt = random_date()
        amt1, amt2 = 1500.00, 2500.00
        tot_amt = amt1 + amt2
        ledger_rows.append((oid1, random.choice(customers), amt1, "INR", dt, "NEFT"))
        ledger_rows.append((oid2, random.choice(customers), amt2, "INR", dt, "NEFT"))
        bank_rows.append((utr, f"BATCH PAY {oid1} AND {oid2}", tot_amt, "INR", dt, 0.0))
        answer_rows.append((oid1, utr, "batch_aggregate", "UNRESOLVED", "Aggregated batch payment"))
        answer_rows.append((oid2, utr, "batch_aggregate", "UNRESOLVED", "Aggregated batch payment"))

    df_ledger = pd.DataFrame(ledger_rows, columns=CONFIG.LEDGER_COLUMNS)
    df_bank = pd.DataFrame(bank_rows, columns=CONFIG.BANK_COLUMNS)
    df_answer = pd.DataFrame(answer_rows, columns=CONFIG.ANSWER_KEY_COLUMNS)

    df_ledger.to_csv(os.path.join(output_dir, "ledger.csv"), index=False)
    df_bank.to_csv(os.path.join(output_dir, "bank_statement.csv"), index=False)
    df_answer.to_csv(os.path.join(output_dir, "answer_key.csv"), index=False)

    # Export combined multi-sheet Excel file for easy spreadsheet viewing
    excel_path = os.path.join(output_dir, "reconciliation_dataset.xlsx")
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_ledger.to_excel(writer, sheet_name="Ledger", index=False)
        df_bank.to_excel(writer, sheet_name="Bank Statement", index=False)
        df_answer.to_excel(writer, sheet_name="Answer Key", index=False)

    print(f"Generated Datasets in '{output_dir}/':")
    print(f"  Ledger Records: {len(df_ledger)}")
    print(f"  Bank Records:   {len(df_bank)}")
    print(f"  Answer Key:     {len(df_answer)}")
    print(f"  Excel Workbook: {excel_path}")
    print("\nScenario Breakdown in Answer Key:")
    print(df_answer["scenario"].value_counts().to_string())

    return df_ledger, df_bank, df_answer


if __name__ == "__main__":
    generate_synthetic_data()
