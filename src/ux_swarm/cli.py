"""ux-swarm command line."""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import time
from pathlib import Path

from .config import data_dir, load_study


def _study(args):
    s = load_study(args.study)
    if getattr(args, "runs", None):
        s.runs = args.runs
    if getattr(args, "model", None):
        s.model = args.model
    if getattr(args, "concurrency", None):
        s.concurrency = args.concurrency
    return s


def _out(s) -> Path:
    return Path(s.out_dir)


def cmd_init(a):
    dst = Path(a.dir)
    dst.mkdir(parents=True, exist_ok=True)
    tpl = data_dir("templates")
    for f in tpl.glob("*.yaml"):
        if not (dst / f.name).exists():
            shutil.copy(f, dst / f.name)
    print(f"wrote templates to {dst}. Edit study.yaml, then: ux-swarm run {dst / 'study.yaml'} --dry-run")


def cmd_personas(a):
    import yaml
    for p in sorted(data_dir("personas").glob("*.yaml")):
        d = yaml.safe_load(p.read_text())
        print(f"default/{d['id']:28} {d['name']}, {d['age']} · literacy {d['tech_literacy']} · patience {d['patience_steps']}")


def cmd_serve_proto(a):
    from .proto import load_flow, serve_proto
    srv = serve_proto(load_flow(a.flow), log_dir=Path(a.flow).parent)
    print(f"prototype at {srv.url}  (gap taps -> {Path(a.flow).parent / 'gaps.jsonl'}); Ctrl-C to stop")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.close()


def cmd_preview(a):
    from .proto import load_flow, preview_sheet
    print(preview_sheet(load_flow(a.flow), a.out))


def cmd_capture(a):
    from .capture import capture_dir
    made = asyncio.run(capture_dir(a.src, a.out, width=a.width, claude_design=a.claude_design, only=a.only))
    print(f"{len(made)} screens -> {a.out}")


def cmd_stitch(a):
    from .capture import stitch_dir
    fp = asyncio.run(stitch_dir(a.src, a.out, start=a.start, width=a.width, claude_design=a.claude_design, only=a.only))
    print(f"wrote {fp} (+ screens/, screens.map.yaml). Next: ux-swarm preview {fp} -o {Path(a.out) / 'sheet.png'}")


def dry_run(s, only: list[str] | None = None) -> str:
    from .runner import plan_runs
    specs = plan_runs(s)
    selected = [spec for spec in specs if not only or any(term in spec.id for term in only)]
    n = len(selected)
    if not n:
        return "0 persona sessions selected"
    scope = (f"selected from {len(specs)} planned" if only else
             f"{len(s.personas)} personas × {len(s.tasks)} tasks × {s.runs} runs")
    backends = dict.fromkeys(s.backend_for("persona", spec.n) for spec in selected)
    models = ", ".join(f"{backend}:{s.model_for('persona', backend)}" for backend in backends)
    calls_lo, calls_hi = n * 4 + 1, n * 5 + 1
    session_label = "session" if n == 1 else "sessions"
    return (f"{n} persona {session_label} ({scope}), persona models {models}, "
            f"{calls_lo}-{calls_hi} estimated model calls through merge "
            f"(session, canary, interview and annotator per session, verifier per claimed success, 1 merge), "
            f"concurrency {s.persona_concurrency}, target {s.target.kind}")


def cmd_run(a):
    s = _study(a)
    print(dry_run(s, only=a.only))
    if a.dry_run:
        return
    from .runner import run_study
    completed = asyncio.run(run_study(s, _out(s), only=a.only))
    if not completed:
        print(f"Study on hold with unstarted sessions. Clear the hold on {_out(s)} to continue.")
    return completed


def cmd_drain(a):
    from .runner import clear_drain, request_drain
    try:
        if a.clear:
            clear_drain(a.out)
            print("Hold cleared. Rerun the original study command to continue.")
        else:
            request_drain(a.out)
            print("Hold requested. Active sessions can finish. Pending sessions will wait for the next launch.")
    except (OSError, ValueError) as error:
        raise SystemExit(f"Could not update the study hold: {error}") from None


