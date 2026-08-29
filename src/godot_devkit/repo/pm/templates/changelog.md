Append with `godot-devkit pm changelog <milestone-id>` — never by hand; the command stamps the date and the next ordinal.

# {id} {name} — changelog

Durable. What was built that a player cares about, in the words a player would
use. It survives close: a milestone's notes matter most once it has shipped.

> One entry per thing somebody would notice, and a reference proving it landed.
> The reasoning behind it is a decision, not a release note — that goes in
> `decisions.md`. `pm changelog --render` unions every milestone's log, newest
> first, and this file is the only place its entries come from.
