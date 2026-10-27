extends SceneTree
## Render — draw one 2D scene, or every scene in one folder as a labeled
## contact sheet, to a PNG. A person reviews a room, or fifty, without
## opening the editor or the game.
##
## Run by render.sh — never invoke godot directly: the wrapper owns the
## user:// sandbox, the bound and the window. It needs a real renderer (a
## window, which the wrapper parks off screen); `--headless` draws nothing.
##
## Arguments (after `--`):
##   --scene res://x.tscn --out /abs/x.png [--rect X,Y,W,H]
##   --sheet res://dir --out /abs/sheet.png
## With no --rect, the frame is the union of every TileMapLayer's used cells,
## Sprite2D and Control in the scene (the default window size when it has
## none). A frame wider than MAX_SIDE is scaled down to fit, and says so.
## The sheet takes the folder's own .tscn files, sorted, not its subfolders.
##
## Output contract (the wrapper greps these; the exit code is advisory):
##   RENDER_SCENE <res://path> <w>x<h> scale=<s>   one per scene drawn
##   RENDER_FAIL <reason>                          one per failure
##   RENDER_RESULT <drawn> <total> <out>           last, when a PNG was saved

const MAX_SIDE := 4096
const DEFAULT_SIZE := Vector2i(1152, 648)
const THUMB := 256
const PAD := 8
const SCENE_SUFFIX := ".tscn"
const BACKGROUND := Color(0.12, 0.12, 0.14)
const LABEL_COLOR := Color(0.9, 0.9, 0.9)

var _failures := 0
var _drawn := 0


func _initialize() -> void:
	_run.call_deferred()


func _run() -> void:
	var args := _parse(OS.get_cmdline_user_args())
	if args.is_empty():
		quit(2)
		return
	var total := 1
	if args.has("sheet"):
		total = await _sheet(args["sheet"], args["out"])
	else:
		var image: Image = await _draw(args["scene"], args.get("rect", Rect2i()))
		if image != null:
			_save(image, args["out"], total)
	quit(1 if _failures > 0 else 0)


func _parse(tokens: PackedStringArray) -> Dictionary:
	var args := {}
	var i := 0
	while i < tokens.size():
		var key := tokens[i]
		if i + 1 >= tokens.size() or key not in ["--scene", "--sheet", "--out", "--rect"]:
			_fail("usage: --scene res://x.tscn | --sheet res://dir, --out /abs.png, [--rect X,Y,W,H]")
			return {}
		args[key.trim_prefix("--")] = tokens[i + 1]
		i += 2
	if not args.has("out") or args.has("scene") == args.has("sheet"):
		_fail("need --out and exactly one of --scene or --sheet")
		return {}
	if args.has("rect"):
		var parts := String(args["rect"]).split(",")
		if parts.size() != 4 or args.has("sheet"):
			_fail("--rect is X,Y,W,H, and only with --scene")
			return {}
		args["rect"] = Rect2i(parts[0].to_int(), parts[1].to_int(), parts[2].to_int(), parts[3].to_int())
	return args


func _draw(scene_path: String, rect: Rect2i) -> Image:
	var packed := load(scene_path) as PackedScene
	if packed == null:
		_fail("%s does not load as a PackedScene" % scene_path)
		return null
	var node := packed.instantiate()
	var viewport := _viewport()
	viewport.add_child(node)
	await process_frame
	var area := Rect2(rect) if rect.has_area() else _bounds(node)
	var scale := minf(1.0, float(MAX_SIDE) / maxf(area.size.x, area.size.y))
	viewport.size = Vector2i((area.size * scale).ceil())
	viewport.canvas_transform = Transform2D(0.0, Vector2(scale, scale), 0.0, -area.position * scale)
	var image := await _grab(viewport)
	viewport.queue_free()
	if image == null or image.is_empty():
		_fail("%s drew no image" % scene_path)
		return null
	_drawn += 1
	var size := image.get_size()
	print("RENDER_SCENE %s %dx%d scale=%s" % [scene_path, size.x, size.y, scale])
	return image


func _sheet(dir_path: String, out: String) -> int:
	var paths := _scenes_in(dir_path)
	if paths.is_empty():
		_fail("no %s files in %s" % [SCENE_SUFFIX, dir_path])
		return 0
	var grid := GridContainer.new()
	grid.columns = int(ceil(sqrt(paths.size())))
	grid.add_theme_constant_override("h_separation", PAD)
	grid.add_theme_constant_override("v_separation", PAD)
	grid.position = Vector2(PAD, PAD)
	for path in paths:
		var image: Image = await _draw(path, Rect2i())
		grid.add_child(_tile(path, image))
	var viewport := _viewport()
	var backdrop := ColorRect.new()
	backdrop.color = BACKGROUND
	viewport.add_child(backdrop)
	viewport.add_child(grid)
	await process_frame
	var size := Vector2i(grid.get_combined_minimum_size().ceil()) + Vector2i(PAD * 2, PAD * 2)
	viewport.size = size
	backdrop.size = size
	var sheet := await _grab(viewport)
	viewport.queue_free()
	if sheet == null or sheet.is_empty():
		_fail("the contact sheet drew no image")
	else:
		_save(sheet, out, paths.size())
	return paths.size()


func _tile(path: String, image: Image) -> Control:
	var cell := VBoxContainer.new()
	var picture := TextureRect.new()
	picture.custom_minimum_size = Vector2(THUMB, THUMB)
	picture.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	picture.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	if image != null:
		picture.texture = ImageTexture.create_from_image(image)
	var label := Label.new()
	label.text = path.get_file().get_basename() + ("" if image != null else "  (FAILED)")
	label.custom_minimum_size = Vector2(THUMB, 0)
	label.clip_text = true
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.add_theme_color_override("font_color", LABEL_COLOR)
	cell.add_child(picture)
	cell.add_child(label)
	return cell


func _viewport() -> SubViewport:
	var viewport := SubViewport.new()
	viewport.size = DEFAULT_SIZE
	viewport.transparent_bg = false
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(viewport)
	return viewport


func _grab(viewport: SubViewport) -> Image:
	await process_frame
	await RenderingServer.frame_post_draw
	return viewport.get_texture().get_image()


func _bounds(node: Node) -> Rect2:
	var area := Rect2()
	var found := false
	for item in [node] + node.find_children("*", "", true, false):
		var piece := _extent(item)
		if piece.has_area():
			area = piece if not found else area.merge(piece)
			found = true
	return area if found else Rect2(Vector2.ZERO, DEFAULT_SIZE)


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


func _scenes_in(dir_path: String) -> PackedStringArray:
	var found := PackedStringArray()
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return found
	for file in dir.get_files():
		if file.ends_with(SCENE_SUFFIX):
			found.append(dir_path.trim_suffix("/") + "/" + file)
	found.sort()
	return found


func _save(image: Image, out: String, total: int) -> void:
	var err := image.save_png(out)
	if err != OK:
		_fail("cannot write %s (error %d)" % [out, err])
		return
	print("RENDER_RESULT %d %d %s" % [_drawn, total, out])


func _fail(reason: String) -> void:
	_failures += 1
	print("RENDER_FAIL " + reason)
