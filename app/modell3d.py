"""3D-Modelle (GLB, wie trellis.cpp sie schreibt) weiterverwenden – ohne Zusatzpakete:

- to_stl(): für den 3D-Druck als STL (binär), Z nach oben, auf die gewünschte Höhe in Millimetern gebracht und mittig
  auf die Druckplatte gestellt (der unterste Punkt liegt auf 0). Farben und Texturen kennt STL nicht.
- write_viewer(): eine eigenständige HTML-Seite mit kleinem WebGL-Betrachter, in der das Modell steckt (base64). Sie
  öffnet sich im Browser auch ohne Internet und ohne Server – Browser laden aus file:// keine Nachbardateien.
"""

from i18n import get_language, tr

import base64
import html
import json
import math
import struct
from array import array
from pathlib import Path

_JSON, _BIN = 0x4E4F534A, 0x004E4942
_COMP = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


# ---------------------------------------------------------------- GLB lesen

def read_glb(data: bytes) -> tuple[dict, bytes]:
    """GLB → (glTF-JSON, Binärteil)."""
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(tr('Das ist keine GLB-Datei.'))
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise ValueError(tr('Nur GLB-Dateien der Version 2 werden unterstützt.'))
    off, doc, binary = 12, None, b""
    end = min(length, len(data))
    while off + 8 <= end:
        size, kind = struct.unpack_from("<II", data, off)
        chunk = data[off + 8:off + 8 + size]
        if kind == _JSON and doc is None:
            doc = json.loads(chunk.decode("utf-8"))
        elif kind == _BIN and not binary:
            binary = bytes(chunk)
        off += 8 + size
    if not isinstance(doc, dict):
        raise ValueError(tr('Die GLB-Datei ist beschädigt.'))
    return doc, binary


def _accessor(doc: dict, binary: bytes, index: int) -> array:
    """Werte eines Accessors als flaches array (Komponenten hintereinander)."""
    acc = doc["accessors"][index]
    if "bufferView" not in acc or acc.get("sparse"):
        raise ValueError(tr('Diese GLB-Datei nutzt eine nicht unterstützte Speicherform.'))
    view = doc["bufferViews"][acc["bufferView"]]
    fmt, n, count = _COMP[acc["componentType"]], _COUNT[acc["type"]], int(acc["count"])
    size = struct.calcsize(fmt)
    start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    stride = int(view.get("byteStride") or size * n)
    out = array(fmt)
    if stride == size * n:
        out.frombytes(binary[start:start + count * n * size])
    else:  # verschränkte Daten: Element für Element
        item = struct.Struct("<" + fmt * n)
        for i in range(count):
            out.extend(item.unpack_from(binary, start + i * stride))
    if len(out) != count * n:
        raise ValueError(tr('Die GLB-Datei ist beschädigt.'))
    return out


def _mul(a: list, b: list) -> list:
    """4×4-Matrizen (spaltenweise wie glTF) multiplizieren: a · b."""
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def _local(node: dict) -> list:
    if "matrix" in node:
        return [float(v) for v in node["matrix"]]
    tx, ty, tz = node.get("translation", (0, 0, 0))
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    sx, sy, sz = node.get("scale", (1, 1, 1))
    r = [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w),
         2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w),
         2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]
    return [r[0] * sx, r[1] * sx, r[2] * sx, 0, r[3] * sy, r[4] * sy, r[5] * sy, 0,
            r[6] * sz, r[7] * sz, r[8] * sz, 0, tx, ty, tz, 1]


