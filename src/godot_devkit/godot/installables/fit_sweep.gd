extends SceneTree
## Fit sweep — instance each listed screen at each size of the game's
## size-class table and report clipped text and controls out of reach.
##
## Run by fit_sweep.sh — never invoke godot directly: the wrapper owns the
## user:// sandbox, the bound, the plan and the display. Each scene is laid out
## in a SubViewport of exactly the size (logical px, no stretch), so the window
## size never limits a size. With --png-dir the wrapper gives it a renderer and
## each scene is drawn at each size; without, it runs --headless and draws
## nothing.
##
## Arguments (after `--`): --plan /abs/plan.txt [--png-dir /abs/dir], the
## plan `godot-devkit fit-sweep-plan` prints:
##   size <w> <h> <class>-<role>    one per size
##   touch <px>                     optional: the touch-target minimum
##   scene <res://x.tscn>           one per scene
##
## Findings, one line per scene, size and node:
##   clipped      a Label or RichTextLabel that sets neither autowrap nor an
##                ellipsis text_overrun_behavior, whose text needs more than its
##                rect, grew it past what its anchors and offsets ask for (under
##                a parent that is not a Container), runs past the viewport, or
##                is hidden by a clip_contents ancestor (a ScrollContainer's
##                scrolling axis is allowed on the last two). A RichTextLabel
##                with scroll_active may run past its height.
##   unreachable  a focusable Control (focus_mode click or all) whose rect
##                leaves the viewport (not under a ScrollContainer that scrolls
##                that axis), or whose centre is covered by a visible Control
##                drawn after it: a later sibling of it or of an ancestor in the
##                scene, whose mouse_filter is not ignore.
##   small        a focusable Control narrower or shorter than the touch target
##                (only when the plan names one).
##
## Output contract (the wrapper greps these; the exit code is advisory):
##   "  <kind>  <scene> <w>x<h> <class>-<role> : <node path> — <why>"
##   FIT_SWEEP_PNG <abs path>                                    one per drawing
##   FIT_SWEEP_FAIL <reason>                                     one per harness failure
##   FIT_SWEEP_RESULT <booted> <total> <sizes> <findings> <ms>   last

const SLACK := 1.0
const SETTLE_FRAMES := 3
const CLIPPED := "clipped"
const UNREACHABLE := "unreachable"
const SMALL := "small"
const ELLIPSIS: Array[int] = [
	TextServer.OVERRUN_TRIM_ELLIPSIS, TextServer.OVERRUN_TRIM_WORD_ELLIPSIS,
	TextServer.OVERRUN_TRIM_ELLIPSIS_FORCE, TextServer.OVERRUN_TRIM_WORD_ELLIPSIS_FORCE]

var _failures := 0
var _findings := 0


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var plan := _read_plan(OS.get_cmdline_user_args())
	if plan.is_empty():
		quit(2)
		return
	var sizes: Array[Dictionary] = plan["sizes"]
	var scenes: Array[String] = plan["scenes"]
	var png_dir: String = plan["png_dir"]
	var touch: int = plan["touch"]
	var vp := SubViewport.new()
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	vp.transparent_bg = false
	root.add_child(vp)
	var booted := 0
	var started := Time.get_ticks_msec()
	for scene: String in scenes:
		var packed := load(scene) as PackedScene
		if packed == null:
			_fail("%s does not load as a PackedScene" % scene)
			continue
		booted += 1
		for size: Dictionary in sizes:
			var at: Vector2i = size["at"]
			vp.size = at
			var node := packed.instantiate()
			vp.add_child(node)
			for _i: int in SETTLE_FRAMES:
				await process_frame
			var where := "%s %dx%d %s" % [scene.trim_prefix("res://"), at.x, at.y, size["label"]]
			_judge(where, node, Rect2(Vector2.ZERO, Vector2(at)), touch)
			if not png_dir.is_empty():
				await RenderingServer.frame_post_draw
				_draw(vp, png_dir.path_join(_png_name(scene, at)))
			node.free()
	var elapsed := Time.get_ticks_msec() - started
	print("FIT_SWEEP_RESULT %d %d %d %d %d" % [booted, scenes.size(), sizes.size(), _findings, elapsed])
	quit(1 if _failures > 0 or _findings > 0 else 0)


