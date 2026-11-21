// 3D view "Where does the evidence come from?". Everything drawn comes from a StarterPack file or from the twin state:
// - the T1-weighted volume, ray-marched on the GPU (Data3DTexture, 3 x 3 x 4 mm voxels from the file's affine);
//   colours are four intensity bands found in the data by k-means (server side), one texture channel per band;
// - the brain mask as one contour per acquired slice, and the acquisition slab (field of view);
// - region-mask surfaces for each session that has a mask file;
// - one spectroscopy cube per evidence packet, at the position its packet states, coloured by the twin's QC decision.
// Three.js r160 is vendored in web/vendor/three, so the page works offline.
import * as THREE from "../vendor/three/three.module.min.js";
import { OrbitControls } from "../vendor/three/OrbitControls.js";

// RAS (x right, y anterior, z superior) to three.js (y up). A proper rotation, so triangle winding is kept.
const toThree = (x, y, z) => new THREE.Vector3(x, z, -y);

export function b64(str, Type = Uint8Array) {
  const bin = atob(str);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Type(bytes.buffer);
}

function meshGeometry(m) {
  const p = b64(m.positions, Float32Array);
  const out = new Float32Array(p.length);
  for (let i = 0; i < p.length; i += 3) { out[i] = p[i]; out[i + 1] = p[i + 2]; out[i + 2] = -p[i + 1]; }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(out, 3));
  g.setIndex(new THREE.BufferAttribute(b64(m.indices, m.index_type === "uint16" ? Uint16Array : Uint32Array), 1));
  g.computeVertexNormals();
  g.computeBoundingBox();
  g.computeBoundingSphere();
  return g;
}

// Resolve any CSS colour (hex, rgb, oklch, color-mix...) to sRGB through a 1 px canvas.
const probe = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
export function cssRGB(name, fallback = "#888") {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  probe.clearRect(0, 0, 1, 1);
  probe.fillStyle = fallback; probe.fillStyle = v;
  probe.fillRect(0, 0, 1, 1);
  return [...probe.getImageData(0, 0, 1, 1).data.slice(0, 3)];
}
const cssColor = (name, fallback) => { const [r, g, b] = cssRGB(name, fallback); return new THREE.Color().setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace); };

/** Per-band membership texture: channel r, g, b, a = band 0..3 (CSF, lesion, grey, white matter). */
function bandTexture(u8, shape, bounds, floor) {
  const [nx, ny, nz] = shape, n = nx * ny * nz;
  const data = new Uint8Array(n * 4);
  for (let i = 0; i < n; i++) {
    const v = u8[i];
    if (v < floor) continue;                       // outside the head: no band
    const band = v < bounds[0] ? 0 : v < bounds[1] ? 1 : v < bounds[2] ? 2 : 3;
    data[i * 4 + band] = 255;
  }
  const tex = new THREE.Data3DTexture(data, nx, ny, nz);
  tex.format = THREE.RGBAFormat; tex.type = THREE.UnsignedByteType;
  tex.minFilter = THREE.LinearFilter; tex.magFilter = THREE.LinearFilter;
  tex.wrapS = tex.wrapT = tex.wrapR = THREE.ClampToEdgeWrapping;
  tex.unpackAlignment = 1; tex.needsUpdate = true;
  return tex;
}

// ---- volume ray marching (front-to-back compositing, early stop at 97 % opacity, jittered start against banding)
const VOL_VERT = `
  varying vec3 vW;
  void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`;
