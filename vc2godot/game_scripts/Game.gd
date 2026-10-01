extends Node3D

enum State { LOADING, CHARACTER_SELECT, PLAYING }
var state: int = State.LOADING
var player: CharacterBody3D = null
const PLAYER_SCRIPT: Script = preload("res://scripts/Player.gd")
const WEAPON_SYSTEM_SCRIPT: Script = preload("res://scripts/WeaponSystem.gd")
const PICKUP_SCRIPT: Script = preload("res://scripts/WeaponPickup.gd")
const VEHICLE_SCRIPT: Script = preload("res://scripts/VehicleController.gd")

var weapon_system: Node = WEAPON_SYSTEM_SCRIPT.new() as Node
var selected_index: int = 0
var characters: Array = []
var weapons: Array = []
var vehicles: Array = []
var spawn_position: Vector3 = Vector3.ZERO
var selection_panel: Control = null
var loading_label: Label = null
var streamer: Node = null
var gameplay_started: bool = false

func _ready() -> void:
	_setup_input()
	streamer = get_node_or_null("WorldStreamer")
	_load_spawn()
	add_child(weapon_system)
	_load_json()
	_build_loading_ui()
	call_deferred("_begin_loading")

func _setup_input() -> void:
	var actions: Dictionary = {
		"move_forward": KEY_W, "move_back": KEY_S, "move_left": KEY_A, "move_right": KEY_D,
		"sprint": KEY_SHIFT, "jump": KEY_SPACE, "interact": KEY_E, "enter_vehicle": KEY_F
	}
	for action_name_variant in actions.keys():
		var action_name: String = str(action_name_variant)
		if not InputMap.has_action(action_name):
			InputMap.add_action(action_name)
		var event: InputEventKey = InputEventKey.new()
		event.keycode = int(actions[action_name])
		event.physical_keycode = int(actions[action_name])
		var already_bound: bool = false
		for existing_variant in InputMap.action_get_events(action_name):
			var existing: InputEventKey = existing_variant as InputEventKey
			if existing != null and (existing.keycode == event.keycode or existing.physical_keycode == event.physical_keycode):
				already_bound = true
				break
		if not already_bound:
			InputMap.action_add_event(action_name, event)

func _load_spawn() -> void:
	if not FileAccess.file_exists("res://data/world_meta.json"):
		return
	var file: FileAccess = FileAccess.open("res://data/world_meta.json", FileAccess.READ)
	if file == null:
		return
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		var data: Dictionary = parsed as Dictionary
		var center_value: Variant = data.get("center", {})
		if center_value is Dictionary:
			var center: Dictionary = center_value as Dictionary
			spawn_position = Vector3(float(center.get("x", 0.0)), 2.0, float(center.get("z", 0.0)))

func _load_json() -> void:
	characters = _read_json("res://data/characters.json")
	weapons = _read_json("res://data/weapons.json")
	vehicles = _read_json("res://data/vehicles.json")
	if characters.is_empty():
		characters = [{"id": "player", "name": "Tommy", "path": ""}]

func _read_json(path: String) -> Array:
	if not FileAccess.file_exists(path):
		return []
	var file: FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return []
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Array:
		return parsed as Array
	return []

func _build_loading_ui() -> void:
	var layer: CanvasLayer = CanvasLayer.new()
	layer.name = "GameUI"
	add_child(layer)
	loading_label = Label.new()
	loading_label.position = Vector2(48.0, 40.0)
	loading_label.add_theme_font_size_override("font_size", 28)
	loading_label.text = "VICE CITY\nЗагрузка острова..."
	layer.add_child(loading_label)

func _begin_loading() -> void:
	await get_tree().process_frame
	if loading_label != null:
		loading_label.text = "VICE CITY\nЗагрузка уровня..."
	if streamer != null:
		streamer.global_position = spawn_position + Vector3.UP * 200.0
		if streamer.has_method("set_target_node"):
			streamer.call("set_target_node", streamer)
	var guard_frames: int = 0
	while streamer != null and streamer.has_method("is_initial_ready") and not bool(streamer.call("is_initial_ready")) and guard_frames < 900:
		guard_frames += 1
		await get_tree().process_frame
	if loading_label != null:
		loading_label.queue_free()
	_show_character_select()

