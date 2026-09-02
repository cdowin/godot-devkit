---
id: 0.18.1/sandbox-hook-quoting
milestone: "0.18.1"
name: The engine-boot guard stops blocking a quoted godot word
status: building
reviewed:
phase:
depends_on: []
consumed_by: []
---

# The engine-boot guard stops blocking a quoted godot word

`cc-godot-sandbox.sh` split the typed command line at `;|&()\`{}` with `tr`, so the split
happened INSIDE quoted text too. Any quoted word that happened to follow one of those
characters became the next segment's command word — and if it looked like the engine, a
perfectly ordinary command was blocked:

    echo "foo; godot --headless"                        # BLOCKED, pre-fix
    git commit -m "block (godot --headless) by hand"    # BLOCKED, pre-fix

Both are data, not boots. A guard that fires on the sentence describing it is a guard
people route around. The consumer fixed it in a fork; the fix belongs in the file every
consumer installs.

## Ship criterion

The tokenizer preserves quoted text verbatim inside its segment (so a quoted word is never
first in a segment), still treats a quoted COMMAND word (`"$GODOT" --headless`) as one, and
falls back to the naive split — strict, never open — on an unbalanced quote. The corpus
that proves it ships IN the hook as `--self-test`, and in the devkit's own hook matrix.
