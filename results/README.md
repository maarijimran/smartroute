# Results

One folder per run, named `<date>_<name>`, so every later change can be compared with what came before it. A folder holds:

- `README.md`: what was run, the setup, the headline numbers and how to read them
- the result files: evaluation reports, privacy report, policy
- `manifest.json`: the exact code commit, the model in each tier, the reward settings, the active learner versions, package versions and SHA-256 fingerprints of the trained weights and input data

On the machine that ran the experiment, create a folder with:

```bash
cd backend
python scripts/snapshot_results.py --name <short_label> --date <YYYY-MM-DD> --note "<one line>" [--include-raw]
```

`--include-raw` also stores the per-request files (workload, outcomes, judge grades) gzip-compressed, so the evaluation can be re-run without the server. The snapshot never copies the database (user accounts, encrypted provider keys), `.env` files, or `data/ratings_key.json`, which would unblind the human raters.

Do not edit a folder after it is committed. A rerun gets a new folder.

| Folder | Router | What it is |
|---|---|---|
| [2026-11-26_baseline_per_tier_ridge](2026-11-26_baseline_per_tier_ridge/README.md) | One ridge model per tier (frozen v3), epsilon-greedy and LinUCB warm-started from it | **Baseline** before separating query difficulty from model ability |
