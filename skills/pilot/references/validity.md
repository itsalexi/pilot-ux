# Reading results honestly

## Known biases of synthetic users

- **Too competent.** Agents are more efficient, literal and patient than people. They rarely walk away, and they read everything. A task they fail is a strong signal. A task they pass is weak evidence.
- **Too positive.** They buy far more often than humans (one study: 25% vs 3%) and soften criticism. Treat use and pay intent as upper bounds.
- **Wrong in different ways.** Persona clicks differed from real users' clicks in about half of the tasks in published comparisons. Personas make the behaviour more varied and believable, but not more accurate.
- **Weak on feelings.** Trust, embarrassment, social pressure (asking a friend for money) and the physical setting are poorly simulated.
- **Vision errors.** An agent can misread a screenshot. Annotators flag `agent_misread`, and the report shows the share for each issue. Discount issues with a high misread share.

## Validity numbers in every report

| Number | Meaning | Worry when |
|---|---|---|
| Leak canary flagged | Persona showed prior product knowledge in its first thought | > 0: check isolation and the `product_hint` |
| Verifier overturned X/Y | Claimed successes the session's screens didn't support | high: agents over-claim, so trust verified numbers only |
| Issue-set Jaccard across runs | How repeatable findings are for the same persona × task | < 0.3: findings are mostly noise; add runs |
| Outcome agreement, Fleiss κ | Whether runs agree on success / quit | κ < 0.2: outcomes are coin flips |

## What to tell the user

- Lead with issues that hit several personas at severity ≥ 3.
- Say plainly which findings are prototype gaps.
- Recommend testing the top issues with about 5 real people before redesigning around them.
