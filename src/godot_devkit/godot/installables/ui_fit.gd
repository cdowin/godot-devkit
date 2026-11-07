extends SceneTree
## UI fit — boot each listed scene under stress and report what spills or is
## cut. The runtime half of `godot-devkit check ui-layout`, which only reads
## scene text.
##
## Run by ui_fit.sh — never invoke godot directly: the wrapper owns the
## user:// sandbox, the bound and the plan. Layout and font metrics resolve
## under --headless, so the wrapper boots it headless.
##
## Arguments (after `--`): --plan /abs/plan.txt, the lines `godot-devkit
## ui-fit-plan` prints:
##   window <w> <h>                 one per window size (smallest, largest)
##   large_text <res://x.gd> <fn>   optional: a static func that turns large text on
##   scene <res://x.tscn>           one per scene
##
## Stresses: Godot's pseudolocalization (expanded, accented text) is on for
## every pass. Each scene boots once per window; when the plan names a large
## text hook, the hook is called once and every scene boots again per window.
##
## Findings (the first stress that shows each):
##   spills  a visible Control's rect leaves its parent Control's rect (the
##           viewport's, for the scene root); a ScrollContainer's scrolling
##           axis is allowed. Under a parent that is not a Container, only an
##           axis the control GREW along counts: its size passed what its
##           anchors and offsets ask for. An overhang the offsets ask for
##           (a tick taller than its track, a corner ornament at negative
##           offsets, a touch target sized by code) is the author's rect.
##   cut     a Label or Button whose text needs more than its own rect, or is
##           hidden by a clip_contents ancestor (a ScrollContainer's scrolling
##           axis is allowed), and which set neither autowrap_mode nor
##           text_overrun_behavior (a chosen ellipsis is by design). clip_text
##           is not a policy: it only drops the text from the minimum size,
##           and it hides text mid-glyph with no cue; a deliberate hard cut is
##           text_overrun_behavior = OVERRUN_TRIM_CHAR. Text a grown control
##           pushes off screen is a `spills`, not a `cut`.
##
## Grouping: a finding is keyed by kind, the scene that saved the node (its
## owner's scene file, so every instance of a sub-scene shares one key) and the
## node's path inside that scene. One line per key; the instance count and the
## first instance follow when the key is not simply the booted scene's own node.
##
## Output contract (the wrapper greps these; the exit code is advisory):
##   "  <kind>  <scene> : <node path> — <why>[ (x<n>, e.g. <scene> : <path>)]"
##                                                  one per key, sorted
##   UI_FIT_AT <kind> <scene> : <node path> — <why> one per instance (the log)
##   UI_FIT_DIRTY <res://scene>                     one per booted scene with findings
##   UI_FIT_FAIL <reason>                           one per harness failure
##   UI_FIT_RESULT <booted> <total> <findings>      last; findings = keys

const EXPANSION_RATIO := 0.3
const SLACK := 1.0
const SETTLE_FRAMES := 3
const SPILLS := "spills"
const CUT := "cut"

var _failures := 0
## [kind, owner scene, path in it] -> {"why", "first": [scene, path], "at": {[scene, path]: true}}
var _found := {}


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var plan := _read_plan(OS.get_cmdline_user_args())
	if plan.is_empty():
		quit(2)
		return
	ProjectSettings.set_setting("internationalization/pseudolocalization/expansion_ratio", EXPANSION_RATIO)
	TranslationServer.pseudolocalization_enabled = true
	TranslationServer.reload_pseudolocalization()
	var booted := {}
	await _pass(plan, "", booted)
	if plan.has("hook"):
		var hook: PackedStringArray = plan["hook"]
		if _call_hook(hook):
			await _pass(plan, ", large text", booted)
	var dirty := {}
	var keys := _found.keys()
	keys.sort()
	for key: Array in keys:
		var owner_scene: String = key[1]
		var group: Dictionary = _found[key]
		var instances: Dictionary = group["at"]
		var line := "  %s  %s : %s — %s" % [key[0], owner_scene.trim_prefix("res://"), key[2], group["why"]]
		var first: Array = group["first"]
		var first_scene: String = first[0]
		if instances.size() > 1 or first != [key[1], key[2]]:
			line += " (x%d, e.g. %s : %s)" % [instances.size(), first_scene.trim_prefix("res://"), first[1]]
		print(line)
		for at: Array in instances:
			dirty[at[0]] = true
	for scene: String in dirty.keys():
		print("UI_FIT_DIRTY " + scene)
	var scenes: Array[String] = plan["scenes"]
	print("UI_FIT_RESULT %d %d %d" % [booted.size(), scenes.size(), _found.size()])
	quit(1 if _failures > 0 or not _found.is_empty() else 0)


