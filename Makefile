# This repo's own check. It runs no Godot: the session hook passes shellcheck and the game Makefile
# parses and expands. Whether check.gd and sheet.gd run is proven in a game, with `make check`.
.PHONY: check
check:
	shellcheck game/tools/session-start.sh
	$(MAKE) --no-print-directory -n -C game help import check sheet play editor >/dev/null
	@echo "CHECK PASS"
