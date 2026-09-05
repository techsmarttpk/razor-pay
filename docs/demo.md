# Demo walkthrough

Prerequisite: backend running on :8000 (`uvicorn app.main:app --port 8000`
after `python -m app.services.seed`), frontend running on :5173/:5174
(`npm run dev`).

1. **Open the dashboard** (`/`). The KPI ribbon shows Money at Risk,
   Recoverable Money, Auto-resolved, Pending Review, Escalated — real numbers
   from the seeded dataset (~₹8L money at risk, hundreds of exceptions).
2. **"Top signal" card** — the single largest open exception, headline style
   ("₹1,21,506 at risk — settlement degradation"), with the agent's plain-
   English explanation.
3. **Click "Investigate →"** — lands on the exception detail page.
4. **WHY** — the agent's explanation (deterministic template or LLM-phrased,
   never inventing a number).
5. **EVIDENCE** — the actual records the detector looked at (settlement id,
   delay in days, expected vs received amounts).
6. **CALCULATION** — the money-at-risk breakdown table, components summing
   exactly to the total.
7. **ROOT CAUSE — Diagnostic tree** — for a `settlement_variance` exception,
   multiple hypotheses (refund timing, fee anomaly, chargeback reserve,
   delayed settlement) are shown with amounts, contradicted ones greyed out,
   the final classification marked.
8. **AGENT DECISION → ACTION** — recommended action + category badge
   (SAFE_AUTO_ACTION / REVIEW_REQUIRED / ESCALATE). Click **RESOLVE SAFE
   ITEMS** on a high-confidence low-amount exception to watch it auto-resolve
   live; click **ESCALATE ₹X** on a low-confidence or high-amount one to
   watch it move to escalated status.
9. **RESULT** — the Action rows created, executed timestamp, idempotent (re-
   clicking the same action returns the same row instead of double-applying).
10. **AUDIT TRAIL** panel (right column) — every decision on this exception,
    with rule/model used, confidence, and outcome. The global `/audit` page
    shows this across all exceptions.
11. **Model Performance** (`/performance`) — real held-out precision/recall/
    F1/FPR/root-cause-accuracy/MAPE, confusion matrix, and a per-scenario
    detection-rate table (16 injected scenario types, including the two
    benign/negative ones which correctly show ~0% detection).

Secondary: **Agent Investigation** (`/investigate`) — a chat surface over the
same facts ("Why is money at risk today?"), useful but not load-bearing —
the product's core value is on the other 8 pages.
