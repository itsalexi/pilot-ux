---
name: ux-swarm
description: Use for synthetic usability studies and goal-driven UX improvement. Turn a product goal into blind screenshot-only sessions, inspect what people attempted, fix an in-scope problem in the target source, and rerun the same study on the changed build.
---

# ux-swarm

You own the study from the user's goal through the requested outcome. For an improvement request on an editable product, plan, pilot, run, review, patch the product, and retest. For a request to evaluate or demonstrate a product, deliver the evidence within that scope. When the user supplies a hosted target without an editable source, the study can still produce a concrete, replayable fix recommendation.

The setup agent can inspect the product, its source and the user's brief. Each participant runs in a fresh Claude or Codex process and receives only a persona card, task situation and goal, neutral product hint, and the device tools. The participant sees screenshots, acts, says what it notices, and can quit. Separate agents verify completion claims and annotate findings. Keep your notes, expected route, source files, prior sessions, issue list and proposed fixes out of participant prompts.

## Run the local CLI

Use the plugin checkout that contains this skill. The plugin root is two levels above the directory containing this file. For the examples below, set `uxs_root` to its absolute path in your shell.

```bash
uxs() { uvx --from "${uxs_root}[openai]" ux-swarm "$@"; }
uxs personas
uxs init ./ux-study
```

Use the installed, authenticated backend the user has selected. Pin its model in the study YAML using `backend: codex` and `codex_model` for Codex, or `backend: claude` and `model` for Claude. Web targets use Chrome or Playwright Chromium. Target and persona paths, and `out_dir`, resolve relative to the study YAML. In the following examples, commands run from the study directory.

## 1. Turn the goal into a steerable study

- State the product, audience, task, observable success criterion, and what you're authorized to change. An owner can supply exact tasks and personas. Otherwise draft them from the brief and relevant evidence, such as support requests, existing user stories or product requirements. Distinguish assumptions from supplied facts. [Task and persona guide](references/personas-and-tasks.md)
- Give the participant a situation and desired outcome in everyday language. A goal such as “pay my friend back and let them know” allows the participant to discover the path. The verifier gets separate, observable criteria. Freeze the task, its start state, and those criteria before running measured sessions.
- Check that the criteria cover the details the user asked for. For “remind me to water Basil every three days,” seeing Basil with a three-day interval in the saved plant list verifies the setup. A generic “Plant added” message verifies only the confirmation step. Label any part of the real outcome that the study cannot observe, such as delivery of a future notification.
- Pick a small set of contrasting behaviors relevant to that goal, such as checking every amount or trying the first apparent action. Record them in YAML. A task is shared across its persona panel. A persona changes how it might be attempted. The runner executes the configured combinations. Use human-supplied priorities where available.
- Share a short working plan and dry-run estimate for baseline and retest. Within the user's scope and budget, start without an approval round. Keep the user informed when evidence changes what is worth testing, when you select a fix, and at the paired result. Apply steering as it arrives. Ask when a meaningful product choice, new access, or a material expansion of scope or spend needs the user's decision.
- A mid-study change to the audience, goal, model, fixture or success criteria starts a new study with its own output. A change in which already-observed issue the user wants fixed can use the existing baseline. Preserve the distinction in the eventual comparison.
- When the user asks to hold a standard `run` or `all`, issue `uxs drain RUN_DIR` for that study's output. Active participants finish their sessions and pending starts stay on hold. To continue the same study, run `uxs drain RUN_DIR --clear` and repeat the original command. Keep steering messages out of participant prompts.

## 2. Prepare and pilot each task

Resolve the input into a runnable, resettable target. Use the [target playbook](references/targets.md) for URLs, repos, prototypes and iOS simulators. Walk the success path yourself as the setup agent to verify the start state, seeded data, inputs, external handoffs and observable endpoint. State what the target can exercise. For example, a payment mock can demonstrate returning to a confirmation screen only when the wallet handoff is modeled.

