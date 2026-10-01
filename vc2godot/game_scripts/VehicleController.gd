extends CharacterBody3D
@export var max_speed: float = 30.0
@export var acceleration: float = 18.0
@export var braking: float = 28.0
@export var turn_speed: float = 1.45
@export var gravity: float = 18.0
var driver: CharacterBody3D = null
var model: Node3D = null

func setup(asset_path: String) -> void:
	var clean: String = asset_path.strip_edges()
	var packed: PackedScene = null
	var candidates: Array[String] = []
	if clean.begins_with("res://"):
		candidates.append(clean)
	else:
		candidates.append("res://assets/gameplay/" + clean)
		candidates.append("res://" + clean)
	for candidate: String in candidates:
		if ResourceLoader.exists(candidate):
			packed = load(candidate) as PackedScene
			if packed != null:
				break
	if packed != null:
		model = packed.instantiate() as Node3D
		if model != null:
			model.name = "VehicleVisual"
			model.scale = Vector3.ONE
			add_child(model)
	var cs: CollisionShape3D = CollisionShape3D.new()
	var box: BoxShape3D = BoxShape3D.new()
	box.size = Vector3(1.9, 1.2, 4.2)
	cs.shape = box
	cs.position.y = 0.65
	add_child(cs)

func enter(p: CharacterBody3D) -> void:
	if driver != null:
		return
	driver = p
	p.set("vehicle", self)
	var rig_value: Variant = p.get("camera_rig")
	var rig: Node3D = rig_value as Node3D
	if rig != null and rig.has_method("set_target"):
		rig.call("set_target", self)
	p.visible = false
	p.set_process(false)
	p.set_physics_process(false)
	rotation.y = p.rotation.y

func exit() -> void:
	if driver == null:
		return
	var p: CharacterBody3D = driver
	driver = null
	p.set("vehicle", null)
	var rig_value: Variant = p.get("camera_rig")
	var rig: Node3D = rig_value as Node3D
	if rig != null and rig.has_method("set_target"):
		rig.call("set_target", p)
	p.global_position = global_position + global_transform.basis.x * 2.0 + Vector3.UP
	p.visible = true
	p.set_process(true)
	p.set_physics_process(true)

func _physics_process(delta: float) -> void:
	if driver == null:
		velocity = Vector3.ZERO
		return
	if not is_on_floor():
		velocity.y -= gravity * delta
	else:
		velocity.y = -0.5
	var throttle: float = Input.get_action_strength("move_forward") - Input.get_action_strength("move_back")
	var steer: float = Input.get_action_strength("move_right") - Input.get_action_strength("move_left")
	var forward: Vector3 = -global_transform.basis.z
	var desired: float = throttle * max_speed
	var horizontal: Vector3 = Vector3(velocity.x, 0.0, velocity.z)
	var target_velocity: Vector3 = forward * desired
	var rate: float = acceleration if absf(throttle) > 0.01 else braking
	horizontal = horizontal.move_toward(Vector3(target_velocity.x, 0.0, target_velocity.z), rate * delta)
	velocity.x = horizontal.x
	velocity.z = horizontal.z
	var speed_factor: float = clampf(horizontal.length() / max_speed, 0.15, 1.0)
	if absf(throttle) > 0.05:
		var direction_sign: float = 1.0 if throttle >= 0.0 else -1.0
		rotation.y -= steer * turn_speed * speed_factor * delta * direction_sign
	move_and_slide()
	if Input.is_action_just_pressed("enter_vehicle"):
		exit()
