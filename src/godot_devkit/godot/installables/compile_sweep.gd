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
## Run by parse.sh (stage 2) and warnings.sh over the whole project, and by
## spot.sh over a LIST — never invoke godot directly, the wrapper owns the
## user:// sandbox.
##
## With user arguments (`-- res://a.gd res://b.gd`) it compiles exactly those
## and walks nothing. Each argument is one script: one that is not a
## `res://….gd` path is a SWEEP_FAIL, never a reason to widen to the project.
##
## With GDK_SWEEP_MAIN_SCENE=1 in the environment and no user arguments, it
## then loads the project's main scene and adds it to the tree, after the
## result line. That is the one thing a `--quit` boot did that `-s` does not
## (autoloads boot under `-s` already), so parse.sh needs ONE engine run, not
## a boot and then a sweep (#49). A main scene that names a missing script, or
## whose _ready reports an error, prints the same engine lines the boot did.
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
const MAIN_SCENE_ENV := "GDK_SWEEP_MAIN_SCENE"
const MAIN_SCENE_SETTING := "application/run/main_scene"

## Directories skipped wholesale — project config, yours to edit after install.
## Hidden entries (.git/, .godot/, .headless-userdata/) are already excluded by
## DirAccess's default include_hidden=false, so only visible non-source trees
## need naming. `assets` and `locale` are the stock pair; a project whose art
## lives elsewhere renames them here.
const SKIPPED_DIRS: PackedStringArray = ["assets", "locale"]


func _initialize() -> void:
	var script_paths := PackedStringArray(OS.get_cmdline_user_args())
	var whole_project := script_paths.is_empty()
	if whole_project:
		script_paths = _collect_script_paths(ROOT_DIR)
	script_paths.sort()

	var failures := PackedStringArray()
	for path in script_paths:
		if not _is_script_path(path) or not _compiles(path):
			failures.append(path)

	for path in failures:
		print(FAIL_PREFIX, path)
	print(RESULT_PREFIX, script_paths.size() - failures.size(), " ", script_paths.size())

	if whole_project and OS.get_environment(MAIN_SCENE_ENV) == "1":
		_boot_main_scene()

	quit(EXIT_FAIL if not failures.is_empty() else 0)


## Load the main scene and add it to the tree, as a `--quit` boot does, so its
## load errors and its _ready run land in this transcript. No main scene set is
## no main scene to boot, the same as a `--quit` boot.
func _boot_main_scene() -> void:
	var main_scene: String = ProjectSettings.get_setting(MAIN_SCENE_SETTING, "")
	if main_scene.is_empty():
		return
	var packed := ResourceLoader.load(main_scene) as PackedScene
	if packed == null:
		return
	var instance := packed.instantiate()
	if instance != null:
		root.add_child(instance)


## True when [param path] names a script under the project root.
func _is_script_path(path: String) -> bool:
	return path.begins_with(ROOT_DIR) and path.ends_with(SCRIPT_SUFFIX)


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
