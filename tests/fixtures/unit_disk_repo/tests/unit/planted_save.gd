extends RefCounted

func _s(uuid: String) -> bool:
	return SaveService.save(uuid)