const VOL_FRAG = `
  precision highp sampler3D;
  uniform sampler3D uVol;
  uniform vec3 uBMin; uniform vec3 uBMax;
  uniform vec3 uC0; uniform vec3 uC1; uniform vec3 uC2; uniform vec3 uC3;
  uniform vec4 uDen; uniform float uStep; uniform float uClipY; uniform float uGain; uniform vec3 uLight;
  varying vec3 vW;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
  vec3 uvw(vec3 p) { vec3 s = uBMax - uBMin; return vec3((p.x - uBMin.x) / s.x, (uBMax.z - p.z) / s.z, (p.y - uBMin.y) / s.y); }
  float dens(vec3 p) { return dot(textureLod(uVol, uvw(p), 0.0), uDen); }
  void main() {
    vec3 ro = cameraPosition; vec3 rd = normalize(vW - ro);
    vec3 inv = 1.0 / rd; vec3 t0 = (uBMin - ro) * inv; vec3 t1 = (uBMax - ro) * inv;
    vec3 tmn = min(t0, t1); vec3 tmx = max(t0, t1);
    float tn = max(max(tmn.x, tmn.y), max(tmn.z, 0.0)); float tf = min(min(tmx.x, tmx.y), tmx.z);
    tf = min(tf, rd.y > 0.0 ? (uClipY - ro.y) / rd.y : tf);
    if (ro.y > uClipY && rd.y < 0.0) tn = max(tn, (uClipY - ro.y) / rd.y);
    if (tn >= tf) discard;
    float t = tn + uStep * hash(gl_FragCoord.xy);
    vec4 acc = vec4(0.0);
    for (int i = 0; i < 260; i++) {
      if (t > tf || acc.a > 0.97) break;
      vec3 p = ro + rd * t;
      vec4 m = textureLod(uVol, uvw(p), 0.0);
      float d = dot(m, uDen);
      if (d > 0.0004) {
        float a = 1.0 - exp(-d * uStep * uGain);
        vec3 c = (m.r * uDen.r * uC0 + m.g * uDen.g * uC1 + m.b * uDen.b * uC2 + m.a * uDen.a * uC3) / d;
        if (a > 0.03) {                     // shade only the samples that matter (3 extra texture reads)
          vec3 g = vec3(dens(p + vec3(1.5, 0.0, 0.0)), dens(p + vec3(0.0, 2.0, 0.0)), dens(p + vec3(0.0, 0.0, 1.5))) - d;
          float gl = length(g);
          if (gl > 1e-5) {
            vec3 n = -g / gl;
            c *= 0.66 + 0.34 * max(dot(n, uLight), 0.0) + 0.22 * pow(1.0 - abs(dot(n, rd)), 2.0);
          }
        }
        acc.rgb += (1.0 - acc.a) * a * c; acc.a += (1.0 - acc.a) * a;
      }
      t += uStep;
    }
    if (acc.a < 0.004) discard;
    gl_FragColor = vec4(acc.rgb / acc.a, acc.a);
    #include <colorspace_fragment>
  }`;

// ---- region surfaces: lit body, bright rim where the surface turns away, slight transparency
const SURF_VERT = `
  varying vec3 vN; varying vec3 vV;
  void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); vN = normalize(normalMatrix * normal); vV = -mv.xyz; gl_Position = projectionMatrix * mv; }`;
const SURF_FRAG = `
  uniform vec3 uColor; uniform float uBody; uniform float uRim; uniform float uOpacity;
  varying vec3 vN; varying vec3 vV;
  void main() {
    vec3 n = normalize(vN); vec3 v = normalize(vV);
    if (!gl_FrontFacing) n = -n;
    float ndv = clamp(dot(n, v), 0.0, 1.0);
    float rim = pow(1.0 - ndv, 2.2);
    vec3 l = normalize(vec3(-0.35, 0.75, 0.55));
    float diff = 0.55 + 0.45 * max(dot(n, l), 0.0);
    float spec = pow(max(dot(reflect(-l, n), v), 0.0), 40.0) * 0.35;
    vec3 col = uColor * diff + spec + uColor * rim * 0.6;
    float a = clamp(uBody + uRim * rim + spec, 0.0, 1.0) * uOpacity;
    gl_FragColor = vec4(col, a);
    #include <colorspace_fragment>
  }`;
function surfaceMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uColor: { value: new THREE.Color() }, uBody: { value: 0.5 }, uRim: { value: 0.5 }, uOpacity: { value: 1 } },
    vertexShader: SURF_VERT, fragmentShader: SURF_FRAG, transparent: true, depthWrite: false, side: THREE.DoubleSide,
  });
}

// ---- a cube drawn as thin rods (WebGL lines are always 1 px). Dashed cubes split each edge into short rods.
const ROD = new THREE.CylinderGeometry(1, 1, 1, 8, 1, true);
const BEAD = new THREE.SphereGeometry(1, 10, 8);
const BOX = new THREE.BoxGeometry(1, 1, 1);
function rodCube(center, size, { radius = 0.34, dash = 0, gap = 0 } = {}) {
  const h = size.map((s) => s / 2);
  const corners = [];
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) corners.push([sx, sy, sz]);
  const pt = ([sx, sy, sz]) => toThree(sx * h[0], sy * h[1], sz * h[2]);       // local, centred on the cube
  const segs = [];
  for (let i = 0; i < 8; i++) for (let j = i + 1; j < 8; j++) {
    if (corners[i].reduce((n, v, k) => n + (v !== corners[j][k]), 0) !== 1) continue;
    const A = pt(corners[i]), B = pt(corners[j]), len = A.distanceTo(B);
    if (!dash) { segs.push([A, B]); continue; }
    for (let t = 0; t < len - 0.01; t += dash + gap) segs.push([A.clone().lerp(B, t / len), A.clone().lerp(B, Math.min(t + dash, len) / len)]);
  }
  const mat = new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false });
  const rods = new THREE.InstancedMesh(ROD, mat, segs.length);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
  segs.forEach(([A, B], i) => {
    const dir = B.clone().sub(A), len = dir.length();
    q.setFromUnitVectors(up, dir.normalize());
    m.compose(A.clone().lerp(B, 0.5), q, new THREE.Vector3(radius, len, radius));
    rods.setMatrixAt(i, m);
  });
  const beads = new THREE.InstancedMesh(BEAD, mat, dash ? 0 : 8);
  if (!dash) corners.forEach((k, i) => { m.compose(pt(k), new THREE.Quaternion(), new THREE.Vector3(radius * 1.8, radius * 1.8, radius * 1.8)); beads.setMatrixAt(i, m); });
  const fillMat = new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, opacity: 0 });
  const fill = new THREE.Mesh(BOX, fillMat);
  fill.scale.set(size[0], size[2], size[1]);
  const group = new THREE.Group();
  group.add(rods, beads, fill);
  group.position.copy(toThree(...center));
  return { group, mat, fill, fillMat };
}

