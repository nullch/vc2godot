extends Node3D
var target: Node3D = null
var spring_arm: SpringArm3D = null
var camera: Camera3D = null
var yaw: float = 0.0
var pitch: float = -10.0
var sensitivity: float = 0.11
var distance: float = 4.2
var aim_distance: float = 2.9
var min_distance: float = 2.2
var max_distance: float = 7.0

func configure(p_spring_arm: SpringArm3D, p_camera: Camera3D, p_target: Node3D) -> void:
	spring_arm = p_spring_arm
	camera = p_camera
	target = p_target
	if target != null:
		global_position = target.global_position + Vector3.UP * 1.55
		rotation_degrees = Vector3(pitch, yaw, 0.0)

func set_target(p_target: Node3D) -> void:
	target = p_target

func _ready() -> void:
	Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)

func _unhandled_input(event: InputEvent) -> void:
	var key: InputEventKey = event as InputEventKey
	if key != null and key.pressed and not key.echo and key.keycode == KEY_ESCAPE:
		Input.set_mouse_mode(Input.MOUSE_MODE_VISIBLE if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED else Input.MOUSE_MODE_CAPTURED)
		return
	var motion: InputEventMouseMotion = event as InputEventMouseMotion
	if motion != null and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		yaw -= motion.relative.x * sensitivity
		pitch = clampf(pitch - motion.relative.y * sensitivity, -55.0, 35.0)
		return
	var button: InputEventMouseButton = event as InputEventMouseButton
	if button != null and button.pressed:
		if button.button_index == MOUSE_BUTTON_WHEEL_UP:
			distance = clampf(distance - 0.35, min_distance, max_distance)
		elif button.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			distance = clampf(distance + 0.35, min_distance, max_distance)
		elif button.button_index == MOUSE_BUTTON_RIGHT and target != null and target.has_method("set_aiming"):
			target.call("set_aiming", true)
		elif button.button_index == MOUSE_BUTTON_LEFT and target != null and target.has_method("fire"):
			target.call("fire")

func _input(event: InputEvent) -> void:
	var button: InputEventMouseButton = event as InputEventMouseButton
	if button != null and not button.pressed and button.button_index == MOUSE_BUTTON_RIGHT:
		if target != null and target.has_method("set_aiming"):
			target.call("set_aiming", false)

func _process(delta: float) -> void:
	if target == null:
		return
	global_position = target.global_position + Vector3.UP * 1.55
	rotation_degrees = Vector3(pitch, yaw, 0.0)
	var desired_distance: float = aim_distance if _is_aiming() else distance
	if spring_arm != null:
		spring_arm.spring_length = lerpf(spring_arm.spring_length, desired_distance, minf(1.0, delta * 12.0))
	if camera != null:
		var desired_fov: float = 62.0 if _is_aiming() else 70.0
		camera.fov = lerpf(camera.fov, desired_fov, minf(1.0, delta * 8.0))

func _is_aiming() -> bool:
	if target == null:
		return false
	var value: Variant = target.get("aiming")
	return bool(value) if value != null else false
