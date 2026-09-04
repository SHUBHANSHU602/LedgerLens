"""Synthetic dataset generator for financial reconciliation benchmarking (Phase 3)."""

import os
import random
from datetime import datetime, timedelta
from typing import Tuple, List, Dict, Any
import pandas as pd

try:
    from src.config import CONFIG
except ModuleNotFoundError:
    from config import CONFIG


def generate_synthetic_data(
    seed: int = 42,
    output_dir: str = "data",
    ledger_count: int = 200,
    bank_count: int = 200,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate controlled synthetic ledger, bank statement, and answer key CSVs."""
    random.seed(seed)
    os.makedirs(output_dir, exist_ok=True)

    base_date = datetime(2026, 8, 1)
    customers = [
        "Acme Corp", "Beta Traders", "Gamma Tech", "Delta Retail", "Epsilon Co",
        "Zeta Logistics", "Eta Systems", "Theta Global", "Iota Digital", "Kappa Mart"
    ]
    payment_methods = ["UPI", "NEFT", "RTGS", "CARD", "NETBANKING"]

    # Reusable common amount pools to ensure realistic repeated amounts across dates
    common_amounts = [999.00, 1500.00, 2500.00, 4999.00, 5000.00, 7500.00, 10000.00, 12499.00, 15000.00]

    ledger_rows: List[Tuple] = []
    bank_rows: List[Tuple] = []
    answer_rows: List[Tuple] = []

    order_counter = 1000
    utr_counter = 500000

    def next_order_id() -> str:
        nonlocal order_counter
        order_counter += 1
        return f"ORD-{order_counter}"

    def next_utr() -> str:
        nonlocal utr_counter
        utr_counter += 1
        return f"UTR{utr_counter}"

    def random_date(start_day: int = 0, max_days: int = 28) -> str:
        return (base_date + timedelta(days=random.randint(start_day, max_days))).strftime("%Y-%m-%d")

    # Reference leakage counters
    exact_ref_count = 0
    partial_ref_count = 0
    no_ref_count = 0

    # Scale target allocations based on ledger_count (base ~200)
    scale = ledger_count / 200.0
    c_easy = int(70 * scale)
    c_noisy = int(40 * scale)
    c_fee = int(20 * scale)
    c_dateshift = int(20 * scale)
    c_nearamt = int(10 * scale)
    c_ambiguous = int(15 * scale)
    c_fptrap = int(10 * scale)
    c_unmatched_l = int(10 * scale)
    c_unmatched_b = int(10 * scale)
    c_dup = int(10 * scale)
    c_reversal = int(6 * scale)
    c_fee_only = int(4 * scale)

    # 1. EASY_EXACT
    for _ in range(c_easy):
        oid, utr, dt = next_order_id(), next_utr(), random_date()
        amt = random.choice(common_amounts) if random.random() < 0.3 else round(random.uniform(500, 20000), 2)
        cust, pm = random.choice(customers), random.choice(payment_methods)

        ledger_rows.append((oid, cust, amt, "INR", dt, pm))
        bank_rows.append((utr, f"PAYMENT FOR {oid} REF {utr} {cust}", amt, "INR", dt, 0.0))
        answer_rows.append((oid, utr, "EASY_EXACT", "MATCHED", "Exact reference, amount, and date match"))
        exact_ref_count += 1

    # 2. NOISY_REFERENCE (OCR substitutions, slashes, space insertions, prefix/suffix variations)
    for i in range(c_noisy):
        oid, utr, dt = next_order_id(), next_utr(), random_date()
        amt = round(random.uniform(1000, 15000), 2)
        cust = random.choice(customers)

        # Mutate reference for bank narration
        raw_num = oid.replace("ORD-", "")
        if i % 4 == 0:
            noisy_ref = f"ORD / {raw_num}"
            partial_ref_count += 1
        elif i % 4 == 1:
            noisy_ref = f"ORD0{raw_num}"  # OCR-style O->0
            partial_ref_count += 1
        elif i % 4 == 2:
            noisy_ref = f"PG_SETTL_TXN_{raw_num}_RECV"
            partial_ref_count += 1
        else:
            noisy_ref = f"PAYMENT FROM {cust.upper()}"
            no_ref_count += 1

        ledger_rows.append((oid, cust, amt, "INR", dt, "NEFT"))
        bank_rows.append((utr, f"CMS/{noisy_ref}/{utr}", amt, "INR", dt, 0.0))
        answer_rows.append((oid, utr, "NOISY_REFERENCE", "MATCHED", f"Noisy narration reference mutation ({noisy_ref})"))

    # 3. FEE_DIFFERENCE (Legitimate settlement fee deduction)
    for _ in range(c_fee):
        oid, utr, dt = next_order_id(), next_utr(), random_date()
        amt = round(random.uniform(3000, 25000), 2)
        fee = round(random.uniform(10, 50), 2)
        net_amt = round(amt - fee, 2)
        cust = random.choice(customers)

        ledger_rows.append((oid, cust, amt, "INR", dt, "CARD"))
        bank_rows.append((utr, f"CARD SETTLEMENT {oid} LESS MDR FEE {fee}", net_amt, "INR", dt, fee))
        answer_rows.append((oid, utr, "FEE_DIFFERENCE", "UNRESOLVED", f"Bank amount reduced by fee {fee} INR"))
        exact_ref_count += 1

    # 4. DATE_SHIFT (1-3 days settlement delay)
    for _ in range(c_dateshift):
        oid, utr = next_order_id(), next_utr()
        l_date_dt = base_date + timedelta(days=random.randint(0, 20))
        shift_days = random.randint(1, 3)
        b_date_dt = l_date_dt + timedelta(days=shift_days)

        l_date_str = l_date_dt.strftime("%Y-%m-%d")
        b_date_str = b_date_dt.strftime("%Y-%m-%d")
        amt = round(random.uniform(1500, 12000), 2)
        cust = random.choice(customers)

        ledger_rows.append((oid, cust, amt, "INR", l_date_str, "UPI"))
        bank_rows.append((utr, f"UPI BATCH SETTLEMENT {oid}", amt, "INR", b_date_str, 0.0))
        answer_rows.append((oid, utr, "DATE_SHIFT", "MATCHED", f"Settlement delayed by {shift_days} days"))
        exact_ref_count += 1

    # 5. AMOUNT_NEAR_MATCH (Minor near-matches 5000 vs 4999)
    for _ in range(c_nearamt):
        oid, utr, dt = next_order_id(), next_utr(), random_date()
        amt = round(random.uniform(2000, 10000), 0)
        near_amt = amt - random.choice([1.0, 2.0, 5.0, 25.0])
        cust = random.choice(customers)

        ledger_rows.append((oid, cust, amt, "INR", dt, "NEFT"))
        bank_rows.append((utr, f"NEFT TRANSFER {oid} {cust}", near_amt, "INR", dt, 0.0))
        answer_rows.append((oid, utr, "AMOUNT_NEAR_MATCH", "UNRESOLVED", f"Amount near match ({amt} vs {near_amt})"))
        exact_ref_count += 1

    # 6. AMBIGUOUS (Multiple bank rows with close amounts & dates without distinct references)
    for _ in range(c_ambiguous):
        oid, dt = next_order_id(), random_date()
        amt = random.choice(common_amounts)
        utr1, utr2 = next_utr(), next_utr()
        cust = random.choice(customers)

        ledger_rows.append((oid, cust, amt, "INR", dt, "UPI"))
        # Bank row 1 (true candidate)
        bank_rows.append((utr1, f"UPI DIRECT PAY {cust}", amt, "INR", dt, 0.0))
        # Bank row 2 (ambiguous decoy candidate)
        bank_rows.append((utr2, f"UPI DIRECT PAY {cust}", amt, "INR", dt, 0.0))
        no_ref_count += 2

        answer_rows.append((oid, utr1, "AMBIGUOUS", "UNRESOLVED", "Multiple bank rows with identical amount/date"))

    # 7. FALSE_POSITIVE_TRAP (High similarity decoy: same amount, same date, similar narration, different ref/customer)
    for _ in range(c_fptrap):
        oid, utr_true, utr_trap = next_order_id(), next_utr(), next_utr()
        dt = random_date()
        amt = round(random.uniform(3000, 8000), 2)
        cust_true = random.choice(customers)
        cust_trap = [c for c in customers if c != cust_true][0]

        ledger_rows.append((oid, cust_true, amt, "INR", dt, "RTGS"))

        # True bank record
        bank_rows.append((utr_true, f"RTGS INWARD {oid} {cust_true}", amt, "INR", dt, 0.0))
        exact_ref_count += 1

        # Trap bank record (same day, same amount, similar narration keyword, but different reference & customer)
        bank_rows.append((utr_trap, f"RTGS INWARD {next_order_id()} {cust_trap}", amt, "INR", dt, 0.0))
        exact_ref_count += 1

        answer_rows.append((oid, utr_true, "FALSE_POSITIVE_TRAP", "MATCHED", "Matcher must select true reference and avoid decoy trap"))

    # 8. UNMATCHED_LEDGER
    for _ in range(c_unmatched_l):
        oid, dt = next_order_id(), random_date()
        amt = round(random.uniform(500, 5000), 2)
        ledger_rows.append((oid, random.choice(customers), amt, "INR", dt, "CARD"))
        answer_rows.append((oid, "", "UNMATCHED_LEDGER", "UNMATCHED", "No bank statement counterpart exists"))

    # 9. UNMATCHED_BANK
    for _ in range(c_unmatched_b):
        utr, dt = next_utr(), random_date()
        amt = round(random.uniform(500, 5000), 2)
        bank_rows.append((utr, f"MISC BANK CREDIT {utr}", amt, "INR", dt, 0.0))
        answer_rows.append(("", utr, "UNMATCHED_BANK", "UNMATCHED", "No ledger record counterpart exists"))
        exact_ref_count += 1

    # 10. DUPLICATE_NEAR_DUPLICATE
    for _ in range(c_dup):
        dt = random_date()
        amt = random.choice(common_amounts)
        oid1, oid2 = next_order_id(), next_order_id()
        utr1, utr2 = next_utr(), next_utr()
        cust = random.choice(customers)

        ledger_rows.append((oid1, cust, amt, "INR", dt, "NEFT"))
        ledger_rows.append((oid2, cust, amt, "INR", dt, "NEFT"))

        bank_rows.append((utr1, f"NEFT BATCH {oid1}", amt, "INR", dt, 0.0))
        bank_rows.append((utr2, f"NEFT BATCH {oid2}", amt, "INR", dt, 0.0))
        exact_ref_count += 2

        answer_rows.append((oid1, utr1, "DUPLICATE_NEAR_DUPLICATE", "MATCHED", "Legitimate duplicate transaction 1"))
        answer_rows.append((oid2, utr2, "DUPLICATE_NEAR_DUPLICATE", "MATCHED", "Legitimate duplicate transaction 2"))

    # 11. REVERSAL_ADJUSTMENT
    for _ in range(c_reversal):
        oid, utr, dt = next_order_id(), next_utr(), random_date()
        amt = round(random.uniform(1000, 4000), 2)
        ledger_rows.append((oid, random.choice(customers), amt, "INR", dt, "CARD"))
        bank_rows.append((utr, f"REVERSAL CHARGEBACK {oid} ADJ", amt, "INR", dt, 0.0))
        answer_rows.append((oid, utr, "REVERSAL_ADJUSTMENT", "UNRESOLVED", "Reversal adjustment transaction"))
        exact_ref_count += 1

    # 12. FEE_ONLY_SETTLEMENT
    for _ in range(c_fee_only):
        oid, utr, dt = next_order_id(), next_utr(), random_date()
        amt = 10000.00
        fee = 75.00
        net_amt = 9925.00
        ledger_rows.append((oid, random.choice(customers), amt, "INR", dt, "NETBANKING"))
        bank_rows.append((utr, f"NETBANKING SETTLEMENT {oid} FEE {fee}", net_amt, "INR", dt, fee))
        answer_rows.append((oid, utr, "FEE_ONLY_SETTLEMENT", "UNRESOLVED", "Explicit settlement fee deduction"))
        exact_ref_count += 1

    df_ledger = pd.DataFrame(ledger_rows, columns=CONFIG.LEDGER_COLUMNS)
    df_bank = pd.DataFrame(bank_rows, columns=CONFIG.BANK_COLUMNS)
    df_answer = pd.DataFrame(answer_rows, columns=CONFIG.ANSWER_KEY_COLUMNS)

    df_ledger.to_csv(os.path.join(output_dir, "ledger.csv"), index=False)
    df_bank.to_csv(os.path.join(output_dir, "bank_statement.csv"), index=False)
    df_answer.to_csv(os.path.join(output_dir, "answer_key.csv"), index=False)

    # Save Excel workbook
    excel_path = os.path.join(output_dir, "reconciliation_dataset.xlsx")
    try:
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df_ledger.to_excel(writer, sheet_name="Ledger", index=False)
            df_bank.to_excel(writer, sheet_name="Bank Statement", index=False)
            df_answer.to_excel(writer, sheet_name="Answer Key", index=False)
    except Exception as e:
        print(f"Warning: Could not save Excel workbook ({e}). CSV files created successfully.")

    # Compute reference leakage metrics
    total_bank = len(df_bank)
    exact_rate = round(exact_ref_count / total_bank, 4) if total_bank > 0 else 0.0
    partial_rate = round(partial_ref_count / total_bank, 4) if total_bank > 0 else 0.0
    no_ref_rate = round(no_ref_count / total_bank, 4) if total_bank > 0 else 0.0

    print(f"Generated Benchmark Dataset in '{output_dir}/':")
    print(f"  Ledger Records: {len(df_ledger)}")
    print(f"  Bank Records:   {len(df_bank)}")
    print(f"  Answer Key:     {len(df_answer)}")
    print(f"  Excel Workbook: {excel_path}")
    print("\nReference Leakage Metrics:")
    print(f"  Exact Reference Rate   : {exact_rate:.2%}")
    print(f"  Partial Reference Rate : {partial_rate:.2%}")
    print(f"  No Reference Rate      : {no_ref_rate:.2%}")
    print("\nScenario Breakdown:")
    print(df_answer["scenario"].value_counts().to_string())

    return df_ledger, df_bank, df_answer


if __name__ == "__main__":
    generate_synthetic_data()