func _read_plan(tokens: PackedStringArray) -> Dictionary:
	var png_dir := ""
	if tokens.size() == 4 and tokens[2] == "--png-dir":
		png_dir = tokens[3]
	elif tokens.size() != 2:
		tokens = PackedStringArray()
	if tokens.size() < 2 or tokens[0] != "--plan":
		_fail("usage: --plan /abs/plan.txt [--png-dir /abs/dir]")
		return {}
	var text := FileAccess.get_file_as_string(tokens[1])
	if text.is_empty():
		_fail("cannot read the plan at %s" % tokens[1])
		return {}
	var sizes: Array[Dictionary] = []
	var scenes: Array[String] = []
	var plan := {"sizes": sizes, "scenes": scenes, "png_dir": png_dir, "touch": 0}
	for line: String in text.split("\n", false):
		var parts := line.split(" ", false)
		if line.begins_with("scene res://"):
			scenes.append(line.trim_prefix("scene "))
		elif parts.size() == 4 and parts[0] == "size" and parts[1].to_int() > 0 and parts[2].to_int() > 0:
			sizes.append({"at": Vector2i(parts[1].to_int(), parts[2].to_int()), "label": parts[3]})
		elif parts.size() == 2 and parts[0] == "touch" and parts[1].to_int() > 0:
			plan["touch"] = parts[1].to_int()
		else:
			_fail("unreadable plan line: %s" % line)
			return {}
	if sizes.is_empty():
		_fail("the plan names no size")
		return {}
	return plan


func _judge(where: String, top: Node, view: Rect2, touch: int) -> void:
	var nodes: Array[Node] = top.find_children("*", "Control", true, true)
	nodes.push_front(top)
	for item: Node in nodes:
		var c := item as Control
		if c == null or not c.is_visible_in_tree():
			continue
		var path := String(top.get_path_to(c))
		var why := _clipped(c, view)
		if not why.is_empty():
			_report(CLIPPED, where, path, why)
		if c.focus_mode != Control.FOCUS_CLICK and c.focus_mode != Control.FOCUS_ALL:
			continue
		why = _out_of_reach(c, top, view)
		if not why.is_empty():
			_report(UNREACHABLE, where, path, why)
		if touch > 0 and (c.size.x < touch - SLACK or c.size.y < touch - SLACK):
			_report(SMALL, where, path, "%dx%d is under the %dpx touch target" % [
				ceili(c.size.x), ceili(c.size.y), touch])


## Why `c`'s text is cut, or "" when it fits or the node chose wrap or ellipsis.
func _clipped(c: Control, view: Rect2) -> String:
	var label := c as Label
	var rich := c as RichTextLabel
	if label == null and rich == null:
		return ""
	if c.get("autowrap_mode") != TextServer.AUTOWRAP_OFF:
		return ""
	if "text_overrun_behavior" in c and c.get("text_overrun_behavior") in ELLIPSIS:
		return ""
	var need := Vector2.ZERO
	if label != null:
		if label.text.is_empty():
			return ""
		var overrun := label.text_overrun_behavior
		var clipped := label.clip_text
		label.text_overrun_behavior = TextServer.OVERRUN_NO_TRIMMING
		label.clip_text = false
		need = label.get_minimum_size()
		label.text_overrun_behavior = overrun
		label.clip_text = clipped
	else:
		if rich.get_parsed_text().is_empty():
			return ""
		need = Vector2(rich.get_content_width(), rich.get_content_height())
	var scrolls := rich != null and rich.scroll_active
	if need.x > c.size.x + SLACK or (need.y > c.size.y + SLACK and not scrolls):
		return "text needs %dx%d in %dx%d, with no autowrap and no overrun ellipsis" % [
			ceili(need.x), ceili(need.y), ceili(c.size.x), ceili(c.size.y)]
	var parent := c.get_parent() as Control
	if parent != null and not parent is Container:
		var asked := _asked_size(c, parent)
		if c.size.x > asked.x + SLACK or c.size.y > asked.y + SLACK:
			return "text grew it to %dx%d past the %dx%d its offsets ask for, with no autowrap and no overrun ellipsis" % [
				ceili(c.size.x), ceili(c.size.y), ceili(asked.x), ceili(asked.y)]
	var r := c.get_global_rect()
	if not _scrolls_over_view(c, r, view):
		return "text runs past the viewport %s at %s, with no autowrap and no overrun ellipsis" % [
			_rect(view), _rect(r)]
	var up := parent
	while up != null:
		if up.clip_contents and not _scrolls_over(up, r):
			return "text is clipped by %s %s, with no autowrap and no overrun ellipsis" % [
				up.name, _rect(up.get_global_rect())]
		up = up.get_parent() as Control
	return ""


