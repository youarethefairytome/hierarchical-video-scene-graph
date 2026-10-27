const runtime = element._timelineRuntime || (element._timelineRuntime = {
  yaw: 0.85,
  pitch: 0.38,
  dist: 80,
  nodes: [],
  sourceFrames: [],
  title: "",
  selected: null,
  dragging: false,
  dragDistance: 0,
  lastX: 0,
  lastY: 0,
  hideLabels: false,
  userMoved: false,
  frameCount: 1,
  focusX: null,
});

const LAYER_Z = { 1: 6.8, 2: 3.4, 3: 0 };
const LAYER_COLOR = { 1: "#3b6ea5", 2: "#2f8f6b", 3: "#c47b00" };
const LAYER_NAME = { 1: "L1", 2: "L2", 3: "L3" };

function apply(raw) {
  let data = { nodes: [], source_frames: [], title: "", frame_count: 1 };
  try {
    data = JSON.parse(raw || "{}");
  } catch (error) {
    data = { nodes: [], source_frames: [], title: "数据无法解析", frame_count: 1 };
  }
  runtime.nodes = data.nodes || [];
  runtime.links = data.links || [];
  runtime.sourceFrames = data.source_frames || [];
  runtime.title = data.title || "";
  runtime.frameCount = data.frame_count || 1;
  runtime.counts = data.counts || {};
  if (!runtime.userMoved) fitCamera();
  draw();
}

function canvasOf() {
  return element.querySelector("canvas");
}

function resize(canvas) {
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(320, rect.width);
  const height = Math.max(480, rect.height);
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";
}

function fitCamera() {
  runtime.dist = Math.max(28, runtime.frameCount * 0.62);
}

function cross(a, b) {
  return { x: a.y * b.z - a.z * b.y, y: a.z * b.x - a.x * b.z, z: a.x * b.y - a.y * b.x };
}

function normalize(v) {
  const length = Math.hypot(v.x, v.y, v.z) || 1;
  return { x: v.x / length, y: v.y / length, z: v.z / length };
}

function camera() {
  const targetX = runtime.focusX == null ? (runtime.frameCount - 1) / 2 : runtime.focusX;
  const target = { x: targetX, y: 0, z: 3.4 };
  const flat = Math.cos(runtime.pitch);
  const eye = {
    x: target.x + runtime.dist * flat * Math.cos(runtime.yaw),
    y: target.y + runtime.dist * flat * Math.sin(runtime.yaw),
    z: target.z + runtime.dist * Math.sin(runtime.pitch),
  };
  const forward = normalize({ x: target.x - eye.x, y: target.y - eye.y, z: target.z - eye.z });
  let right = cross(forward, { x: 0, y: 0, z: 1 });
  if (Math.hypot(right.x, right.y, right.z) < 1e-4) right = { x: 1, y: 0, z: 0 };
  right = normalize(right);
  const up = normalize(cross(right, forward));
  return { eye, f: forward, r: right, u: up };
}

function project(point, cam, canvas) {
  const vx = point.x - cam.eye.x;
  const vy = point.y - cam.eye.y;
  const vz = point.z - cam.eye.z;
  const depth = vx * cam.f.x + vy * cam.f.y + vz * cam.f.z;
  const x = vx * cam.r.x + vy * cam.r.y + vz * cam.r.z;
  const y = vx * cam.u.x + vy * cam.u.y + vz * cam.u.z;
  const scale = 740 / Math.max(0.25, depth);
  return {
    sx: canvas.width / 2 + x * scale,
    sy: canvas.height / 2 - y * scale,
    depth,
    scale,
  };
}

function drawArrow(ctx, cam, canvas, origin, target, color, label) {
  const a = project(origin, cam, canvas);
  const b = project(target, cam, canvas);
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 3;
  ctx.globalAlpha = 0.95;
  ctx.beginPath();
  ctx.moveTo(a.sx, a.sy);
  ctx.lineTo(b.sx, b.sy);
  ctx.stroke();
  const angle = Math.atan2(b.sy - a.sy, b.sx - a.sx);
  ctx.beginPath();
  ctx.moveTo(b.sx, b.sy);
  ctx.lineTo(b.sx - 12 * Math.cos(angle - 0.4), b.sy - 12 * Math.sin(angle - 0.4));
  ctx.lineTo(b.sx - 12 * Math.cos(angle + 0.4), b.sy - 12 * Math.sin(angle + 0.4));
  ctx.closePath();
  ctx.fill();
  ctx.font = "18px Microsoft YaHei, sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(label, b.sx + 8, b.sy);
  ctx.globalAlpha = 1;
}

