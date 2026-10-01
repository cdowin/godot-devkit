class_name Player
extends Node2D


func hurt(amount: int) -> void:
	position.x += amount


signal died


func _on_button_pressed() -> void:
	DataRegistry.lookup("hp")


func _on_died() -> void:
	pass


func watch() -> void:
	if not is_connected("died", _on_died):
		pass
	died.disconnect(_on_died)
	has_signal("died")
	has_user_signal("died")
	var relay := Signal(self, "died")
