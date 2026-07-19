# Worker reports — drop folder

**Drop the nationality-classification reports from your other workers/LLMs in this
folder.** Then tell me they're in and I'll take it from here.

## What to drop
- Any number of files, **`.md` or `.json`** (the formats the handoff asked for).
- Name them however you like — ideally by source so I can weight them, e.g.
  `gpt5.json`, `gemini.md`, `grok-batch1.json`, `human-van.md`. I'll read whatever's here.
- Each file should follow the brief's return shape: per brand → **brand, bucket**
  (definitely_china / likely_china / unknown / likely_not_china / definitely_not_china),
  **confidence, evidence (with source URLs), reasoning**. Partial files / batches are fine.
- Don't worry about matching brand names exactly to ours — I'll fuzzy-match to the
  401-brand queue and flag anything I can't line up.

## What I'll do (myself — no subagents)
1. Read every report here **plus my own pass** (`../opportunity-queue-findings-claude.json`).
2. Per brand, line up every source's call + evidence.
3. **Reconcile:** agreement → that bucket; disagreement → I adjudicate on evidence
   strength (a hard record — CN/HK trademark owner, Amazon/Walmart seller-of-record in
   China, a Chinese parent — beats footer/vibes; a verified non-China founder+HQ beats a
   bare US LLC). I'll show my reasoning and every conflict.
4. Produce the **final bucket list** for all 401.
5. **Flip the definites:** apply `definitely_china → china` and
   `definitely_not_china → not_china` to the verdict system.
6. Report **how many remain in the two "probably" buckets (likely_china + likely_not_china)
   and how many are still unknown** — the residual queue that still needs a human call.

Nothing gets flipped until the reconciliation is done and you've seen the final list.
