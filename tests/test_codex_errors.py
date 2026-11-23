from pilot_ux.codex import stderr_summary


def test_spawn_failure_names_the_cause_not_the_prompt():
    stderr = ("Error: spawn /opt/codex/vendor/codex ENOENT\n"
              "    at ChildProcess._handle.onexit (node:internal/child_process:283:19)\n"
              "  spawnargs: [ 'exec', 'You are a first-time user. Don't be polite to the app...' ]\n")
    out = stderr_summary(stderr, 1)
    assert out == "codex CLI failed: Error: spawn /opt/codex/vendor/codex ENOENT"


def test_other_failures_keep_the_tail():
    assert stderr_summary("rate limited, retry later\n", 1) == "rate limited, retry later"


def test_silent_failure_reports_the_exit_code():
    assert stderr_summary("", 3) == "codex exited with code 3"
