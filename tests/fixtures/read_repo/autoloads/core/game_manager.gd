extends Node

signal tick


func _ready() -> void:
	tick.emit()
