Pilot tests any UX like real first-time users, so that you can fix it with your coding agent before shipping.

- Testers that have never seen your app. Each runs in its own Claude or Codex process, sees only screenshots, thinks aloud and can give up.
- Works on a URL, a repo, linked HTML pages, design artboards or screenshots, an iOS Simulator app, or a written idea.
- `pilot.html`: watch every tester replay side by side, with each problem ranked by severity and reach.
- `fix-plan.md`: the same findings as briefs your coding agent can act on, with the screens to check and how to retest.
- `pilot recheck`: before and after on the same testers and tasks.
- Interview answers scored with Semantic Similarity Rating; English lines for testers who think aloud in another language.

Install in Claude Code:

```
/plugin marketplace add itsalexi/pilot-ux
/plugin install pilot@pilot
```
