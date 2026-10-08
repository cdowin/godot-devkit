extends Node

var dialog := FileDialog.new()


func _ready() -> void:
	dialog.add_filter("*.png ; PNG Images")
	dialog.add_filter("*.jpg", "JPEG Images")
	dialog.add_filter("*.raw")
	dialog.filters = ["*.gd;GDScript Files", "*.cfg"]
	dialog.set_filters(PackedStringArray(["*.txt ; Text Files"]))
	tr("Open")  # TRANSLATORS: Opens the file picker.
	# TRANSLATORS: A save prompt.
	# It spans two lines.
	tr("Open", "menu")
	tr("Hidden")  # NO_TRANSLATE
	# NO_TRANSLATE: a debug label.
	tr("Debug only")
	tr_n("One apple", "%d apple(s)", 1)
	tr("Welcome")  # TRANSLATORS: Shown on the title screen.
	tr("Welcome")  # TRANSLATORS: Shown again after a reload.
