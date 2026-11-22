<p align="center"><img src="assets/pilot-mark.svg" alt="Pilot" width="96"></p>

# Pilot

We created Pilot to test any UX like real first-time users, so that you can fix it with your coding agent before shipping.

Give Pilot your app and a goal a new user should be able to reach. It sends testers who have never seen your product. Each one sees only screenshots, thinks aloud, and gives up when they would. You get a report of where they got stuck, and a fix plan your coding agent can work through.

## Quickstart

Install the plugin in Claude Code.

```
/plugin marketplace add itsalexi/pilot-ux
/plugin install pilot@pilot
```

Then ask for a test in plain words.

```
Use Pilot to test whether a new user can sign up and invite a teammate on http://localhost:3000.
```

Pilot drafts the tasks and picks a few contrasting testers, runs them, and writes the results to the study's output folder. You can name the audience and tasks yourself, or let it draft them from your app.

Pilot can test a URL, a repo, a folder of HTML pages, design artboards or screenshots stitched into a clickable prototype, an iOS Simulator app, or a written idea.

## What you get

**`pilot.html`** is the interactive report. It ranks every problem by how bad it is and how many testers hit it. Click any problem to see the exact screens, taps and words of the testers who ran into it. The file works offline, so you can send it to anyone.

**`fix-plan.md`** is the same findings written for your coding agent. Each problem is a complete brief: what went wrong, where, a suggested fix, what counts as fixed, and the command to retest it. Hand it to Claude Code or Codex and ask it to work through the list.

## The loop

1. **Find.** Run Pilot on the current build. Keep that run as your baseline.
2. **Fix.** Give `fix-plan.md` to your coding agent and let it fix the top problem.
3. **Retest.** Run the same tasks on the changed build with fresh testers, then compare the two runs.

```bash
pilot all fixed.yaml --only signup
pilot recheck runs/baseline runs/baseline-fixed
```

`recheck` pairs the sessions from both runs and shows whether the problem came back. The [fix and retest guide](skills/pilot/references/fix-and-retest.md) explains how to record the evidence.

## How it works

Each tester runs in its own Claude or Codex process, in an empty folder, with only a device to drive. It can look, tap, type, scroll, go back, give up, or finish. It never sees your code, your notes, or the expected path.

After the sessions, separate agents check the results. A verifier looks at each tester's final screens and decides whether the task really succeeded. An annotator rates each problem from 0 to 4. A merger counts how many testers hit the same problem.

Each tester also answers a short interview in character about ease, trust, and whether they would use or pay for the product. Pilot scores those answers with Semantic Similarity Rating (SSR), which turns free text into a 1 to 5 distribution instead of a single number.

Every report includes checks on itself: whether a tester seemed to know the product already, how often the verifier overturned a claimed success, how much two runs agree, and the exact model IDs used.

## Honest limits

- **Synthetic testers are more patient and literal than people.** They read every word and rarely quit. Use Pilot to find and fix problems before you test with about 5 real people, not instead of it.
- **They see only screenshots.** Small text can be misread. The report flags suspected misreads for each problem.
- **A failure is a strong signal. A pass is weak evidence.** If a tester gets stuck, a real person probably will too. If every tester succeeds, real people still might not.
- **Personas change how testers behave, not who they are.** A persona that writes in Taglish tests your copy in that register. It does not stand in for real people from that culture.
- **SSR was validated on purchase intent.** The ease, trust and SUS scores use the same method but have not been checked against real people.
- **Each session costs model calls.** Run with `--dry-run` first to see how many sessions a study will start.

## Setup

- [uv](https://docs.astral.sh/uv/)
- A Claude Code or Codex login, for the testers and the analysis
- Google Chrome or Playwright Chromium, for web apps
- For SSR scoring, either `OPENAI_API_KEY` with the `[openai]` extra, or a local embedder such as `embedder: local:all-MiniLM-L6-v2` with the `[local]` extra

To try Pilot from a checkout without installing the plugin:

```bash
claude --plugin-dir .
```

Or use the command line directly. The example is a plant-watering app with planted usability problems.

```bash
uv run pilot run examples/smoke/study.yaml --dry-run
uv run pilot all examples/smoke/study.yaml
```

Open `runs/smoke/pilot.html` when it finishes. Start your own study with `uv run pilot init my-study`.

Environment variables use the `PILOT_` prefix, for example `PILOT_STORAGE_STATE` for a signed-in browser session. The older `UX_SWARM_` names still work.

## Privacy

Testers and analysis run on the model backend you choose. If you pick a remote embedder, it receives the interview answers. Reports contain screenshots of your app and the testers' comments, so treat them like any other screenshot. Run folders, browser sign-in files and `.env` files are ignored by git.

## Citations

- **Semantic Similarity Rating.** Maier, Aslak, Fiaschi, Rismal, Fletcher, Luhmann, Dow, Pappas and Wiecki. *LLMs Reproduce Human Purchase Intent via Semantic Similarity Elicitation of Likert Ratings*, 2025. [arXiv:2510.08338](https://arxiv.org/abs/2510.08338)
- **UXAgent.** Lu et al. *An LLM Agent-Based Usability Testing Framework for Web Design*, CHI EA 2025. [arXiv:2502.12561](https://arxiv.org/abs/2502.12561)
- **UXCascade.** Holter, Koh, Dogan and Chan. *Scalable Usability Testing with Simulated User Agents*, 2026. [arXiv:2601.15777](https://arxiv.org/abs/2601.15777)
- **SUS.** Brooke, *SUS: A "quick and dirty" usability scale*, 1996. **Severity scale.** Nielsen, 1994.

To cite Pilot, see [`CITATION.cff`](CITATION.cff).

## License

MIT. See [LICENSE](LICENSE).
