"""The workflow is the only part of this that runs unattended, and nothing else
tests it. Each assertion below is a mistake that has already been made on this
estate, in this repo or a neighbouring one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "collect.yml"


@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def raw():
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script(raw):
    """The workflow with comments stripped.

    The first version of these tests matched the whole file and failed on the
    comments explaining WHY `git add -A` and `reset --soft` are banned. A test
    that a warning about a mistake is itself the mistake is worse than no test:
    it either gets deleted or the comment does, and the comment is load-bearing.
    """
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        lines.append(line.split(" #")[0] if " #" in line else line)
    return "\n".join(lines)


def test_it_commits_the_ledgers_and_not_the_database(script):
    """corpus.db is gitignored and derived. The workflow was written before that
    decision and kept staging it: `git add` on an ignored path stages nothing,
    so every run would have committed the text files and silently lost the
    entire fetch and rejection history."""
    assert "data/*.jsonl" in script
    assert "git add data/corpus.db" not in script


def test_the_committed_ledgers_are_not_gitignored():
    """The inverse of the above, checked from the other side."""
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/corpus.db" in ignored
    assert "*.jsonl" not in ignored


def test_reset_is_mixed_not_soft(script):
    """`reset --soft` in CI keeps the index from the ORIGINAL checkout, so the
    replay commit rewrites every tracked file to how it stood when the job
    started. That is how the hub reverted nine pages under a thumbnail commit."""
    assert "reset --mixed" in script
    assert "reset --soft" not in script


def test_it_never_adds_everything(script):
    """`git add -A` has twice committed another session's work under a message
    describing something else."""
    assert "git add -A" not in script
    assert "git add ." not in script


def test_the_health_check_runs_even_when_collection_fails(wf):
    """A skipped health check on a failed run is the quietest possible outcome,
    and this collector's whole problem is that failures are silent."""
    steps = wf["jobs"]["collect"]["steps"]
    health = next(s for s in steps if s.get("name") == "Health")
    assert health.get("if") == "always()"


def test_it_accepts_the_heartbeat_dispatch(wf):
    """GitHub's scheduler on this account runs 3-7 hours late with no incident
    open, so the cron is the backstop and site-stats/heartbeat is the primary.
    A workflow without this trigger cannot be driven by the Worker, and adding
    it to the Worker's TARGETS without this is silent."""
    on = wf[True] if True in wf else wf["on"]
    assert "heartbeat" in on["repository_dispatch"]["types"]


def test_it_has_a_second_daily_cron(wf):
    """One schedule is not a schedule here: GitHub drops runs, and a dropped run
    is a permanently lost document rather than a late one."""
    on = wf[True] if True in wf else wf["on"]
    crons = [c["cron"] for c in on["schedule"]]
    assert len(crons) >= 2
    # Off the hour on purpose: on-the-hour slots are the congested ones.
    assert all(not c.startswith("0 ") for c in crons), crons
