extends CharacterBody3D
@export var walk_speed: float = 4.2
@export var run_speed: float = 7.2
@export var sprint_speed: float = 9.5
@export var acceleration: float = 26.0
@export var air_acceleration: float = 8.0
@export var jump_velocity: float = 5.2
@export var gravity: float = 18.0
@export var mouse_sensitivity: float = 0.08

const CAMERA_SCRIPT: Script = preload("res://scripts/ThirdPersonCamera.gd")

var visual: Node3D = null
var camera_rig: Node3D = null
var weapon_socket: Node3D = null
var anim_player: AnimationPlayer = null
var current_anim: String = ""
var aiming: bool = false
var shooting: bool = false
var vehicle: Node3D = null
var visual_asset_path: String = ""

func _ready() -> void:
	var shape: CollisionShape3D = CollisionShape3D.new()
	var capsule: CapsuleShape3D = CapsuleShape3D.new()
	capsule.radius = 0.34
	capsule.height = 1.76
	shape.shape = capsule
	shape.position.y = 0.90
	add_child(shape)
	collision_layer = 2
	collision_mask = 1
	floor_snap_length = 0.32
	floor_max_angle = deg_to_rad(52.0)
	safe_margin = 0.03
	up_direction = Vector3.UP
	visible = true

func setup(asset_path: String) -> void:
	visual_asset_path = asset_path
	_create_camera()
	var packed: PackedScene = _load_scene_path(asset_path)
	if packed == null:
		push_error("Character asset missing: " + asset_path)
		_create_fallback_visual()
		return
	visual = packed.instantiate() as Node3D
	if visual == null:
		push_error("Character asset is not a Node3D: " + asset_path)
		_create_fallback_visual()
		return
	visual.name = "Visual"
	visual.position = Vector3.ZERO
	visual.rotation = Vector3.ZERO
	visual.scale = Vector3.ONE
	visual.visible = true
	add_child(visual)
	_set_tree_visible(visual)
	_find_animation_player(visual)
	_make_weapon_socket(visual)
	_fit_visual_to_player(visual)
	if not _contains_mesh_instance(visual):
		push_error("Character asset contains no MeshInstance3D nodes: " + asset_path)
		visual.queue_free()
		visual = null
		_create_fallback_visual()
	else:
		# A GLTF skeleton can initially evaluate its bounds before the imported animation
		# pose is active. Force a clean bind pose before gameplay starts.
		var skeleton: Skeleton3D = visual.find_child("Skeleton3D", true, false) as Skeleton3D
		if skeleton != null:
			skeleton.reset_bone_poses()
		_play_best("idle")

func _load_scene_path(asset_path: String) -> PackedScene:
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
			var packed: PackedScene = load(candidate) as PackedScene
			if packed != null:
				return packed
	return null

func _set_tree_visible(root: Node) -> void:
	var node3d: Node3D = root as Node3D
	if node3d != null:
		node3d.visible = true
	for child in root.get_children():
		_set_tree_visible(child)

func _create_fallback_visual() -> void:
	if visual != null:
		return
	var mesh_instance: MeshInstance3D = MeshInstance3D.new()
	var capsule: CapsuleMesh = CapsuleMesh.new()
	capsule.radius = 0.34
	capsule.height = 1.72
	mesh_instance.mesh = capsule
	var mat: StandardMaterial3D = StandardMaterial3D.new()
	mat.albedo_color = Color(0.72, 0.52, 0.34, 1.0)
	mat.roughness = 0.82
	mesh_instance.material_override = mat
	mesh_instance.position.y = 0.86
	mesh_instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON
	mesh_instance.name = "CharacterFallback"
	add_child(mesh_instance)
	visual = mesh_instance

func _create_camera() -> void:
	if camera_rig != null and is_instance_valid(camera_rig):
		return
	var rig: Node3D = CAMERA_SCRIPT.new() as Node3D
	if rig == null:
		return
	rig.name = "CameraRig"
	var scene_root: Node = get_tree().current_scene
	if scene_root == null:
		scene_root = get_parent()
	if scene_root != null:
		scene_root.add_child(rig)
	else:
		add_child(rig)
	camera_rig = rig
	var spring: SpringArm3D = SpringArm3D.new()
	spring.name = "SpringArm"
	spring.spring_length = 4.2
	spring.margin = 0.2
	spring.collision_mask = 1
	rig.add_child(spring)
	var cam: Camera3D = Camera3D.new()
	cam.name = "Camera"
	cam.current = true
	cam.fov = 70.0
	spring.add_child(cam)
	rig.call("configure", spring, cam, self)
	rig.set("sensitivity", mouse_sensitivity)

