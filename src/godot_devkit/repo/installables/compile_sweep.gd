extends SceneTree
## Compile sweep — load EVERY .gd in the project and report which ones the
## engine refuses to compile.
##
## Why this exists: GDScript compiles LAZILY. A plain headless boot only
## compiles what the boot graph reaches (autoloads, the main scene, and
## transitive preload/class_name references), so a parse error in anything
## unreachable — tests/**, @tool/editor scripts, non-autoloaded addons,
## anything only load()ed by string path — is invisible to a boot log. This
## sweep makes the claim "every .gd in the repo compiles" checkable instead of
## assumed; a consumer shipped a broken integration scenario through a green
## parse gate for exactly this reason.
##
## Run by parse.sh (stage 2) — never invoke godot directly, the wrapper owns
## the user:// sandbox.
##
## Output contract (the wrapper greps these; the exit code is advisory):
##   SWEEP_FAIL <res://path.gd>      one per script that would not compile
##   SWEEP_RESULT <compiled> <total>

const SCRIPT_SUFFIX := ".gd"
const SCRIPT_TYPE_HINT := "Script"
const ROOT_DIR := "res://"
const FAIL_PREFIX := "SWEEP_FAIL "
const RESULT_PREFIX := "SWEEP_RESULT "
const EXIT_FAIL := 1

## Directories skipped wholesale — project config, yours to edit after install.
## Hidden entries (.git/, .godot/, .headless-userdata/) are already excluded by
## DirAccess's default include_hidden=false, so only visible non-source trees
## need naming. `assets` and `locale` are the stock pair; a project whose art
## lives elsewhere renames them here.
const SKIPPED_DIRS: PackedStringArray = ["assets", "locale"]


func _initialize() -> void:
	var script_paths := _collect_script_paths(ROOT_DIR)
	script_paths.sort()

	var failures := PackedStringArray()
	for path in script_paths:
		if not _compiles(path):
			failures.append(path)

	for path in failures:
		print(FAIL_PREFIX, path)
	print(RESULT_PREFIX, script_paths.size() - failures.size(), " ", script_paths.size())

	quit(EXIT_FAIL if not failures.is_empty() else 0)


## True when the engine can fully compile the script at [param path].
##
## `loaded == null` is NOT sufficient: GDScript's resource loader deliberately
## returns a half-built script object when parse/analyze fails, so the editor
## can still offer autocompletion on broken source. The load-failed signal that
## survives that is [method Script.can_instantiate] — it mirrors the script's
## internal `valid` flag, which is only set by a successful compile. Verified
## against a deliberate probe: a script calling an undeclared function loads
## non-null with can_instantiate() == false.
func _compiles(path: String) -> bool:
	var loaded := ResourceLoader.load(path, SCRIPT_TYPE_HINT, ResourceLoader.CACHE_MODE_REUSE)
	if loaded == null:
		return false
	var script_resource := loaded as Script
	if script_resource == null:
		return false
	return script_resource.can_instantiate()


func _collect_script_paths(dir_path: String) -> PackedStringArray:
	var found := PackedStringArray()
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return found
	dir.list_dir_begin()
	var entry := dir.get_next()
	while entry != "":
		var entry_path := dir_path.path_join(entry)
		if dir.current_is_dir():
			if not SKIPPED_DIRS.has(entry):
				found.append_array(_collect_script_paths(entry_path))
		elif entry.ends_with(SCRIPT_SUFFIX):
			found.append(entry_path)
		entry = dir.get_next()
	dir.list_dir_end()
	return found
