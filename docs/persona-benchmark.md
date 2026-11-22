# Do persona cards change which usability problems an agent finds?

This experimental protocol compares behavioral personas with fresh generic agents. Only studies that include the generic control contribute to the comparison.

For precedent, UXCascade mapped model findings to known issues on a seeded website. Agents covered nine of 17 under the authors’ permissive matching rules. Our comparison asks how much of that sort of coverage comes from giving the agents different behavioral instructions. [UXCascade study, section 6.2](https://www.steffenholter.com/projects/uxcascade/uist26-135.pdf)

## The comparison

Give a first-time user one goal on an instrumented, working app. Freeze the task, fixture, data, model version, viewport, device tools, action ceiling, timeout, analysis prompts, and retry policy. Test three conditions on those same inputs.

| Condition | What one panel sees | Question |
|---|---|---|
| One generic session | One fresh agent with a neutral first-time-user card | What does the cheapest interactive run catch? |
| Six generic sessions | Six independent fresh starts with that same neutral card | What does spending six attempts buy? |
| Six persona sessions | Six independent fresh starts, one per frozen behavioral card | What does varying the cards add at six attempts? |

Reserve generic slot one as the singleton before shuffling the schedule. This gives a nested baseline at zero extra cost. Also publish the mean yield of the six individual generic runs to show how lucky or unlucky that singleton was. Each generic run can explore, express uncertainty, and quit. Reset app and agent state between sessions. Interleave conditions in a recorded random order.

If one persistent agent is a deployment option, add a separate comparison on the same tasks. Give it the panel’s aggregate token budget and permission to restart the app while retaining its own session history. This measures the value of spending the whole budget on one explorer. The six-fresh-start comparison still isolates the effect of the persona cards.

Use the same enforced patience budget for every card. A larger budget gives one card more opportunities to discover issues. Behavioral tendencies to check details or quit early can still affect actual usage. Record device actions, tokens by role, wall time and reviewer minutes. Compare discovery curves at a common cumulative token budget as a secondary check. Use recorded tokens when provider costs are unavailable.

The current CLI varies only the behavioral habits in the source cards. It holds identity, proficiency, device description, language register and patience constant. The score includes device calls, UI actions such as taps and typing, elapsed participant time and available provider telemetry for the retained attempts. A tap counts even if the screen stays unchanged. Codex exposes token counts. Analysis calls, discarded retries and total study spend still lack full accounting. The seed reproduces allocation and order. A new model run can take a different path.

For hosted apps, plan for account and database isolation. Starting a fresh browser or reinstalling an app resets local session state. A booking made or an item deleted in a shared account can still affect the following participant. Give each start equivalent independent data and verify the initial state before drawing conclusions across arms.

## First Sprout pilot

On November 22, 2026, four fresh Codex sessions (`gpt-6.2-astra`) attempted to add a basil watering reminder every three days. The schedule used one panel, seed 20261122 and 18 patience units per session. Two sessions received the neutral card. The other two used the habits from the older-non-techy and impatient-power-user cards. A separate AI reviewer saw shuffled claims, the goal, the recorded actions and their screenshots. The reviewer inspected all 13 claims before the results were attributed to the groups.

| Condition | Distinct supported issues | Device calls | UI actions |
|---|---:|---:|---:|
| Prespecified generic singleton | 2 | 9 | 7 |
| Two fresh generic agents | 2 | 18 | 14 |
| Two behavioral personas | 2 | 17 | 13 |

All four sessions surfaced the same two issues. The Save button looked disabled even when it worked, and the watering interval used the unexplained unit “d”. Eight candidate observations supported those two issues. Four reports about an apparently missing picker were classified as fixture or capture limitations. The recordings could not establish whether a native picker had appeared outside the captured frame. One claim about hesitation lacked visible evidence.

All four sessions reached a “Plant added” confirmation. The frozen success criterion checked that message. It did not establish that Basil was saved with the requested interval or that a reminder would be delivered. Both groups had similar elapsed participant time (105 and 104 seconds summed across their sessions). Total study spend is unknown.

This pilot establishes that the comparison can return a tie. Sprout is a familiar fixture with one short path and deliberate faults. No independently reviewed held-out recall or release threshold was measured here. The [README](../README.md) includes the commands to run a fresh panel.

## Save and reopen a note

The second pilot used a local copy of the [MDN IndexedDB notes example](https://github.com/mdn/learning-area/tree/21973263ba859ff3477919087b488157f9d618a6/javascript/apis/client-side-storage/indexeddb/notes). A fixture author planted one persistence fault and kept its implementation out of the participant, reviewer and repair contexts. The public MDN example worked correctly. The goal was to save a note titled “Bike pickup” with the text “Friday at four”, close the tab, and check for both on reopening. Each participant started with fresh browser data. Reopening within a session preserved the browser profile and returned to the original URL in a new tab.

On the defective copy, the note appeared after creation and disappeared on return in all four sessions. The prespecified generic singleton, the two generic agents together, and the two behavioral personas together each detected the one planted fault. A masked AI reviewer supported the four reports of the missing note and rejected a fifth claim about confusion over the save button. The study owner independently read “No notes stored” on one masked post-reopen screenshot. The four first-reopen screenshots were byte-identical.

The repair agent worked from the observed failure and the defective copy's source. It found that the app chose its database name using an ID kept only for the life of the tab. The fix used a stable database name. An independent browser check verified the exact title and body together in the saved list after closing and reopening the repaired app. This establishes persistence for newly created notes. Recovering entries already stranded in older databases would be a separate migration.

The matched rerun kept the task, model (`gpt-6.2-astra`), habits, 18-unit patience allowance and seed (20261123) fixed. On the defective build, zero of four sessions retained the note after reopening. On the repaired build, four of four did. Each repaired verdict used the first screenshot after the recorded reopen at step 6. Both groups found the planted fault before the fix, including the prespecified single generic agent. This gives the workflow a reproducible example of a repair it can verify. Measuring any benefit from additional personas still requires more tasks with different paths.

## Tasks, personas and fixtures

Choose three held-out apps with different interactions, for example reserving a time slot, splitting an expense and managing a reminder. Give each app two goals with an observable end state. Use two independent panels per goal. That makes **144 sessions on the defective builds**: 3 apps × 2 tasks × 2 panels × 12 starts. The same design on corrected builds adds 144. Use a separate small app to debug the protocol first.

1. The product owner supplies the user intent, starting state and what counts as completion. The setup assistant can draft task wording and suggest undercovered journeys. Freeze the wording before seeing the issue list. “Get a reminder to water the basil every three days” leaves room for discovery. “Open Settings and inspect the interval field” gives away the route.
2. Write six behavioral cards from plausible usage contexts. For example, one participant scans for the next action, another checks the inputs behind a total. Keep the factual context identical across arms. A card may change what the agent pays attention to. It must never name the fault, affected control, or expected complaint. Log which traits came from research and which are hypotheses.
3. A separate fixture author documents three reachable issues per task, for **18 distinct known issues**, with a frame or action sequence that demonstrates each. Include issues a reasonable user could encounter through different routes. Pair each flawed build with a repaired version containing the same data and unrelated controls. Keep the issue registry, repairs and build labels hidden from the participants, annotators and first-pass reviewers.
4. Pilot each task from a clean reset. Check the proposed endpoint, at least one alternative path and any external handoff. If the task cannot be completed for infrastructure reasons, repair the fixture before freezing or score a smaller, explicitly observable goal. Reserve at least one app from any prompt or persona tuning.

## What counts as an additional discovery

Deduplicate candidates from both arms by underlying failure and affected state. Give reviewers shuffled evidence packets with the goal, screenshot before the action, action and resulting screenshot. Mask card names, arm, and how often the complaint appeared. Review the UI claim before showing any potentially identifying first-person quote. A human records **supported product issue**, **fixture limitation**, **unsupported claim**, or **preference**, with a reason. A second reviewer resolves contested matches and independently checks the high-severity calls.

Only after adjudication, map each supported issue back to its sessions and to the frozen issue registry. Keep well-supported novel issues as a separate discovery count. Score both directions: issues found only by personas, issues found only by generic agents, and shared issues. Raw complaint counts and the current report’s distinct-persona frequency do not compare these arms fairly.

The primary score is known-issue recall at six starts. For each task and panel divide distinct matched issues by eligible issues. Average paired persona-minus-generic differences within app, then equally across apps. Publish the raw table for every task and both panels. With three apps, show the range and recalculate the result leaving each app out. These are estimates for these fixtures. More sessions on one app do little to establish transfer to other products.

For each promising persona-only finding, ask two questions. Did the generic sessions ever reach the relevant state? If so, did their actions show the same friction even though the annotator missed it? The first distinguishes route discovery from recognition. The second can reveal an analysis failure. Replay confirmed misses under the same goal on the corrected build, and track whether the relevant state was revisited before crediting a fix.

## Release decisions

These are proposed thresholds to freeze before inspecting held-out results. Publish the denominators and reviewer provenance even when a threshold is missed.

- **For an open-source experimental runner**, I would want a stranger to install it from a clean checkout, reproduce a public replay, and audit a finding back to its exact screens and utterance. On the held-out set I would want at least 80% of headline product claims supported by blind human review, with at least ten such claims reviewed. Count fixture gaps and unsupported or preference claims that reached the headline list against this precision figure. Publish fixture-gap rates separately. Use a distinct public package name.
- **To make persona mode the default**, I would also want at least a **10 percentage-point increase** in macro recall over six generic sessions, positive paired gains on at least two of the three apps, and repeatable persona-only findings on at least two apps. A repeatable example must recur in both independent persona panels and be absent from both generic panels. Show the generic-only discoveries and corroborate the direction of the gain at matched actual cost. If a few long sessions explain the gain, keep the result exploratory.
- **For using the results to guide fixes**, I would want at most one stale reflag per ten distinct repaired issues that the runner previously detected and revisited on the fixed build. If fewer than ten qualify, publish their outcomes and collect more examples before making a reliability claim.
- **If generic repeats tie or win**, the open-source runner can still earn its release through reproducible evidence. Ship the cheaper mode that meets the quality bar, label personas experimental, and publish the comparison. Claims about actual customer behavior need a separate study observing people doing those same tasks.

## The demo to show

Use a finding with a documented before-and-after pair. Start at the exact action, show the screen the participant saw, display their recorded think-aloud, and reveal the resulting screen. Let the viewer scrub backward and switch to a same-goal generic run or the fixed build. Only label something a persona-only discovery after the blinded benchmark qualifies it. The Sprout and Notes pilots above illustrate how to report a tie.
