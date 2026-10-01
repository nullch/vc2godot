from __future__ import annotations
from pathlib import Path

PROJECT_GODOT = '''config_version=5

[application]
config/name="Vice City Godot - Full Map"
run/main_scene="res://world/ViceCity.tscn"

[display]
window/size/viewport_width=1280
window/size/viewport_height=720

[rendering]
renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
textures/default_filters/use_nearest_mipmap_filter=false
textures/default_filters/anisotropic_filtering_level=4
anti_aliasing/quality/msaa_3d=2
environment/defaults/default_clear_color=Color(0.45, 0.6, 0.8, 1)

[physics]
common/physics_ticks_per_second=60

[importer_defaults]

scene={
"meshes/create_shadow_meshes": false,
"meshes/ensure_tangents": false,
"meshes/generate_lods": false,
"meshes/light_baking": 0
}
'''

WATER_SHADER = '''shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_disabled, specular_schlick_ggx;

uniform vec3 shallow_color : source_color = vec3(0.10, 0.62, 0.66);
uniform vec3 deep_color : source_color = vec3(0.02, 0.28, 0.42);
uniform vec3 sky_color : source_color = vec3(0.70, 0.84, 0.95);
uniform float wave_speed = 0.6;
uniform float wave_scale = 0.22;
uniform float wave_height = 0.06;
uniform float opacity = 0.88;

varying vec3 wpos;

float h(vec2 p, float t) {
    float a = sin(p.x * 0.9 + t * 1.3) * 0.5 + sin(p.y * 1.1 - t * 1.1) * 0.5;
    a += sin((p.x + p.y) * 1.7 + t * 2.1) * 0.35;
    a += sin((p.x * 2.3 - p.y * 1.9) - t * 2.7) * 0.2;
    return a;
}

void vertex() {
    wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
    float t = TIME * wave_speed;
    vec2 p = wpos.xz * wave_scale;
    float e = 0.15;
    float dx = h(p + vec2(e, 0.0), t) - h(p - vec2(e, 0.0), t);
    float dz = h(p + vec2(0.0, e), t) - h(p - vec2(0.0, e), t);
    vec3 n_world = normalize(vec3(-dx * wave_height * 8.0, 1.0, -dz * wave_height * 8.0));
    NORMAL = normalize((VIEW_MATRIX * vec4(n_world, 0.0)).xyz);

    float fres = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 3.0);
    float dist = clamp(length(wpos.xz - CAMERA_POSITION_WORLD.xz) / 1500.0, 0.0, 1.0);
    float sparkle = smoothstep(0.55, 1.0, h(p * 2.3, t * 1.7) * 0.5 + 0.5) * 0.18;
    vec3 base = mix(shallow_color, deep_color, dist * 0.8);
    ALBEDO = mix(base, sky_color, fres * 0.55) + vec3(sparkle);
    ROUGHNESS = 0.12;
    SPECULAR = 0.7;
    METALLIC = 0.0;
    ALPHA = clamp(opacity + fres * 0.1, 0.0, 1.0);
}
'''

