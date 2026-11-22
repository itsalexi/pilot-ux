import textwrap
import pytest
from pydantic import ValidationError
from pilot_ux.config import load_study, Persona


def write(tmp_path, body):
    p = tmp_path / "study.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_load_study_inline_and_ref_personas(tmp_path):
    p = write(tmp_path, """
        name: demo
        target: {kind: url, url: "http://localhost:3000"}
        tasks:
          - {id: t1, goal: "split dinner with friends", success_criteria: ["shows each person's amount"]}
        personas:
          - ref: default/impatient-power-user
          - id: tita
            name: Tita Baby
            age: 58
            locale: en-PH
            device: Android phone
            tech_literacy: 1
            patience_steps: 25
            language_register: Taglish, polite
            goals: [not be embarrassed]
            fears: [being scammed]
            habits: [asks her niece]
        """)
    s = load_study(p)
    assert [x.id for x in s.personas] == ["impatient-power-user", "tita"]
    assert s.runs == 3
    assert s.target.viewport == (390, 844)


def test_model_for_falls_back_to_default(tmp_path):
    p = write(tmp_path, """
        name: demo
        target: {kind: url, url: "http://x"}
        tasks: [{id: t, goal: g, success_criteria: [c]}]
        personas: [{ref: default/older-non-techy}]
        models: {annotator: claude-sonnet-5-5}
        """)
    s = load_study(p)
    assert s.model_for("annotator") == "claude-sonnet-5-5"
    assert s.model_for("persona") == "claude-opus-5-5"


def test_persona_literacy_bounds_rejected():
    with pytest.raises(ValidationError):
        Persona(id="x", name="x", age=30, locale="en", device="phone", tech_literacy=6,
                patience_steps=10, language_register="plain", goals=[], fears=[], habits=[])


def test_flow_path_resolved_relative_to_study(tmp_path):
    p = write(tmp_path, """
        name: demo
        target: {kind: proto, flow: proto/flow.yaml}
        tasks: [{id: t, goal: g, success_criteria: [c]}]
        personas: [{ref: default/older-non-techy}]
        """)
    s = load_study(p)
    assert s.target.flow == str(tmp_path / "proto/flow.yaml")


def test_ios_app_path_and_serial_personas(tmp_path):
    p = write(tmp_path, """
        name: demo
        target: {kind: ios, app_bundle: app.demo, ios_app_path: Demo.app, launch_args: ["--example"]}
        tasks: [{id: t, goal: g, success_criteria: [c]}]
        personas: [{ref: default/older-non-techy}]
        concurrency: 6
        """)
    s = load_study(p)
    assert s.target.ios_app_path == str(tmp_path / "Demo.app")
    assert s.target.launch_args == ["--example"]
    assert s.persona_concurrency == 1