func _read_plan(tokens: PackedStringArray) -> Dictionary:
	if tokens.size() != 2 or tokens[0] != "--plan":
		_fail("usage: --plan /abs/plan.txt")
		return {}
	var text := FileAccess.get_file_as_string(tokens[1])
	if text.is_empty():
		_fail("cannot read the plan at %s" % tokens[1])
		return {}
	var windows: Array[Vector2i] = []
	var scenes: Array[String] = []
	var plan := {"windows": windows, "scenes": scenes}
	for line: String in text.split("\n", false):
		var parts := line.split(" ", false)
		if line.begins_with("scene res://"):
			scenes.append(line.trim_prefix("scene "))
		elif parts.size() == 3 and parts[0] == "window" and parts[1].to_int() > 0 and parts[2].to_int() > 0:
			windows.append(Vector2i(parts[1].to_int(), parts[2].to_int()))
		elif parts.size() == 3 and parts[0] == "large_text":
			plan["hook"] = parts.slice(1)
		else:
			_fail("unreadable plan line: %s" % line)
			return {}
	if windows.is_empty():
		_fail("the plan names no window")
		return {}
	return plan


func _call_hook(hook: PackedStringArray) -> bool:
	var script := load(hook[0]) as Script
	if script == null:
		_fail("large text hook %s does not load as a script" % hook[0])
		return false
	if not script.has_method(hook[1]):
		_fail("large text hook %s has no static func %s" % [hook[0], hook[1]])
		return false
	script.call(hook[1])
	return true


func _pass(plan: Dictionary, stress: String, booted: Dictionary) -> void:
	var windows: Array[Vector2i] = plan["windows"]
	var scenes: Array[String] = plan["scenes"]
	for window: Vector2i in windows:
		root.size = window
		for scene: String in scenes:
			var packed := load(scene) as PackedScene
			if packed == null:
				_fail("%s does not load as a PackedScene" % scene)
				continue
			var node := packed.instantiate()
			root.add_child(node)
			for _i: int in SETTLE_FRAMES:
				await process_frame
			booted[scene] = true
			_judge(scene, node, "at %dx%d%s" % [window.x, window.y, stress])
			node.free()
			await process_frame


func _judge(scene: String, top: Node, stress: String) -> void:
	var nodes: Array[Node] = top.find_children("*", "Control", true, true)
	nodes.push_front(top)
	for item: Node in nodes:
		var c := item as Control
		if c == null or not c.is_visible_in_tree():
			continue
		var why := _spill(c, top)
		if not why.is_empty():
			_add(SPILLS, scene, top, c, "%s %s" % [why, stress])
		why = _cut(c)
		if not why.is_empty():
			_add(CUT, scene, top, c, "%s %s" % [why, stress])


## Why `c` leaves its parent's rect, or "" when it stays inside.
func _spill(c: Control, top: Node) -> String:
	if c.top_level:
		return ""
	var parent := c.get_parent() as Control
	var outer: Rect2
	var name := "the viewport"
	if parent != null:
		outer = parent.get_global_rect()
		name = String(parent.name)
	elif c == top:
		outer = root.get_visible_rect()
	else:
		return ""
	var r := c.get_global_rect()
	var scroll := parent as ScrollContainer
	var free_x := scroll != null and scroll.horizontal_scroll_mode != ScrollContainer.SCROLL_MODE_DISABLED
	var free_y := scroll != null and scroll.vertical_scroll_mode != ScrollContainer.SCROLL_MODE_DISABLED
	var out_x := r.position.x < outer.position.x - SLACK or r.end.x > outer.end.x + SLACK
	var out_y := r.position.y < outer.position.y - SLACK or r.end.y > outer.end.y + SLACK
	if parent != null and not parent is Container:
		var asked := _asked_size(c, parent)
		free_x = c.size.x <= asked.x + SLACK
		free_y = c.size.y <= asked.y + SLACK
	if (out_x and not free_x) or (out_y and not free_y):
		return "rect %s leaves %s %s" % [_rect(r), name, _rect(outer)]
	return ""


