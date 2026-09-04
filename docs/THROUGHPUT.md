# Throughput Benchmark

## Methodology

LedgerLens throughput is measured using `scripts/run_throughput.py` with Python's `time.perf_counter()` for high-resolution timing.

### What Is Measured

| Metric | Description |
|--------|-------------|
| **Preprocessing** | Dataset generation time (synthetic data creation) |
| **Reconciliation** | Deterministic matching engine execution time |
| **Records/sec** | Ledger records processed per second |
| **Status Counts** | MATCHED / REVIEW / UNMATCHED breakdown |

### Important Notes

1. **AI is disabled** for throughput benchmarks. LLM API calls would dominate latency and measure Groq's infrastructure, not LedgerLens.
2. All timing uses `time.perf_counter()` — the highest resolution timer available on the platform.
3. Throughput numbers measure the **reconciliation engine only**, not I/O or preprocessing.

### How to Run

```bash
python -m scripts.run_throughput
```

### Benchmark Scales

| Scale | Purpose |
|-------|---------|
| 250 | Small batch — typical daily reconciliation |
| 1,000 | Medium batch — weekly settlement |
| 5,000 | Large batch — monthly close |
| 10,000 | Stress test — high-volume processing |

### Deterministic vs AI Throughput

| Component | Characteristics |
|-----------|----------------|
| **Deterministic** | O(n×m) candidate generation, sub-second for 1000 rows |
| **AI-assisted** | Bounded to review-pool only (~15-25% of rows), each call ~200-500ms |

The deterministic engine handles 75%+ of records without any LLM dependency. AI is invoked only for genuinely ambiguous cases in the review pool.

### Interpreting Results

- **Records/sec** reflects pure deterministic throughput
- Real-world batches will be slower if AI is enabled, proportional to the review rate
- A batch of 1,000 records with 20% AI review rate = ~800 deterministic + ~200 AI calls
