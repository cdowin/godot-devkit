# Copy to test_<journey>.gd and set SCENE_PATH and the scene-specific control.
# GUT 9.6.1+; the scene owns its behavior. No global scenario runner is required.
extends GutTest

const SCENE_PATH := "res://scenes/example.tscn"
const READY_TIMEOUT_SECONDS := 2.0

var _sender: GutInputSender
var _activated: bool = false

func after_each() -> void:
	if _sender != null:
		_sender.release_all()
		_sender = null
	await wait_process_frames(1)
	assert_no_new_orphans()

func test_scene_accepts_player_input() -> void:
	assert_true(ResourceLoader.exists(SCENE_PATH), "Set the scene under test")
	if not ResourceLoader.exists(SCENE_PATH):
		return
	var scene: Node = (load(SCENE_PATH) as PackedScene).instantiate()
	add_child_autofree(scene)
	assert_true(await wait_until(func(): return scene.is_node_ready(), READY_TIMEOUT_SECONDS))
	var button: Button = scene.get_node("StartButton")
	button.pressed.connect(func(): _activated = true)
	button.grab_focus()
	await wait_process_frames(1)
	_sender = GutInputSender.new(Input)
	_sender.action_down("ui_accept").action_up("ui_accept")
	assert_true(await wait_until(func(): return _activated, READY_TIMEOUT_SECONDS))
