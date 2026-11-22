# Semantic Similarity Rating (SSR)

LLMs asked directly for a 1–5 rating give narrow, skewed answers (mostly 3s and 4s). SSR (Maier et al., 2025, arXiv 2510.08338) asks for a free-text answer in character instead. It then maps that answer onto a Likert distribution:

1. Embed the answer and the 5 anchor statements of one anchor set (point 1 … point 5).
2. `s_r = cos(answer, anchor_r)`; `d_r = s_r − min(s) (+ ε on the minimum)`; `p_r = d_r^(1/T) / Σ`.
3. Average the pmfs over all anchor sets for that question.

In the paper this reached about 90% of human test–retest reliability across 57 product surveys, with realistic distribution shapes.

## In Pilot

- **Constructs:** ease, trust, use_intent, pay_intent, and the 10 System Usability Scale (SUS) items. Anchors are in `anchors/*.yaml`, with ≥4 sets each. SUS items share templated agreement anchors.
- **SUS:** each item's pmf is sampled and scored with standard SUS scoring. The report gives a median and an 80% interval, not a point.
- **Comparison:** each interview also asks for naive 1–5 numbers, so you can see the narrowing effect on your own data.
- **Embedder:** pluggable via `embedder:`. Options:
  - `openai:text-embedding-3-small` (default, needs `OPENAI_API_KEY`)
  - `local:all-MiniLM-L6-v2` (offline, needs the `[local]` extra)
  - `voyage:voyage-3`
  - `fake` (tests only; meaningless)

## Limits

- **Anchors are the main researcher degree of freedom.** Compare studies only when anchors and embedder are identical.
- **The paper validated purchase intent for consumer products.** Ease, trust and SUS items here use the same method but are not validated against humans.
- **Short or off-topic answers give flat distributions.** The interview prompt asks for 1–3 sentences per question.