func _show_character_select() -> void:
	state = State.CHARACTER_SELECT
	selection_panel = ColorRect.new()
	selection_panel.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	selection_panel.color = Color(0.0, 0.0, 0.0, 0.62)
	add_child(selection_panel)
	var title: Label = Label.new()
	title.position = Vector2(70.0, 55.0)
	title.text = "ВЫБОР ПЕРСОНАЖА"
	title.add_theme_font_size_override("font_size", 30)
	selection_panel.add_child(title)
	var hint: Label = Label.new()
	hint.position = Vector2(70.0, 110.0)
	hint.text = "A/D или ←/→ — выбор    ENTER — начать"
	selection_panel.add_child(hint)
	var name_label: Label = Label.new()
	name_label.name = "CharacterName"
	name_label.position = Vector2(70.0, 180.0)
	name_label.add_theme_font_size_override("font_size", 42)
	selection_panel.add_child(name_label)
	selection_panel.set_meta("name_label", name_label)
	_update_selection()

func _update_selection() -> void:
	if selection_panel == null or characters.is_empty():
		return
	var value: Variant = selection_panel.get_meta("name_label")
	var label: Label = value as Label
	if label == null:
		return
	var selected: Variant = characters[selected_index]
	if selected is Dictionary:
		var data: Dictionary = selected as Dictionary
		var suffix: String = ""
		if bool(data.get("skinned", false)):
			suffix = "  [SKIN]"
		label.text = str(data.get("name", "Character")) + suffix

func _unhandled_input(event: InputEvent) -> void:
	if state != State.CHARACTER_SELECT:
		return
	var key: InputEventKey = event as InputEventKey
	if key == null or not key.pressed or key.echo:
		return
	if key.keycode == KEY_A or key.keycode == KEY_LEFT:
		selected_index = posmod(selected_index - 1, characters.size())
		_update_selection()
	elif key.keycode == KEY_D or key.keycode == KEY_RIGHT:
		selected_index = posmod(selected_index + 1, characters.size())
		_update_selection()
	elif key.keycode == KEY_ENTER or key.keycode == KEY_KP_ENTER:
		_start_game()

func _start_game() -> void:
	if gameplay_started:
		return
	gameplay_started = true
	state = State.PLAYING
	if selection_panel != null:
		selection_panel.queue_free()
	var selected: Variant = characters[selected_index]
	var data: Dictionary = {}
	if selected is Dictionary:
		data = selected as Dictionary

	player = PLAYER_SCRIPT.new() as CharacterBody3D
	if player == null:
		push_error("Could not instantiate Player.gd")
		return
	player.name = "Player"
	player.global_position = spawn_position + Vector3.UP * 40.0
	player.set_physics_process(false)
	add_child(player)

	var path: String = str(data.get("path", ""))
	player.call("setup", path)
	if streamer != null and streamer.has_method("set_target_node"):
		streamer.call("set_target_node", player)

	var placed: bool = await _place_player_on_loaded_ground()
	if not placed:
		push_error("Gameplay spawn failed: no loaded walkable collision surface after retries.")
		player.set_physics_process(true)
		return

	player.visible = true
	player.velocity = Vector3.ZERO
	player.set_physics_process(true)
	await get_tree().physics_frame
	_spawn_weapons()
	_spawn_vehicle()

func _place_player_on_loaded_ground() -> bool:
	if player == null or streamer == null or not streamer.has_method("prepare_random_spawn_area"):
		return false

	# Try several completely different chunks. A valid map chunk may contain water or
	# props only, so one random chunk is not treated as a fatal condition.
	for area_attempt in range(18):
		var prepared_value: Variant = streamer.call("prepare_random_spawn_area")
		if not bool(prepared_value):
			await get_tree().process_frame
			continue

		var ready_frames: int = 0
		while streamer.has_method("is_spawn_chunk_ready") and not bool(streamer.call("is_spawn_chunk_ready")) and ready_frames < 360:
			ready_frames += 1
			await get_tree().physics_frame

		if streamer.has_method("is_spawn_chunk_ready") and not bool(streamer.call("is_spawn_chunk_ready")):
			continue

		for _attempt in range(160):
			var result_value: Variant = streamer.call("get_random_ground_spawn", player, 1)
			if result_value is Dictionary:
				var result: Dictionary = result_value as Dictionary
				if bool(result.get("ok", false)):
					var pos_value: Variant = result.get("position", Vector3.ZERO)
					if pos_value is Vector3:
						spawn_position = pos_value as Vector3
						player.global_position = spawn_position
						player.velocity = Vector3.ZERO
						return true
			await get_tree().physics_frame

	return false

