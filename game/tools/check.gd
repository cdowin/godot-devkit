extends SceneTree
## `make check`: loads every script, scene, resource, shader and JSON file outside addons/ and names
## each one the engine refuses. Scripts load first, so a script that does not compile is blamed on
## itself and not on the first scene that uses it; it must compile with the project's warning
## levels. A scene is added to the tree for a frame, so _ready, @onready and %Name reads run, and
## then freed. A scene or resource whose ext_resource path is not the file its uid names fails:
## the engine would load the uid's file and say nothing. Any engine error, or a warning about a
## uid or a missing path, is blamed on the file being checked: deferred work is flushed before the
## next file starts. Prints `FAIL <path>: <why>` per problem and ends `checked N files, M failed`.

const KINDS: PackedStringArray = ["gd", "tscn", "tres", "gdshader", "json"]
const SKIPPED: PackedStringArray = ["res://addons"]

var _errors := ErrorTap.new()
var _ext_resource := RegEx.create_from_string('\\[ext_resource [^\\]]*uid="([^"]+)" path="([^"]+)"')


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


func _initialize() -> void:
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
	var failed := 0
	for path in paths:
		var problems := await _check(path)
		await process_frame
		problems.append_array(_errors.take())
		for problem in problems:
			print("FAIL %s: %s" % [path, problem])
		failed += 1 if problems else 0
	print("checked %d files, %d failed" % [paths.size(), failed])
	quit(1 if failed else 0)


func _check(path: String) -> PackedStringArray:
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
	var script := loaded as Script
	if script != null and not script.is_abstract() and not script.can_instantiate():
		return ["does not compile"]
	if loaded is Shader:
		(loaded as Shader).get_shader_uniform_list()
	if loaded is PackedScene:
		var node := (loaded as PackedScene).instantiate()
		if node == null:
			return ["does not instantiate"]
		root.add_child(node)
		await process_frame
		if is_instance_valid(node):
			node.queue_free()
	return []


func _mismatched_references(path: String) -> PackedStringArray:
	var problems := PackedStringArray()
	for found in _ext_resource.search_all(FileAccess.get_file_as_string(path)):
		var id := ResourceUID.text_to_id(found.get_string(1))
		var by_uid := ResourceUID.get_id_path(id) if ResourceUID.has_id(id) else "nothing"
		if by_uid != found.get_string(2):
			problems.append("ext_resource path %s, but %s is %s" % [found.get_string(2), found.get_string(1), by_uid])
	return problems