FLYCAM_GD = '''extends Camera3D
# Free-fly camera.  WASD move, Q/C (or Ctrl-less Space/E) up/down, Shift = fast,
# Ctrl = slow, mouse wheel = change base speed, Esc = release/capture mouse,
# F2 = jump to map centre.

@export var speed: float = 80.0
@export var fast_multiplier: float = 6.0
@export var slow_multiplier: float = 0.12
@export var mouse_sensitivity: float = 0.15
var yaw: float = 0.0
var pitch: float = 0.0
var captured: bool = true
var home: Vector3 = Vector3.ZERO

func _ready() -> void:
    yaw = rotation_degrees.y
    pitch = rotation_degrees.x
    home = global_position
    _set_captured(true)

func _set_captured(value: bool) -> void:
    captured = value
    if captured:
        Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)
    else:
        Input.set_mouse_mode(Input.MOUSE_MODE_VISIBLE)

func _unhandled_input(event: InputEvent) -> void:
    var key: InputEventKey = event as InputEventKey
    if key != null:
        if key.pressed and not key.echo:
            if key.keycode == KEY_ESCAPE:
                _set_captured(not captured)
            elif key.keycode == KEY_F2:
                global_position = home
        return
    var btn: InputEventMouseButton = event as InputEventMouseButton
    if btn != null:
        if btn.pressed:
            if btn.button_index == MOUSE_BUTTON_WHEEL_UP:
                speed = minf(speed * 1.25, 4000.0)
            elif btn.button_index == MOUSE_BUTTON_WHEEL_DOWN:
                speed = maxf(speed / 1.25, 1.0)
            elif btn.button_index == MOUSE_BUTTON_LEFT and not captured:
                _set_captured(true)
        return
    var motion: InputEventMouseMotion = event as InputEventMouseMotion
    if motion != null and captured:
        yaw -= motion.relative.x * mouse_sensitivity
        pitch = clampf(pitch - motion.relative.y * mouse_sensitivity, -89.0, 89.0)
        rotation_degrees = Vector3(pitch, yaw, 0.0)

func _process(delta: float) -> void:
    var dir: Vector3 = Vector3.ZERO
    var b: Basis = global_transform.basis
    if Input.is_key_pressed(KEY_W):
        dir -= b.z
    if Input.is_key_pressed(KEY_S):
        dir += b.z
    if Input.is_key_pressed(KEY_A):
        dir -= b.x
    if Input.is_key_pressed(KEY_D):
        dir += b.x
    if Input.is_key_pressed(KEY_E) or Input.is_key_pressed(KEY_SPACE):
        dir += Vector3.UP
    if Input.is_key_pressed(KEY_Q) or Input.is_key_pressed(KEY_C):
        dir -= Vector3.UP
    if dir == Vector3.ZERO:
        return
    var mult: float = 1.0
    if Input.is_key_pressed(KEY_SHIFT):
        mult = fast_multiplier
    elif Input.is_key_pressed(KEY_CTRL):
        mult = slow_multiplier
    global_position += dir.normalized() * speed * mult * delta
'''

