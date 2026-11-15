extends SceneTree
## `make sheet`: draws every scene under the given folders onto one labeled contact-sheet page per
## folder, <out>/<folder>.png, at the project's viewport size, cropped to what the scene draws.
## Prints one `SHEET <png> (N scenes)` line per page and `FAIL <path>: <why>` for a scene that
## raised an engine error while it was drawn; then it exits 1. It needs a real renderer:
## `--headless` draws nothing. Arguments after `--`: the output directory, then the folders.

const Check := preload("res://tools/check.gd")
const THUMB := 256
const PAD := 8
const MAX_SIDE := 4096 ## A larger scene, such as a whole map, is scaled down to fit.
const BACKGROUND := Color(0.12, 0.12, 0.12)
const LABEL_COLOR := Color(0.9, 0.9, 0.9)

var _errors := Check.ErrorTap.new()
var _size := Vector2i.ZERO


func _initialize() -> void:
	var width: int = ProjectSettings.get_setting("display/window/size/viewport_width")
	var height: int = ProjectSettings.get_setting("display/window/size/viewport_height")
	_size = Vector2i(width, height)
	OS.add_logger(_errors)
	_run.call_deferred()


func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() < 2:
		print("FAIL usage: -- <output dir> <folder>...")
		quit(2)
		return
	var out_dir := args[0]
	var by_folder: Dictionary[String, Array] = {}
	for dir in args.slice(1):
		for path in Check.files_under(_res_path(dir), ["tscn"]):
			var folder := path.get_base_dir()
			if not by_folder.has(folder):
				by_folder[folder] = []
			by_folder[folder].append(path)
	var folders := by_folder.keys()
	folders.sort()
	var failed := 0
	for folder: String in folders:
		var paths := by_folder[folder]
		paths.sort()
		failed += await _page(folder, paths, out_dir)
	print("sheet: %d pages in %s, %d failed" % [folders.size(), out_dir, failed])
	quit(1 if failed else 0)


func _page(folder: String, paths: Array, out_dir: String) -> int:
	var failed := 0
	var grid := GridContainer.new()
	grid.columns = ceili(sqrt(paths.size()))
	grid.position = Vector2(PAD, PAD)
	grid.add_theme_constant_override("h_separation", PAD)
	grid.add_theme_constant_override("v_separation", PAD)
	for path: String in paths:
		var image := await _draw(path)
		await process_frame
		var problems := _errors.take()
		for problem in problems:
			print("FAIL %s: %s" % [path, problem])
		failed += 1 if problems else 0
		grid.add_child(_tile(path, image))
	var viewport := _viewport(Vector2i.ONE)
	var backdrop := ColorRect.new()
	backdrop.color = BACKGROUND
	viewport.add_child(backdrop)
	viewport.add_child(grid)
	await process_frame
	viewport.size = Vector2i(grid.get_combined_minimum_size().ceil()) + Vector2i(PAD, PAD) * 2
	backdrop.size = viewport.size
	var sheet := await _grab(viewport)
	viewport.free()
	var name := folder.trim_prefix("res://").replace("/", "_")
	var out := out_dir.path_join((name if name else "root") + ".png")
	if sheet == null or sheet.is_empty() or sheet.save_png(out) != OK:
		print("FAIL %s: the page did not save" % out)
		return failed + 1
	print("SHEET %s (%d scenes)" % [out, paths.size()])
	return failed


func _draw(path: String) -> Image:
	var packed := load(path) as PackedScene
	var node: Node = packed.instantiate() if packed != null else null
	if node == null:
		return null
	var viewport := _viewport(_size)
	viewport.add_child(node)
	# Containers settle their layout over a few frames.
	for _frame in 4:
		await process_frame
	# A scene that frees itself as it plays out (a one-shot effect) leaves the viewport's own size.
	var area := _bounds(node) if is_instance_valid(node) else Rect2(Vector2.ZERO, _size)
	var scale := minf(1.0, float(MAX_SIDE) / maxf(area.size.x, area.size.y))
	viewport.size = Vector2i((area.size * scale).ceil())
	viewport.canvas_transform = Transform2D(0.0, Vector2(scale, scale), 0.0, -area.position * scale)
	var image := await _grab(viewport)
	viewport.free()
	return image


func _tile(path: String, image: Image) -> Control:
	var cell := VBoxContainer.new()
	var picture := TextureRect.new()
	picture.custom_minimum_size = Vector2(THUMB, THUMB)
	picture.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	picture.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	if image != null and not image.is_empty():
		picture.texture = ImageTexture.create_from_image(image)
	var label := Label.new()
	label.text = path.get_file().get_basename() + ("" if picture.texture else "  (FAILED)")
	label.custom_minimum_size = Vector2(THUMB, 0)
	label.clip_text = true
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.add_theme_color_override("font_color", LABEL_COLOR)
	cell.add_child(picture)
	cell.add_child(label)
	return cell


func _viewport(size: Vector2i) -> SubViewport:
	var viewport := SubViewport.new()
	viewport.size = size
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(viewport)
	return viewport


func _grab(viewport: SubViewport) -> Image:
	await process_frame
	await RenderingServer.frame_post_draw
	return viewport.get_texture().get_image()


func _bounds(node: Node) -> Rect2:
	var area := Rect2()
	var nodes: Array[Node] = [node]
	nodes.append_array(node.find_children("*", "", true, false))
	for item: Node in nodes:
		var piece := _extent(item)
		if piece.has_area():
			area = piece if not area.has_area() else area.merge(piece)
	return area if area.has_area() else Rect2(Vector2.ZERO, _size)


func _extent(item: Node) -> Rect2:
	var layer := item as TileMapLayer
	if layer != null and layer.tile_set != null:
		var used := layer.get_used_rect()
		if not used.has_area():
			return Rect2()
		var half := Vector2(layer.tile_set.tile_size) / 2.0
		var first := layer.map_to_local(used.position) - half
		var last := layer.map_to_local(used.end - Vector2i.ONE) + half
		return layer.get_global_transform() * Rect2(first, last - first)
	var sprite := item as Sprite2D
	if sprite != null and sprite.texture != null:
		return sprite.get_global_transform() * sprite.get_rect()
	var control := item as Control
	if control != null:
		return control.get_global_rect()
	return Rect2()


static func _res_path(dir: String) -> String:
	var relative := dir.trim_prefix("res://").trim_prefix("./").trim_suffix("/")
	return "res://" if relative in ["", "."] else "res://" + relative