def cmd_interview(a):
    from .interview import run_interviews
    s = _study(a)
    asyncio.run(run_interviews(s, _out(s)))


def cmd_analyze(a):
    from . import analyze
    s = _study(a)

    async def go():
        await analyze.verify(s, _out(s))
        await analyze.annotate(s, _out(s))
        await analyze.merge(s, _out(s))
        await translate(s, _out(s))
    from .translate import translate
    asyncio.run(go())


def cmd_report(a):
    from .report import build
    s = _study(a)
    md, html = build(s, _out(s))
    from .report_app import build as build_app
    app, plan = build_app(_out(s), study=s)
    print(f"report: {app}\n        {plan}\n        {md}\n        {html}")


def cmd_replay(a):
    from .replay import build_replay
    try:
        study = load_study(a.study)
        print(build_replay(study, _out(study), a.output, a.sessions, a.start_step))
    except (OSError, ValueError) as error:
        raise SystemExit(f"Replay export failed: {error}") from None


def cmd_all(a):
    completed = cmd_run(a)
    if a.dry_run or completed is False:
        return
    cmd_interview(a)
    cmd_analyze(a)
    if a.truth:
        a.labels = None
        cmd_eval(a)
    cmd_report(a)


def cmd_eval(a):
    from .evaluate import run
    s = _study(a)
    m = asyncio.run(run(s, _out(s), Path(a.truth), Path(a.labels) if a.labels else None))
    print(f"recall {m['recall']:.0%} ({m['matched_in_scope']}/{m['in_scope']}) · FP {m['false_positive_rate']:.0%} · "
          f"stale {m['stale_rate']:.0%} · labels by {m['labelled_by']} -> {_out(s) / 'eval'}")


def cmd_recheck(a):
    from .recheck import recheck
    import yaml
    try:
        print(recheck(a.before, a.after, a.witness))
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise SystemExit(f"Repair recheck failed: {error}") from None


def cmd_benchmark(a):
    import yaml

    try:
        if a.operation == "export":
            from . import benchmark_review
            print(benchmark_review.export_review(a.out, a.review_dir))
        elif a.operation == "score":
            from . import benchmark_review
            benchmark_review.score_review(a.out, a.review_dir)
            print(a.out / "benchmark-score.json")
        else:
            from . import benchmark
            study = load_study(a.study)
            options = dict(panels=a.panels, seed=a.seed, patience=a.patience)
            if a.operation == "plan":
                plan = benchmark.prepare_benchmark(study, a.out, **options)
            else:
                plan = asyncio.run(benchmark.run_benchmark(study, a.out, **options))
            print(f"{len(plan['sessions'])} scheduled sessions · {a.out / 'benchmark.json'}")
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as error:
        raise SystemExit(f"Benchmark {a.operation} failed: {error}") from None


