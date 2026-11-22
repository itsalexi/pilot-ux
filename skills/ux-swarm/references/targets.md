# Resolving the target

Personas only see pixels. Your job is to turn whatever the user gave you into something that renders in a phone-sized browser (or the iOS Simulator), with nothing on screen that gives the product away: no URL bar, no meaningful page titles, no file names.

| Input | Do this | `target:` |
|---|---|---|
| Live or local URL | Open the target and seed the authorized test environment with realistic sample data. For signed-in tasks, use a test identity and an ignored Playwright storage-state file through `UX_SWARM_STORAGE_STATE`. Keep credentials and real customer data out of the task, screenshots and reports. Reset mutable data between measured attempts using an isolated test account or fixture. | `{kind: url, url: ...}` |
| Repo | Read the README, package scripts and framework config. Start its dev server, wait for the port, and use the project's test fixtures. Resolve build or seed failures within scope. Record the build under test. For a retest, restart or rebuild the target and check that it serves the patched source. For a native iOS target, use the simulator workflow below. | `{kind: url, url: http://localhost:PORT}` |
| Folder of HTML pages that link to each other | Serve it as is. Routes are made opaque and `<title>` is blanked automatically. | `{kind: static, folder: path, url: index.html}` |
| Static screens: design artboards, Figma or Claude Design exports, a screenshot folder, HTML with no working links | Stitch a clickable prototype (below). | `{kind: proto, flow: flow.yaml, fidelity: prototype}` |
| iOS app | Use AXe and a disposable booted test simulator. Record its UDID and the simulator build. Setting `ios_app_path` reinstalls the matching bundle before each attempt, so use a fixture with expendable state. Keep the model, simulator, viewport and starting data consistent across builds. | `{kind: ios, app_bundle: com.example.app, ios_app_path: build/Example.app, udid: SIMULATOR_UDID}` |
| Only an idea or a description | Build a throwaway low-fidelity HTML prototype of just the flows in the tasks: plain controls and realistic copy, no lorem ipsum. Serve it as `static`. Tell the user the findings test the *idea's structure*, not the visual design. | `{kind: static, ..., fidelity: sketch}` |

## Stitching static screens into a prototype

**HTML pages or artboards that link to each other** (`<a href="Other.html">`): let the tool do the first pass.

```bash
uxs stitch <folder> -o proto --start <first-page-stem> [--claude-design] [--only Stem1 Stem2 ...]
```

It renders every page and writes:
- `proto/flow.yaml`: links become hotspots, text fields become `input:` hotspots, and other controls become `UNLINKED` hotspots;
- `proto/screens/`;
- `proto/screens.map.yaml`: neutral id → original name. This is for you only.

Then edit `flow.yaml`: point UNLINKED hotspots at screens you do have, and leave the rest UNLINKED, because taps on them are real prototype gaps.

**Images, or HTML without links:** run `uxs capture <folder> -o proto/screens`. It renders HTML and resizes PNG, JPG or WEBP files to 390 px wide. Then write `flow.yaml` by hand from `templates/flow.yaml`:
- `rect` is `[x, y, w, h]` in CSS px on the 390-wide image;
- `to:` is a screen id;
- `input: <any name>` draws a text box the persona can type into.

Either way:

1. Include the screens on the task flows, plus the ones a curious user reaches in one tap from them (settings, menus, back destinations).
2. Screen ids stay neutral (`s01`). They are never shown, but they keep you honest.
3. Put a hotspot on **every visible control** on every included screen, not just the "right" path. A control with no destination screen leaves the screen unchanged and is logged as a prototype gap. Text that only *might* be a control (a row reading "Notifications: on") also gets a hotspot if a user could reasonably tap it.
4. **States:**
   - A sheet, menu or overlay is its own screen.
   - A change on the same screen (an open dropdown, a toggle, a selected option, a button enabled after typing) is a second image of that screen, reached by a hotspot.
   - If the source has no image of a state the task needs, say so (step 3 of the workflow).
   - Tall images scroll. Hotspot y-coordinates are measured from the top of the full image.
5. Run `uxs preview proto/flow.yaml -o proto/sheet.png` and **look at the sheet**. Every box should sit on a real control. Fix any that don't; a misplaced hotspot creates fake confusion.
6. If the flow is long, click through it yourself once with `uxs serve-proto proto/flow.yaml`.

## What leaks, and how to stop it

- File names and routes: handled by `proto` and `static` (opaque hashes). For a `url` target, check that routes don't spell out the flow (`/step-3-success`). If they do, serve the app behind a proxy or accept the leak and note it in the report.
- Page titles: blanked for `proto` and `static`. For `url` targets they aren't visible anyway (there's no browser chrome in the screenshots).
- Debug overlays, dev toolbars, "prototype" watermarks: turn them off.
- `product_hint` is the only thing personas are told. Make it one generic line naming the product category, not the feature the task tests:
  - "an app for looking after houseplants", not "an app that reminds you to water plants";
  - "an app for splitting bills with friends", not "an app with receipt scanning".

  No brand names.
