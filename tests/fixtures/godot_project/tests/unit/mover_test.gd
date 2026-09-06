extends RefCounted


## One use case, asserted once: the exported default is what the scene relies on.
func test_default_speed() -> void:
	var mover := preload("res://systems/mover.gd").new()
	assert(mover.speed == 1.0, "stock speed")
