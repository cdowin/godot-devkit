extends RefCounted

func _mint() -> void:
	SaveSlotManager.create_new_slot()
