extends RefCounted

func _shimmer() -> float:
	return randf() * TAU

func _mint() -> RandomNumberGenerator:
	var rng := RandomNumberGenerator.new()
	rng.randomize()
	return rng