function sliceTexture(u8, shape, k, window) {
  const [nx, ny] = shape;
  const data = new Uint8Array(nx * ny * 4);
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
    const v = u8[i + j * nx + k * nx * ny];
    const o = (i + j * nx) * 4;
    data[o] = data[o + 1] = data[o + 2] = 255;
    data[o + 3] = Math.min(255, Math.round((v / window) * 255));
  }
  const tex = new THREE.DataTexture(data, nx, ny, THREE.RGBAFormat);
  tex.magFilter = THREE.LinearFilter; tex.minFilter = THREE.LinearFilter; tex.needsUpdate = true;
  return tex;
}

/**
 * Mount the scene into `stage` (an empty, sized element). Returns a small control API.
 * The scene disposes itself when `stage` leaves the document (the router replaces the page container).
 */
export function mountScene(stage, data, opts = {}) {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  } catch (err) {
    throw new Error("This browser cannot draw 3D (WebGL 2 is off or unavailable).");
  }
  let pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);   // crisp enough; ray marching is costly
  renderer.setPixelRatio(pixelRatio);
  renderer.setClearColor(0x000000, 0);
  const canvas = renderer.domElement;
  canvas.className = "scene3d-canvas";
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "Rotatable 3D view: the scanned T1-weighted volume, the region masks and one spectroscopy cube per evidence packet");
  stage.appendChild(canvas);
  const overlay = document.createElement("div");
  overlay.className = "scene3d-overlay";
  overlay.setAttribute("aria-hidden", "true");
  stage.appendChild(overlay);
  const tip = document.createElement("div");
  tip.className = "scene3d-tip";
  stage.appendChild(tip);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 1, 4000);
  const disposables = [];
  const shape = data.shape;
  const [slabLo, slabHi] = data.slab_mm;

  // ---- acquisition slab and its centre
  const bMin = toThree(slabLo[0], slabHi[1], slabLo[2]), bMax = toThree(slabHi[0], slabLo[1], slabHi[2]);
  const boxMin = bMin.clone().min(bMax), boxMax = bMin.clone().max(bMax);
  const boxSize = boxMax.clone().sub(boxMin), center = boxMin.clone().add(boxMax).multiplyScalar(0.5);
  const slabGeo = new THREE.EdgesGeometry(new THREE.BoxGeometry(boxSize.x, boxSize.y, boxSize.z));
  const slabMat = new THREE.LineDashedMaterial({ dashSize: 4, gapSize: 3, transparent: true, depthWrite: false });
  const slab = new THREE.LineSegments(slabGeo, slabMat);
  slab.computeLineDistances(); slab.position.copy(center); slab.renderOrder = 2;
  disposables.push(slabGeo, slabMat);

  // ---- brain-mask contours, one per acquired slice
  const ringMat = new THREE.LineBasicMaterial({ transparent: true, depthWrite: false });
  const ringHot = new THREE.LineBasicMaterial({ transparent: true, depthWrite: false });
  disposables.push(ringMat, ringHot);
  const rings = data.contours.map((c) => {
    const g = new THREE.Group();
    for (const ring of c.rings) {
      const pts = ring.map(([x, y]) => toThree(x, y, c.z_mm));
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      disposables.push(geo);
      const line = new THREE.LineLoop(geo, ringMat);
      line.renderOrder = 3;
      g.add(line);
    }
    return { k: c.k, z: c.z_mm, group: g };
  });

  // ---- volume
  const bounds = data.band_bounds_u8, floor = data.bands[0].centre * 0.5;
  const volumes = {};
  for (const [ses, s] of Object.entries(data.sessions)) {
    const u8 = b64(s.t1w);
    volumes[ses] = { u8, tex: bandTexture(u8, shape, bounds, floor) };
    disposables.push(volumes[ses].tex);
  }
  const refSession = Object.keys(volumes)[0];
  const volMat = new THREE.ShaderMaterial({
    uniforms: {
      uVol: { value: volumes[refSession].tex }, uBMin: { value: boxMin }, uBMax: { value: boxMax },
      uC0: { value: new THREE.Color() }, uC1: { value: new THREE.Color() }, uC2: { value: new THREE.Color() }, uC3: { value: new THREE.Color() },
      uDen: { value: new THREE.Vector4(0.05, 0.4, 0.0045, 0.009) }, uStep: { value: 2.0 }, uClipY: { value: 1e4 },
      uGain: { value: 1 }, uLight: { value: new THREE.Vector3(0, 1, 0) },
    },
    vertexShader: VOL_VERT, fragmentShader: VOL_FRAG, transparent: true, depthWrite: false, depthTest: false, side: THREE.BackSide,
  });
  const volGeo = new THREE.BoxGeometry(boxSize.x, boxSize.y, boxSize.z);
  const volume = new THREE.Mesh(volGeo, volMat);
  volume.position.copy(center);
  disposables.push(volMat, volGeo);
  // The data is 64 x 64 x 16 voxels, so the volume is ray-marched into a smaller render target and scaled up:
  // no visible loss, and many times less GPU work. The surfaces, lines and cubes stay at full resolution.
  const volScene = new THREE.Scene();
  volScene.add(volume);
  const rtVol = new THREE.WebGLRenderTarget(4, 4, { depthBuffer: false, minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter });
  const quadMat = new THREE.ShaderMaterial({
    uniforms: { uTex: { value: rtVol.texture } },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
    fragmentShader: `uniform sampler2D uTex; varying vec2 vUv;
      void main(){ vec4 c = texture2D(uTex, vUv); if (c.a < 0.003) discard; gl_FragColor = vec4(c.rgb / c.a, c.a);
      #include <colorspace_fragment>
      }`,
    transparent: true, depthTest: false, depthWrite: false,
  });
  const quadGeo = new THREE.PlaneGeometry(2, 2);
  const quad = new THREE.Mesh(quadGeo, quadMat);
  quad.frustumCulled = false; quad.renderOrder = -10;
  disposables.push(rtVol, quadMat, quadGeo);
  let volScale = 0.42;                 // render-target size relative to the canvas in CSS pixels

  // ---- highlighted slice: the real T1w slice as a translucent plane
  const planeMat = new THREE.ShaderMaterial({
    uniforms: { uTex: { value: null }, uColor: { value: new THREE.Color() }, uOpacity: { value: 0.5 } },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform sampler2D uTex; uniform vec3 uColor; uniform float uOpacity; varying vec2 vUv;
      void main(){ float a = texture2D(uTex, vUv).a; gl_FragColor = vec4(uColor, smoothstep(0.04, 1.0, a) * uOpacity);
      #include <colorspace_fragment>
      }`,
    transparent: true, depthWrite: false, side: THREE.DoubleSide,
  });
  const planeGeo = new THREE.PlaneGeometry(slabHi[0] - slabLo[0], slabHi[1] - slabLo[1]);
  const plane = new THREE.Mesh(planeGeo, planeMat);
  plane.rotation.x = -Math.PI / 2;                 // plane +y becomes three -z (anterior); uv (0,0) is (x min, y min)
  plane.renderOrder = 1;
  disposables.push(planeMat, planeGeo);
  let planeTex = null;

  // ---- region surfaces, one per session with a mask file
  const regions = {};
  for (const [ses, s] of Object.entries(data.sessions)) {
    if (!s.roi_surface) continue;
    const geo = meshGeometry(s.roi_surface);
    const mat = surfaceMaterial();
    const mesh = new THREE.Mesh(geo, mat);
    mesh.renderOrder = ses === "ses-baseline" ? 4 : 5;
    regions[ses] = { mesh, mat, geo, vis: 0, target: 0 };
    disposables.push(geo, mat);
  }

  // ---- the brain as a glass shell (the brain-mask surface from the file)
  let brain = null;
  if (data.brain_surface) {
    const geo = meshGeometry(data.brain_surface), mat = surfaceMaterial();
    brain = { mesh: new THREE.Mesh(geo, mat), mat };
    brain.mesh.renderOrder = 0;
    disposables.push(geo, mat);
    scene.add(brain.mesh);
  }
  let sliceShown = false;               // the real slice appears only once the user moves the slider or ticks "cut away"

  scene.add(plane, slab, ...rings.map((r) => r.group), ...Object.values(regions).map((r) => r.mesh));
  const evGroup = new THREE.Group();
  scene.add(evGroup);

  // ---- camera: view from front-left and above, distance fitted to the slab
  const radius = boxSize.length() / 2;
  const homeDir = new THREE.Vector3(-0.62, 0.86, -1).normalize();
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.dampingFactor = 0.08; controls.enablePan = false;
  controls.minDistance = radius * 0.6; controls.maxDistance = radius * 5;
  controls.autoRotate = false;            // no idle spinning: the view holds still and the GPU rests until the user drags
  const SPIN_MS = 24000;                // a gentle turn on arrival, then the view holds still and the GPU rests
  let spinUntil = performance.now() + SPIN_MS;
  function fitDistance() {
    const vfov = THREE.MathUtils.degToRad(camera.fov), hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
    return (radius * 0.9) / Math.sin(Math.min(vfov, hfov) / 2);
  }
  function home() { controls.target.copy(center); camera.position.copy(center).addScaledVector(homeDir, fitDistance()); controls.update(); }
  { const w = stage.clientWidth, h = stage.clientHeight; if (w && h) { camera.aspect = w / h; camera.updateProjectionMatrix(); } }
  const saved = opts.view;
  let userTouched = !!saved?.touched;
  if (userTouched) { camera.position.fromArray(saved.position); controls.target.fromArray(saved.target); controls.autoRotate = false; controls.update(); }
  else home();
  controls.addEventListener("start", () => { userTouched = true; interacting = true; controls.autoRotate = false; hideTip(); });
  controls.addEventListener("end", () => { interacting = false; });

  // ---- HTML labels anchored in 3D
  const anchors = [];
  function addTag(text, pos, cls = "tag") {
    const el = document.createElement("span");
    el.className = `scene3d-label ${cls}`;
    el.textContent = text;
    overlay.appendChild(el);
    const a = { el, pos, visible: true };
    anchors.push(a);
    return a;
  }
  addTag(`Scanned slab: ${shape[2]} slices, ${Math.round(slabHi[2] - slabLo[2])} mm`, toThree(slabLo[0], slabHi[1], slabLo[2]), "tag slab");
  const evTag = addTag("", new THREE.Vector3(), "tag ev");
  const regionTag = addTag("Region mask", new THREE.Vector3(), "tag");

  // orientation gizmo (bottom left): R, A, S at the positive ends, L, P, I at the negative ends
  const AX = [["R", "L", toThree(1, 0, 0)], ["A", "P", toThree(0, 1, 0)], ["S", "I", toThree(0, 0, 1)]];
  const gizmo = document.createElement("div");
  gizmo.className = "scene3d-gizmo";
  gizmo.innerHTML = `<svg viewBox="-40 -40 80 80">${AX.map(() => `<line class="neg"/><line class="pos"/>`).join("")}</svg>`
    + AX.map(([p, n]) => `<span class="pos">${p}</span><span class="neg">${n}</span>`).join("");
  overlay.appendChild(gizmo);
  const gLines = [...gizmo.querySelectorAll("line")], gText = [...gizmo.querySelectorAll("span")];
  const gv = new THREE.Vector3(), proj = new THREE.Vector3();
  function placeLabels() {
    const w = stage.clientWidth, h = stage.clientHeight;
    for (const a of anchors) if (a.visible && !a.w) a.w = a.el.offsetWidth;   // read all sizes before any write (no layout thrash)
    for (const a of anchors) {
      if (!a.visible) { a.el.style.opacity = 0; continue; }
      proj.copy(a.pos).project(camera);
      const half = (a.w || 0) / 2 + 6;                                   // keep tags inside the stage
      const x = Math.min(Math.max(((proj.x + 1) / 2) * w, half), w - half), y = Math.min(Math.max(((1 - proj.y) / 2) * h, 14), h - 14);
      a.el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
      a.el.style.opacity = proj.z > 1 ? 0 : 1;
    }
    AX.forEach(([, , dir], i) => {
      gv.copy(dir).transformDirection(camera.matrixWorldInverse);
      const x = gv.x * 24, y = -gv.y * 24, k = 32 / 24;
      gLines[2 * i].setAttribute("x2", -x); gLines[2 * i].setAttribute("y2", -y);
      gLines[2 * i + 1].setAttribute("x2", x); gLines[2 * i + 1].setAttribute("y2", y);
      gText[2 * i].style.transform = `translate(${40 + x * k}px, ${40 + y * k}px) translate(-50%, -50%)`;
      gText[2 * i + 1].style.transform = `translate(${40 - x * k}px, ${40 - y * k}px) translate(-50%, -50%)`;
      gText[2 * i].style.opacity = gv.z < -0.2 ? 0.55 : 1;
      gText[2 * i + 1].style.opacity = gv.z > 0.2 ? 0.3 : 0.55;
    });
  }

  // ---- state
  let session = opts.session || "all";
  let sliceK = opts.slice ?? Math.floor(shape[2] / 2);
  let clip = !!opts.clip;
  let focus = null;                 // legend hover
  let selected = opts.selected ?? null;
  let evidence = [];                // [{ item, cube, born }]
  const colors = {};

  function applyTheme() {
    const light = document.documentElement.dataset.theme === "light";
    Object.assign(colors, {
      ink: cssColor("--text", "#e2ecee"), ink2: cssColor("--text-2", "#a0b3b7"), ink3: cssColor("--text-3", "#7f9398"),
      line: cssColor("--line-2", "#2a3d44"), accent: cssColor("--accent", "#57cfc6"), accent2: cssColor("--accent-2", "#38aea6"),
      PASS: cssColor("--pass", "#93d17f"), WARN: cssColor("--warn", "#ebb556"), FAIL: cssColor("--fail", "#f2806f"),
      INFO: cssColor("--text-2", "#a0b3b7"), light,
    });
    const u = volMat.uniforms;
    u.uC0.value.copy(colors.accent2);               // CSF
    u.uC1.value.copy(colors.accent);                // lesion
    u.uC2.value.copy(colors.ink3);                  // grey matter: a faint outer veil
    u.uC3.value.copy(colors.ink2);                  // white matter: the brighter inner body
    u.uDen.value.set(light ? 0.16 : 0.12, 0.9, light ? 0.006 : 0.0045, light ? 0.018 : 0.014);
    slabMat.color.copy(colors.ink3);
    ringMat.color.copy(colors.ink3); ringHot.color.copy(colors.accent);
    planeMat.uniforms.uColor.value.copy(colors.ink2);
    if (brain) brain.mat.uniforms.uColor.value.copy(light ? colors.ink3 : colors.ink2);
    if (regions["ses-baseline"]) regions["ses-baseline"].mat.uniforms.uColor.value.copy(colors.accent);
    if (regions["ses-followup"]) regions["ses-followup"].mat.uniforms.uColor.value.copy(colors.WARN);
    for (const e of evidence) e.mat.color.copy(colors[e.item.status] || colors.INFO);
    dirty = true;
  }

  function setSession(s) {
    session = s;
    const img = volumes[s] ? s : refSession;
    volMat.uniforms.uVol.value = volumes[img].tex;
    volMat.uniforms.uGain.value = volumes[s] || s === "all" ? 1 : 0.55;        // no image of its own: reference anatomy, dimmed
    for (const [ses, r] of Object.entries(regions)) r.target = s === "all" || s === ses ? 1 : 0;
    if (reduceMotion) for (const r of Object.values(regions)) r.vis = r.target;
    updateSlicePlane();
    dirty = true;
  }

  function updateSlicePlane() {
    const ses = volumes[session] ? session : refSession;
    planeTex?.dispose();
    const wm = data.bands[3].centre;
    planeTex = sliceTexture(volumes[ses].u8, shape, sliceK, wm * 1.05);
    planeMat.uniforms.uTex.value = planeTex;
    const z = data.contours[sliceK].z_mm;
    plane.position.copy(toThree((slabLo[0] + slabHi[0]) / 2, (slabLo[1] + slabHi[1]) / 2, z));
    volMat.uniforms.uClipY.value = clip ? z + 2 : 1e4;           // keep the highlighted slice, cut what lies above it
    rings.forEach((r) => {
      r.group.children.forEach((l) => { l.material = r.k === sliceK ? ringHot : ringMat; });
      r.group.visible = !clip || r.z <= z + 0.1;
    });
    dirty = true;
  }

  // ---- evidence cubes (rebuilt in place when the twin state changes)
  function setEvidence(items) {
    const old = new Map(evidence.map((e) => [e.item.id, e]));
    const next = [];
    const now = performance.now();
    for (const item of items) {
      if (!item.cube) continue;
      const prev = old.get(item.id);
      if (prev && prev.item.status === item.status) { prev.item = item; next.push(prev); old.delete(item.id); continue; }
      const rc = rodCube(item.cube.center, item.cube.size, item.rejected ? { radius: 0.22, dash: 2.2, gap: 1.8 } : { radius: 0.3 });
      rc.mat.color.copy(colors[item.status] || colors.INFO);
      rc.group.renderOrder = 6;
      rc.group.children.forEach((o) => { o.renderOrder = 6; });
      evGroup.add(rc.group);
      next.push({ item, ...rc, born: prev || !opts.animateNew || reduceMotion ? -1 : now });
    }
    for (const e of old.values()) { evGroup.remove(e.group); e.mat.dispose(); e.fillMat.dispose(); e.group.children.forEach((o) => o.isInstancedMesh && o.dispose()); }
    evidence = next;
    opts.animateNew = true;            // only evidence that arrives after the first draw gets the appear animation
    dirty = true; kick();
  }

  // Cubes at exactly the same place would draw on top of each other: show the newest one (or the selected one).
  const placeKey = (e) => `${e.item.cube.center.join(",")}|${e.item.cube.size.join(",")}`;
  function evidenceVisible(e) { return session === "all" || e.item.session_id === session; }
  function styleEvidence(t) {
    let animating = false;
    const front = new Map();
    for (const e of evidence) {
      if (!evidenceVisible(e)) continue;
      const k = placeKey(e), cur = front.get(k);
      if (!cur || (cur.item.id !== selected && (e.item.id === selected || (!e.item.rejected && (cur.item.rejected || e.item.id > cur.item.id))))) front.set(k, e);
    }
    for (const e of evidence) {
      const shown = evidenceVisible(e) && (front.get(placeKey(e)) === e || e.item.rejected);
      e.group.visible = shown;
      if (!shown) continue;
      let k = 1;
      if (e.born > 0) { k = Math.min(1, (t - e.born) / 900); if (k < 1) animating = true; else e.born = -1; }
      const ease = 1 - Math.pow(1 - k, 3);
      const isSel = selected === e.item.id;
      const base = e.item.rejected ? 0.45 : isSel || selected == null ? 1 : 0.55;
      const dim = focus && focus !== "evidence" ? 0.3 : 1;
      e.mat.opacity = base * dim * ease;
      e.fillMat.color.copy(e.mat.color);
      e.fillMat.opacity = (isSel ? 0.16 : 0.04) * ease + (1 - ease) * 0.35 * (k < 1 ? 1 : 0);
      e.group.scale.setScalar(1 + (1 - ease) * 0.35);
    }
    return animating;
  }

  function setSelected(id) {
    selected = id;
    const e = evidence.find((x) => x.item.id === id);
    evTag.visible = !!e && evidenceVisible(e);
    if (e) {
      const c = e.item.cube, h = c.size;
      evTag.pos.copy(toThree(c.center[0] - h[0] / 2, c.center[1] + h[1] / 2, c.center[2] + h[2] / 2 + 4));
      evTag.el.textContent = `${e.item.packet_id}, ${e.item.session_id.replace("ses-", "")}`;
      evTag.w = 0;
      evTag.el.dataset.status = e.item.status;
    }
    dirty = true; kick();
  }

  // ---- visibility per legend hover, and region fades
  function styleScene() {
    const dim = (k) => (focus && focus !== k ? 0.3 : 1);
    volMat.uniforms.uGain.value = (volumes[session] || session === "all" ? 1 : 0.55) * (focus && focus !== "volume" ? 0.45 : 1);
    slabMat.opacity = 0.75 * dim("slab");
    ringMat.opacity = (sliceShown ? 0.3 : 0.1) * dim("rings"); ringHot.opacity = sliceShown ? dim("rings") : 0;
    plane.visible = sliceShown;
    planeMat.uniforms.uOpacity.value = (colors.light ? 0.62 : 0.7) * dim("slice");
    if (brain) {
      brain.mat.uniforms.uBody.value = colors.light ? 0.06 : 0.04;      // nearly clear glass: the region and cubes inside stay visible
      brain.mat.uniforms.uRim.value = colors.light ? 0.5 : 0.55;
      brain.mat.uniforms.uOpacity.value = (sliceShown ? 0.55 : 1) * dim("brain");
    }
    const both = session === "all";
    for (const [ses, r] of Object.entries(regions)) {
      const outer = both && ses === "ses-followup";
      r.mat.uniforms.uBody.value = outer ? 0.05 : 0.14;      // see-through, so the lesion inside stays visible
      r.mat.uniforms.uRim.value = outer ? 0.8 : 0.75;
      r.mat.uniforms.uOpacity.value = r.vis * dim("region");
      r.mesh.visible = r.vis > 0.01;
    }
    const shown = Object.entries(regions).filter(([, r]) => r.target > 0);
    regionTag.visible = shown.length > 0;
    if (shown.length) {
      const bb = shown[shown.length - 1][1].geo.boundingBox;
      regionTag.pos.set((bb.min.x + bb.max.x) / 2, bb.max.y + 6, (bb.min.z + bb.max.z) / 2);
    }
  }

  // ---- sizing
  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    rtVol.setSize(Math.max(2, Math.round(w * volScale)), Math.max(2, Math.round(h * volScale)));
    camera.aspect = w / h; camera.updateProjectionMatrix();
    if (!userTouched) { const d = camera.position.clone().sub(controls.target).normalize(); camera.position.copy(controls.target).addScaledVector(d, fitDistance()); }
    dirty = true; kick();
  }
  const ro = new ResizeObserver(resize); ro.observe(stage);

  // ---- hover and click: cubes first, then regions
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  let pointer = null, downAt = null, pickPending = false;
  function hideTip() { tip.classList.remove("on"); }
  function hitAt(x, y) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((x - r.left) / r.width) * 2 - 1, -((y - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const shownEv = evidence.filter((e) => e.group.visible);
    const hits = ray.intersectObjects(shownEv.map((e) => e.fill), false);
    if (hits.length) {
      const d0 = hits[0].distance;
      const near = hits.filter((h) => h.distance < d0 + 0.5).map((h) => shownEv.find((e) => e.fill === h.object));
      const pick = near.find((e) => e.item.id === selected) || near[near.length - 1];
      return { kind: "evidence", e: pick, count: near.length };
    }
    const regs = Object.entries(regions).filter(([, r]) => r.mesh.visible);
    const rh = ray.intersectObjects(regs.map(([, r]) => r.mesh), false);
    if (rh.length) return { kind: "region", ses: regs.find(([, r]) => r.mesh === rh[0].object)[0] };
    return null;
  }
  function pick() {
    if (!pointer || downAt) return;
    const hit = hitAt(pointer.x, pointer.y);
    if (!hit) { hideTip(); canvas.style.cursor = "grab"; return; }
    const [title, body] = opts.describe ? opts.describe(hit) : ["", ""];
    tip.innerHTML = `<b>${title}</b><span>${body}</span>`;
    const r = canvas.getBoundingClientRect();
    tip.style.transform = `translate(${Math.min(pointer.x - r.left + 14, r.width - 270)}px, ${Math.max(pointer.y - r.top - 14 - tip.offsetHeight, 8)}px)`;
    tip.classList.add("on");
    canvas.style.cursor = "pointer";
  }
  const onMove = (e) => { pointer = { x: e.clientX, y: e.clientY }; pickPending = true; kick(); };
  const onLeave = () => { pointer = null; hideTip(); };
  const onDown = (e) => { downAt = { x: e.clientX, y: e.clientY }; };
  const onUp = (e) => {
    if (downAt && Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) < 5 && e.target === canvas) {
      const hit = hitAt(e.clientX, e.clientY);
      if (hit?.kind === "evidence") { setSelected(hit.e.item.id); opts.onSelect?.(hit.e.item.id); }
      else if (hit?.kind === "region") opts.onRegion?.(hit.ses);
    }
    downAt = null;
  };
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerleave", onLeave);
  canvas.addEventListener("pointerdown", onDown);
  window.addEventListener("pointerup", onUp);

  const mo = new MutationObserver(applyTheme);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  // ---- render loop: pauses when off screen or hidden, stops for good when the page is left
  let dirty = true, running = true, onScreen = true, raf = 0, last = 0, slow = 0, lastDraw = 0, interacting = false;
  const io = new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; if (onScreen) kick(); });
  io.observe(stage);
  const onVis = () => { if (!document.hidden) kick(); };
  document.addEventListener("visibilitychange", onVis);
  function frame(t) {
    raf = 0;
    if (!stage.isConnected) { dispose(); return; }
    if (!running || !onScreen || document.hidden) return;
    let moving = false;
    for (const r of Object.values(regions)) {
      const d = r.target - r.vis;
      if (Math.abs(d) > 0.004) { r.vis += d * 0.14; moving = true; } else r.vis = r.target;
    }
    if (controls.autoRotate && t > spinUntil) controls.autoRotate = false;
    const changed = controls.update();
    if (pickPending) { pickPending = false; pick(); }
    const animating = styleEvidence(t);
    // the slow auto-rotate alone is drawn at about 30 frames per second; anything the user does is drawn every frame
    const idleSpin = controls.autoRotate && !interacting && !moving && !animating && !dirty;
    if (idleSpin && t - lastDraw < 31) { raf = requestAnimationFrame(frame); return; }
    if (changed || moving || animating || dirty || controls.autoRotate) {
      lastDraw = t;
      styleScene();
      const L = camera.position.clone().sub(controls.target).normalize().add(new THREE.Vector3(0, 0.8, 0)).normalize();
      volMat.uniforms.uLight.value.copy(L);

      renderer.render(scene, camera);
      placeLabels();
      dirty = false;
      // adaptive quality: on a slow GPU, first shrink the volume target, then the pixel ratio, then stop auto-rotate
      if (last) {
        slow = t - last > 50 ? slow + 1 : Math.max(0, slow - 1);
        if (slow > 12) {
          slow = 0;
          if (pixelRatio > 1) { pixelRatio = 1; renderer.setPixelRatio(1); resize(); }
          else if (controls.autoRotate) controls.autoRotate = false;
        }
      }
      last = t;
      raf = requestAnimationFrame(frame);
    } else last = 0;                    // idle: no frame is scheduled until something changes
  }
  function kick() { if (!raf && running) raf = requestAnimationFrame(frame); }
  controls.addEventListener("change", kick);
  const watchdog = setInterval(() => { if (!stage.isConnected) dispose(); }, 1000);

  function dispose() {
    if (!running) return;
    running = false;
    if (raf) cancelAnimationFrame(raf);
    clearInterval(watchdog);
    ro.disconnect(); io.disconnect(); mo.disconnect();
    document.removeEventListener("visibilitychange", onVis);
    canvas.removeEventListener("pointermove", onMove);
    canvas.removeEventListener("pointerleave", onLeave);
    canvas.removeEventListener("pointerdown", onDown);
    window.removeEventListener("pointerup", onUp);
    opts.onDispose?.({ position: camera.position.toArray(), target: controls.target.toArray(), touched: userTouched });
    controls.dispose();
    for (const e of evidence) { e.mat.dispose(); e.fillMat.dispose(); e.group.children.forEach((o) => o.isInstancedMesh && o.dispose()); }
    disposables.forEach((d) => d.dispose());
    planeTex?.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
    canvas.remove(); overlay.remove(); tip.remove();
  }

  applyTheme();
  setSession(session);
  for (const r of Object.values(regions)) r.vis = r.target;
  resize();
  kick();
  return {
    setSession: (s) => { setSession(s); setSelected(selected); kick(); },
    setSlice: (k) => { sliceK = k; sliceShown = true; updateSlicePlane(); kick(); },
    setClip: (on) => { clip = on; if (on) sliceShown = true; updateSlicePlane(); kick(); },
    setEvidence,
    select: (id) => setSelected(id),
    highlight: (k) => { focus = k || null; dirty = true; kick(); },
    resetView: () => { home(); userTouched = false; dirty = true; kick(); },
    dispose,
  };
}