def cmd_ssr(a):
    from . import embedders, ssr
    r = ssr.score(a.text, a.construct, embedders.get(a.embedder))
    print(" ".join(f"{i + 1}:{p:.2f}" for i, p in enumerate(r["pmf"])), f"mean {r['mean']:.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ux-swarm", description="Synthetic-user UX testing with blind persona agents.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="copy study/persona/flow templates into a folder")
    p.add_argument("dir")
    p.set_defaults(f=cmd_init)
    sub.add_parser("personas", help="list default personas").set_defaults(f=cmd_personas)
    p = sub.add_parser("serve-proto", help="serve a stitched prototype for a manual click-through")
    p.add_argument("flow")
    p.set_defaults(f=cmd_serve_proto)
    p = sub.add_parser("preview", help="contact sheet of a flow's screens and hotspots")
    p.add_argument("flow")
    p.add_argument("-o", "--out", default="flow-preview.png")
    p.set_defaults(f=cmd_preview)

    p = sub.add_parser("capture", help="render a folder of HTML pages / design artboards to PNG screens")
    p.add_argument("src")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--width", type=int, default=390)
    p.add_argument("--claude-design", action="store_true", help="inject the .dc.html artboard runtime shim")
    p.add_argument("--only", nargs="*", help="file stems to render")
    p.set_defaults(f=cmd_capture)

    p = sub.add_parser("stitch", help="turn a folder of linked HTML pages / artboards into flow.yaml + screens")
    p.add_argument("src")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--start", required=True, help="file stem of the first screen")
    p.add_argument("--width", type=int, default=390)
    p.add_argument("--claude-design", action="store_true")
    p.add_argument("--only", nargs="*", help="file stems to include")
    p.set_defaults(f=cmd_stitch)

    def study_cmd(name, f, help):
        p = sub.add_parser(name, help=help)
        p.add_argument("study")
        p.add_argument("--runs", type=int)
        p.add_argument("--model")
        p.add_argument("--concurrency", type=int)
        p.set_defaults(f=f)
        return p

    p = study_cmd("run", cmd_run, "run persona sessions (resumable)")
    p.add_argument("--only", nargs="*", help="only run ids containing these strings")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("drain", help="finish active study sessions and hold the pending queue")
    p.add_argument("out", type=Path, help="output directory of the active study")
    p.add_argument("--clear", action="store_true", help="clear the hold before relaunching the study")
    p.set_defaults(f=cmd_drain)
    study_cmd("interview", cmd_interview, "post-task interviews + SSR scoring")
    study_cmd("analyze", cmd_analyze, "verify successes, annotate sessions, merge issues")
    study_cmd("report", cmd_report, "write pilot.html, fix-plan.md, report.md and report.html")
    p = sub.add_parser("replay", help="export recorded sessions as a self-contained HTML player")
    p.add_argument("study", type=Path)
    p.add_argument("--output", type=Path, required=True, help="destination HTML file")
    p.add_argument("--session", action="extend", nargs="+", dest="sessions", metavar="ID",
                   help="include these session IDs in order (repeatable)")
    p.add_argument("--start-step", type=int, metavar="N",
                   help="open at recorded step N (zero-based) in the first selected session")
    p.set_defaults(f=cmd_replay)
    p = study_cmd("all", cmd_all, "run -> interview -> analyze -> (eval) -> report")
    p.add_argument("--only", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--truth", help="known-issue list for eval")
    p = study_cmd("eval", cmd_eval, "score findings against a known-issue list")
    p.add_argument("--truth", required=True)
    p.add_argument("--labels", help="labels.csv with human_label filled in")
    p = sub.add_parser("recheck", help="compare original and repaired study output directories")
    p.add_argument("before", type=Path, help="original study output directory")
    p.add_argument("after", type=Path, help="fresh study output directory for the repaired build")
    p.add_argument("--witness", type=Path, help="YAML with versions, reviewer and observed before/after steps")
    p.set_defaults(f=cmd_recheck)
    p = sub.add_parser("benchmark", help="compare fresh generic sessions with a matched panel of behavioral personas")
    bench = p.add_subparsers(dest="operation", required=True)
    for name, summary in [("plan", "freeze the panel and its order without calling a model"),
                          ("run", "collect or resume a frozen comparison")]:
        bp = bench.add_parser(name, help=summary)
        bp.add_argument("study", type=Path)
        bp.add_argument("--out", type=Path, required=True, help="benchmark output directory")
        bp.add_argument("--panels", type=int, default=1, help="independent panels per task")
        bp.add_argument("--seed", type=int, default=0, help="seed used to schedule sessions")
        bp.add_argument("--patience", type=int, default=18, help="device patience units per session")
        bp.set_defaults(f=cmd_benchmark)
    for name, summary in [("export", "export evidence to a fresh directory for a blind reviewer"),
                          ("score", "score the completed review against the frozen panel")]:
        bp = bench.add_parser(name, help=summary)
        bp.add_argument("out", type=Path, help="benchmark output directory")
        bp.add_argument("review_dir", type=Path, help="directory shared with the reviewer")
        bp.set_defaults(f=cmd_benchmark)
    p = sub.add_parser("ssr", help="score one free-text answer with SSR")
    p.add_argument("text")
    p.add_argument("--construct", default="ease")
    p.add_argument("--embedder", default="openai:text-embedding-3-small")
    p.set_defaults(f=cmd_ssr)

    a = ap.parse_args(argv)
    try:
        a.f(a)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
