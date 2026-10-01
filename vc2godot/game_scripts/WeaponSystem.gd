extends Node
var current_id: String = ""
var current_name: String = ""
var current_scene: PackedScene = null
var infinite_ammo: bool = true
var ammo: int = 999999
var cooldown: float = 0.0

func equip(id: String, label: String, scene: PackedScene, player: CharacterBody3D) -> void:
	current_id = id
	current_name = label
	current_scene = scene
	ammo = 999999
	player.call("set_weapon_visual", scene)

func try_fire(player: CharacterBody3D) -> void:
	if current_id == "" or cooldown > 0.0:
		return
	if not infinite_ammo and ammo <= 0:
		return
	if not infinite_ammo:
		ammo -= 1
	cooldown = 0.16
	player.call("play_fire_animation")
	var cam: Camera3D = get_viewport().get_camera_3d()
	if cam == null:
		return
	var origin: Vector3 = cam.global_position
	var direction: Vector3 = -cam.global_transform.basis.z
	var query: PhysicsRayQueryParameters3D = PhysicsRayQueryParameters3D.create(origin, origin + direction * 250.0)
	query.exclude = [player.get_rid()]
	var world_3d: World3D = player.get_world_3d()
	if world_3d == null:
		return
	var hit: Dictionary = world_3d.direct_space_state.intersect_ray(query)
	if not hit.is_empty():
		var obj: Object = hit.get("collider") as Object
		if obj != null and obj.has_method("apply_damage"):
			obj.call("apply_damage", 25.0)

func _process(delta: float) -> void:
	cooldown = maxf(0.0, cooldown - delta)
