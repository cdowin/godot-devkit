# This project's commands. They call Godot directly. Every target but play and editor runs Godot
# under a throwaway HOME, so a headless run never reads or writes the user:// data of the person at
# this machine: the engine keeps user:// under HOME and has no flag for a per-run one.
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
GODOT ?= godot
DIRS ?= .
OUT ?= .sheet
SANDBOX = h=$$(mktemp -d) && trap 'rm -rf "$$h"' EXIT && export HOME=$$h XDG_DATA_HOME=$$h/data XDG_CONFIG_HOME=$$h/config XDG_CACHE_HOME=$$h/cache &&
# `--headless` draws nothing, so sheet opens a window: a virtual display on Linux with none,
# else parked off screen, and no sound device (`--headless` already has none).
WINDOW = $(if $(and $(filter Linux,$(shell uname -s)),$(if $(DISPLAY)$(WAYLAND_DISPLAY),,1)),xvfb-run -a -s "-screen 0 1280x1024x24" $(GODOT) --rendering-driver opengl3,$(GODOT)) --audio-driver Dummy --position 100000,100000 --resolution 64x64
ERROR_RE := ^(SCRIPT |SHADER |USER |USER SCRIPT )?ERROR:
# The engine reports objects alive at exit; they are worth reading, not a failed check.
LEAK_RE := still in use at exit|leaked at exit

.PHONY: help import check sheet script play editor
help:
	@awk -F ':.*## ' '/^[a-z-]+:.*## / { name[++n] = $$1; what[n] = $$2; if (length($$1) > w) w = length($$1) } \
		END { for (i = 1; i <= n; i++) printf "make %-" w "s  %s\n", name[i], what[i] }' $(MAKEFILE_LIST)

# The engine's caches trail its first import of a fresh checkout, or one after a file moved: that
# pass logs errors for loaders and paths it has not registered yet. A second pass is judged then.
# The engine does not retry a file that failed to import, so that failure fails from either pass.
import: ## the engine's import (it skips what has not changed); any engine error fails it
	@mkdir -p .godot
	@$(SANDBOX) refused=; for pass in 1 2; do \
		{ $(GODOT) --headless --path . --import 2>&1 || echo "engine exit $$?"; } > .godot/import.log; \
		refused=$$refused$$(grep -a 'Error importing' .godot/import.log || true); \
		errors=$$(grep -aE '$(ERROR_RE)|^engine exit' .godot/import.log | grep -avE '$(LEAK_RE)' || true); \
		[ -n "$$errors" ] || break; \
	done; \
	if [ -n "$$errors$$refused" ]; then printf '%s\n' "$$refused" "$$errors" | grep .; \
		echo "IMPORT FAIL (log: .godot/import.log)"; exit 1; fi

# check.gd names the file behind each error it sees; this also fails on an engine error printed
# outside its walk, such as an autoload's or one at shutdown.
check: import ## every file loads and every scene runs a frame in the tree (a part, inside its hosts), with zero engine errors
	@$(SANDBOX) { $(GODOT) --headless --path . -s res://tools/check.gd 2>&1 || echo "engine exit $$?"; } > .godot/check.log
	@grep -aE '^(FAIL|PART|parts|checked|engine exit)' .godot/check.log || true
	@grep -aE '$(LEAK_RE)' .godot/check.log | sed 's/^/LEAK /' || true
	@if grep -aE '$(ERROR_RE)' .godot/check.log | grep -avE '$(LEAK_RE)' | sed 's/^/FAIL engine /' | grep . \
		|| grep -aqE '^(FAIL|engine exit)' .godot/check.log || ! grep -aqE '^checked [0-9]+ files, 0 failed' .godot/check.log; \
		then echo "CHECK FAIL (log: .godot/check.log)"; exit 1; fi; echo "CHECK PASS"

# The .gdignore keeps the engine from importing the pages when OUT is inside the project.
sheet: import ## every scene under DIRS on one contact-sheet page per folder, in OUT
	@rm -rf $(OUT) && mkdir -p $(OUT) && touch $(OUT)/.gdignore
	@$(SANDBOX) $(WINDOW) --path . -s res://tools/sheet.gd -- "$(abspath $(OUT))" $(DIRS)

script: import ## run one scratch SceneTree script headless, off the real user data: make script S=build/try.gd
	@$(SANDBOX) $(GODOT) --headless --path . -s "$(S)"

play: ## run the game (a window, the real user data)
	@$(GODOT) --path .

editor: ## open the editor (a window, the real user data)
	@$(GODOT) --editor --path .

# This game's own targets go below this line, with their own .PHONY line. Run each headless one
# under $(SANDBOX); `make help` lists any target with a `## ` description.
