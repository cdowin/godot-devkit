## Constructs its own throwaway state; never writes a real user:// path.
extends RefCounted

const IsolationHelper := preload("res://tests/support/helper.gd")

func _mint(slots) -> void:
	# NOT SaveSlotManager.create_new_slot() directly — the helper owns it
	slots.mint_slot()
	assert(slots != null, "SaveSlotIndex.scan() surfaced slot A")

func _s(uuid: String, root: String) -> bool:
	return SaveService.save(uuid, root)

func _sc(root: String) -> Array:
	return SaveSlotIndex.scan(root)

func _one_literal_arg() -> Array:
	return SaveSlotIndex.scan("res://throwaway")
