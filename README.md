# ux-swarm

Give the skill an app and a goal a person should be able to accomplish. It prepares the tasks, runs blind synthetic participants, and delivers a complete HTML report. For an improvement request on an editable app, it follows a finding back to the screen, patches the source, and reruns the same task on the changed build. You can steer the study or reprioritize a fix as it runs.

- **Point it at anything:** a URL, a repo, a folder of HTML pages, design artboards or screenshots (stitched into a clickable prototype), an iOS Simulator app, or a written UX idea. The Claude Code skill works out how to make it testable.
- **Blind participants.** Each synthetic user runs in an isolated Claude or Codex process. Its product inputs are screenshots. It can look, tap, type, scroll, go back, give up, or finish. On web targets it can also close the tab and reopen the app. Its recorded comments and screenshots are available from individual findings.
- **Blind analysis.** A verifier checks every claimed success against the final screens, without seeing the claim. An annotator rates each session's problems on a 0–4 severity scale. A merger counts frequency across personas. Prototype dead ends are separated from real confusion.
- **Attitudes as distributions.** In-character interview answers (ease, trust, would use, would pay, the 10 SUS items, "what would make you close the app?") are scored with **Semantic Similarity Rating** into 1–5 distributions, next to the naive 1–5 numbers for comparison.
- **Validity numbers in every report:** a leak canary, verifier overturns, run-to-run agreement (Jaccard, Fleiss κ), and pinned model IDs. `ux-swarm eval` measures recall and false-positive rate against a known-issue list.

## Try the skill from this checkout

From the repository root, load the skill for a Claude Code session.

```
claude --plugin-dir .
```

For example, ask *“Can someone sign up and invite a teammate? Test my local app. Fix the biggest problem you can reproduce and run the same task again.”* You can supply an exact audience or task. Otherwise the setup agent drafts the goals and selects behavioral personas, then freezes both for the measured runs.

You need `uv`, an authenticated CLI for the selected participant backend, and Google Chrome or Playwright Chromium for web targets. For SSR embeddings, set `OPENAI_API_KEY` and install the `[openai]` extra, or configure `embedder: local:all-MiniLM-L6-v2` with the `[local]` extra.

### CLI without the skill

Run these commands from the repository root. `uv run` uses the implementation in this checkout.

```bash
uv run ux-swarm run examples/smoke/study.yaml --dry-run
uv run ux-swarm all examples/smoke/study.yaml
```

`examples/smoke/` is a plant-watering app with deliberate usability problems. Its two sessions use the Codex backend and test embeddings. Open `runs/smoke/report.html` for outcomes, ranked findings, suggested changes, interview answers, and study limitations. Click a cited step to see the actual screen, action, and comment. The HTML file contains its recordings and can be opened offline.

To start your own study, use `uv run ux-swarm init my-study`. For a repair, preserve the baseline and use a fresh output directory for the changed build. After the rerun, `ux-swarm recheck BEFORE_DIR AFTER_DIR --witness witness.yaml` adds the reviewed comparison to the changed report. The [fix and retest guide](skills/ux-swarm/references/fix-and-retest.md) describes the evidence format.

During `run` or `all`, use `ux-swarm drain RUN_DIR` to finish the participants already in progress and hold the queue. To continue, run `ux-swarm drain RUN_DIR --clear` and repeat the original study command. Completed sessions are reused. If you change the goal or audience, create a separate study output so the original evidence stays attributable.

### Measure what personas add

The public Sprout example supports a four-session pilot. Two fresh agents receive the same neutral card. Two more receive different behavioral habits. Each starts with the same task, model and patience allowance. Freeze the order and inspect the plan before starting the model calls.

```bash
uv run ux-swarm benchmark plan examples/smoke/study.yaml --out runs/sprout-panel --seed 20261122
uv run ux-swarm benchmark run examples/smoke/study.yaml --out runs/sprout-panel --seed 20261122
uv run ux-swarm benchmark export runs/sprout-panel runs/sprout-review
```

