from __future__ import annotations
from pathlib import Path
import json, math, os, re, struct
from array import array
from urllib.parse import quote

from rwfury import Dff, Ifp

from .converter import Converter
from .gltf import validate_glb


# Vice City-era ped names.  If a particular model is absent, it is simply skipped.
DEFAULT_PEDS = [
    "player", "lance", "sonny", "ken", "phil", "diaz", "avery", "cortez",
    "kentpaul", "hilary", "mitchbaker", "lovefist", "mercedes", "candy",
    "alex", "cam", "rico", "jezz"
]

DEFAULT_WEAPONS = [
    ("colt45", "Colt 45"), ("python", "Python"), ("shotgspa", "Shotgun"),
    ("stubby", "Stubby Shotgun"), ("tec9", "Tec-9"), ("uzi", "Uzi"),
    ("mp5", "MP5"), ("m4", "M4"), ("ruger", "Ruger"), ("flamethr", "Flamethrower"),
    ("rocket", "Rocket Launcher"), ("sniper", "Sniper Rifle")
]

C = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, -1.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _mat_mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)) for i in range(4))


def _mat_inv_orth(a):
    r = tuple(tuple(a[i][j] for j in range(3)) for i in range(3))
    t = (a[0][3], a[1][3], a[2][3])
    rt = tuple(tuple(r[j][i] for j in range(3)) for i in range(3))
    out = [[0.0] * 4 for _ in range(4)]
    for i in range(3):
        for j in range(3):
            out[i][j] = rt[i][j]
    for i in range(3):
        out[i][3] = -sum(rt[i][j] * t[j] for j in range(3))
    out[3][3] = 1.0
    return tuple(tuple(x) for x in out)


CI = _mat_inv_orth(C)


