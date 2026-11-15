extends SceneTree
## `make check`: loads every script, scene, resource, shader and JSON file outside addons/ and names
## each one the engine refuses. Scripts load first, so a script that does not compile is blamed on
## itself and not on the first scene that uses it; it must compile with the project's warning
## levels. A scene is added to the tree for a frame, so _ready, @onready and %Name reads run, and
## then freed with anything it left at the root; every scene instanced in it that says what it needs
## (`_get_configuration_warnings()` on its root) must need nothing. A scene whose root says, as
## instanced alone, that it needs a host is a part: it is loaded but not run alone, and is judged
## inside the scenes that host it. A scene or resource whose ext_resource path is not the file its
## uid names fails: the engine would load the uid's file and say nothing. Any engine error, or a
## warning about a uid or a missing path, is blamed on the file being checked: deferred work is
## flushed before the next file starts. Prints `FAIL <path>: <why>` per problem, the parts count,
## `PART <path>: ...` for a part that no scene hosts and no script names, and ends
## `checked N files, M failed`.

const KINDS: PackedStringArray = ["gd", "tscn", "tres", "gdshader", "gdshaderinc", "json"]
const SKIPPED: PackedStringArray = ["res://addons"]
const NEEDS := &"_get_configuration_warnings"

## Whether each script says what its node needs, so a scene's nodes are asked without listing
## methods again.
static var _says_needs: Dictionary[Script, bool] = {}

var _errors := ErrorTap.new()
var _ext_resource := RegEx.create_from_string('\\[ext_resource [^\\]]*uid="([^"]+)" path="([^"]+)"')
## Each part, with what it says it needs when alone.
var _parts: Dictionary[String, PackedStringArray] = {}
## Every file a scene or resource names, so a part with no host is found.
var _named: Dictionary[String, bool] = {}


class ErrorTap extends Logger:
	var lines := PackedStringArray()
	var _mutex := Mutex.new()

	func _log_error(function: String, file: String, line: int, code: String, rationale: String,
			_editor_notify: bool, error_type: int, _backtraces: Array[ScriptBacktrace]) -> void:
		var text := rationale if rationale else code
		if error_type == ERROR_TYPE_WARNING and not _is_resource_mismatch(text):
			return
		_add("%s (%s:%d %s)" % [text, file, line, function])

	func _log_message(message: String, error: bool) -> void:
		# ERROR:, WARNING: and their "at:" lines arrive through _log_error as well.
		if error and not message.begins_with("ERROR:") and not message.begins_with("WARNING:") \
				and not message.begins_with("   at:"):
			_add(message.strip_edges())

	func take() -> PackedStringArray:
		_mutex.lock()
		var taken := lines
		lines = PackedStringArray()
		_mutex.unlock()
		return taken

	func _add(text: String) -> void:
		_mutex.lock()
		lines.append(text)
		_mutex.unlock()

	static func _is_resource_mismatch(text: String) -> bool:
		var lower := text.to_lower()
		return lower.contains("uid") or lower.contains("text path") or lower.contains("not found")


## Every file under dir_path with one of the extensions, skipping addons/, hidden folders and any
## folder that holds a .gdignore. sheet.gd walks the same tree.
static func files_under(dir_path: String, kinds: PackedStringArray) -> PackedStringArray:
	var found := PackedStringArray()
	if SKIPPED.has(dir_path) or FileAccess.file_exists(dir_path.path_join(".gdignore")):
		return found
	for sub in DirAccess.get_directories_at(dir_path):
		if not sub.begins_with("."):
			found.append_array(files_under(dir_path.path_join(sub), kinds))
	for file in DirAccess.get_files_at(dir_path):
		if kinds.has(file.get_extension()):
			found.append(dir_path.path_join(file))
	return found


## What `node` says it needs and lacks, through its script's `_get_configuration_warnings()`. The
## engine asks only a tool script in the editor; any script answers when called.
## `Script.has_method()` does not see that method on a script, so its method list is read.
static func unmet_needs(node: Node) -> PackedStringArray:
	var script: Script = node.get_script()
	if script == null:
		return PackedStringArray()
	if not _says_needs.has(script):
		_says_needs[script] = script.get_script_method_list().any(
			func(method: Dictionary) -> bool: return method.name == NEEDS)
	if not _says_needs[script]:
		return PackedStringArray()
	var needs: PackedStringArray = node.call(NEEDS)
	return needs


