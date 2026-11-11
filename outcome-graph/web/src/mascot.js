// Iris, Oversight's guide: a drop of drinking water with one big eye. The iris is striped in the
// five colors of EPA's verdicts, the same colors as the ring on the graph. Built procedurally in
// three.js, so there are no model files to load.
//
//   const iris = createMascot(el, { size: 120 });
//   iris.setState("thinking")      idle | listening | thinking | speaking | sleepy
//   iris.react("happy")            happy | oops | wave   (one-shot, then back to the state)
//   iris.lookAt(x, y, ms)          glance at a point on the screen (viewport px)
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

const VERDICT = ["#3ddc97", "#f5c451", "#a98bff", "#8b9bb4", "#ff6b6b"];  // adopted, partly, already, clarified, declined
const REDUCED = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function irisTexture() {
  const s = 256, c = document.createElement("canvas");
  c.width = c.height = s;
  const g = c.getContext("2d"), m = s / 2;
  const share = [0.22, 0.06, 0.07, 0.17, 0.48];  // roughly the verdict mix across the three rules
  let a0 = -Math.PI / 2;
  share.forEach((f, i) => {  // the verdict ring
    const a1 = a0 + f * Math.PI * 2;
    g.beginPath(); g.moveTo(m, m); g.arc(m, m, m, a0, a1); g.closePath();
    g.fillStyle = VERDICT[i]; g.fill();
    a0 = a1;
  });
  for (let k = 0; k < 90; k++) {  // fibres, so it reads as an eye and not a pie chart
    const a = (k / 90) * Math.PI * 2;
    g.strokeStyle = k % 2 ? "rgba(255,255,255,0.18)" : "rgba(0,0,0,0.16)";
    g.lineWidth = 1.6;
    g.beginPath(); g.moveTo(m + Math.cos(a) * m * 0.42, m + Math.sin(a) * m * 0.42); g.lineTo(m + Math.cos(a) * m, m + Math.sin(a) * m); g.stroke();
  }
  const rim = g.createRadialGradient(m, m, m * 0.7, m, m, m);
  rim.addColorStop(0, "rgba(10,20,40,0)"); rim.addColorStop(1, "rgba(10,20,40,0.75)");
  g.fillStyle = rim; g.beginPath(); g.arc(m, m, m, 0, Math.PI * 2); g.fill();
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function softDisc(inner, outer) {
  const s = 128, c = document.createElement("canvas");
  c.width = c.height = s;
  const g = c.getContext("2d"), grad = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  grad.addColorStop(0, inner); grad.addColorStop(1, outer);
  g.fillStyle = grad; g.fillRect(0, 0, s, s);
  return new THREE.CanvasTexture(c);
}

function dropGeometry() {  // a teardrop, round at the bottom and pointed at the top
  const pts = [];
  for (let i = 0; i <= 64; i++) {
    const t = Math.PI - (i / 64) * Math.PI;  // bottom to top
    const r = Math.sin(t) * Math.pow(Math.sin(t / 2), 1.1) * 1.18;
    pts.push(new THREE.Vector2(Math.max(r, 1e-4), Math.cos(t) * 1.25));
  }
  const geo = new THREE.LatheGeometry(pts, 96);
  geo.computeVertexNormals();
  return geo;
}

export function createMascot(el, { size = 120, interactive = true, ground = true } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  // The canvas is bigger than the layout box so hops, sparkles and ripples have room and never hit
  // its edge. The drop is drawn at the same on-screen size; the extra margin overflows the box.
  const PAD = 1.6, full = Math.round(size * PAD), off = (full - size) / 2;
  renderer.setSize(full, full);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  el.appendChild(renderer.domElement);
  renderer.domElement.style.cssText = `width:${full}px;height:${full}px;display:block;margin:${-off}px;pointer-events:none`;

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  const camera = new THREE.PerspectiveCamera(2 * Math.atan(PAD * Math.tan(THREE.MathUtils.degToRad(14))) * 180 / Math.PI, 1, 0.1, 50);
  camera.position.set(0, 0.1, 5.9);
  camera.lookAt(0, -0.15, 0);
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(2, 3, 4); scene.add(key);
  const rim = new THREE.DirectionalLight(0x2fd4e6, 2.5); rim.position.set(-3, 1, -2); scene.add(rim);
  scene.add(new THREE.AmbientLight(0x8fb6ff, 0.5));

  const root = new THREE.Group(); scene.add(root);     // position: hops and bobbing
  const body = new THREE.Group(); root.add(body);      // rotation and squash

  // the drop
  const water = new THREE.MeshPhysicalMaterial({
    color: 0x9fd0ff, transmission: 0.92, thickness: 0.6, ior: 1.33, roughness: 0.04, metalness: 0,
    clearcoat: 1, clearcoatRoughness: 0.05, iridescence: 0.15, iridescenceIOR: 1.3, attenuationColor: new THREE.Color(0x3d7bff),
    attenuationDistance: 2.6, envMapIntensity: 1.2,
  });
  const drop = new THREE.Mesh(dropGeometry(), water);
  body.add(drop);
  const glow = new THREE.Mesh(new THREE.SphereGeometry(0.72, 32, 24), new THREE.MeshBasicMaterial({ color: 0x3d7bff, transparent: true, opacity: 0.22 }));
  glow.position.set(0, -0.5, -0.1); body.add(glow);  // inner light, so the drop reads on a dark page

  // the eye
  const eye = new THREE.Group(); eye.position.set(0, -0.4, 0.3); body.add(eye);
  const look = new THREE.Group(); eye.add(look);
  const sclera = new THREE.Mesh(new THREE.SphereGeometry(0.44, 40, 30), new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.25, emissive: 0x9fbfff, emissiveIntensity: 0.18 }));
  look.add(sclera);
  const iris = new THREE.Mesh(new THREE.CircleGeometry(0.265, 48), new THREE.MeshStandardMaterial({ map: irisTexture(), roughness: 0.3, emissive: 0xffffff, emissiveIntensity: 0.12, emissiveMap: null }));
  iris.position.z = 0.425; look.add(iris);
  const pupil = new THREE.Mesh(new THREE.CircleGeometry(0.11, 40), new THREE.MeshBasicMaterial({ color: 0x05070d }));
  pupil.position.z = 0.428; look.add(pupil);
  const shine = new THREE.Mesh(new THREE.CircleGeometry(0.045, 20), new THREE.MeshBasicMaterial({ color: 0xffffff }));
  shine.position.set(0.08, 0.09, 0.432); look.add(shine);
  const shine2 = new THREE.Mesh(new THREE.CircleGeometry(0.02, 16), new THREE.MeshBasicMaterial({ color: 0xffffff }));
  shine2.position.set(-0.07, -0.07, 0.432); look.add(shine2);
  // eyelid: a dark band that drops over the eye for blinks and sleepiness
  const lid = new THREE.Mesh(new THREE.SphereGeometry(0.455, 40, 30, 0, Math.PI * 2, 0, Math.PI / 2), new THREE.MeshStandardMaterial({ color: 0x5f93ea, roughness: 0.3, emissive: 0x1d3f9a, emissiveIntensity: 0.3 }));
  eye.add(lid);

  // mouth: a smile, or an open "o" while talking
  const smileCurve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(-0.13, 0, 0), new THREE.Vector3(0, -0.1, 0.03), new THREE.Vector3(0.13, 0, 0));
  const mouthMat = new THREE.MeshBasicMaterial({ color: 0x0b1a3d });
  const smile = new THREE.Mesh(new THREE.TubeGeometry(smileCurve, 20, 0.03, 8), mouthMat);
  const mouth = new THREE.Group(); mouth.position.set(0, -1.0, 0.62); mouth.rotation.x = -0.35; body.add(mouth);
  mouth.add(smile);
  const ohh = new THREE.Mesh(new THREE.CircleGeometry(0.075, 24), mouthMat);
  ohh.position.set(0, -0.04, 0.01); ohh.scale.set(1, 0.01, 1); mouth.add(ohh);
  const cheekMat = new THREE.MeshBasicMaterial({ map: softDisc("rgba(255,120,150,0.55)", "rgba(255,120,150,0)"), transparent: true, depthWrite: false });
  for (const s of [-1, 1]) {
    const ch = new THREE.Mesh(new THREE.PlaneGeometry(0.26, 0.17), cheekMat);
    ch.position.set(s * 0.36, -0.86, 0.6); ch.rotation.y = s * 0.45; body.add(ch);
  }

  // The face is drawn over the water instead of through it, so it stays crisp: refraction made the
  // eye unreadable at small sizes. Draw order: bubbles, eye, lid, mouth and cheeks.
  const onTop = (obj, order) => obj.traverse((o) => {
    if (!o.isMesh) return;
    o.material.depthTest = false; o.material.transparent = true; o.renderOrder = order;
  });
  onTop(sclera, 10); onTop(iris, 11); onTop(pupil, 12); onTop(shine, 13); onTop(shine2, 13); onTop(lid, 14); onTop(mouth, 15);
  body.children.filter((c) => c.geometry?.type === "PlaneGeometry").forEach((c) => onTop(c, 15));

  // bubbles that rise inside while thinking
  const bubbleMat = new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.55, roughness: 0.1, depthTest: false });
  const bubbles = Array.from({ length: 7 }, (_, i) => {
    const b = new THREE.Mesh(new THREE.SphereGeometry(0.035 + (i % 3) * 0.015, 12, 10), bubbleMat);
    b.userData = { x: (Math.random() - 0.5) * 0.7, z: -0.25 + Math.random() * 0.2, p: Math.random(), v: 0.25 + Math.random() * 0.3 };
    b.visible = false; b.renderOrder = 9; body.add(b);
    return b;
  });

  // the asks it is reading: verdict-colored dots orbiting like the graph's ring
  const orbit = new THREE.Group(); orbit.rotation.x = 1.15; orbit.position.y = -0.45; root.add(orbit);
  const dots = Array.from({ length: 22 }, (_, i) => {
    const d = new THREE.Mesh(new THREE.SphereGeometry(0.075, 12, 10), new THREE.MeshBasicMaterial({ color: VERDICT[i % 5] }));
    const a = (i / 22) * Math.PI * 2;
    d.position.set(Math.cos(a) * 1.3, Math.sin(a) * 1.3, 0);
    orbit.add(d);
    return d;
  });

  // ripples on the "water" below: listening and talking
  const ripples = Array.from({ length: 3 }, () => {
    const r = new THREE.Mesh(new THREE.TorusGeometry(0.7, 0.012, 8, 64), new THREE.MeshBasicMaterial({ color: 0x8fb6ff, transparent: true, opacity: 0 }));
    r.rotation.x = Math.PI / 2; r.position.y = -1.42; scene.add(r);
    return r;
  });
  let shadow = null;
  if (ground) {
    shadow = new THREE.Mesh(new THREE.PlaneGeometry(1.9, 0.6), new THREE.MeshBasicMaterial({ map: softDisc("rgba(61,123,255,0.5)", "rgba(61,123,255,0)"), transparent: true, depthWrite: false }));
    shadow.rotation.x = -Math.PI / 2; shadow.position.y = -1.42; scene.add(shadow);
  }
  // sparkles for "happy"
  const sparkMat = new THREE.MeshBasicMaterial({ color: 0xfff2b0, transparent: true, opacity: 0 });
  const sparks = Array.from({ length: 6 }, (_, i) => {
    const s = new THREE.Mesh(new THREE.OctahedronGeometry(0.06), sparkMat.clone());
    s.userData.a = (i / 6) * Math.PI * 2; scene.add(s);
    return s;
  });

  // ------------------------------------------------------------------ behaviour
  const S = {
    state: "idle", react: null, reactT: 0, t0: performance.now(), last: performance.now(),
    look: new THREE.Vector2(), lookGoal: new THREE.Vector2(), hold: 0,
    level: null, blink: 0, nextBlink: 1.5, orbitOn: 0, rippleOn: 0, lean: 0, talk: 0, lid: 0, wave: 0,
  };
  const rect = () => renderer.domElement.getBoundingClientRect();
  function aim(x, y) {  // screen point -> eye angles
    const r = rect(), cx = r.left + r.width / 2, cy = r.top + r.height * 0.42;
    const d = Math.max(260, r.width * 2.4);
    return new THREE.Vector2(THREE.MathUtils.clamp(Math.atan2(x - cx, d), -0.46, 0.46), THREE.MathUtils.clamp(Math.atan2(y - cy, d), -0.36, 0.36));
  }
  const onMove = (e) => { if (performance.now() > S.hold) S.lookGoal.copy(aim(e.clientX, e.clientY)); };
  if (interactive) window.addEventListener("pointermove", onMove, { passive: true });

  let raf = 0, alive = true, visible = true;
  const io = new IntersectionObserver((es) => { visible = es[0].isIntersecting; if (visible && !raf) raf = requestAnimationFrame(frame); });
  io.observe(renderer.domElement);

  function frame(now) {
    raf = 0;
    if (!alive) return;
    const dt = Math.min(0.05, (now - S.last) / 1000); S.last = now;
    const t = (now - S.t0) / 1000;
    const st = S.state, rx = S.react, rt = (now - S.reactT) / 1000;
    const k = (rate) => 1 - Math.exp(-rate * dt);
    const calm = REDUCED ? 0.25 : 1;

    // where the eye points
    if (st === "thinking" && now > S.hold) S.lookGoal.set(Math.sin(t * 2.2) * 0.45, -0.12 + Math.sin(t * 1.3) * 0.08);
    if (st === "sleepy") S.lookGoal.set(0, 0.25);
    S.look.lerp(S.lookGoal, k(10));
    look.rotation.y = S.look.x; look.rotation.x = S.look.y;
    body.rotation.y = THREE.MathUtils.lerp(body.rotation.y, S.look.x * 0.45, k(4));

    // blinks
    S.nextBlink -= dt;
    if (S.nextBlink <= 0) { S.blink = 1; S.nextBlink = 1.8 + Math.random() * 3.5 + (Math.random() < 0.2 ? -1.5 : 0); }
    S.blink = Math.max(0, S.blink - dt * 7);
    const lidGoal = st === "sleepy" ? 0.5 : st === "thinking" ? 0.22 : rx === "oops" ? 0.4 : 0;
    S.lid += (lidGoal - S.lid) * k(6);
    const shut = Math.max(S.lid, Math.sin(S.blink * Math.PI));  // 0 open .. 1 shut
    // the lid is the top half-shell: tipped back it is out of sight, tipped forward it covers the eye
    lid.rotation.x = -1.35 + shut * (Math.PI / 2 + 1.3);
    lid.visible = shut > 0.03;
    const happyEye = rx === "happy" && rt < 1.1;
    eye.scale.set(1, happyEye ? 0.55 : st === "listening" ? 1.08 : 1, 1);
    pupil.scale.setScalar(THREE.MathUtils.lerp(pupil.scale.x, st === "listening" ? 1.35 : st === "thinking" ? 0.8 : 1, k(6)));

    // body: bob, breathe, lean, hop
    let y = Math.sin(t * 1.7) * 0.07 * calm, sq = 1 + Math.sin(t * 3.4) * 0.025 * calm;
    S.lean += ((st === "listening" ? 0.18 : st === "sleepy" ? 0.12 : 0) - S.lean) * k(5);
    if (rx === "happy" && rt < 0.9) {
      const p = rt / 0.9, h = Math.sin(p * Math.PI);
      y += h * 0.55 * calm; sq = p < 0.12 ? 1 - (0.12 - p) * 1.6 : p > 0.88 ? 1 - (p - 0.88) * 1.8 : 1 + h * 0.08;
    }
    if (rx === "oops" && rt < 0.7) body.rotation.z = Math.sin(rt * 40) * 0.1 * (1 - rt / 0.7) * calm; else body.rotation.z *= 0.85;
    if (rx === "wave" && rt < 1.4) body.rotation.z = Math.sin(rt * 9) * 0.16 * (1 - rt / 1.4) * calm;
    if (rx && rt > 1.6) S.react = null;
    root.position.y = y;
    body.rotation.x = S.lean;
    body.scale.set(1 / Math.sqrt(sq), sq, 1 / Math.sqrt(sq));
    glow.material.opacity = 0.18 + (st === "thinking" ? 0.12 + Math.sin(t * 6) * 0.06 : st === "listening" ? 0.16 : 0.02 * Math.sin(t * 2));
    if (shadow) { const s = 1 - y * 0.6; shadow.scale.set(s, s, s); shadow.material.opacity = 0.9 - y; }

    // mouth
    const talking = st === "speaking";
    // with real audio the mouth follows its loudness; otherwise it flaps on its own
    S.talk = talking ? (S.level != null ? 0.15 + S.level * 1.6 : 0.35 + Math.abs(Math.sin(t * 13) * Math.sin(t * 7.3)) * 0.9) : 0;
    ohh.scale.y += ((talking ? S.talk : rx === "oops" ? 0.55 : st === "listening" ? 0.3 : 0.01) - ohh.scale.y) * k(18);
    smile.visible = ohh.scale.y < 0.2;
    smile.scale.y = THREE.MathUtils.lerp(smile.scale.y, rx === "happy" ? 1.8 : st === "thinking" ? 0.25 : st === "sleepy" ? 0.4 : 1, k(8));

    // thinking: orbiting asks and rising bubbles
    S.orbitOn += ((st === "thinking" ? 1 : 0) - S.orbitOn) * k(5);
    orbit.visible = S.orbitOn > 0.02;
    orbit.rotation.z += dt * 1.6 * calm;
    dots.forEach((d, i) => d.scale.setScalar(S.orbitOn * (0.75 + 0.35 * Math.sin(t * 5 + i))));
    for (const b of bubbles) {
      b.visible = st === "thinking" || b.userData.p < 0.98 && b.visible;
      if (!b.visible) continue;
      b.userData.p += dt * b.userData.v;
      if (b.userData.p > 1) { b.userData.p = 0; b.visible = st === "thinking"; }
      const p = b.userData.p;
      b.position.set(b.userData.x * (1 - p * 0.8) + Math.sin(t * 3 + b.userData.v * 9) * 0.03, -1.05 + p * 1.7, b.userData.z);
    }

    // ripples
    S.rippleOn += ((st === "listening" || talking ? 1 : 0) - S.rippleOn) * k(4);
    ripples.forEach((r, i) => {
      const p = ((t * 0.7 + i / 3) % 1);
      r.scale.setScalar(0.6 + p * 1.3);
      r.material.opacity = S.rippleOn * (1 - p) * 0.7;
      r.material.color.set(st === "listening" ? 0xff8a9a : 0x8fb6ff);
    });

    // sparkles
    sparks.forEach((s, i) => {
      const on = rx === "happy" && rt < 1.2;
      const p = Math.min(1, rt / 1.2);
      s.material.opacity = on ? (1 - p) : 0;
      const a = s.userData.a + p * 1.2;
      s.position.set(Math.cos(a) * (0.9 + p * 0.7), 0.2 + Math.sin(a) * (0.6 + p * 0.5) + y, 0.3);
      s.rotation.set(t * 3, t * 4 + i, 0);
    });

    renderer.render(scene, camera);
    if (visible && !document.hidden) raf = requestAnimationFrame(frame);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && visible && !raf) raf = requestAnimationFrame(frame); });
  raf = requestAnimationFrame(frame);

  return {
    el: renderer.domElement,
    setState(s) { if (S.state !== s) { S.state = s; if (s === "listening") S.react = null; } },
    get state() { return S.state; },
    level(v) { S.level = v; },  // 0..1 loudness of the voice, or null
    react(kind) { S.react = kind; S.reactT = performance.now(); },
    lookAt(x, y, ms = 1400) { S.lookGoal.copy(aim(x, y)); S.hold = performance.now() + ms; },
    dispose() {
      alive = false; cancelAnimationFrame(raf); io.disconnect();
      window.removeEventListener("pointermove", onMove);
      renderer.dispose(); pmrem.dispose(); renderer.domElement.remove();
    },
  };
}
