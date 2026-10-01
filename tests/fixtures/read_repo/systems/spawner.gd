extends Node2D

var target: Player = null


func _ready() -> void:
	var manager = GameManager
	if GameManager:
		pass
	get_node("/root/GameManager")
