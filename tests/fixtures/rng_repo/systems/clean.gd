## Seeded per placement — never `randomize()`d, and never a bare randf().
extends RefCounted

func eject(rng: RandomNumberGenerator) -> float:
	var label := "randf() is named here in a string, not called"
	assert(label != "")
	return rng.randf() * rng.randf_range(0.0, 1.0)  # rng.randi() is fine too
