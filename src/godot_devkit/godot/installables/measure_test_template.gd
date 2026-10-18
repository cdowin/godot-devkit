# Copy to test_<performance_case>.gd, mount the representative scene, then tune
# its budgets for the target device. These values illustrate a 60 FPS target.
extends GutTest

const SCENE_PATH := "res://scenes/performance_case.tscn"
const SAMPLE_FRAMES := 120
const FRAME_BUDGET_SECONDS := 1.0 / 60.0
const MAX_DRAW_CALLS := 1000.0
const MAX_OBJECTS := 10000.0
const CUSTOM_MONITOR: StringName = &""
const CUSTOM_MONITOR_BUDGET := 1000.0

func test_native_monitor_budgets() -> void:
	assert_true(ResourceLoader.exists(SCENE_PATH), "Set the representative workload scene")
	if not ResourceLoader.exists(SCENE_PATH):
		return
	add_child_autofree((load(SCENE_PATH) as PackedScene).instantiate())
	await wait_process_frames(2)
	var process_times: Array[float] = []
	var physics_times: Array[float] = []
	var peak_draw_calls := 0.0
	var peak_objects := 0.0
	var peak_custom := 0.0
	var orphan_baseline := Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT)
	if not CUSTOM_MONITOR.is_empty():
		assert_true(Performance.has_custom_monitor(CUSTOM_MONITOR))
		if not Performance.has_custom_monitor(CUSTOM_MONITOR):
			return
	for _frame in range(SAMPLE_FRAMES):
		await get_tree().process_frame
		process_times.append(Performance.get_monitor(Performance.TIME_PROCESS))
		physics_times.append(Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS))
		peak_draw_calls = maxf(peak_draw_calls, Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME))
		peak_objects = maxf(peak_objects, Performance.get_monitor(Performance.OBJECT_COUNT))
		if not CUSTOM_MONITOR.is_empty():
			peak_custom = maxf(peak_custom, float(Performance.get_custom_monitor(CUSTOM_MONITOR)))
	process_times.sort()
	physics_times.sort()
	var p95_index := ceili(SAMPLE_FRAMES * 0.95) - 1
	assert_lte(process_times[p95_index], FRAME_BUDGET_SECONDS, "process p95 seconds")
	assert_lte(physics_times[p95_index], FRAME_BUDGET_SECONDS, "physics p95 seconds")
	assert_lte(peak_draw_calls, MAX_DRAW_CALLS)
	assert_lte(peak_objects, MAX_OBJECTS)
	assert_lte(Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT), orphan_baseline)
	if not CUSTOM_MONITOR.is_empty():
		assert_lte(peak_custom, CUSTOM_MONITOR_BUDGET)
