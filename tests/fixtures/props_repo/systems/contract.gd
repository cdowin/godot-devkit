class_name FixtureContract
extends Node2D

## The rename at the heart of the motivating incident: this export used to be
## called `floor_layer`. Any scene still assigning the old name is dead weight.
@export var background_layer: NodePath
@export var wall_layer: NodePath

@export_flags("Alpha:1", "Beta:2") var flags: int = 0

@export_group("Cosmetic")
@export var tint: Color = Color.WHITE