function drawAxis(ctx, cam, canvas) {
  const last = Math.max(0, runtime.frameCount - 1);
  const y0 = -6.2;
  [1, 2, 3].forEach((layer) => {
    const z = LAYER_Z[layer];
    const a = project({ x: 0, y: 0, z }, cam, canvas);
    const b = project({ x: last, y: 0, z }, cam, canvas);
    ctx.strokeStyle = LAYER_COLOR[layer];
    ctx.globalAlpha = 0.28;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(a.sx, a.sy);
    ctx.lineTo(b.sx, b.sy);
    ctx.stroke();
    ctx.globalAlpha = 1;
    const tag = project({ x: -Math.max(8, last * 0.03), y: 0, z }, cam, canvas);
    ctx.fillStyle = LAYER_COLOR[layer];
    ctx.font = "16px Microsoft YaHei, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(LAYER_NAME[layer], tag.sx, tag.sy);
  });
  drawArrow(ctx, cam, canvas, { x: 0, y: y0, z: 0 }, { x: Math.max(18, last * 0.16), y: y0, z: 0 }, "#dc2626", "X 时间");
  drawArrow(ctx, cam, canvas, { x: 0, y: y0, z: 0 }, { x: 0, y: y0 + 4.5, z: 0 }, "#15803d", "Y 画面左右");
  drawArrow(ctx, cam, canvas, { x: 0, y: y0, z: 0 }, { x: 0, y: y0, z: 8.2 }, "#1d4ed8", "Z 层次");
  if (runtime.focusX != null) {
    const top = project({ x: runtime.focusX, y: 0, z: 7.4 }, cam, canvas);
    const bottom = project({ x: runtime.focusX, y: 0, z: -0.4 }, cam, canvas);
    ctx.strokeStyle = "#b42318";
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(bottom.sx, bottom.sy);
    ctx.lineTo(top.sx, top.sy);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  const step = last > 400 ? 100 : 40;
  ctx.fillStyle = "#4b5563";
  ctx.font = "13px Microsoft YaHei, sans-serif";
  ctx.textAlign = "center";
  for (let frame = 0; frame <= last; frame += step) {
    const tickA = project({ x: frame, y: y0, z: 0 }, cam, canvas);
    const tickB = project({ x: frame, y: y0 - 0.7, z: 0 }, cam, canvas);
    ctx.strokeStyle = "#dc2626";
    ctx.globalAlpha = 0.7;
    ctx.beginPath();
    ctx.moveTo(tickA.sx, tickA.sy);
    ctx.lineTo(tickB.sx, tickB.sy);
    ctx.stroke();
    ctx.globalAlpha = 1;
    if (!runtime.hideLabels) {
      const source = runtime.sourceFrames[frame];
      ctx.fillStyle = "#4b5563";
      ctx.fillText(source === undefined ? String(frame) : String(source), tickB.sx, tickB.sy + 14);
    }
  }
}

function drawNearbyLabels(ctx, canvas, projected) {
  if (runtime.hideLabels) return;
  const anchor = runtime.focusX == null ? (runtime.frameCount - 1) / 2 : runtime.focusX;
  const windowFrames = runtime.dist < 45 ? 4 : runtime.dist < 90 ? 8 : 16;
  const labels = projected.filter((item) => {
    if (Math.abs(item.node[0] - anchor) > windowFrames) return false;
    if (item.depth < 0.2) return false;
    if (item.sx < -40 || item.sy < -40 || item.sx > canvas.width + 40 || item.sy > canvas.height + 40) return false;
    return true;
  });
  labels.sort((a, b) => Math.abs(a.node[0] - anchor) - Math.abs(b.node[0] - anchor) || a.node[1] - b.node[1]);
  ctx.font = "13px Microsoft YaHei, sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.lineWidth = 3;
  labels.slice(0, 800).forEach((item) => {
    const layer = item.node[1];
    const text = item.node[3];
    const x = item.sx + item.hit + 4;
    const y = item.sy + (layer - 2) * 11;
    ctx.strokeStyle = "rgba(255,255,255,0.92)";
    ctx.strokeText(text, x, y);
    ctx.fillStyle = LAYER_COLOR[layer] || "#1f2937";
    ctx.fillText(text, x, y);
  });
}

function draw() {
  const canvas = canvasOf();
  const hud = element.querySelector(".hud");
  if (!canvas) return;
  resize(canvas);
  const ctx = canvas.getContext("2d");
  const cam = camera();
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#f7f8fb";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  drawAxis(ctx, cam, canvas);

  const projected = runtime.nodes.map((node) => {
    const point = project({ x: node[0], y: node[2], z: LAYER_Z[node[1]] || 0 }, cam, canvas);
    return { node, ...point };
  });
  runtime.links.forEach((pair) => {
    const parent = projected[pair[0]];
    const child = projected[pair[1]];
    if (!parent || !child || parent.depth < 0.2 || child.depth < 0.2) return;
    ctx.strokeStyle = LAYER_COLOR[child.node[1]] || "#94a3b8";
    ctx.globalAlpha = 0.55;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(parent.sx, parent.sy);
    ctx.lineTo(child.sx, child.sy);
    ctx.stroke();
    ctx.globalAlpha = 1;
  });
  projected.sort((a, b) => b.depth - a.depth);
  projected.forEach((item) => {
    const radius = Math.max(2.2, 5.5 * item.scale / 40);
    const color = LAYER_COLOR[item.node[1]] || "#64748b";
    ctx.fillStyle = color;
    ctx.globalAlpha = item.node[1] === 3 ? 0.95 : 0.82;
    ctx.beginPath();
    ctx.arc(item.sx, item.sy, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
    item.hit = radius;
  });
  drawNearbyLabels(ctx, canvas, projected);
  runtime.projected = projected;

  const hideBox = element.querySelector(".hide-labels");
  if (hideBox) hideBox.checked = !!runtime.hideLabels;
  const slider = element.querySelector(".x-slider");
  const readout = element.querySelector(".x-readout");
  if (slider) {
    slider.max = String(Math.max(0, runtime.frameCount - 1));
    slider.value = String(runtime.focusX == null ? 0 : runtime.focusX);
  }
  if (readout) {
    if (runtime.focusX == null) {
      readout.textContent = "全段";
    } else {
      const source = runtime.sourceFrames[runtime.focusX];
      readout.textContent = source === undefined ? `采样帧 ${runtime.focusX}` : `原始帧 ${source}`;
    }
  }
  if (hud) {
    const picked = runtime.selected;
    if (picked) {
      const source = runtime.sourceFrames[picked[0]];
      hud.innerHTML = [
        picked[3],
        `层: L${picked[1]}`,
        `采样帧: ${picked[0]}`,
        `原始帧: ${source === undefined ? "-" : source}`,
        `类别: ${picked[5] || "-"}`,
        `轨迹: ${picked[4] || "-"}`,
      ].map((line) => `<div>${escapeHtml(line)}</div>`).join("");
    } else {
      const counts = runtime.counts || {};
      hud.innerHTML = `<div>${escapeHtml(runtime.title)}</div><div>竖轴是 Z，从上到下是 L1、L2、L3。横轴 X 是时间。Y 是目标在画面里的左右位置。节点 ${runtime.nodes.length}（L1 ${counts[1] || 0}，L2 ${counts[2] || 0}，L3 ${counts[3] || 0}）</div>`;
    }
  }
}

function escapeHtml(text) {
  return String(text).replace(/[&<>]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[char]));
}

function hitTest(event) {
  const canvas = canvasOf();
  if (!canvas || !runtime.projected) return null;
  const rect = canvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) * (canvas.width / rect.width);
  const y = (event.clientY - rect.top) * (canvas.height / rect.height);
  let best = null;
  let bestDist = Infinity;
  runtime.projected.forEach((item) => {
    const dist = Math.hypot(item.sx - x, item.sy - y);
    const limit = Math.max(8, (item.hit || 4) * 1.8);
    if (dist <= limit && dist < bestDist) {
      best = item;
      bestDist = dist;
    }
  });
  return best;
}

