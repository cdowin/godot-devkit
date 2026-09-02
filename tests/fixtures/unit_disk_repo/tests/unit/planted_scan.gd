extends RefCounted

func _sc() -> Array:
	return SaveSlotIndex.scan()