func _transform_aabb_box(box: AABB, transform: Transform3D) -> AABB:
	var points: Array[Vector3] = []
	var min_v: Vector3 = box.position
	var max_v: Vector3 = box.position + box.size
	for x in [min_v.x, max_v.x]:
		for y in [min_v.y, max_v.y]:
			for z in [min_v.z, max_v.z]:
				points.append(transform * Vector3(x, y, z))
	var out_min: Vector3 = Vector3(1000000000.0, 1000000000.0, 1000000000.0)
	var out_max: Vector3 = Vector3(-1000000000.0, -1000000000.0, -1000000000.0)
	for point in points:
		out_min.x = minf(out_min.x, point.x)
		out_min.y = minf(out_min.y, point.y)
		out_min.z = minf(out_min.z, point.z)
		out_max.x = maxf(out_max.x, point.x)
		out_max.y = maxf(out_max.y, point.y)
		out_max.z = maxf(out_max.z, point.z)
	return AABB(out_min, out_max - out_min)

func _collect_visual_bounds(root: Node, parent_transform: Transform3D, have_bounds: Array[bool], bounds: Array[AABB]) -> void:
	var current_transform: Transform3D = parent_transform
	var node3d: Node3D = root as Node3D
	if node3d != null:
		current_transform = parent_transform * node3d.transform
	if root is MeshInstance3D:
		var mesh_node: MeshInstance3D = root as MeshInstance3D
		if mesh_node.mesh != null:
			var local_box: AABB = mesh_node.get_aabb()
			if local_box.size.length() > 0.0001:
				var world_box: AABB = _transform_aabb_box(local_box, current_transform)
				if not have_bounds[0]:
					bounds[0] = world_box
					have_bounds[0] = true
				else:
					bounds[0] = bounds[0].merge(world_box)
	for child in root.get_children():
		_collect_visual_bounds(child, current_transform, have_bounds, bounds)

func _fit_visual_to_player(root: Node3D) -> void:
	var have_bounds: Array[bool] = [false]
	var bounds: Array[AABB] = [AABB()]
	_collect_visual_bounds(root, Transform3D.IDENTITY, have_bounds, bounds)
	if not have_bounds[0]:
		return
	var box: AABB = bounds[0]
	var height: float = box.size.y
	if height <= 0.001:
		return
	if height < 0.70 or height > 3.60:
		var scale_factor: float = clampf(1.78 / height, 0.55, 2.60)
		root.scale *= Vector3.ONE * scale_factor
		have_bounds[0] = false
		bounds[0] = AABB()
		_collect_visual_bounds(root, Transform3D.IDENTITY, have_bounds, bounds)
		if not have_bounds[0]:
			return
		box = bounds[0]
	# Keep the source model's X/Z root. Only put its feet on the controller origin.
	root.position.y -= box.position.y

func _contains_mesh_instance(root: Node) -> bool:
	if root is MeshInstance3D:
		var mesh_node: MeshInstance3D = root as MeshInstance3D
		return mesh_node.mesh != null
	for child in root.get_children():
		if _contains_mesh_instance(child):
			return true
	return false

func _find_animation_player(root: Node) -> void:
	anim_player = root.find_child("AnimationPlayer", true, false) as AnimationPlayer
	if anim_player != null:
		anim_player.playback_active = true
		_play_best("idle")

func _make_weapon_socket(root: Node) -> void:
	var skel: Skeleton3D = root.find_child("Skeleton3D", true, false) as Skeleton3D
	if skel == null:
		weapon_socket = Node3D.new()
		weapon_socket.name = "WeaponSocket"
		root.add_child(weapon_socket)
		return
	var attach: BoneAttachment3D = BoneAttachment3D.new()
	attach.name = "WeaponSocket"
	var candidates: Array[String] = ["R Hand", " R Hand", "Right Hand", "r_hand", "hand_r", "R Fingers", " R Finger"]
	for bone_name in candidates:
		var bone_index: int = skel.find_bone(bone_name)
		if bone_index >= 0:
			attach.bone_name = bone_name
			break
	skel.add_child(attach)
	weapon_socket = attach