Give the reviewer only `runs/sprout-review/`. They inspect each claim's screenshots and fill in the decisions in `review.csv`, assigning the same issue ID to equivalent claims. Then run `uv run ux-swarm benchmark score runs/sprout-panel runs/sprout-review`. The score identifies supported issues shared by both groups and issues observed in just one. The [benchmark protocol](docs/persona-benchmark.md) describes the held-out comparison and proposed release criteria.

### Export a replay for a demo

The HTML report already includes session playback. To make a separate presentation file from the same study, run the export from the checkout.

```bash
uv run ux-swarm replay examples/smoke/study.yaml --output runs/smoke/replay.html
```

Choose a session, play or scrub through its actions, and compare the screen before a tap with the result. Each caption is the synthetic participant’s recorded think-aloud. To curate a demo, pass `--session` followed by the run IDs in presentation order. Use `--start-step 2` to open on recorded step 2 (the third action) of the first session. The HTML contains the selected screenshots and captions and works offline.

## How it works

```
 your input ──► resolve target (skill, full context) ──► study.yaml (+ flow.yaml for stitched screens)
                    │
 personas × tasks × runs ──► isolated Claude or Codex + device MCP (Playwright / iOS AXe)
                    │           steps.jsonl (think-aloud) · shots/ · outcome.json · gaps.jsonl
                    ▼
     interview (in character) ──► SSR ──► Likert pmfs, SUS distribution
     verifier (final screens only) ──► verified / not
     annotator (anonymous "P") ──► findings 0–4 ──► merger ──► issues × frequency
                    ▼
     report.md + self-contained report.html with step evidence
                    ▼
     for an improvement goal: patch target source → fresh blind rerun → reviewed comparison
```

Each participant starts in an empty temporary directory with only the device MCP server. A separate check reviews its first recorded comment for prior knowledge of the product.

## Limitations

- **Synthetic users are not users.** Use this to triage and to decide what to test with about 5 real people. Don't use it to skip that step.
- **Agents are too competent and too polite.** They read everything, rarely quit and over-report intent to buy. A failure is a strong signal; a pass is weak evidence.
- **Personas add believability, not accuracy.** Published comparisons found persona agents' clicks differed from real users' in about half of tasks.
- **Cultural and language personas** (for example Taglish) test your copy against that register. They do not model real people from that culture.
- **Emotion, trust and social context** (asking friends for money, a noisy restaurant) are weakly simulated.
- **SSR** was validated for consumer purchase intent. The ease, trust and SUS anchors here use the same method but have not been validated against humans. Results depend on the anchors and the embedding model.
- **Screenshot vision can misread small text.** Annotators flag suspected misreads, and the report shows the share for each issue.
- **Cost:** each session is a multi-turn `claude -p` run with images. Check `--dry-run` first.

## Privacy and keys

The runner uses the configured model backend for screenshot-based sessions and analysis. A remote embedding provider receives interview text when selected. The portable report and replay contain app screenshots and participant comments. Run folders, storage states and environment files are excluded by the repository's ignore rules.

## Citations

The workflow draws on these methods.

- **UXAgent.** Lu et al. describe using simulated participants and post-session interviews to pilot usability studies. [CHI EA 2025 paper](https://arxiv.org/abs/2502.12561)
- **UXCascade.** Holter, Koh, Dogan and Chan study how simulated users can identify usability issues. [UXCascade paper](https://arxiv.org/abs/2601.15777)
- **Semantic Similarity Rating.** Maier et al. map free-text answers to distributions over Likert ratings and evaluate the method on purchase intent. [SSR paper](https://arxiv.org/abs/2510.08338)
- **SUS:** Brooke, *SUS: A "quick and dirty" usability scale*, 1996. **Severity scale:** Nielsen, 1994.

See `CITATION.cff`.

## License

MIT