def _mat_from9_pos(r, p):
    return (
        (r[0], r[1], r[2], p[0]),
        (r[3], r[4], r[5], p[1]),
        (r[6], r[7], r[8], p[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


def _convert_matrix(m):
    return _mat_mul(_mat_mul(C, m), CI)


def _q_from_m(m):
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2.0
        return ((m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s,
                (m[1][0] - m[0][1]) / s, 0.25 * s)
    if m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(max(1e-12, 1.0 + m[0][0] - m[1][1] - m[2][2])) * 2.0
        return (0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s,
                (m[2][1] - m[1][2]) / s)
    if m[1][1] > m[2][2]:
        s = math.sqrt(max(1e-12, 1.0 + m[1][1] - m[0][0] - m[2][2])) * 2.0
        return ((m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s,
                (m[0][2] - m[2][0]) / s)
    s = math.sqrt(max(1e-12, 1.0 + m[2][2] - m[0][0] - m[1][1])) * 2.0
    return ((m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s,
            0.25 * s, (m[1][0] - m[0][1]) / s)


def _convert_q(q):
    x, y, z, w = q
    # Quaternion -> matrix -> basis change -> quaternion.
    n = x*x + y*y + z*z + w*w
    if n < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    s = 2.0 / n
    m = (
        (1-y*y*s-z*z*s, x*y*s-z*w*s, x*z*s+y*w*s, 0),
        (x*y*s+z*w*s, 1-x*x*s-z*z*s, y*z*s-x*w*s, 0),
        (x*z*s-y*w*s, y*z*s+x*w*s, 1-x*x*s-y*y*s, 0),
        (0, 0, 0, 1),
    )
    return _q_from_m(_convert_matrix(m))


def _f4(data):
    return struct.pack("<%df" % len(data), *data)


def _u4(data):
    return struct.pack("<%dI" % len(data), *data)


def _u1(data):
    return bytes(int(max(0, min(255, x))) for x in data)


def _add_view(blob, views, data, target=None):
    while len(blob) % 4:
        blob.append(0)
    off = len(blob)
    blob.extend(data)
    v = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
    if target is not None:
        v["target"] = target
    views.append(v)
    return len(views) - 1


def _add_accessor(accessors, view, component, typ, count, mn=None, mx=None):
    a = {"bufferView": view, "componentType": component, "count": count, "type": typ}
    if mn is not None:
        a["min"] = mn
    if mx is not None:
        a["max"] = mx
    accessors.append(a)
    return len(accessors) - 1


def _pack_glb(gltf, blob, path):
    js = json.dumps(gltf, separators=(",", ":"), allow_nan=False).encode("utf-8")
    while len(js) % 4:
        js += b" "
    while len(blob) % 4:
        blob.append(0)
    total = 12 + 8 + len(js) + 8 + len(blob)
    out = bytearray(struct.pack("<4sII", b"glTF", 2, total))
    out.extend(struct.pack("<II", len(js), 0x4E4F534A)); out.extend(js)
    out.extend(struct.pack("<II", len(blob), 0x004E4942)); out.extend(blob)
    Path(path).write_bytes(out)


def _find_ifp(converter, candidates):
    for name in candidates:
        data = converter.find_bytes(name if name.lower().endswith(".ifp") else name + ".ifp")
        if data:
            return data, name
    return None, None


def _ped_file_candidates(name):
    n = name.lower()
    return [n + ".dff", "models/" + n + ".dff", "gta3.img/" + n + ".dff"]


def _texture_map_for_dff(converter, dff, dff_name):
    texmap = {}
    txd_candidates = []
    # DFF materials carry texture names but not the TXD owner. Reuse the same
    # shared dictionaries used by the world importer and search all TXDs as fallback.
    for g in dff.geometries:
        for mat in g.materials:
            if mat.texture_name:
                if not txd_candidates:
                    txd_candidates = [Path(dff_name).stem]
                for t in txd_candidates:
                    texmap.update(converter.txd(t))
    for t in ("generic", "particle"):
        texmap.update(converter.txd(t))
    return texmap


def export_ped(converter, name, out_dir, ifp_bytes=None):
    dff_data = converter.find_bytes(name + ".dff")
    if not dff_data:
        return None
    dff = Dff.from_bytes(dff_data)
    meshes = dff.to_generic_meshes()
    meshes = [m for m in meshes if m.positions and m.indices]
    if not meshes:
        return None
    if not any(m.has_skinning for m in meshes):
        # Vice City's stock player models may use frame hierarchy but no SkinPLG.
        # We still export them as a normal animated scene; animation support is only
        # attached when a real skinned DFF is present.
        pass

    texmap = _texture_map_for_dff(converter, dff, name)
    blob = bytearray(); views=[]; accessors=[]; images=[]; textures=[]; materials=[]; meshes_json=[]; nodes=[]
    img_index={}
    def tex_index(path):
        k=str(path).lower()
        if k in img_index: return img_index[k]
        try: rel=os.path.relpath(Path(path).resolve(), (Path(out_dir)/"characters").resolve()).replace("\\","/")
        except Exception: rel=str(path)
        images.append({"uri":quote(rel, safe="/._-"),"name":Path(path).stem})
        textures.append({"sampler":0,"source":len(images)-1})
        img_index[k]=len(textures)-1
        return img_index[k]

    # Build skeleton from DFF frames.
    frame_to_node={}
    frame_name_to_index={}
    for fi, fr in enumerate(dff.frames):
        frame_to_node[fi]=len(nodes)
        if fr.name:
            frame_name_to_index.setdefault(fr.name, fi)
        m=_convert_matrix(_mat_from9_pos(fr.rotation_matrix, fr.position))
        q=_q_from_m(m)
        node={"name":fr.name or ("bone_%d"%fi)}
        node["translation"]=[m[0][3],m[1][3],m[2][3]]
        node["rotation"]=list(q)
        if fr.parent >= 0:
            pass
        nodes.append(node)
    for fi, fr in enumerate(dff.frames):
        if fr.parent >= 0 and fr.parent in frame_to_node:
            nodes[frame_to_node[fr.parent]].setdefault("children",[]).append(frame_to_node[fi])
    if not dff.frames:
        frame_to_node[0]=len(nodes)
        frame_name_to_index["root"]=0
        nodes.append({"name": name + "_Root"})

    # Skin joints in HAnim/skin order.
    hanim=dff.get_hanim_bones()
    joint_pairs=[]
    for b in hanim:
        fi=dff.get_hanim_frame_index(b.node_id)
        if fi is not None:
            # rwfury's SkinPLG bone_indices are already skin-bone indices.
            # HAnimBone.node_index is the skin index that corresponds to that entry.
            joint_pairs.append((int(b.node_index), int(fi)))
    joint_pairs.sort()
    joint_frames=[]
    skin_index_by_node={}
    if joint_pairs:
        max_skin_index=max(node_i for node_i,_ in joint_pairs)
        joint_frames=[0]*(max_skin_index+1)
        for skin_i, frame_i in joint_pairs:
            joint_frames[skin_i]=frame_i
            skin_index_by_node[skin_i]=skin_i
    if not joint_frames and dff.frames:
        joint_frames=list(range(len(dff.frames)))
        skin_index_by_node={i:i for i in range(len(joint_frames))}

    # inverse bind matrices
    ibms=[]
    for fi in joint_frames:
        # Locate the skin index by the HAnim node_index.
        si=skin_index_by_node.get(next((b.node_index for b in hanim if dff.get_hanim_frame_index(b.node_id)==fi),0),0)
        raw=None
        for g in dff.geometries:
            if g.skin and si < len(g.skin.inverse_matrices):
                raw=g.skin.inverse_matrices[si]; break
        if raw is None:
            raw=((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))
        flat=list(raw)
        if len(flat)==16:
            mat=tuple(tuple(float(flat[r*4+c]) for c in range(4)) for r in range(4))
        else:
            mat=((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))
        mat=_convert_matrix(mat)
        ibms.extend([mat[r][c] for c in range(4) for r in range(4)])

    skin_index_glb = -1
    skins = []
    if joint_frames and any(m.has_skinning for m in meshes):
        ibm_view=_add_view(blob,views,_f4(ibms))
        ibm_acc=_add_accessor(accessors,ibm_view,5126,"MAT4",len(joint_frames))
        skins.append({"joints":[frame_to_node[f] for f in joint_frames],"inverseBindMatrices":ibm_acc,"skeleton":frame_to_node.get(0,0)})
        skin_index_glb=0

    for mi,m in enumerate(meshes):
        n=m.vertex_count
        pos=[float(x) for x in m.positions]
        # VC -> Godot/glTF basis.
        P=[]
        for i in range(0,len(pos),3):
            x,y,z=pos[i:i+3]; P.extend((x,z,-y))
        nor=[]
        for i in range(0,len(m.normals),3):
            x,y,z=m.normals[i:i+3]; nor.extend((x,z,-y))
        uv=(m.texcoords[0] if m.texcoords else [0.0,0.0]*n)
        col=m.colors if m.colors else [255,255,255,255]*n
        joints = []
        weights = []
        if m.has_skinning and skin_index_glb >= 0:
            joints=list(m.bone_indices)
            weights=list(m.bone_weights)
            # SkinPLG already stores indices in skin-bone order. Keep those indices unchanged
            # so they line up with glTF skin.joints above; clamp corrupt/out-of-range values.
            max_joint_index=max(0, len(joint_frames)-1)
            joints=[min(max(int(j), 0), max_joint_index) for j in joints]
            for i in range(0,len(weights),4):
                s=sum(weights[i:i+4]) or 1.0
                weights[i:i+4]=[w/s for w in weights[i:i+4]]
        pa=_add_accessor(accessors,_add_view(blob,views,_f4(P),34962),5126,"VEC3",n)
        na=_add_accessor(accessors,_add_view(blob,views,_f4(nor if len(nor)==n*3 else [0,1,0]*n),34962),5126,"VEC3",n)
        ua=_add_accessor(accessors,_add_view(blob,views,_f4(uv),34962),5126,"VEC2",n)
        ca=_add_accessor(accessors,_add_view(blob,views,_u1(col),34962),5121,"VEC4",n); accessors[ca]["normalized"]=True
        attrs={"POSITION":pa,"NORMAL":na,"TEXCOORD_0":ua,"COLOR_0":ca}
        if m.has_skinning and skin_index_glb >= 0:
            ja=_add_accessor(accessors,_add_view(blob,views,_u1(joints),34962),5121,"VEC4",n)
            wa=_add_accessor(accessors,_add_view(blob,views,_f4(weights),34962),5126,"VEC4",n)
            attrs["JOINTS_0"]=ja
            attrs["WEIGHTS_0"]=wa
        ia=_add_accessor(accessors,_add_view(blob,views,_u4(m.indices),34963),5125,"SCALAR",len(m.indices))
        tex=texmap.get((m.texture_name or "").casefold())
        mat={"name":m.texture_name or "ped_default","pbrMetallicRoughness":{"baseColorFactor":[1,1,1,1],"roughnessFactor":1.0},"doubleSided":True}
        if tex and Path(tex).is_file():
            mat["pbrMetallicRoughness"]["baseColorTexture"]={"index":tex_index(tex)}
        materials.append(mat); mat_i=len(materials)-1
        meshes_json.append({"name":m.name or ("mesh_%d"%mi),"primitives":[{"attributes":attrs,"indices":ia,"material":mat_i}]})
        node={"name":m.name or ("mesh_%d"%mi),"mesh":len(meshes_json)-1}
        if m.has_skinning and skin_index_glb >= 0:
            node["skin"]=skin_index_glb
        nodes.append(node)
        mesh_node_index=len(nodes)-1
        # GenericMesh.name is the RenderWare atomic's frame name in rwfury.
        # Non-skinned peds must be parented to that frame or their limbs/body parts
        # remain at the wrong transform. Skinned meshes are driven by the glTF skin.
        frame_index=frame_name_to_index.get(m.name or "", 0)
        parent_node=frame_to_node.get(frame_index, frame_to_node.get(0, mesh_node_index))
        nodes[parent_node].setdefault("children",[]).append(mesh_node_index)

    # Root scene uses frame 0.
    root=frame_to_node.get(0,0)

    animations=[]
    if ifp_bytes:
        try:
            ifp=Ifp.from_bytes(ifp_bytes)
            generic=ifp.to_generic_animation_set()
            for clip in generic.animations:
                channels=[]; samplers=[]
                for tr in clip.tracks:
                    fi=dff.get_hanim_frame_index(tr.bone_id)
                    if fi is None or fi not in frame_to_node or not tr.times:
                        continue
                    # rotation
                    rot=[]
                    trans=[]; scale=[]
                    has_t=tr.translations is not None
                    has_s=tr.scales is not None
                    for k in range(tr.keyframe_count):
                        q=tr.rotations[k*4:k*4+4]
                        rot.extend(_convert_q(q))
                        if has_t:
                            v=tr.translations[k*3:k*3+3]; trans.extend((v[0],v[2],-v[1]))
                        if has_s:
                            scale.extend(tr.scales[k*3:k*3+3])
                    tv=_add_accessor(accessors,_add_view(blob,views,_f4(tr.times)),5126,"SCALAR",len(tr.times))
                    rv=_add_accessor(accessors,_add_view(blob,views,_f4(rot)),5126,"VEC4",len(tr.times))
                    sidx=len(samplers); samplers.append({"input":tv,"output":rv,"interpolation":"LINEAR"})
                    channels.append({"sampler":sidx,"target":{"node":frame_to_node[fi],"path":"rotation"}})
                    if has_t:
                        tv2=_add_accessor(accessors,_add_view(blob,views,_f4(trans)),5126,"VEC3",len(tr.times))
                        s2=len(samplers); samplers.append({"input":tv,"output":tv2,"interpolation":"LINEAR"})
                        channels.append({"sampler":s2,"target":{"node":frame_to_node[fi],"path":"translation"}})
                    if has_s:
                        sv=_add_accessor(accessors,_add_view(blob,views,_f4(scale)),5126,"VEC3",len(tr.times))
                        s3=len(samplers); samplers.append({"input":tv,"output":sv,"interpolation":"LINEAR"})
                        channels.append({"sampler":s3,"target":{"node":frame_to_node[fi],"path":"scale"}})
                if channels:
                    animations.append({"name":clip.name,"samplers":samplers,"channels":channels})
        except Exception as exc:
            print("WARNING: animation export failed for",name,":",exc)

    gltf={
        "asset":{"version":"2.0","generator":"vc2godot character importer"},
        "scene":0,"scenes":[{"nodes":[root]}],"nodes":nodes,
        "meshes":meshes_json,"skins":skins,"materials":materials,
        "images":images,"textures":textures,
        "samplers":[{"magFilter":9729,"minFilter":9987,"wrapS":10497,"wrapT":10497}],
        "buffers":[{"byteLength":len(blob)}],"bufferViews":views,"accessors":accessors,
        "animations":animations,
    }
    out_dir=Path(out_dir); out_dir.mkdir(parents=True,exist_ok=True)
    path=out_dir/(name+".glb")
    _pack_glb(gltf,blob,path)
    try:
        bad,stats=validate_glb(path)
        if bad: print("WARNING invalid character GLB",path,bad[:3])
    except Exception:
        pass
    return {"id":name,"name":name.replace("_"," ").title(),"path":"characters/"+path.name,
            "animations":[a["name"] for a in animations], "skinned":any(m.has_skinning for m in meshes)}


def export_weapon(converter, model, label, out_dir):
    from .gltf import mesh_records, export_records
    data=converter.meshes(model, Path(model).stem)
    if not data:
        # retry with likely texture dictionary name equal to model.
        data=converter.meshes(model, model)
    if not data: return None
    meshes,texmap=data
    records=mesh_records(meshes,texmap,model)
    if not records:return None
    out=Path(out_dir)/(model+".glb"); export_records(records,out)
    return {"id":model,"name":label,"path":"weapons/"+out.name}


def export_characters_and_weapons(converter, out):
    out=Path(out); char_dir=out/"assets/gameplay/characters"; weapon_dir=out/"assets/gameplay/weapons"
    char_dir.mkdir(parents=True,exist_ok=True); weapon_dir.mkdir(parents=True,exist_ok=True)
    # Common VC ped animation package. We deliberately try several locations because
    # retail/modded installs place the IFP in different IMG/loose-file layouts.
    ifp_bytes,_=_find_ifp(converter,["ped.ifp","anim/ped.ifp","models/ped.ifp","ped"])
    chars=[]
    for name in DEFAULT_PEDS:
        try:
            item=export_ped(converter,name,char_dir,ifp_bytes)
            if item: chars.append(item)
        except Exception as exc:
            print("WARNING: ped",name,"failed:",exc)
    weapons=[]
    for model,label in DEFAULT_WEAPONS:
        try:
            item=export_weapon(converter,model,label,weapon_dir)
            if item: weapons.append(item)
        except Exception as exc:
            print("WARNING: weapon",model,"failed:",exc)
    data_dir=out/"data"; data_dir.mkdir(exist_ok=True)
    (data_dir/"characters.json").write_text(json.dumps(chars,indent=2),encoding="utf-8")
    (data_dir/"weapons.json").write_text(json.dumps(weapons,indent=2),encoding="utf-8")
    vehicles = export_vehicles(converter, out)
    return chars,weapons,vehicles

DEFAULT_VEHICLES = [
    ("infernus", "Infernus"),
    ("cheetah", "Cheetah"),
    ("sentinel", "Sentinel"),
    ("cuban", "Cuban Hermes"),
]


def export_vehicle(converter, model, label, out_dir):
    from .gltf import mesh_records, export_records
    data = converter.meshes(model, Path(model).stem)
    if not data:
        data = converter.meshes(model, model)
    if not data:
        return None
    meshes, texmap = data
    records = mesh_records(meshes, texmap, model)
    if not records:
        return None
    out = Path(out_dir) / (model + ".glb")
    export_records(records, out)
    return {"id": model, "name": label, "path": "vehicles/" + out.name}


def export_vehicles(converter, out):
    out = Path(out)
    vehicle_dir = out / "assets/gameplay/vehicles"
    vehicle_dir.mkdir(parents=True, exist_ok=True)
    vehicles = []
    for model, label in DEFAULT_VEHICLES:
        try:
            item = export_vehicle(converter, model, label, vehicle_dir)
            if item:
                vehicles.append(item)
        except Exception as exc:
            print("WARNING: vehicle", model, "failed:", exc)
    (out / "data/vehicles.json").write_text(json.dumps(vehicles, indent=2), encoding="utf-8")
    return vehicles
