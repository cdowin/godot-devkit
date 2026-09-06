extends "res://systems/base_rule.gd"

const IdsClass = preload("res://systems/ids.gd")
const SPEED := 300.0

enum Trigger {
	ALL_DOWN,
	OBJECTIVE,
	SELF_EXIT,
}

@export var trigger: Trigger = Trigger.ALL_DOWN
@export var kind: int = IdsClass.Kind.THIRD
@export var owner_id: int = IdsClass.INVALID_ID
@export var tag: StringName = IdsClass.DEFAULT_TAG
@export var speed: float = SPEED
@export var label: String = "unnamed"
@export var offset: Vector2 = Vector2.ZERO
@export var extent: Rect2 = Rect2(0, 0, 4, 4)
@export var untouched: int
@export var members: Array[Resource] = []
@export var lookup: Dictionary = {}
@export var payload: Resource

## An accessor means the STORED value need not be the assigned one — never elide.
@export var guarded: int = 0:
	set(value):
		guarded = maxi(value, 0)

## A default the closed value language cannot evaluate — never elide.
@export var computed: int = int(SPEED / 100.0)
