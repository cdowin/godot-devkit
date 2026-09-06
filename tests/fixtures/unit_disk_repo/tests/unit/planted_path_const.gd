extends RefCounted

func _p(uuid: String) -> String:
	return PathConstants.PLAYER_SAVE_DIR_PATTERN % uuid
