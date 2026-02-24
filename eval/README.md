# Copilot Evaluation Toolkit

Tools for evaluating how well the Copilot performs in live situations.

## Contents

| File | Purpose |
|------|---------|
| `collect-signals.py` | Query Mimir for all primary + amplifier signals in a time window |
| `post-test-analysis-template.md` | Template for structured post-test analysis reports |

## Workflow

1. Run a load test against the monitored cluster
2. Collect signals for the test window:
   ```bash
   python eval/collect-signals.py \
     --start 2026-02-23T18:43:00Z \
     --end 2026-02-23T19:02:00Z \
     --name "50-wps-starter"
   ```
3. Copy the template and fill it in:
   ```bash
   cp eval/post-test-analysis-template.md eval/reports/analysis-2026-02-23.md
   ```
4. Use the collected data + Grafana to complete each section
5. Evaluate the Copilot's assessment against your analysis

## Output

- `eval/data/` — collected signal JSON (gitignored)
- `eval/reports/` — completed analysis reports (gitignored)

Both directories are ephemeral. The tooling and template are the permanent artifacts.