STREAMER_GD = '''extends Node3D
# Streams chunk scenes around the free camera.  Near chunks use the full
# ("high") GLB, farther chunks use the LOD GLB (or the high GLB if a chunk has
# no LOD).  One chunk is instantiated per frame so the camera never freezes.

@export var chunk_size: float = 512.0
@export var high_radius: int = 4
@export var lod_radius: int = 7
@export var unload_radius: int = 8
@export var loads_per_frame: int = 1
@export var attach_collision: bool = false
@export var target_path: NodePath = NodePath("FlyCam")

var loaded: Dictionary = {}
var wanted: Dictionary = {}
var pending: Array = []
var center: Vector2i = Vector2i(999999, 999999)
var target: Node3D
var water: Node3D
var sea_floor: Node3D
var hud: Label
var collision_triangles: int = 0
var hud_timer: float = 0.0
var force_kind: String = ""
var pick_text: String = "F5 = what am I looking at?"
var show_lod_overlay: bool = false
var failed: Dictionary = {}

func _ready() -> void:
    target = get_node_or_null(target_path) as Node3D
    if target == null:
        target = self
    water = get_node_or_null("Water") as Node3D
    sea_floor = get_node_or_null("SeaFloor") as Node3D
    hud = get_node_or_null("HUD") as Label
    _refresh()

func _process(delta: float) -> void:
    _refresh()
    var n: int = 0
    while pending.size() > 0 and n < loads_per_frame:
        var cc: Vector2i = pending.pop_front()
        if wanted.has(cc):
            var kind: String = wanted[cc]
            _load_chunk(cc, kind)
            n += 1
    if water != null:
        var p: Vector3 = target.global_position
        water.global_position = Vector3(p.x, water.global_position.y, p.z)
    if sea_floor != null:
        var q: Vector3 = target.global_position
        sea_floor.global_position = Vector3(q.x, sea_floor.global_position.y, q.z)
    hud_timer += delta
    if hud != null and hud_timer > 0.25:
        hud_timer = 0.0
        _update_hud()

func _update_hud() -> void:
    var p: Vector3 = target.global_position
    var spd: float = 0.0
    if "speed" in target:
        spd = float(target.get("speed"))
    var mode: String = "auto (near=high, far=lod)"
    if force_kind != "":
        mode = "FORCED " + force_kind.to_upper() + " everywhere"
    var nh: int = 0
    var nl: int = 0
    for k in loaded.keys():
        var nd: Node = loaded[k] as Node
        if is_instance_valid(nd) and str(nd.get_meta("kind", "")) == "high":
            nh += 1
        else:
            nl += 1
    hud.text = "FPS %d | chunks high=%d lod=%d (queue %d) | speed %.0f | high_radius=%d\\nGodot xyz: %.0f %.0f %.0f | GTA x=%.0f y=%.0f z=%.0f | chunk %d,%d\\nMODE: %s\\n%s\\nWASD move, Q/C down, E/Space up, Shift fast, Ctrl slow, wheel speed, Esc mouse, F2 home | F4 force high/lod/auto | F5 pick | F6 water on/off | F7 LOD overlay | PgUp/PgDn high_radius" % [Engine.get_frames_per_second(), nh, nl, pending.size(), spd, high_radius, p.x, p.y, p.z, p.x, -p.z, p.y, center.x, center.y, mode, pick_text]
    hud.text += _failed_text()

func _failed_text() -> String:
    if failed.is_empty():
        return ""
    var parts: Array = []
    for k in failed.keys():
        var cc: Vector2i = k
        parts.append("%d,%d" % [cc.x, cc.y])
    return "\\n!! HIGH-DETAIL FAILED (LOD shown instead) in chunks: " + ", ".join(parts)

func _chunk_coord(v: Vector3) -> Vector2i:
    return Vector2i(floori(v.x / chunk_size), floori(v.z / chunk_size))

func _refresh() -> void:
    var c: Vector2i = _chunk_coord(target.global_position)
    if c == center:
        return
    center = c
    wanted.clear()
    pending.clear()
    for x in range(c.x - lod_radius, c.x + lod_radius + 1):
        for z in range(c.y - lod_radius, c.y + lod_radius + 1):
            var cc: Vector2i = Vector2i(x, z)
            var near: bool = absi(x - c.x) <= high_radius and absi(z - c.y) <= high_radius
            var kind: String = "lod"
            if near:
                kind = "high"
            if force_kind != "":
                kind = force_kind
            wanted[cc] = kind
            var have: bool = false
            if loaded.has(cc):
                var node: Node = loaded[cc] as Node
                if is_instance_valid(node) and str(node.get_meta("kind", "")) == kind:
                    have = true
            if not have:
                pending.append(cc)
    pending.sort_custom(func(a: Vector2i, b: Vector2i) -> bool: return a.distance_squared_to(c) < b.distance_squared_to(c))
    for k in loaded.keys():
        var key: Vector2i = k
        if absi(key.x - c.x) > unload_radius or absi(key.y - c.y) > unload_radius:
            var old: Node = loaded[key] as Node
            if is_instance_valid(old):
                old.queue_free()
            loaded.erase(key)

func _scene_path(cc: Vector2i, kind: String) -> String:
    var base: String = "res://world/chunks/chunk_%d_%d" % [cc.x, cc.y]
    var high_path: String = base + ".glb"
    var lod_path: String = base + "_lod.glb"
    if kind == "high":
        if ResourceLoader.exists(high_path):
            failed.erase(cc)
            return high_path
        if FileAccess.file_exists(high_path):
            # The exporter wrote a detailed GLB but Godot has NO imported version of it:
            # the import failed / crashed / was skipped.  Before 0.6.7 this silently showed the
            # LOD model instead, which looked like "the district only exists as LOD".
            failed[cc] = "high GLB exists but is NOT imported"
            push_error("VC2GODOT: chunk %d,%d high GLB not imported -> showing LOD instead" % [cc.x, cc.y])
        if ResourceLoader.exists(lod_path):
            return lod_path
        return ""
    if ResourceLoader.exists(lod_path):
        return lod_path
    if ResourceLoader.exists(high_path):
        return high_path
    return ""

func _load_chunk(cc: Vector2i, kind: String) -> void:
    if loaded.has(cc):
        var current: Node = loaded[cc] as Node
        if is_instance_valid(current):
            if str(current.get_meta("kind", "")) == kind:
                return
            current.queue_free()
        loaded.erase(cc)
    var path: String = _scene_path(cc, kind)
    if path == "":
        return
    var scene: PackedScene = load(path) as PackedScene
    if scene == null:
        failed[cc] = "load() returned null for " + path
        push_error("VC2GODOT: cannot load " + path)
        return
    var node: Node3D = scene.instantiate() as Node3D
    node.set_meta("kind", kind)
    if kind == "high" and path.ends_with("_lod.glb"):
        node.set_meta("fallback", true)
    add_child(node)
    loaded[cc] = node
    if kind == "high" and show_lod_overlay:
        var lod_path: String = "res://world/chunks/chunk_%d_%d_lod.glb" % [cc.x, cc.y]
        if path != lod_path and ResourceLoader.exists(lod_path):
            var lod_scene: PackedScene = load(lod_path) as PackedScene
            if lod_scene != null:
                node.add_child(lod_scene.instantiate())
    if kind == "high" and attach_collision:
        _attach_collision(node, cc)

func _attach_collision(parent: Node3D, cc: Vector2i) -> void:
    var path: String = "res://world/collision/chunk_%d_%d.bin" % [cc.x, cc.y]
    if not FileAccess.file_exists(path):
        return
    var data: PackedByteArray = FileAccess.get_file_as_bytes(path)
    var stream: StreamPeerBuffer = StreamPeerBuffer.new()
    stream.data_array = data
    if stream.get_size() < 8:
        return
    var magic: PackedByteArray = PackedByteArray(stream.get_data(4)[1])
    if magic.get_string_from_ascii() != "VCOL":
        return
    var point_count: int = int(stream.get_u32())
    if point_count < 3 or point_count > 5000000:
        return
    var faces: PackedVector3Array = PackedVector3Array()
    faces.resize(point_count)
    for i in range(point_count):
        faces[i] = Vector3(stream.get_float(), stream.get_float(), stream.get_float())
    var shape: ConcavePolygonShape3D = ConcavePolygonShape3D.new()
    shape.set_faces(faces)
    var body: StaticBody3D = StaticBody3D.new()
    body.name = "Collision"
    var cs: CollisionShape3D = CollisionShape3D.new()
    cs.shape = shape
    body.add_child(cs)
    parent.add_child(body)
    collision_triangles += point_count / 3

func _unhandled_input(e: InputEvent) -> void:
    var key: InputEventKey = e as InputEventKey
    if key == null or not key.pressed or key.echo:
        return
    if key.keycode == KEY_F3:
        print("Loaded chunks: ", loaded.size(), " collision triangles: ", collision_triangles)
    elif key.keycode == KEY_F4:
        if force_kind == "":
            force_kind = "high"
        elif force_kind == "high":
            force_kind = "lod"
        else:
            force_kind = ""
        _reload_all()
    elif key.keycode == KEY_F5:
        _pick()
    elif key.keycode == KEY_F6:
        if water != null:
            water.visible = not water.visible
            if sea_floor != null:
                sea_floor.visible = water.visible
    elif key.keycode == KEY_F7:
        show_lod_overlay = not show_lod_overlay
        _reload_all()
    elif key.keycode == KEY_PAGEUP:
        high_radius = mini(high_radius + 1, 9)
        center = Vector2i(999999, 999999)
    elif key.keycode == KEY_PAGEDOWN:
        high_radius = maxi(high_radius - 1, 0)
        center = Vector2i(999999, 999999)

func _reload_all() -> void:
    for k in loaded.keys():
        var nd: Node = loaded[k] as Node
        if is_instance_valid(nd):
            nd.queue_free()
    loaded.clear()
    pending.clear()
    center = Vector2i(999999, 999999)

func _collect_meshes(node: Node, out: Array) -> void:
    var mi: MeshInstance3D = node as MeshInstance3D
    if mi != null and mi.mesh != null:
        out.append(mi)
    for c in node.get_children():
        _collect_meshes(c, out)

func _pick() -> void:
    var cam: Camera3D = target as Camera3D
    if cam == null:
        return
    var origin: Vector3 = cam.global_position
    var dir: Vector3 = (-cam.global_transform.basis.z).normalized()
    var best_dist: float = 1.0e20
    var best: String = "nothing under the crosshair"
    for k in loaded.keys():
        var chunk: Node = loaded[k] as Node
        if not is_instance_valid(chunk):
            continue
        var kind: String = str(chunk.get_meta("kind", "?"))
        var list: Array = []
        _collect_meshes(chunk, list)
        for item in list:
            var inst: MeshInstance3D = item as MeshInstance3D
            var inv: Transform3D = inst.global_transform.affine_inverse()
            var lo: Vector3 = inv * origin
            var ld: Vector3 = (inv.basis * dir).normalized()
            var box_hit: Variant = inst.get_aabb().intersects_ray(lo, ld)
            if box_hit == null:
                continue
            var tm: TriangleMesh = inst.mesh.generate_triangle_mesh()
            if tm == null:
                continue
            var hit: Dictionary = tm.intersect_ray(lo, ld)
            if hit.is_empty():
                continue
            var wp: Vector3 = inst.global_transform * (hit["position"] as Vector3)
            var d: float = origin.distance_to(wp)
            if d < best_dist:
                best_dist = d
                var mat_name: String = "?"
                var tex_path: String = "(no texture)"
                var mat: Material = inst.mesh.surface_get_material(0)
                if mat != null:
                    mat_name = mat.resource_name
                    var bm: BaseMaterial3D = mat as BaseMaterial3D
                    if bm != null and bm.albedo_texture != null:
                        tex_path = bm.albedo_texture.resource_path
                var cc: Vector2i = k
                best = "PICK %s chunk %d,%d node=%s material=%s tex=%s dist=%.0fm" % [kind.to_upper(), cc.x, cc.y, inst.name, mat_name, tex_path, d]
    pick_text = best
    print(best)
'''