def triangles(doc: dict, binary: bytes) -> tuple[list[float], array]:
    """Alle Dreiecke der Szene in Weltkoordinaten: (Positionen flach x,y,z,…, Indizes je drei)."""
    nodes = doc.get("nodes", [])
    scenes = doc.get("scenes") or [{"nodes": list(range(len(nodes)))}]
    roots = scenes[int(doc.get("scene", 0))].get("nodes", [])
    positions: list[float] = []
    indices = array("I")
    ident = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    stack = [(i, ident, 0) for i in roots]
    while stack:
        i, parent, depth = stack.pop()
        if depth > 64:  # Schleife in der Datei
            continue
        node = nodes[i]
        m = _mul(parent, _local(node))
        stack.extend((c, m, depth + 1) for c in node.get("children", []))
        if "mesh" not in node:
            continue
        for prim in doc["meshes"][node["mesh"]].get("primitives", []):
            if prim.get("mode", 4) != 4 or "POSITION" not in prim.get("attributes", {}):
                continue  # nur Dreiecke
            pos = _accessor(doc, binary, prim["attributes"]["POSITION"])
            base = len(positions) // 3
            for k in range(0, len(pos), 3):
                x, y, z = pos[k], pos[k + 1], pos[k + 2]
                positions += (m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13],
                              m[2] * x + m[6] * y + m[10] * z + m[14])
            idx = _accessor(doc, binary, prim["indices"]) if "indices" in prim else range(len(pos) // 3)
            count = len(idx) - len(idx) % 3
            indices.extend(base + int(idx[k]) for k in range(count))
    return positions, indices


def stats(glb: Path) -> dict:
    """Dreiecke und Seitenverhältnisse (Breite, Tiefe, Höhe relativ) eines GLB – für die Anzeige."""
    doc, binary = read_glb(Path(glb).read_bytes())
    pos, idx = triangles(doc, binary)
    if not pos:
        return {"triangles": 0, "size": (0.0, 0.0, 0.0)}
    ext = [max(pos[a::3]) - min(pos[a::3]) for a in range(3)]
    return {"triangles": len(idx) // 3, "size": (ext[0], ext[2], ext[1])}


# ---------------------------------------------------------------- STL

def to_stl(glb: Path, stl: Path, height_mm: float = 100.0) -> tuple[float, float, float]:
    """GLB → binäre STL für den 3D-Druck. glTF hat Y oben, Drucker Z oben: (x, y, z) → (x, −z, y). Das Modell wird auf
    height_mm Höhe gebracht, auf der Platte mittig ausgerichtet und auf z = 0 gestellt. → (Breite, Tiefe, Höhe) in mm."""
    if not height_mm or height_mm <= 0:
        raise ValueError(tr('Die Höhe muss größer als 0 sein.'))
    doc, binary = read_glb(Path(glb).read_bytes())
    pos, idx = triangles(doc, binary)
    if not idx:
        raise ValueError(tr('Das Modell enthält keine Flächen.'))
    xs, ys, zs = pos[0::3], [-v for v in pos[2::3]], pos[1::3]
    lo = (min(xs), min(ys), min(zs))
    hi = (max(xs), max(ys), max(zs))
    if hi[2] - lo[2] <= 0:
        raise ValueError(tr('Das Modell ist flach – es lässt sich nicht auf eine Höhe bringen.'))
    f = height_mm / (hi[2] - lo[2])
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    verts = [((x - cx) * f, (y - cy) * f, (z - lo[2]) * f) for x, y, z in zip(xs, ys, zs)]
    n = len(idx) // 3
    out = bytearray(84 + 50 * n)
    head = b"Monhip - 3D-Modell (TRELLIS.2) als STL, Einheit mm"
    out[:len(head)] = head
    struct.pack_into("<I", out, 80, n)
    face = struct.Struct("<12fH")
    off = 84
    for k in range(0, 3 * n, 3):
        a, b, c = verts[idx[k]], verts[idx[k + 1]], verts[idx[k + 2]]
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        face.pack_into(out, off, nx / length, ny / length, nz / length, *a, *b, *c, 0)
        off += 50
    stl = Path(stl)
    tmp = stl.with_name(stl.name + ".part")
    tmp.write_bytes(out)
    tmp.replace(stl)
    return (hi[0] - lo[0]) * f, (hi[1] - lo[1]) * f, height_mm


# ---------------------------------------------------------------- Betrachter im Browser

def viewer_html(glb: Path, title: str) -> str:
    """Eigenständige HTML-Seite, die das GLB im Browser zeigt (drehen, zoomen, verschieben)."""
    labels = {
        "title": title, "spin": tr('Drehen'), "background": tr('Hintergrund'), "reset": tr('Ansicht zurücksetzen'),
        "hint": tr('Ziehen: drehen · Mausrad: zoomen · rechte Maustaste oder Umschalt+Ziehen: verschieben · '
                   'Doppelklick: zurücksetzen'),
        "triangles": tr('{0} Dreiecke'), "noWebgl": tr('Dieser Browser kann kein WebGL 2 – das Modell lässt sich hier '
                                                      'nicht zeigen. Die GLB-Datei öffnet auch Blender.'),
        "broken": tr('Das Modell ließ sich nicht lesen'),
    }
    data = base64.b64encode(Path(glb).read_bytes()).decode("ascii")
    page = (_PAGE.replace("%%LANG%%", get_language() or "de").replace("%%TITLE%%", html.escape(title))
            .replace("%%LABELS%%", json.dumps(labels, ensure_ascii=False).replace("<", "\\u003c")))  # nie ein Tag
    return page.replace("%%GLB%%", data)


def write_viewer(glb: Path, dest: Path, title: str) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(viewer_html(glb, title), encoding="utf-8")
    return dest


_PAGE = r"""<!doctype html>
<html lang="%%LANG%%"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%%TITLE%%</title>
<style>
html,body{margin:0;height:100%;overflow:hidden;background:#202020;color:#e6e6e6;font:14px system-ui,"Segoe UI",sans-serif}
body.hell{background:#f2f2f2;color:#1b1b1b}
canvas{display:block;width:100vw;height:100vh;touch-action:none;cursor:grab}
canvas:active{cursor:grabbing}
#bar{position:fixed;left:12px;right:12px;top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;font-weight:600;margin:0 8px 0 0;max-width:50vw;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
button{font:inherit;color:inherit;background:rgba(128,128,128,.18);border:1px solid rgba(128,128,128,.45);
border-radius:6px;padding:4px 10px;cursor:pointer}
button[aria-pressed=true]{background:rgba(217,119,87,.35)}
#hint{position:fixed;left:12px;right:12px;bottom:10px;font-size:12px;opacity:.7}
#msg{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;
pointer-events:none}
</style></head><body>
<canvas id="c"></canvas>
<div id="bar"><h1 id="title"></h1><button id="spin" aria-pressed="false"></button><button id="bg"></button>
<button id="reset"></button></div>
<div id="hint"></div><div id="msg"></div>
<script>
const T = %%LABELS%%;
const GLB = "%%GLB%%";
(function () {
"use strict";
const $ = id => document.getElementById(id);
$("title").textContent = T.title;
$("spin").textContent = T.spin; $("bg").textContent = T.background; $("reset").textContent = T.reset;
const msg = t => { $("msg").textContent = t; };
const canvas = $("c");
const gl = canvas.getContext("webgl2", {antialias: true});
if (!gl) { msg(T.noWebgl); return; }

// ---- GLB lesen
const raw = atob(GLB), data = new Uint8Array(raw.length);
for (let i = 0; i < raw.length; i++) data[i] = raw.charCodeAt(i);
const dv = new DataView(data.buffer);
let doc = null, bin = null;
try {
  if (dv.getUint32(0, true) !== 0x46546C67) throw new Error("glTF");
  for (let off = 12; off + 8 <= data.length;) {
    const len = dv.getUint32(off, true), type = dv.getUint32(off + 4, true);
    if (type === 0x4E4F534A && !doc) doc = JSON.parse(new TextDecoder().decode(data.subarray(off + 8, off + 8 + len)));
    else if (type === 0x004E4942 && !bin) bin = data.slice(off + 8, off + 8 + len);
    off += 8 + len;
  }
  if (!doc) throw new Error("JSON");
} catch (e) { msg(T.broken + ": " + e.message); return; }
const COMP = {5120: Int8Array, 5121: Uint8Array, 5122: Int16Array, 5123: Uint16Array, 5125: Uint32Array, 5126: Float32Array};
const GET = {5120: "getInt8", 5121: "getUint8", 5122: "getInt16", 5123: "getUint16", 5125: "getUint32", 5126: "getFloat32"};
const NUM = {SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4};
function accessor(i) {
  const a = doc.accessors[i], v = doc.bufferViews[a.bufferView], C = COMP[a.componentType], n = NUM[a.type];
  const size = C.BYTES_PER_ELEMENT, start = (v.byteOffset || 0) + (a.byteOffset || 0), stride = v.byteStride || size * n;
  if (stride === size * n) return new C(bin.buffer.slice(start, start + a.count * n * size));
  const out = new C(a.count * n), src = new DataView(bin.buffer), get = GET[a.componentType];
  for (let k = 0; k < a.count; k++) for (let j = 0; j < n; j++) out[k * n + j] = src[get](start + k * stride + j * size, true);
  return out;
}

// ---- kleine Matrizen (spaltenweise)
function mul(a, b) { const o = new Array(16); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
  let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s; } return o; }
function local(n) {
  if (n.matrix) return n.matrix.slice();
  const [tx, ty, tz] = n.translation || [0, 0, 0], [x, y, z, w] = n.rotation || [0, 0, 0, 1], [sx, sy, sz] = n.scale || [1, 1, 1];
  return [(1 - 2 * (y * y + z * z)) * sx, 2 * (x * y + z * w) * sx, 2 * (x * z - y * w) * sx, 0,
          2 * (x * y - z * w) * sy, (1 - 2 * (x * x + z * z)) * sy, 2 * (y * z + x * w) * sy, 0,
          2 * (x * z + y * w) * sz, 2 * (y * z - x * w) * sz, (1 - 2 * (x * x + y * y)) * sz, 0, tx, ty, tz, 1];
}
function perspective(fov, aspect, near, far) { const f = 1 / Math.tan(fov / 2), nf = 1 / (near - far);
  return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]; }
function lookAt(e, t) {
  let zx = e[0] - t[0], zy = e[1] - t[1], zz = e[2] - t[2], l = Math.hypot(zx, zy, zz); zx /= l; zy /= l; zz /= l;
  let xx = zz, xy = 0, xz = -zx; l = Math.hypot(xx, xz) || 1; xx /= l; xz /= l;   // oben = +Y
  const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;
  return [xx, yx, zx, 0, xy, yy, zy, 0, xz, yz, zz, 0,
          -(xx * e[0] + xy * e[1] + xz * e[2]), -(yx * e[0] + yy * e[1] + yz * e[2]), -(zx * e[0] + zy * e[1] + zz * e[2]), 1];
}

// ---- Szene: Dreiecke in Weltkoordinaten (Knoten-Transformationen eingerechnet)
const prims = [], lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
let triangleCount = 0;
try {
  const nodes = doc.nodes || [], scenes = doc.scenes || [{nodes: nodes.map((_, i) => i)}];
  const stack = (scenes[doc.scene || 0].nodes || []).map(i => [i, [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]]);
  while (stack.length) {
    const [i, parent] = stack.pop(), node = nodes[i], m = mul(parent, local(node));
    (node.children || []).forEach(c => stack.push([c, m]));
    if (node.mesh === undefined) continue;
    for (const p of doc.meshes[node.mesh].primitives || []) {
      if ((p.mode ?? 4) !== 4 || p.attributes.POSITION === undefined) continue;
      const pos = accessor(p.attributes.POSITION), n = pos.length / 3;
      for (let k = 0; k < n; k++) {
        const x = pos[3 * k], y = pos[3 * k + 1], z = pos[3 * k + 2];
        for (let a = 0; a < 3; a++) {
          const v = m[a] * x + m[4 + a] * y + m[8 + a] * z + m[12 + a];
          pos[3 * k + a] = v; if (v < lo[a]) lo[a] = v; if (v > hi[a]) hi[a] = v;
        }
      }
      const idx = p.indices !== undefined ? accessor(p.indices) : Uint32Array.from({length: n}, (_, k) => k);
      let nrm = p.attributes.NORMAL !== undefined ? accessor(p.attributes.NORMAL) : null;
      if (nrm) for (let k = 0; k < n; k++) {
        const x = nrm[3 * k], y = nrm[3 * k + 1], z = nrm[3 * k + 2];
        const a = m[0] * x + m[4] * y + m[8] * z, b = m[1] * x + m[5] * y + m[9] * z, c = m[2] * x + m[6] * y + m[10] * z;
        const l = Math.hypot(a, b, c) || 1; nrm[3 * k] = a / l; nrm[3 * k + 1] = b / l; nrm[3 * k + 2] = c / l;
      } else {  // ohne Normalen: aus den Flächen mitteln
        nrm = new Float32Array(pos.length);
        for (let k = 0; k + 2 < idx.length; k += 3) {
          const a = idx[k] * 3, b = idx[k + 1] * 3, c = idx[k + 2] * 3;
          const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
          const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
          const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
          for (const q of [a, b, c]) { nrm[q] += nx; nrm[q + 1] += ny; nrm[q + 2] += nz; }
        }
        for (let k = 0; k < nrm.length; k += 3) {
          const l = Math.hypot(nrm[k], nrm[k + 1], nrm[k + 2]) || 1; nrm[k] /= l; nrm[k + 1] /= l; nrm[k + 2] /= l; }
      }
      const uv = p.attributes.TEXCOORD_0 !== undefined ? accessor(p.attributes.TEXCOORD_0) : null;
      let col = null;
      if (p.attributes.COLOR_0 !== undefined && doc.accessors[p.attributes.COLOR_0].componentType === 5126)
        col = {data: accessor(p.attributes.COLOR_0), size: NUM[doc.accessors[p.attributes.COLOR_0].type]};
      const mat = (doc.materials || [])[p.material] || {}, pbr = mat.pbrMetallicRoughness || {};
      prims.push({pos, nrm, uv, col, idx, factor: pbr.baseColorFactor || [1, 1, 1, 1],
                  tex: pbr.baseColorTexture ? pbr.baseColorTexture.index : null});
      triangleCount += Math.floor(idx.length / 3);
    }
  }
  if (!prims.length) throw new Error("mesh");
} catch (e) { msg(T.broken + ": " + e.message); return; }
$("hint").textContent = T.triangles.replace("{0}", triangleCount.toLocaleString()) + "  ·  " + T.hint;

// ---- Grafik
function shader(type, src) { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; }
const prog = gl.createProgram();
gl.attachShader(prog, shader(gl.VERTEX_SHADER, `#version 300 es
layout(location=0) in vec3 aPos; layout(location=1) in vec3 aNrm; layout(location=2) in vec2 aUv;
layout(location=3) in vec4 aCol;
uniform mat4 uProj, uView; out vec3 vNrm, vPos; out vec2 vUv; out vec4 vCol;
void main() { vec4 p = uView * vec4(aPos, 1.0); vPos = p.xyz; vNrm = mat3(uView) * aNrm; vUv = aUv; vCol = aCol;
  gl_Position = uProj * p; }`));
gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, `#version 300 es
precision highp float;
in vec3 vNrm, vPos; in vec2 vUv; in vec4 vCol; uniform sampler2D uTex; uniform bool uHasTex; uniform vec4 uFactor;
out vec4 outColor;
void main() {
  vec4 base = uFactor * vCol; if (uHasTex) base *= texture(uTex, vUv);
  vec3 n = normalize(vNrm); if (!gl_FrontFacing) n = -n;
  vec3 v = normalize(-vPos), key = normalize(vec3(0.45, 0.65, 0.6)), fill = normalize(vec3(-0.6, -0.1, 0.5));
  float hemi = 0.5 + 0.5 * n.y;
  vec3 light = mix(vec3(0.16, 0.15, 0.14), vec3(0.30, 0.31, 0.34), hemi)
             + vec3(1.0, 0.97, 0.92) * max(dot(n, key), 0.0) * 0.85 + vec3(0.55, 0.62, 0.75) * max(dot(n, fill), 0.0) * 0.35;
  float spec = pow(max(dot(n, normalize(key + v)), 0.0), 40.0) * 0.10;
  outColor = vec4(pow(base.rgb * light + spec, vec3(1.0 / 2.2)), 1.0);
}`));
gl.linkProgram(prog);
if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { msg(T.broken + ": " + gl.getProgramInfoLog(prog)); return; }
const U = n => gl.getUniformLocation(prog, n);
const uProj = U("uProj"), uView = U("uView"), uTex = U("uTex"), uHasTex = U("uHasTex"), uFactor = U("uFactor");
const textures = {};
function texture(i) {  // Grundfarbe: PNG/JPEG oder WebP (EXT_texture_webp), im Browser dekodiert
  if (i === null || i === undefined) return null;
  if (textures[i] !== undefined) return textures[i];
  textures[i] = null;
  const t = (doc.textures || [])[i] || {}, ext = t.extensions || {};
  const src = t.source !== undefined ? t.source : (ext.EXT_texture_webp || {}).source;
  const img = (doc.images || [])[src];
  if (!img || img.bufferView === undefined) return null;
  const v = doc.bufferViews[img.bufferView], start = v.byteOffset || 0;
  const blob = new Blob([bin.slice(start, start + v.byteLength)], {type: img.mimeType || "image/png"});
  createImageBitmap(blob, {colorSpaceConversion: "none", premultiplyAlpha: "none"}).then(bmp => {
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.SRGB8_ALPHA8, gl.RGBA, gl.UNSIGNED_BYTE, bmp);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    textures[i] = tex; draw();
  }).catch(() => {});
  return null;
}
for (const p of prims) {
  p.vao = gl.createVertexArray(); gl.bindVertexArray(p.vao);
  const buf = (loc, arr, size) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW); gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0); };
  buf(0, p.pos, 3); buf(1, p.nrm, 3);
  if (p.uv) buf(2, p.uv, 2); else gl.vertexAttrib2f(2, 0, 0);
  if (p.col) buf(3, p.col.data, p.col.size); else gl.vertexAttrib4f(3, 1, 1, 1, 1);  // VEC3: w ist dann 1
  const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, p.idx, gl.STATIC_DRAW);
  p.type = p.idx instanceof Uint32Array ? gl.UNSIGNED_INT : p.idx instanceof Uint16Array ? gl.UNSIGNED_SHORT : gl.UNSIGNED_BYTE;
  p.count = p.idx.length; p.pos = p.nrm = p.uv = p.col = p.idx = null;
}
gl.bindVertexArray(null);
gl.enable(gl.DEPTH_TEST);
gl.disable(gl.CULL_FACE);  // erzeugte Modelle haben mitunter dünne Stellen: beide Seiten zeichnen

// ---- Kamera: kreist um die Mitte des Modells
const center = [0, 1, 2].map(a => (lo[a] + hi[a]) / 2);
const radius = Math.max(1e-6, Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2);
const FOV = 40 * Math.PI / 180;
let yaw, pitch, dist, target, spinning = false, light = false, last = 0, pending = false;
function reset() { yaw = 0.55; pitch = 0.32; dist = radius / Math.sin(FOV / 2) * 1.08; target = center.slice(); draw(); }
function draw() { if (!pending) { pending = true; requestAnimationFrame(frame); } }
function frame(t) {
  pending = false;
  if (spinning) { yaw += Math.min(0.05, (t - (last || t)) / 1000) * 0.6; last = t; draw(); } else last = 0;
  const dpr = window.devicePixelRatio || 1, w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  gl.viewport(0, 0, w, h);
  const bg = light ? [0.95, 0.95, 0.95] : [0.125, 0.125, 0.125];
  gl.clearColor(bg[0], bg[1], bg[2], 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  const eye = [target[0] + dist * Math.cos(pitch) * Math.sin(yaw), target[1] + dist * Math.sin(pitch),
               target[2] + dist * Math.cos(pitch) * Math.cos(yaw)];
  gl.useProgram(prog);
  gl.uniformMatrix4fv(uProj, false, perspective(FOV, w / Math.max(1, h), dist * 0.01, dist + radius * 4));
  gl.uniformMatrix4fv(uView, false, lookAt(eye, target));
  gl.uniform1i(uTex, 0); gl.activeTexture(gl.TEXTURE0);
  for (const p of prims) {
    const tex = texture(p.tex);
    gl.uniform1i(uHasTex, tex ? 1 : 0); if (tex) gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.uniform4fv(uFactor, p.factor);
    gl.bindVertexArray(p.vao); gl.drawElements(gl.TRIANGLES, p.count, p.type, 0);
  }
  gl.bindVertexArray(null);
}

// ---- Bedienung: Maus, Stift und Finger
const pointers = new Map();
let mode = null, pinch = 0;
canvas.addEventListener("contextmenu", e => e.preventDefault());
canvas.addEventListener("pointerdown", e => {
  canvas.setPointerCapture(e.pointerId); pointers.set(e.pointerId, [e.clientX, e.clientY]);
  mode = pointers.size > 1 ? "pinch" : (e.button === 2 || e.shiftKey ? "pan" : "rotate");
  if (mode === "pinch") { const [a, b] = [...pointers.values()]; pinch = Math.hypot(a[0] - b[0], a[1] - b[1]); }
});
canvas.addEventListener("pointermove", e => {
  const prev = pointers.get(e.pointerId); if (!prev) return;
  const dx = e.clientX - prev[0], dy = e.clientY - prev[1]; pointers.set(e.pointerId, [e.clientX, e.clientY]);
  if (mode === "rotate") { yaw -= dx * 0.008; pitch = Math.max(-1.5, Math.min(1.5, pitch + dy * 0.008)); }
  else if (mode === "pan") {
    const s = dist * Math.tan(FOV / 2) * 2 / Math.max(1, canvas.clientHeight);
    const rx = Math.cos(yaw), rz = -Math.sin(yaw);                      // rechts
    const ux = -Math.sin(pitch) * Math.sin(yaw), uy = Math.cos(pitch), uz = -Math.sin(pitch) * Math.cos(yaw);  // oben
    target = [target[0] - (dx * rx - dy * ux) * s, target[1] + dy * uy * s, target[2] - (dx * rz - dy * uz) * s];
  } else if (mode === "pinch" && pointers.size > 1) {
    const [a, b] = [...pointers.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
    if (pinch) dist = Math.max(radius * 0.2, Math.min(radius * 40, dist * pinch / Math.max(1, d))); pinch = d;
  }
  draw();
});
const up = e => { pointers.delete(e.pointerId); if (!pointers.size) mode = null; };
canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
canvas.addEventListener("wheel", e => { e.preventDefault();
  dist = Math.max(radius * 0.2, Math.min(radius * 40, dist * Math.exp(e.deltaY * 0.0015))); draw(); }, {passive: false});
canvas.addEventListener("dblclick", reset);
$("reset").addEventListener("click", reset);
$("spin").addEventListener("click", () => { spinning = !spinning; $("spin").setAttribute("aria-pressed", spinning); draw(); });
$("bg").addEventListener("click", () => { light = !light; document.body.classList.toggle("hell", light); draw(); });
window.addEventListener("resize", draw);
reset();
})();
</script></body></html>
"""
