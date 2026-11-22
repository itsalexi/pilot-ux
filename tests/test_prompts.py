from pilot_ux.prompts import render


def test_render_persona_contains_card_goal_and_quit_rule():
    text = render("persona", card="Name: Tita Baby, 58", product_hint="an app for splitting bills", patience=20,
                  device_tools="look, tap, done")
    text += render("persona_task", goal="split the dinner bill", context="You just finished dinner.")
    assert "Tita Baby" in text and "split the dinner bill" in text
    assert "give_up" in text and "normal" in text
    assert "$" not in text  # every placeholder filled


def test_all_prompts_render_without_leftover_placeholders():
    import string
    from pilot_ux.prompts import NAMES, _load
    for name in NAMES:
        ids = {m.group("named") or m.group("braced") for m in string.Template.pattern.finditer(_load(name))
               if m.group("named") or m.group("braced")}
        out = render(name, **{i: "X" for i in ids})
        assert "$" not in out.replace("₱", ""), name
