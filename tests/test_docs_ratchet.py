"""test_docs_ratchet.py — docs for people live in the wiki, so the repo cannot grow them back.

Fails when a tracked file is a `docs/` path, a `CHANGELOG*` file, or a `.md` outside the
allowlist (README.md, CLAUDE.md, AGENTS.md, and `.md` fixtures under tests/fixtures/).
README.md is a landing page: at most README_MAX_LINES lines.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_MD = {"README.md", "CLAUDE.md", "AGENTS.md"}
README_MAX_LINES = 80


def _tracked() -> list[str]:
    done = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    files = done.stdout.splitlines()
    assert len(files) > 50, f"git ls-files returned {len(files)} files; the census collapsed"
    return files


def test_no_docs_dir_changelog_or_stray_markdown():
    bad = []
    for f in _tracked():
        name = f.rsplit("/", 1)[-1]
        if f.startswith("docs/") or name.upper().startswith("CHANGELOG"):
            bad.append(f)
        elif f.lower().endswith(".md") and f not in ALLOWED_MD and not f.startswith("tests/fixtures/"):
            bad.append(f)
    assert not bad, "docs for people go in the wiki, not the repo:\n  " + "\n  ".join(bad)


def test_readme_is_a_landing_page():
    lines = (ROOT / "README.md").read_text(encoding="utf-8").count("\n") + 1
    assert lines <= README_MAX_LINES, f"README.md is {lines} lines; the cap is {README_MAX_LINES}. Move text to the wiki."
