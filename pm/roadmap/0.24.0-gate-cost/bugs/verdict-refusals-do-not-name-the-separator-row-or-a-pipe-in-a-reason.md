---
id: 0.24.0/bugs/verdict-refusals-do-not-name-the-separator-row-or-a-pipe-in-a-reason
milestone: "0.24.0"
name: "a markdown separator row or a `|` inside a disposition reason refuses with a message that does not name what was written"
status: fixed
caught_in: "0.24.0"
fix_milestone: 0.24.0
caused_by: 0.23.0/review-record-shape
---

# verdict-refusals-do-not-name-the-separator-row-or-a-pipe-in-a-reason

## Symptom

v0.23.0 release review n1. `|---|---|---|` under the verdict table refuses as "unknown severity
'---'"; a `|` inside a `rejected: …` reason refuses as "4 cell(s)". Both loud, both exactly what an
LLM reviewer writes next.

## Root cause

`src/godot_devkit/repo/pm/verdict.py` (~:328) parses the row before recognising the two shapes; the
agent definitions' paragraph says "no separator row" but not "no pipe in the reason".

## Fix

Name both shapes in the refusal (`a markdown separator row is not a finding — drop it`; `a | inside
a reason splits the row — write 'or'`), and add the pipe rule to the paragraph the five emitters
carry. Tests: the two refusals by message.