## Why the focusable `c` is out of reach, or "" when a pointer can hit it.
func _out_of_reach(c: Control, top: Node, view: Rect2) -> String:
	var r := c.get_global_rect()
	if not _scrolls_over_view(c, r, view):
		return "rect %s leaves the viewport %s" % [_rect(r), _rect(view)]
	var centre := r.get_center()
	var at: Node = c
	while at != top:
		var parent := at.get_parent()
		for i: int in range(at.get_index() + 1, parent.get_child_count()):
			var cover := parent.get_child(i) as Control
			if cover == null or not cover.is_visible_in_tree():
				continue
			if cover.mouse_filter == Control.MOUSE_FILTER_IGNORE:
				continue
			if cover.get_global_rect().has_point(centre):
				return "its centre is covered by %s %s" % [
					top.get_path_to(cover), _rect(cover.get_global_rect())]
		at = parent
	return ""


## The size `c`'s anchors and offsets ask for inside `parent`; a Control only
## grows past it when its minimum size forces it.
func _asked_size(c: Control, parent: Control) -> Vector2:
	return Vector2(
		(c.anchor_right - c.anchor_left) * parent.size.x + c.offset_right - c.offset_left,
		(c.anchor_bottom - c.anchor_top) * parent.size.y + c.offset_bottom - c.offset_top)


## True when `r` is inside `view`, or runs past it only along an axis an
## ancestor ScrollContainer of `c` scrolls.
func _scrolls_over_view(c: Control, r: Rect2, view: Rect2) -> bool:
	var out_x := r.position.x < view.position.x - SLACK or r.end.x > view.end.x + SLACK
	var out_y := r.position.y < view.position.y - SLACK or r.end.y > view.end.y + SLACK
	var up := c.get_parent() as Control
	while up != null and (out_x or out_y):
		var scroll := up as ScrollContainer
		if scroll != null:
			out_x = out_x and scroll.horizontal_scroll_mode == ScrollContainer.SCROLL_MODE_DISABLED
			out_y = out_y and scroll.vertical_scroll_mode == ScrollContainer.SCROLL_MODE_DISABLED
		up = up.get_parent() as Control
	return not out_x and not out_y


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


func _draw(vp: SubViewport, out: String) -> void:
	var image := vp.get_texture().get_image()
	if image == null or image.is_empty():
		_fail("no image to draw %s" % out)
		return
	var status := image.save_png(out)
	if status != OK:
		_fail("cannot save %s (error %d)" % [out, status])
		return
	print("FIT_SWEEP_PNG " + out)


## The drawing's file name: the scene's res:// path with "/" as "__", and the size.
func _png_name(scene: String, at: Vector2i) -> String:
	return "%s__%dx%d.png" % [scene.trim_prefix("res://").trim_suffix(".tscn").replace("/", "__"), at.x, at.y]


func _report(kind: String, where: String, path: String, why: String) -> void:
	_findings += 1
	print("  %s  %s : %s — %s" % [kind, where, path, why])


func _rect(r: Rect2) -> String:
	return "(%d, %d, %dx%d)" % [roundi(r.position.x), roundi(r.position.y), roundi(r.size.x), roundi(r.size.y)]


func _fail(reason: String) -> void:
	_failures += 1
	print("FIT_SWEEP_FAIL " + reason)
