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


def test_the_project_is_parked_consistently(wf, raw):
    """PARKED 10/09/2026. Two halves have to agree, and a half-parked project is
    worse than either state: crons on with no heartbeat target is a job firing
    into an estate nobody watches, and a heartbeat target with no crons is a
    Worker dispatching at a repo that ignores it.

    Guards the restart too - anyone uncommenting these crons has to read the
    instruction that says to re-add the heartbeat target as well."""
    on = wf[True] if True in wf else wf["on"]
    assert "schedule" not in on, "crons are live again; is the heartbeat target back?"
    assert "# schedule:" in raw, "the parked crons should stay as comments, not be deleted"
    assert "TO RESTART" in raw
    assert "TARGETS in site-stats/heartbeat" in raw
    # A hand-run must still be possible without editing the file.
    assert "workflow_dispatch" in on


def test_it_stages_the_sharded_announcements_directory(script):
    """announcements moved from data/announcements.jsonl to a directory of month
    shards. `data/*.jsonl` stopped matching it, and a glob that matches nothing
    stages nothing and fails nothing - the whole largest table would have gone
    uncommitted with the job still green. Same shape as the corpus.db bug."""
    assert "data/announcements" in script
