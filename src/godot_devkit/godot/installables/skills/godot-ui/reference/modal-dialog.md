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

```gdscript
class_name ActionBar
extends HBoxContainer
## Orders children by role: destructive (far left), spacer, cancel, primary.

enum Role { DESTRUCTIVE, CANCEL, PRIMARY }

var _spacer := Control.new()

func _ready() -> void:
    _spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    _spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
    add_child(_spacer)
    child_entered_tree.connect(func(_n: Node) -> void: _sort.call_deferred())
    _sort()

func _sort() -> void:
    var buttons: Array[Node] = get_children().filter(func(n: Node) -> bool: return n != _spacer)
    buttons.sort_custom(func(a: Node, b: Node) -> bool: return _role(a) < _role(b))
    var gap := buttons.filter(func(n: Node) -> bool: return _role(n) == Role.DESTRUCTIVE).size()
    for i in buttons.size():
        move_child(buttons[i], i if i < gap else i + 1)
    move_child(_spacer, gap)

func _role(node: Node) -> int:
    return int(node.get(&"ui_role"))  # exported Role on the button's script
```

The role property name must match `role_property` in `[ui_layout]`. Adapt the enum to the
roles you configure in `action_roles`.

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
