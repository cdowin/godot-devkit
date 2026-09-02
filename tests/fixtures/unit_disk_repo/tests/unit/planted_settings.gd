extends RefCounted

func _reset() -> void:
	SettingsManager.reset_to_defaults()