func _load_gameplay_scene(asset_path: String) -> PackedScene:
	var clean: String = asset_path.strip_edges()
	if clean.is_empty():
		return null
	var candidates: Array[String] = []
	if clean.begins_with("res://"):
		candidates.append(clean)
	else:
		candidates.append("res://assets/gameplay/" + clean)
		candidates.append("res://" + clean)
		if clean.begins_with("assets/gameplay/"):
			candidates.append("res://" + clean)
	for candidate in candidates:
		if ResourceLoader.exists(candidate):
			var scene_value: PackedScene = load(candidate) as PackedScene
			if scene_value != null:
				return scene_value
	return null

func _snap_xz_to_ground(x: float, z: float, y_hint: float) -> Vector3:
	var world_3d: World3D = get_world_3d()
	if world_3d == null:
		return Vector3(x, y_hint, z)
	var query: PhysicsRayQueryParameters3D = PhysicsRayQueryParameters3D.create(
		Vector3(x, 2000.0, z), Vector3(x, -200.0, z)
	)
	query.collision_mask = 1
	query.collide_with_bodies = true
	query.collide_with_areas = false
	if player != null:
		query.exclude = [player.get_rid()]
	var hit: Dictionary = world_3d.direct_space_state.intersect_ray(query)
	if hit.is_empty():
		return Vector3(x, y_hint, z)
	var normal_value: Variant = hit.get("normal", Vector3.UP)
	var normal: Vector3 = Vector3(normal_value)
	if normal.y < 0.60:
		return Vector3(x, y_hint, z)
	var point_value: Variant = hit.get("position", Vector3(x, y_hint, z))
	var point: Vector3 = Vector3(point_value)
	return point + Vector3.UP * 0.20

func _spawn_weapons() -> void:
	if player == null or weapons.is_empty():
		return
	var center_pos: Vector3 = player.global_position
	var count: int = weapons.size()
	var radius: float = 2.6
	for i in range(count):
		var value: Variant = weapons[i]
		if not value is Dictionary:
			continue
		var data: Dictionary = value as Dictionary
		var pickup: Area3D = PICKUP_SCRIPT.new() as Area3D
		if pickup == null:
			continue
		var angle: float = float(i) * TAU / float(count)
		var x: float = center_pos.x + cos(angle) * radius
		var z: float = center_pos.z + sin(angle) * radius
		var ground: Vector3 = _snap_xz_to_ground(x, z, center_pos.y)
		pickup.global_position = ground
		pickup.name = "WeaponPickup_%s" % str(data.get("id", i))
		add_child(pickup)
		var scene: PackedScene = _load_gameplay_scene(str(data.get("path", "")))
		pickup.call("setup", str(data.get("id", "")), str(data.get("name", "Weapon")), scene)

func _spawn_vehicle() -> void:
	if player == null or vehicles.is_empty():
		return
	var value: Variant = vehicles[0]
	if not value is Dictionary:
		return
	var data: Dictionary = value as Dictionary
	var car: CharacterBody3D = VEHICLE_SCRIPT.new() as CharacterBody3D
	if car == null:
		return
	car.name = "VCVehicle"
	var car_pos: Vector3 = _snap_xz_to_ground(player.global_position.x + 5.5, player.global_position.z, player.global_position.y + 1.0)
	car.global_position = car_pos + Vector3.UP * 0.35
	add_child(car)
	car.call("setup", str(data.get("path", "")))

func equip_weapon(id: String, label: String, scene: PackedScene) -> void:
	if player != null:
		weapon_system.call("equip", id, label, scene, player)

func fire_weapon() -> void:
	if player != null:
		weapon_system.call("try_fire", player)

func _process(_delta: float) -> void:
	if state != State.PLAYING or player == null:
		return
	if Input.is_action_just_pressed("interact"):
		_try_pickup()
	if Input.is_action_just_pressed("enter_vehicle"):
		_try_vehicle()

func _try_pickup() -> void:
	for child in get_children():
		if child is Area3D and child.has_method("interact"):
			var pickup: Area3D = child as Area3D
			if player.global_position.distance_to(pickup.global_position) < 2.4:
				pickup.call("interact", player)
				return

func _try_vehicle() -> void:
	for child in get_children():
		if child is CharacterBody3D and child.has_method("enter") and child != player:
			var vehicle_node: CharacterBody3D = child as CharacterBody3D
			if player.global_position.distance_to(vehicle_node.global_position) < 4.0:
				vehicle_node.call("enter", player)
				return
