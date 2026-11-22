# Claude Design canvases

A Claude Design canvas is an Artifact whose files include `project/*.dc.html` artboards and `project/canvas.json`. Artboards need a small runtime to fill `{{holes}}`, `<sc-for>` and `<sc-if>`. `claude-design/support.js` in this skill is a minimal stand-in for that runtime. Artboards are static frames, so they always become a stitched `proto` target.

1. List the canvas files with the Artifact tool (`action: list, scope: files, url: <canvas url>`). Read `project/canvas.json` for the artboard order and any grouping.
2. Fetch the artboards you need with `action: read, paths: [...]`. Copy them into one local folder.
3. Artboards usually link to each other with `<a href="X.dc.html">`, so stitch them: `uxs stitch <folder> -o proto --start Home --claude-design`. Phone artboards are 390×844; taller ones scroll.
4. Check a few PNGs by eye. A blank or half-filled screen means the shim missed a feature that artboard uses: patch `support.js` locally, or drop that artboard.
5. Continue with "Stitching static screens" in [targets.md](targets.md). Artboard names (`AllPaid`, `PayPage`) give the flow away, so they must never reach the persona. `stitch` replaces them with neutral ids.

Canvas artboards are usually proprietary design work. Keep the rendered screens and flow files in a gitignored folder unless the owner says otherwise.