func _play_best(kind: String) -> void:
	if anim_player == null:
		return
	var chosen: String = ""
	var animation_names: PackedStringArray = anim_player.get_animation_list()
	for animation_name in animation_names:
		if animation_name.to_lower() == "reset":
			continue
		var lowered: String = animation_name.to_lower()
		if kind == "idle" and ("idle" in lowered or "stand" in lowered):
			chosen = animation_name
			break
		if kind == "walk" and ("walk" in lowered or "walk_civi" in lowered):
			chosen = animation_name
			break
		if kind == "run" and ("run" in lowered or "sprint" in lowered):
			chosen = animation_name
			break
		if kind == "aim" and ("aim" in lowered or "gun_stand" in lowered):
			chosen = animation_name
			break
		if kind == "fire" and ("fire" in lowered or "shot" in lowered or "shoot" in lowered):
			chosen = animation_name
			break
	if chosen == "" and kind == "idle":
		for animation_name in animation_names:
			if animation_name.to_lower() != "reset":
				chosen = animation_name
				break
	if chosen != "" and chosen != current_anim:
			anim_player.play(chosen, 0.12)
			current_anim = chosen

func set_weapon_visual(weapon_scene: PackedScene) -> void:
	if weapon_socket == null:
		return
	for child in weapon_socket.get_children():
		child.queue_free()
	if weapon_scene == null:
		return
	var node: Node3D = weapon_scene.instantiate() as Node3D
	if node == null:
		return
	node.scale = Vector3.ONE * 0.65
	node.position = Vector3(0.04, -0.02, 0.03)
	node.rotation_degrees = Vector3(-90.0, 0.0, 90.0)
	_set_tree_visible(node)
	weapon_socket.add_child(node)

func set_aiming(value: bool) -> void:
	aiming = value
	_play_best("aim" if value else "idle")

func fire() -> void:
	var parent_node: Node = get_parent()
	if parent_node != null and parent_node.has_method("fire_weapon"):
		parent_node.call("fire_weapon")

func play_fire_animation() -> void:
	shooting = true
	_play_best("fire")
	await get_tree().create_timer(0.10).timeout
	shooting = false
	if aiming:
		_play_best("aim")
	else:
		_play_best("idle")

func _physics_process(delta: float) -> void:
	if vehicle != null:
		return
	if not is_on_floor():
		velocity.y -= gravity * delta
	elif Input.is_key_pressed(KEY_SPACE):
		velocity.y = jump_velocity
	else:
		velocity.y = -0.5

	# Read the physical keys directly. This avoids relying on InputMap state when the
	# game has just switched from the character-selection UI to gameplay.
	var forward_input: float = 0.0
	var right_input: float = 0.0
	if Input.is_key_pressed(KEY_W):
		forward_input += 1.0
	if Input.is_key_pressed(KEY_S):
		forward_input -= 1.0
	if Input.is_key_pressed(KEY_D):
		right_input += 1.0
	if Input.is_key_pressed(KEY_A):
		right_input -= 1.0
	var input_vector: Vector2 = Vector2(right_input, forward_input)
	if input_vector.length() > 1.0:
		input_vector = input_vector.normalized()

	var cam: Camera3D = get_viewport().get_camera_3d()
	var forward: Vector3 = -global_transform.basis.z
	var right: Vector3 = global_transform.basis.x
	if cam != null:
		forward = -cam.global_transform.basis.z
		right = cam.global_transform.basis.x
	forward.y = 0.0
	right.y = 0.0
	if forward.length_squared() < 0.001:
		forward = Vector3.FORWARD
	else:
		forward = forward.normalized()
	if right.length_squared() < 0.001:
		right = Vector3.RIGHT
	else:
		right = right.normalized()
	var direction: Vector3 = right * input_vector.x + forward * input_vector.y

	var speed: float = walk_speed
	if Input.is_key_pressed(KEY_SHIFT):
		speed = sprint_speed
	elif input_vector.length() < 0.01:
		speed = 0.0
	elif input_vector.length() > 0.55:
		speed = run_speed
	var target_velocity: Vector3 = direction.normalized() * speed if direction.length() > 0.01 else Vector3.ZERO
	var rate: float = acceleration if is_on_floor() else air_acceleration
	velocity.x = move_toward(velocity.x, target_velocity.x, rate * delta)
	velocity.z = move_toward(velocity.z, target_velocity.z, rate * delta)

	if direction.length() > 0.10:
		var face_angle: float = atan2(direction.x, -direction.z)
		rotation.y = lerp_angle(rotation.y, face_angle, minf(1.0, delta * 14.0))
		if speed >= sprint_speed - 0.1:
			_play_best("run")
		elif speed > 0.1:
			_play_best("walk")
	else:
		_play_best("aim" if aiming else "idle")
	move_and_slide()