Save sibling study files using the same task and persona IDs and relative paths. Give pilots, the baseline and each changed build distinct output directories, for example `runs/pilot`, `runs/baseline` and `runs/fixed-01`. Record the revision or build digest and any local fixture changes. The runner fingerprints local static and prototype content by default. For a mutable hosted target, set `target.build_id` to the actual immutable deployment identifier. If the service exposes no version, disclose that the URL alone cannot verify which build was served.

```bash
uxs run pilot.yaml --dry-run
uxs run pilot.yaml --only impatient-power-user__reorder__r1
```

Substitute an actual full run ID for each task. Inspect the recorded actions and screenshots. A pilot can quit for a legitimate usability reason. Repair evidenced fixture gaps and recheck reachability before freezing the baseline. If the intended endpoint cannot be exercised, narrow the task transparently or report that limitation. Keep pilots out of the measured output.

## 3. Run and review the baseline

```bash
uxs run baseline.yaml --dry-run
uxs run baseline.yaml
uxs analyze baseline.yaml
uxs report baseline.yaml
```

Monitor longer runs through completion. Resume an interrupted pass with the same study settings, target build and output directory. The runner preserves `study.lock.json`, checks the study design, effective model schedule and recorded target identity, and skips completed sessions. If the checks reject a changed or unverifiable collection, keep its evidence and use a fresh output directory for new sessions.

Use `uxs all baseline.yaml` in place of the run/analyze/report commands when interviews and SSR are part of the study. The OpenAI embedder uses `OPENAI_API_KEY`. For local embeddings, install the `[local]` extra and configure `local:all-MiniLM-L6-v2`. The fake embedder supplies test fixtures. [SSR methodology](references/ssr.md)

Open `runs/baseline/report.html` and check coverage against the planned sessions. Each finding with recorded evidence links to the relevant step inside the report. Inspect what the participant said, the action, the preceding screen, and the resulting screen. The saved screenshot follows the action. A repeated observation can establish repeatability. An unwired prototype control is a fixture gap. Keep verified success, quits, missing verdicts, and infrastructure failures visible in the denominators. The self-contained report includes the recorded screens and spoken text. Keep it local unless sharing is authorized. [Interpreting validity](references/validity.md)

When an independent known-issue list exists, keep it on the evaluation side. Run `uxs eval baseline.yaml --truth truth.yaml`, review the issue rows against screenshots, then rerun with `--labels runs/baseline/eval/labels.csv` and the same truth file. Record who reviewed each decision. The CSV field `human_label` accepts overrides from either a human or AI reviewer. Rerun `uxs report baseline.yaml` to refresh the metrics. Preserve the exact merged `issues.json` used for reviewed labels and witnesses. Another `analyze` or `all` can rebuild its IDs.

## 4. Patch the target and retest

1. Select a supported, in-scope finding from the baseline. Open its cited frame and verify that the issue belongs to the source product. State the observed failure and the visible behavior that would count as improvement. If the evidence only supports a fixture repair, describe that as a change to the test setup.
2. For an improvement goal, implement the smallest coherent change in the target's normal source and follow its normal build and test paths. Preserve unrelated work. Pin or fingerprint the changed build. Restart or rebuild the actual target and confirm the changed revision is being served.
3. Copy the measured study settings into `fixed-01.yaml`. Point it at the changed build and set a **fresh** `out_dir` such as `runs/fixed-01`. Preserve tasks, personas, model pins, starting data, interface conditions, patience and repeat count so the outcomes can be paired. Use the same run/analyze/report or all commands. If the authorized retest covers only a named subset, identify the paired subset and the untested cases.
4. Open the relevant steps in the two HTML reports. Record whether the same problem recurred, an observed action demonstrated improvement, or the evidence was inconclusive. A session that takes another path or never reaches the control leaves that finding unresolved. Use `uxs recheck` to add the reviewed before/after comparison to the changed report. [Paired comparison and witness format](references/fix-and-retest.md)
5. Return the source change, the report with its paired comparison, the baseline link, verified outcomes with counts, and any new or unresolved friction. If a corrected issue still reproduces, use the evidence to revise the patch within scope and repeat into a new output directory. Stop when the agreed target behavior is demonstrated, the agreed budget is reached, or further progress needs an owner decision.
