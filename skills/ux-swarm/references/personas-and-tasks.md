# Writing tasks and personas

## Tasks

A task is a situation plus a goal, in the words a real user would use, with success criteria that a verifier can check from the screen alone.

```yaml
# BAD: names the UI, so it tests whether the persona can read labels.
goal: "Tap New Split, choose Scan Receipt, then assign items."

# GOOD: a situation and an outcome, in the user's words.
context: "You just had dinner with 5 friends. You paid the whole ₱5,140 bill and have the receipt."
goal: "Get everyone to pay you back their share of what they ordered."
success_criteria:
  - "a screen shows each of the 6 people with their own amount"
  - "there is a way to send the request to the friends (link, share or message)"
```

- One goal per task. Split "set up and share" into two only when the second step can start from a known state.
- Give concrete facts the persona needs (names, amounts, what was ordered) in `context`. Personas can't invent data the app asks for.
- Write success criteria about an observable outcome. By default the verifier sees the final three screenshots.
- For a web task that requires data to survive closing and reopening the app, add `verify_after: reopen` to that task. Give the participant a natural reason to close and return. The verifier checks the first screen captured after the last reopen. For example, a criterion can require a named item and its saved quantity to appear on the reopened list. Choose this rule when the relevant details are visible immediately on return.
- During the pilot, check that the intended outcome is visible to the verifier. If a confirmation hides a required detail, report the limit and preserve that requirement when interpreting the result. When the owner changes the goal, freeze the revised criterion in a new measured study.

## Personas

Start from the defaults (`uxs personas`) and add product-specific behaviors as needed. The card fields describe a hypothesis about how someone might approach a task. The runner enforces the patience budget. The configured target determines the actual device and viewport.

| Field | Effect |
|---|---|
| `tech_literacy` 1–5 | how much the persona reads icons, gestures and jargon |
| `patience_steps` | how many actions before quitting; dead taps cost double. 15 = impatient, 25 = normal, 45 = thorough |
| `language_register` | how they think aloud (Taglish, terse, formal); also tests whether the copy works for them |
| `goals`, `fears` | what they look for and what makes them stop (fees, scams, embarrassment) |
| `habits` | concrete behaviours ("never reads body text", "uses the back button when lost") |

Write fears and habits as specific behaviours, not adjectives. "Worried" does nothing; "abandons if asked for a phone number before seeing the price" does.

Choose panel size and repeats to fit the goal and run budget. A single attempt can demonstrate an observed problem. Repeated attempts help measure how often it recurs. Keep the same panel, patience limits and number of attempts when comparing a fix.

Personas add believability more than accuracy. A cultural or language persona (for example Taglish) tests your copy against that register, but it is not a model of real people from that culture.
