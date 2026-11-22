import asyncio
import json

from pilot_ux import report_app, translate
from test_report import _out


def _with_lock(study, out):
    (out / "study.lock.json").write_text(json.dumps({"study": study.model_dump(), "started": "2026-11-22T14:07:08+0800",
                                                     "models": {"persona": "codex:gpt-pinned"}}))


def test_build_writes_visual_report_and_agent_fix_plan(tmp_path):
    study, out = _out(tmp_path)
    _with_lock(study, out)
    html, plan = report_app.build(out)
    page = html.read_text()
    assert html.name == "pilot.html" and plan.name == "fix-plan.md"
    assert "/*__SNAG_DATA__*/" not in page and "data:image/" in page
    assert 'id="fix-plan"' in page and "Common major" in page  # the plan travels inside the HTML too


def test_fix_plan_carries_everything_an_agent_needs(tmp_path):
    study, out = _out(tmp_path)
    _with_lock(study, out)
    _, plan = report_app.build(out)
    text = plan.read_text()
    major = text[text.index("Common major"):]
    assert "where is it" in major  # tester quote
    assert "Suggested fix: f" in major
    assert str(out / "runs/detail-checker__t__r1/shots/0000.png") in major  # exact screen to look at
    assert "--only t" in major and "pilot recheck" in major  # how to retest
    gaps = text[text.index("Not product problems"):]
    assert "Unbuilt button" in gaps and text.count("Unbuilt button") == 1  # gaps are listed, never queued as fixes


def test_fix_plan_orders_issues_like_the_report(tmp_path):
    study, out = _out(tmp_path)
    _with_lock(study, out)
    text = report_app.build(out)[1].read_text()
    assert text.index("Common major") < text.index("Rare catastrophe")


def test_gather_falls_back_to_study_without_lock(tmp_path):
    study, out = _out(tmp_path)
    d = report_app.gather(out, study=study)
    assert [t["id"] for t in d["tasks"]] == ["t"] and len(d["tasks"][0]["sessions"]) == 2


def test_translations_reach_frames_and_quotes(tmp_path):
    study, out = _out(tmp_path)
    _with_lock(study, out)
    (out / "translations.json").write_text(json.dumps({"older-non-techy__t__r1": {"0": "hm, in English"},
                                                       "_quotes": {translate.quote_key("where is it"): "where, in English"}}))
    d = report_app.gather(out)
    sess = {s["id"]: s for s in d["tasks"][0]["sessions"]}
    assert sess["older-non-techy__t__r1"]["frames"][0]["en"] == "hm, in English"
    assert d["hasEn"] is True
    assert '"where is it" (where, in English)' in report_app.build(out)[1].read_text()


def test_translate_pass_keeps_only_non_english_lines(tmp_path, monkeypatch):
    study, out = _out(tmp_path)
    calls = []

    async def fake(study_, role, system, prompt, schema, **kw):
        calls.append(prompt)
        return {"lines": [{"k": "older-non-techy__t__r1#0", "en": "hm in English"},
                          {"k": "detail-checker__t__r1#0", "en": ""},
                          {"k": "q#" + translate.quote_key("where is it"), "en": ""}]}

    monkeypatch.setattr(translate.agents, "ask_json", fake)
    got = asyncio.run(translate.translate(study, out))
    assert got == {"older-non-techy__t__r1": {"0": "hm in English"}, "_quotes": {}, "_reasons": {}}
    assert json.loads((out / "translations.json").read_text()) == got
    asyncio.run(translate.translate(study, out))
    assert len(calls) == 1  # cached


def test_quote_english_never_borrows_another_steps_translation(tmp_path):
    study, out = _out(tmp_path)
    _with_lock(study, out)
    # step 0 said "hm"; the issue quotes "where is it", which no step said verbatim
    (out / "translations.json").write_text(json.dumps({"older-non-techy__t__r1": {"0": "hm, in English"}, "_quotes": {}}))
    d = report_app.gather(out)
    ev = next(i for i in d["issues"] if i["id"] == "I1")["evidence"][0]
    assert ev["en"] == ""
    key = translate.quote_key("where is it")
    (out / "translations.json").write_text(json.dumps({"_quotes": {key: "where is it, translated"}}))
    ev = next(i for i in report_app.gather(out)["issues"] if i["id"] == "I1")["evidence"][0]
    assert ev["en"] == "where is it, translated"


def test_task_label_from_study_overrides_id(tmp_path):
    study, out = _out(tmp_path)
    study.tasks[0].label = "Find the thing"
    d = report_app.gather(out, study=study)
    assert d["tasks"][0]["label"] == "Find the thing"
    assert "label" not in study.model_copy(update={"tasks": [study.tasks[0].model_copy(update={"label": ""})]}).model_dump()["tasks"][0]



def test_report_page_runs_without_script_errors(tmp_path):
    from playwright.sync_api import sync_playwright

    study, out = _out(tmp_path)
    _with_lock(study, out)
    html, _ = report_app.build(out)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(html.as_uri())
        page.click('[data-issue="I2"]')
        page.click("#getFix")
        assert "Common major" in page.inner_text("#handoff pre")
        page.keyboard.press("Escape")
        page.click(".tester")
        assert page.is_visible("#follow")
        browser.close()
    assert errors == []


def test_gave_up_reason_gets_its_own_translation(tmp_path, monkeypatch):
    study, out = _out(tmp_path)
    _with_lock(study, out)
    rd = out / "runs/older-non-techy__t__r1"
    outcome = json.loads((rd / "outcome.json").read_text())
    (rd / "outcome.json").write_text(json.dumps({**outcome, "reason": "Hindi ko makita"}))
    (out / "translations.json").write_text(json.dumps({"older-non-techy__t__r1": {"0": "hm"}, "_quotes": {}}))
    calls = []

    async def fake(study_, role, system, prompt, schema, **kw):
        calls.append(prompt)
        return {"lines": [{"k": "r#older-non-techy__t__r1", "en": "I can't find it"}]}

    monkeypatch.setattr(translate.agents, "ask_json", fake)
    got = asyncio.run(translate.translate(study, out))  # a cache from before reasons were translated
    assert got["_reasons"] == {"older-non-techy__t__r1": "I can't find it"} and got["older-non-techy__t__r1"] == {"0": "hm"}
    assert "Hindi ko makita" in calls[0] and '"hm"' not in calls[0]  # only the missing reason is sent
    sess = {s["id"]: s for s in report_app.gather(out)["tasks"][0]["sessions"]}
    assert sess["older-non-techy__t__r1"]["reason"] == "Hindi ko makita"
    assert sess["older-non-techy__t__r1"]["reasonEn"] == "I can't find it"