## The size `c`'s anchors and offsets ask for inside `parent`. A Control only
## grows past it when its minimum size forces it; code that sets `size` moves
## the offsets, so a rect sized by hand asks for exactly what it gets.
func _asked_size(c: Control, parent: Control) -> Vector2:
	return Vector2(
		(c.anchor_right - c.anchor_left) * parent.size.x + c.offset_right - c.offset_left,
		(c.anchor_bottom - c.anchor_top) * parent.size.y + c.offset_bottom - c.offset_top)


## Why `c`'s text is cut, or "" when it fits or the node chose a policy.
func _cut(c: Control) -> String:
	if not (c is Label or c is Button):
		return ""
	var text: String = c.get("text")
	if text.is_empty():
		return ""
	if c.get("autowrap_mode") != TextServer.AUTOWRAP_OFF:
		return ""
	if c.get("text_overrun_behavior") != TextServer.OVERRUN_NO_TRIMMING:
		return ""
	var clipped: bool = c.get("clip_text")
	c.set("clip_text", false)
	var natural := c.get_minimum_size()
	c.set("clip_text", clipped)
	if natural.x > c.size.x + SLACK or natural.y > c.size.y + SLACK:
		return "text needs %dx%d in %dx%d and sets neither autowrap_mode nor text_overrun_behavior%s" % [
			ceili(natural.x), ceili(natural.y), ceili(c.size.x), ceili(c.size.y),
			" (clip_text cuts mid-glyph; OVERRUN_TRIM_CHAR is the declared hard cut)" if clipped else ""]
	var r := c.get_global_rect()
	var up := c.get_parent() as Control
	while up != null:
		if up.clip_contents and not _scrolls_over(up, r):
			return "text is clipped by %s and sets neither autowrap_mode nor text_overrun_behavior" % up.name
		up = up.get_parent() as Control
	return ""


## True when `clipper` does not hide any of `r`: `r` is inside it, or it is a
## ScrollContainer that scrolls along every axis `r` runs past it.
func _scrolls_over(clipper: Control, r: Rect2) -> bool:
	var outer := clipper.get_global_rect()
	var out_x := r.position.x < outer.position.x - SLACK or r.end.x > outer.end.x + SLACK
	var out_y := r.position.y < outer.position.y - SLACK or r.end.y > outer.end.y + SLACK
	var scroll := clipper as ScrollContainer
	if scroll != null:
		out_x = out_x and scroll.horizontal_scroll_mode == ScrollContainer.SCROLL_MODE_DISABLED
		out_y = out_y and scroll.vertical_scroll_mode == ScrollContainer.SCROLL_MODE_DISABLED
	return not out_x and not out_y


## Record `c`'s finding under its group key; the first instance gives the why.
func _add(kind: String, scene: String, top: Node, c: Control, why: String) -> void:
	var at := [scene, String(top.get_path_to(c))]
	var key := [kind] + at
	var owner := c.owner
	if owner != null and not owner.scene_file_path.is_empty():
		key = [kind, owner.scene_file_path, String(owner.get_path_to(c))]
	if not _found.has(key):
		_found[key] = {"why": why, "first": at, "at": {}}
	var group: Dictionary = _found[key]
	var instances: Dictionary = group["at"]
	if not instances.has(at):
		instances[at] = true
		print("UI_FIT_AT %s %s : %s — %s" % [kind, scene.trim_prefix("res://"), at[1], why])


func _rect(r: Rect2) -> String:
	return "(%d, %d, %dx%d)" % [roundi(r.position.x), roundi(r.position.y), roundi(r.size.x), roundi(r.size.y)]


func _fail(reason: String) -> void:
	_failures += 1
	print("UI_FIT_FAIL " + reason)
