// The landing page's moving parts: the ring of asks behind Iris, count-up numbers, and reveals.
const VCOL = { adopted: "#3ddc97", partly_adopted: "#f5c451", already_required: "#a98bff", clarified: "#8b9bb4", declined: "#ff6b6b" };
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

function rng(seed) { return () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646; }

// A small version of the graph: columns of asks around a ring. They appear grey in order (what
// commenters asked), a sweep gives each one EPA's verdict color (what EPA decided), then comments
// keep arriving and Iris watches each one land.
export function heroRing(canvas, verdicts, iris) {
  const ctx = canvas.getContext("2d");
  const r = rng(7), dpr = Math.min(2, devicePixelRatio || 1);
  let W = 0, H = 0, R0 = 0, gap = 0;
  const total = Object.values(verdicts).reduce((a, b) => a + b, 0) || 1;
  const bag = [];
  for (const [k, n] of Object.entries(verdicts)) for (let i = 0; i < Math.round((n / total) * 240); i++) bag.push(k);
  for (let i = bag.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [bag[i], bag[j]] = [bag[j], bag[i]]; }
  const COLS = 30, dots = [];
  let b = 0;
  for (let c = 0; c < COLS && b < bag.length; c++) {
    const h = 3 + Math.floor(r() * 9);
    for (let j = 0; j < h && b < bag.length; j++) dots.push({ c, j, v: bag[b++], changed: r() < 0.2, pulse: -9 });
  }
  const order = (d) => d.c / COLS;
  function size() {
    const box = canvas.getBoundingClientRect();
    W = box.width; H = box.height;
    canvas.width = W * dpr; canvas.height = H * dpr;
    R0 = Math.min(W, H) * 0.3; gap = Math.min(W, H) * 0.021;
  }
  size();
  addEventListener("resize", size);
  const pos = (d, rot) => {
    const a = -Math.PI / 2 + order(d) * Math.PI * 2 + rot + (d.j % 2 ? 0.012 : -0.012);
    const rr = R0 + d.j * gap;
    return [W / 2 + Math.cos(a) * rr, H / 2 + Math.sin(a) * rr];
  };
  const flights = [];
  let t0 = performance.now(), nextFlight = 3.6, mouse = null;
  canvas.parentElement.addEventListener("pointermove", (e) => { const bx = canvas.getBoundingClientRect(); mouse = [e.clientX - bx.left, e.clientY - bx.top]; });
  canvas.parentElement.addEventListener("pointerleave", () => { mouse = null; });

  function draw(now) {
    const t = (now - t0) / 1000;
    const rot = REDUCED ? 0 : t * 0.018;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    // the faint track, like the topic arcs on the graph
    ctx.strokeStyle = "rgba(143,182,255,0.10)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(W / 2, H / 2, R0 - gap * 1.2, 0, Math.PI * 2); ctx.stroke();
    const appear = REDUCED ? 99 : t / 1.5, sweep = REDUCED ? 99 : (t - 1.7) / 1.6;
    for (const d of dots) {
      const o = order(d);
      if (appear < o) continue;
      const [x, y] = pos(d, rot);
      let rad = gap * 0.36;
      if (mouse) { const dd = Math.hypot(mouse[0] - x, mouse[1] - y); if (dd < 50) rad *= 1 + (1 - dd / 50) * 0.8; }
      const fresh = (t - d.pulse);
      if (fresh < 0.8) rad *= 1 + Math.sin((fresh / 0.8) * Math.PI) * 1.4;
      const colored = sweep >= o;
      ctx.fillStyle = colored ? VCOL[d.v] : "#46526b";
      ctx.globalAlpha = Math.min(1, (appear - o) * 8);
      ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.fill();
      if (colored && d.changed) { ctx.strokeStyle = "#f4f7fb"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, rad + 2, 0, Math.PI * 2); ctx.stroke(); }
      if (fresh < 0.8) { ctx.strokeStyle = VCOL[d.v]; ctx.globalAlpha = 1 - fresh / 0.8; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, rad + fresh * 26, 0, Math.PI * 2); ctx.stroke(); }
    }
    ctx.globalAlpha = 1;
    // a comment flies in from outside and lands on its ask
    if (!REDUCED && t > nextFlight) {
      nextFlight = t + 1.6 + Math.random() * 1.8;
      const d = dots[Math.floor(Math.random() * dots.length)];
      const a = Math.random() * Math.PI * 2;
      flights.push({ d, t: t, sx: W / 2 + Math.cos(a) * W * 0.62, sy: H / 2 + Math.sin(a) * H * 0.62 });
    }
    for (let i = flights.length - 1; i >= 0; i--) {
      const f = flights[i], p = (t - f.t) / 1.1;
      const [x, y] = pos(f.d, rot);
      if (p >= 1) {
        f.d.pulse = t; flights.splice(i, 1);
        if (iris) { const bx = canvas.getBoundingClientRect(); iris.lookAt(bx.left + x, bx.top + y, 900); }
        continue;
      }
      const e = 1 - Math.pow(1 - p, 3);
      const cx = f.sx + (x - f.sx) * e, cy = f.sy + (y - f.sy) * e;
      const g = ctx.createLinearGradient(f.sx + (x - f.sx) * Math.max(0, e - 0.25), f.sy + (y - f.sy) * Math.max(0, e - 0.25), cx, cy);
      g.addColorStop(0, "rgba(143,182,255,0)"); g.addColorStop(1, "rgba(220,235,255,0.9)");
      ctx.strokeStyle = g; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(f.sx + (x - f.sx) * Math.max(0, e - 0.25), f.sy + (y - f.sy) * Math.max(0, e - 0.25)); ctx.lineTo(cx, cy); ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(cx, cy, 2.2, 0, Math.PI * 2); ctx.fill();
      if (iris && p > 0.35 && p < 0.4) { const bx = canvas.getBoundingClientRect(); iris.lookAt(bx.left + cx, bx.top + cy, 700); }
    }
    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);
}

export function countUp(el, to, ms = 1400) {
  if (REDUCED) { el.textContent = to.toLocaleString("en-US"); return; }
  const t0 = performance.now();
  const step = (now) => {
    const p = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - p, 4);
    el.textContent = Math.round(to * e).toLocaleString("en-US");
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// Add .in when an element scrolls into view; count-ups inside start then.
export function reveal(root = document) {
  const io = new IntersectionObserver((es) => es.forEach((e) => {
    if (!e.isIntersecting) return;
    e.target.classList.add("in");
    e.target.querySelectorAll("[data-to]").forEach((n) => countUp(n, +n.dataset.to, 1100));
    io.unobserve(e.target);
  }), { threshold: 0.15 });
  root.querySelectorAll(".reveal:not(.in)").forEach((el) => io.observe(el));
}

// Types a line into Iris's speech bubble.
export function say(el, text, speed = 22) {
  clearInterval(el._t);
  el.textContent = "";
  el.classList.add("on");
  let i = 0;
  el._t = setInterval(() => { el.textContent = text.slice(0, ++i); if (i >= text.length) clearInterval(el._t); }, REDUCED ? 0 : speed);
}