func _initialize() -> void:
	# With no window that can draw, the engine sleeps this long every frame; the check passes
	# thousands of frames.
	OS.low_processor_usage_mode_sleep_usec = 0
	OS.add_logger(_errors)
	_run.call_deferred()


func _run() -> void:
	var found := files_under("res://", KINDS)
	found.sort()
	var paths := PackedStringArray()
	for path in found:
		if path.get_extension() == "gd":
			paths.append(path)
	for path in found:
		if path.get_extension() != "gd":
			paths.append(path)
	var resident := root.get_children()
	# Holding each loaded file keeps its dependencies in the cache, so the next file does not load
	# them again.
	var kept: Array[Resource] = []
	var failed := 0
	for path in paths:
		var problems := await _check(path, kept, resident)
		await process_frame
		problems.append_array(_errors.take())
		for problem in problems:
			print("FAIL %s: %s" % [path, problem])
		failed += 1 if problems else 0
	kept.clear()
	print("parts: %d scenes need a host and were judged inside their hosts" % _parts.size())
	for part: String in _unhosted(paths):
		print("PART %s: no scene hosts it and no script names it (%s)" % [part, _parts[part][0]])
	print("checked %d files, %d failed" % [paths.size(), failed])
	quit(1 if failed else 0)


func _check(path: String, kept: Array[Resource], resident: Array[Node]) -> PackedStringArray:
	if path.get_extension() == "json":
		var json := JSON.new()
		if json.parse(FileAccess.get_file_as_string(path)) != OK:
			return ["line %d: %s" % [json.get_error_line(), json.get_error_message()]]
		return []
	if path.get_extension() in ["tscn", "tres"]:
		var mismatched := _mismatched_references(path)
		if mismatched:
			return mismatched
	var loaded := ResourceLoader.load(path)
	if loaded == null:
		return ["does not load"]
	kept.append(loaded)
	var script := loaded as Script
	if script != null and not script.is_abstract() and not script.can_instantiate():
		return ["does not compile"]
	# Loading a shader does not compile it; giving it to a material does, and reports its errors.
	if loaded is Shader:
		ShaderMaterial.new().shader = loaded as Shader
	if loaded is PackedScene:
		return await _stand(path, loaded as PackedScene, resident)
	return []


## Adds the scene to the tree for a frame, unless it is a part; then every scene it hosts must
## have what it needs.
func _stand(path: String, packed: PackedScene, resident: Array[Node]) -> PackedStringArray:
	var node := packed.instantiate()
	if node == null:
		return ["does not instantiate"]
	var alone := unmet_needs(node)
	if alone:
		_parts[path] = alone
		node.free()
		return []
	root.add_child(node)
	await process_frame
	var problems := PackedStringArray()
	if is_instance_valid(node):
		# Each scene it hosts must have what that scene says it needs.
		for item in node.find_children("*", "", true, false):
			if item.scene_file_path:
				for need in unmet_needs(item):
					problems.append("%s (%s): %s" % [node.get_path_to(item), item.scene_file_path, need])
	# A scene may leave nodes beside itself at the root (a popup, a spawned effect); they go with
	# it.
	for left in root.get_children():
		if left not in resident:
			left.queue_free()
	return problems


func _mismatched_references(path: String) -> PackedStringArray:
	var problems := PackedStringArray()
	for found in _ext_resource.search_all(FileAccess.get_file_as_string(path)):
		_named[found.get_string(2)] = true
		var id := ResourceUID.text_to_id(found.get_string(1))
		var by_uid := ResourceUID.get_id_path(id) if ResourceUID.has_id(id) else "nothing"
		if by_uid != found.get_string(2):
			problems.append("ext_resource path %s, but %s is %s" % [found.get_string(2), found.get_string(1), by_uid])
	return problems


## The parts that no scene or resource names and no script names by path or uid.
func _unhosted(paths: PackedStringArray) -> PackedStringArray:
	var left := PackedStringArray()
	for part: String in _parts:
		if not _named.has(part):
			left.append(part)
	if left.is_empty():
		return left
	var code := PackedStringArray()
	for path in paths:
		if path.get_extension() == "gd":
			code.append(FileAccess.get_file_as_string(path))
	var source := "\n".join(code)
	var unhosted := PackedStringArray()
	for part in left:
		var uid := ResourceUID.id_to_text(ResourceLoader.get_resource_uid(part))
		if not source.contains(part) and not source.contains(uid):
			unhosted.append(part)
	return unhosted