if (!runtime.bound) {
  runtime.bound = true;
  element.addEventListener("pointerdown", (event) => {
    if (event.target !== canvasOf()) return;
    runtime.dragging = true;
    runtime.dragDistance = 0;
    runtime.userMoved = true;
    runtime.lastX = event.clientX;
    runtime.lastY = event.clientY;
  });
  element.addEventListener("pointermove", (event) => {
    if (!runtime.dragging) return;
    const dx = event.clientX - runtime.lastX;
    const dy = event.clientY - runtime.lastY;
    runtime.dragDistance += Math.hypot(dx, dy);
    runtime.yaw += dx * 0.007;
    runtime.pitch = Math.max(-0.15, Math.min(1.2, runtime.pitch + dy * 0.005));
    runtime.lastX = event.clientX;
    runtime.lastY = event.clientY;
    draw();
  });
  element.addEventListener("pointerup", (event) => {
    runtime.dragging = false;
    if ((runtime.dragDistance || 0) < 5) {
      const hit = hitTest(event);
      runtime.selected = hit ? hit.node : null;
      draw();
    }
  });
  element.addEventListener("wheel", (event) => {
    if (event.target !== canvasOf()) return;
    event.preventDefault();
    runtime.userMoved = true;
    runtime.dist = Math.max(12, Math.min(runtime.frameCount * 1.4, runtime.dist + event.deltaY * 0.08));
    draw();
  }, { passive: false });
  element.addEventListener("change", (event) => {
    if (!event.target.classList || !event.target.classList.contains("hide-labels")) return;
    runtime.hideLabels = event.target.checked;
    draw();
  });
  element.addEventListener("input", (event) => {
    if (!event.target.classList || !event.target.classList.contains("x-slider")) return;
    runtime.focusX = Number(event.target.value);
    runtime.userMoved = true;
    runtime.dist = 24;
    runtime.pitch = 0.42;
    draw();
  });
  element.addEventListener("click", (event) => {
    if (!event.target.classList || !event.target.classList.contains("reset")) return;
    runtime.yaw = 0.85;
    runtime.pitch = 0.38;
    runtime.userMoved = false;
    runtime.focusX = null;
    runtime.selected = null;
    fitCamera();
    draw();
  });
}

apply(props.value);
watch("value", () => apply(props.value));
