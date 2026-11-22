# Checking a fix across builds

Keep baseline and changed studies side by side, with separate output directories and fresh participant processes. An issue ID such as `I1` belongs to one specific merged report. Compare the described behavior and cited screens across builds. Keep the prior report hidden from the rerun's participants and annotator.

Open `runs/baseline/report.html` and `runs/fixed-01/report.html`. Each finding's step links open its session player inside that report. The initial comparison identifies matched sessions and candidate recurrences.

```bash
uxs recheck runs/baseline runs/fixed-01
```

Inspect the before and after traces. Check whether each participant reached the affected control, what action they took, and the resulting screen. An earlier screenshot can establish what the participant saw before tapping. Inspect new findings and outcome regressions as well. The unreviewed comparison can point to candidate recurrences.

Record the reviewed decisions in `witness.yaml`, outside participant-visible context. This example illustrates the format. Use the real build identifiers, source issue ID, matching session IDs, observed steps and evidence from your two runs.

```yaml
before_version: checkout-v1
after_version: checkout-v2
reviewer: AI screenshot review
observations:
  - issue: I1
    before_run: impatient-power-user__reorder__r1
    before_step: 3
    after_run: impatient-power-user__reorder__r1
    after_step: 5
    result: improved
    note: Both sessions reached the saved order. The first participant left when delivery fees were hidden. The second saw the itemized charge and confirmed the order.
```

Use `improved` when comparable evidence shows the corrected behavior, `recurred` when the same friction is visible again, and `inconclusive` when the comparison cannot establish either. Name the person or AI reviewer who actually checked the evidence. The conclusion applies to the cited observation.

```bash
uxs recheck runs/baseline runs/fixed-01 --witness witness.yaml > runs/fixed-01/comparison.md
```

The command saves the comparison in `runs/fixed-01/recheck.json` and refreshes the changed study's Markdown and HTML reports. Keep the witness and build identifiers alongside the results so a reviewer can recreate the comparison.

When reporting, give the number of paired attempts that actually reached the control and how often the issue recurred among them. Report unaffected tasks and incomplete attempts separately. Verified task completion can improve for several reasons, so tie any statement about a specific fix to a local behavioral witness.

For a requested presentation, `uxs replay fixed-01.yaml --session impatient-power-user__reorder__r1 --start-step 5 --output runs/fixed-01/reorder.html` exports a standalone player for a selected session, opened at a zero-based step. Substitute the session and step from the actual study. The ordinary HTML report already includes playback.
