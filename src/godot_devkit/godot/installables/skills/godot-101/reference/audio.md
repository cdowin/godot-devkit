# Audio (Godot 4.7, 2D)

## Nodes and resources

| Node or resource | Job |
|---|---|
| `AudioStreamPlayer` | Non-positional sound: music, UI clicks |
| `AudioStreamPlayer2D` | Positional sound, panned and attenuated by distance from the listener |
| `AudioListener2D` | Where the ears are, when not at the current `Camera2D` |
| Audio buses (Audio tab, `default_bus_layout.tres`) | Mixing groups with volume and effects: Master, Music, SFX, UI |
| `AudioStreamRandomizer` | One stream that picks a variant and varies pitch and volume |
| `AudioStreamPlaylist` | Plays streams in order or shuffled, with a fade |
| `AudioStreamInteractive` | Music clips with transitions between them |

3D: `AudioStreamPlayer3D`, `AudioListener3D`.

## The usual setup

The thing that makes the sound owns the player. An enemy scene has its own
`AudioStreamPlayer2D` child with `bus = "SFX"`; it calls `$HitSound.play()`. The sound then
follows the enemy, pans with it and stops being heard with distance (`max_distance`,
`attenuation`). Set `max_polyphony` above 1 when the same player can overlap itself.

For variety, make the player's stream an `AudioStreamRandomizer` with several takes and a
`random_pitch` above 1.0. No code picks the take.

```gdscript
func take_hit() -> void:
    $HitSound.play()   # the randomizer picks the take and the pitch
```

A sound that must outlive its node (a death sound on an enemy that frees itself) needs a player
that outlives it: reparent the player to the level before `queue_free()`, or spawn a small one-shot
sound scene at that place that frees itself on `finished`.

## Buses and settings

Volume sliders change buses, not players.

```gdscript
var bus := AudioServer.get_bus_index("Music")
AudioServer.set_bus_volume_linear(bus, slider.value)   # 0.0 to 1.0
AudioServer.set_bus_mute(bus, muted)
```

Bus effects (reverb in a cave, a low-pass filter when paused) are added in the Audio tab and turned
on with `AudioServer.set_bus_effect_enabled(bus, effect_index, true)`. Save the values with the
other settings in a `ConfigFile`.

## Music

One `AudioStreamPlayer` on a music bus, often in an autoload so it plays across scene changes.
Its stream is an `AudioStreamPlaylist` for a track list, or an `AudioStreamInteractive` for music
that changes with the game:

```gdscript
var playback := $Music.get_stream_playback() as AudioStreamPlaybackInteractive
playback.switch_to_clip_by_name("combat")
```

Transitions (fade, sync to beat or bar) are set on the `AudioStreamInteractive` resource.

## Traps

- One global player that plays every effect at one place loses panning, attenuation and pause
  behavior. The emitter owns its player.
- Audio players follow `process_mode` and pause with the tree. Music that must keep playing in the
  pause menu needs `PROCESS_MODE_ALWAYS`.
- `volume_db` is in decibels; 0 is full, -80 is silent. Use the linear setters for sliders.
- A bus name typed in a scene that the bus layout lacks falls back to Master without an error.
- Imported loops: set loop in the import settings of the `.ogg` or `.wav`, not in code.

## Class reference

- https://docs.godotengine.org/en/4.7/classes/class_audiostreamplayer.html
- https://docs.godotengine.org/en/4.7/classes/class_audiostreamplayer2d.html
- https://docs.godotengine.org/en/4.7/classes/class_audiolistener2d.html
- https://docs.godotengine.org/en/4.7/classes/class_audioserver.html
- https://docs.godotengine.org/en/4.7/classes/class_audiostreamrandomizer.html
- https://docs.godotengine.org/en/4.7/classes/class_audiostreamplaylist.html
- https://docs.godotengine.org/en/4.7/classes/class_audiostreaminteractive.html
- Manual: https://docs.godotengine.org/en/4.7/tutorials/audio/index.html
