extends Area3D
var weapon_id: String = ""
var display_name: String = ""
var weapon_scene: PackedScene = null
var visual_root: Node3D = null

func _ready() -> void:
	monitoring = false
	monitorable = false
	collision_layer = 0
	collision_mask = 0

func setup(id: String, label: String, scene: PackedScene) -> void:
	weapon_id = id
	display_name = label
	weapon_scene = scene
	var shape: CollisionShape3D = CollisionShape3D.new()
	var sphere: SphereShape3D = SphereShape3D.new()
	sphere.radius = 1.15
	shape.shape = sphere
	add_child(shape)
	var label3d: Label3D = Label3D.new()
	label3d.text = "[E] " + display_name
	label3d.position.y = 1.15
	label3d.font_size = 36
	label3d.pixel_size = 0.004
	label3d.no_depth_test = true
	label3d.modulate = Color(1.0, 0.92, 0.62, 1.0)
	label3d.outline_size = 8
	label3d.outline_modulate = Color(0.02, 0.02, 0.02, 0.92)
	add_child(label3d)
	var beacon: MeshInstance3D = MeshInstance3D.new()
	var beacon_mesh: CylinderMesh = CylinderMesh.new()
	beacon_mesh.top_radius = 0.42
	beacon_mesh.bottom_radius = 0.42
	beacon_mesh.height = 0.035
	beacon.mesh = beacon_mesh
	var beacon_mat: StandardMaterial3D = StandardMaterial3D.new()
	beacon_mat.albedo_color = Color(0.95, 0.72, 0.12, 1.0)
	beacon_mat.emission_enabled = true
	beacon_mat.emission = Color(0.95, 0.35, 0.03, 1.0)
	beacon_mat.emission_energy_multiplier = 2.5
	beacon.material_override = beacon_mat
	beacon.position.y = 0.03
	add_child(beacon)
	if weapon_scene != null:
		visual_root = weapon_scene.instantiate() as Node3D
		if visual_root != null:
			visual_root.name = "WeaponVisual"
			visual_root.position = Vector3.ZERO
			visual_root.rotation = Vector3.ZERO
			visual_root.scale = Vector3.ONE * 1.15
			_set_tree_visible(visual_root)
			add_child(visual_root)
	else:
		push_warning("Weapon asset could not be loaded: " + weapon_id)
		_add_missing_marker()
	
func _set_tree_visible(root: Node) -> void:
	var node3d: Node3D = root as Node3D
	if node3d != null:
		node3d.visible = true
	for child: Node in root.get_children():
		_set_tree_visible(child)

func _add_missing_marker() -> void:
	var mesh_instance: MeshInstance3D = MeshInstance3D.new()
	var mesh: BoxMesh = BoxMesh.new()
	mesh.size = Vector3(0.45, 0.18, 0.8)
	mesh_instance.mesh = mesh
	var mat: StandardMaterial3D = StandardMaterial3D.new()
	mat.albedo_color = Color(0.35, 0.35, 0.35, 1.0)
	mat.emission_enabled = true
	mat.emission = Color(0.8, 0.55, 0.08, 1.0)
	mat.emission_energy_multiplier = 2.0
	mesh_instance.material_override = mat
	mesh_instance.position.y = 0.25
	add_child(mesh_instance)

func interact(player: CharacterBody3D) -> void:
	var root: Node = player.get_parent()
	if root != null and root.has_method("equip_weapon"):
		root.call("equip_weapon", weapon_id, display_name, weapon_scene)
	queue_free()
