extends "res://shared/base_panel.gd"

const Labels = preload("res://shared/labels.gd")
const LOCAL := "Play"
const PREFIX := "New "
const ITEMS := ["Easy", "Hard"]
const NEVER_WALKED := "A const initializer is never walked"

@export_enum("Annotation", "Arguments") var mode: int = 0

var text := ""
var title_label := Label.new()
var greeting := tr("Welcome")

var status: String = "":
	get:
		return tr("Getter")
	set(value):
		status = tr("Setter")


func _ready() -> void:
	tr(LOCAL)
	tr(TITLE)
	tr(Labels.SAVE)
	tr(FixtureLabels.SAVE)
	tr(Strings.QUIT)
	tr(PREFIX + "game")
	tr(Labels.GREETING_FORMAT % "friend")
	tr(ITEMS[1])
	tr(FixtureLabels.CAPTIONS[FixtureLabels.Kind.SHIELD])
	tr(&"Name")
	tr("Open", "menu")
	tr("Open")
	tr_n("One apple", "%d apples", 3)
	atr("Accessible")
	atr_n("One file", "%d files", 2, "disk")
	tr("")
	var local_text := "Run"
	tr(local_text)
	const INNER := "Local const"
	tr(INNER)
	tr("Context is a variable", local_text)
	title_label.text = "Title text"
	title_label.tooltip_text = "Tooltip"
	title_label.name = "Name is no pattern"
	text = "Bare name"
	var props := {}
	props["placeholder_text"] = "Subscript"
	title_label.text += " more"
	title_label.set_text("Set text")
	var popup := PopupMenu.new()
	popup.add_item("Item")
	popup.add_separator("Separator")
	popup.set_item_text(0, "Renamed")
	popup.add_icon_item(null, "Icon item")
	match local_text:
		"A match pattern":
			pass
		_ when local_text == tr("Guard"):
			pass
	var later := func() -> String: return tr("Lambda")
	later.call()
	tr("Quote \" and backslash \\ and\ttab")
	tr("Line one\nLine two")
	tr("Trailing newline\n")


func pick(choice: String = tr("Default")) -> String:
	return choice


class Inner:
	func caption() -> String:
		return tr(LOCAL + "!")