RUN_SH = '''#!/bin/bash
# Imports every new/changed GLB/PNG (fast when nothing changed), VERIFIES that each chunk GLB
# really got imported, retries failed ones, then starts the game.
cd "$(dirname "$0")"
GODOT="${GODOT:-godot}"
check_missing() {
  ls .godot/imported 2>/dev/null > /tmp/vc2godot_imported.txt
  MISSING=()
  for f in world/chunks/*.glb; do
    b="$(basename "$f")"
    if ! grep -q -F "$b-" /tmp/vc2godot_imported.txt; then MISSING+=("$b"); fi
  done
}
for attempt in 1 2 3; do
  "$GODOT" --headless --import --path . 2>&1 | tee import_godot.log || true
  check_missing
  if [[ ${#MISSING[@]} -eq 0 ]]; then break; fi
  echo "== attempt $attempt: ${#MISSING[@]} chunk GLB(s) NOT imported: ${MISSING[*]}"
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "!! Still not imported: ${MISSING[*]}"
  echo "!! Those chunks will show LOD instead of the detailed map. Errors from Godot:"
  grep -i -E "error|failed|invalid|crash" import_godot.log | head -40
fi
exec "$GODOT" --path .
'''


def make_project(out: Path):
    (out/'world').mkdir(parents=True, exist_ok=True)
    (out/'scripts').mkdir(parents=True, exist_ok=True)
    (out/'project.godot').write_text(PROJECT_GODOT, encoding='utf-8')
    (out/'scripts/WorldStreamer.gd').write_text(STREAMER_GD, encoding='utf-8')
    (out/'scripts/FlyCam.gd').write_text(FLYCAM_GD, encoding='utf-8')
    (out/'shaders').mkdir(parents=True, exist_ok=True)
    (out/'shaders/water.gdshader').write_text(WATER_SHADER, encoding='utf-8')
    sh = out/'run_godot.sh'
    sh.write_text(RUN_SH, encoding='utf-8')
    try:
        sh.chmod(0o755)
    except OSError:
        pass
    old = out/'scripts/Player.gd'
    if old.exists():
        old.unlink()


