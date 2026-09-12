class_name Item
extends "res://systems/base_item.gd"

enum Mode { IDLE, BUSY }

@export var price: float
@export var scale: Vector2 = Vector2.ONE
@export var ratios: Array[float] = []
@export var children: Array[Item] = []
@export var icons: Array[Texture2D] = []
## An enum element type: the saver's spelling of it is not knowable by parse.
@export var modes: Array[Mode] = []
@export var count: int
@export var notes: Array = []

## The saver writes what the GETTER returns — never respelled.
@export var guarded: float = 0.0:
	set(value):
		guarded = maxf(value, 0.0)
