class_name KitPanel
extends PanelContainer


func _ready() -> void:
	theme_type_variation = KitThemeKeys.PANEL
	add_theme_color_override(KitThemeKeys.FONT_COLOR, Color.WHITE)