SCENE = '''[gd_scene format=3]

[ext_resource type="Script" path="res://scripts/WorldStreamer.gd" id="1"]
[ext_resource type="Script" path="res://scripts/FlyCam.gd" id="2"]
[ext_resource type="Shader" path="res://shaders/water.gdshader" id="3"]

[sub_resource type="PlaneMesh" id="WaterMesh"]
size = Vector2(16000, 16000)
subdivide_width = 0
subdivide_depth = 0

[sub_resource type="ShaderMaterial" id="WaterMat"]
shader = ExtResource("3")

[sub_resource type="PlaneMesh" id="FloorMesh"]
size = Vector2(16000, 16000)
subdivide_width = 0
subdivide_depth = 0

[sub_resource type="StandardMaterial3D" id="FloorMat"]
shading_mode = 0
albedo_color = Color(0.30, 0.52, 0.55, 1)
cull_mode = 2

[sub_resource type="ProceduralSkyMaterial" id="SkyMaterial"]
sky_top_color = Color(0.16, 0.36, 0.70, 1)
sky_horizon_color = Color(0.78, 0.86, 0.93, 1)
ground_bottom_color = Color(0.10, 0.45, 0.55, 1)
ground_horizon_color = Color(0.78, 0.86, 0.93, 1)

[sub_resource type="Sky" id="Sky"]
sky_material = SubResource("SkyMaterial")

[sub_resource type="Environment" id="Environment"]
background_mode = 2
sky = SubResource("Sky")
ambient_light_source = 2
tonemap_mode = 0
fog_enabled = true
fog_light_color = Color(0.78, 0.86, 0.93, 1)
fog_density = 0.00025

[node name="ViceCity" type="Node3D"]
script = ExtResource("1")
chunk_size = %0.1f

[node name="WorldEnvironment" type="WorldEnvironment" parent="."]
environment = SubResource("Environment")

[node name="Water" type="MeshInstance3D" parent="."]
position = Vector3(0, -0.3, 0)
mesh = SubResource("WaterMesh")
material_override = SubResource("WaterMat")

[node name="SeaFloor" type="MeshInstance3D" parent="."]
position = Vector3(0, -45, 0)
mesh = SubResource("FloorMesh")
material_override = SubResource("FloorMat")

[node name="Sun" type="DirectionalLight3D" parent="."]
rotation_degrees = Vector3(-50, -30, 0)

[node name="FlyCam" type="Camera3D" parent="."]
position = Vector3(%0.3f, %0.3f, %0.3f)
rotation_degrees = Vector3(-25, 0, 0)
current = true
fov = 75.0
near = 0.3
far = 9000.0
script = ExtResource("2")

[node name="HUD" type="Label" parent="."]
offset_left = 12.0
offset_top = 8.0
offset_right = 900.0
offset_bottom = 90.0
theme_override_colors/font_color = Color(1, 1, 1, 1)
theme_override_colors/font_outline_color = Color(0, 0, 0, 1)
theme_override_constants/outline_size = 5
text = "loading..."
'''


def make_world(out: Path, center, chunk_size=512):
    # Start above the centre of the imported world looking slightly down.
    c = center
    text = SCENE % (float(chunk_size), float(c['x']), 250.0, float(c['z']) + 300.0)
    (out/'world/ViceCity.tscn').write_text(text, encoding='utf-8')
