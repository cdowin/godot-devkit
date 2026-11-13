# Modal dialog

## Purpose

Ask the player to confirm, choose or fill in something before play or navigation continues.

## Regions

Title, body (scrolls if long), and one action bar. The action bar is the dialog action area.
It is a sticky footer: pinned outside the scroll, always visible.

## What may move and what may not

- Order is fixed: Cancel on the left, the primary action on the right, a destructive action apart
  on the far left. This is positional consistency: players build spatial memory for where
  "no" and "yes" sit, so the same role is in the same place in every dialog.
- Action buttons are never inside the body scroll. The body may grow up to a maximum height,
  then scrolls; the bar does not move.
- Buttons keep a fixed height and a minimum width when labels change.

## Overflow policy

Body text scrolls in its own `ScrollContainer`. Keep button labels short; never wrap the bar.

## Focus and input

- On open, focus the safest action (usually Cancel; the primary for a harmless confirm). Never
  focus a destructive action first.
- `ui_cancel` presses Cancel. `ui_accept` presses the focused button. Focus stays inside the dialog.
- Show a visible focus and device-matched prompts. Close returns focus to the opener.
- Godot's `gui/common/swap_cancel_ok` flips the OK/Cancel order of native dialogs per platform.
  A project should fix the order itself in its own bar and not depend on that setting.

## Reference ActionBar

The bar is an authored scene, `action_bar.tscn`; the order is in the file, not in code:

```
ActionBar (HBoxContainer)
├── Destructive (Button, text "Delete save")   far left; hidden when the dialog has none
├── Spacer (Control, size_flags_horizontal = Expand Fill, mouse_filter = Ignore)
├── Cancel (Button, text "Cancel")
└── Primary (Button, text "Confirm")
```

The sample labels make the scene render on its own. The dialog's script only binds live data:

```gdscript
class_name ActionBar
extends HBoxContainer

@onready var _destructive: Button = $Destructive
@onready var _primary: Button = $Primary

func bind(primary_text: String, destructive_text: String = "") -> void:
    _primary.text = primary_text
    _destructive.text = destructive_text
    _destructive.visible = not destructive_text.is_empty()
```

If the project runs `check ui-layout`, give each button the role property named by
`role_property` in `[ui_layout]`, with a role from `action_roles`.

## Proof to capture

- Capture the dialog with a short and a very long body: the bar stays in place.
- Run `godot-devkit check ui-layout` (`action-outside-bar`, `button-in-modal-scroll`).
- Drive `ui_cancel` and `ui_accept` through real input and confirm the result and focus return.

## Sources

- Godot: HBoxContainer, `gui/common/swap_cancel_ok`, Using the UI focus system
  (https://docs.godotengine.org/en/stable/tutorials/ui/gui_navigation.html)
- Xbox Accessibility Guidelines 112 (UI navigation), 107 (input)
- Game Accessibility Guidelines: confirm destructive actions; consistent controls
- Material: dialogs and their action area (https://m3.material.io/components/dialogs)
