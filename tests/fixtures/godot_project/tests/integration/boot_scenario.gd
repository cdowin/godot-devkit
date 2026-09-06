extends "res://tests/integration/support/scenario_base.gd"

## Boots because: tests/unit/mover_test.gd cannot prove the scene loads.
## covers: systems/mover.gd


func run() -> void:
	step("boot")
