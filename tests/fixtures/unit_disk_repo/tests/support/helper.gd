extends RefCounted

func mint_slot() -> void:
	SaveSlotManager.create_new_slot()
	SaveService.save("probe")
