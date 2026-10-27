const runtime = element._layeredRuntime || (element._layeredRuntime = {
  yaw: -0.62,
  pitch: 0.48,
  dist: 15.5,
  nodes: [],
  edges: [],
  title: "",
  selected: null,
  dragging: false,
  lastX: 0,
  lastY: 0,
});

const LAYER_Y = [4.55, 3.25, 2.0, 0.75, -0.5];
const LAYER_NAME = ["L0 Scene Layer", "L1 Entity Layer", "L2 Part Layer", "L3 Attribute Layer", "L4 Relation Layer"];
const PLANE = [
  [214, 228, 245],
  [223, 236, 214],
  [245, 236, 196],
  [230, 223, 245],
  [245, 214, 224],
];

function apply(raw) {
  let data = { nodes: [], edges: [], title: "" };
  try {
    data = JSON.parse(raw || "{}");
  } catch (error) {
    data = { nodes: [], edges: [], title: "数据无法解析" };
  }
  runtime.nodes = data.nodes || [];
  runtime.edges = data.edges || [];
  runtime.title = data.title || "";
  if (runtime.selected && !runtime.nodes.some((node) => node.id === runtime.selected)) {
    runtime.selected = null;
  }
  if (!runtime.userMoved) fitCamera();
  draw();
}

function extents() {
  let maxX = 4;
  let maxZ = 1.6;
  runtime.nodes.forEach((node) => {
    maxX = Math.max(maxX, Math.abs(node.x));
    maxZ = Math.max(maxZ, Math.abs(node.z));
  });
  return { spanX: maxX + 1.8, spanZ: Math.max(3.2, maxZ + 1.5) };
}

function fitCamera() {
  runtime.dist = Math.max(14, extents().spanX * 1.45);
}

function canvasOf() {
  return element.querySelector("canvas");
}

function resize(canvas) {
  const stage = canvas.parentElement;
  const rect = stage.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(320, rect.width);
  const height = Math.max(420, rect.height);
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";
}

function camera() {
  const target = { x: 0, y: 2.0, z: 0.35 };
  const eye = {
    x: target.x + runtime.dist * Math.cos(runtime.pitch) * Math.sin(runtime.yaw),
    y: target.y + runtime.dist * Math.sin(runtime.pitch),
    z: target.z + runtime.dist * Math.cos(runtime.pitch) * Math.cos(runtime.yaw),
  };
  let fx = target.x - eye.x;
  let fy = target.y - eye.y;
  let fz = target.z - eye.z;
  const fl = Math.hypot(fx, fy, fz) || 1;
  fx /= fl; fy /= fl; fz /= fl;
  let rx = fy * 0 - fz * 1;
  let ry = fz * 0 - fx * 0;
  let rz = fx * 1 - fy * 0;
  const rl = Math.hypot(rx, ry, rz) || 1;
  rx /= rl; ry /= rl; rz /= rl;
  const ux = ry * fz - rz * fy;
  const uy = rz * fx - rx * fz;
  const uz = rx * fy - ry * fx;
  return { eye, target, f: { x: fx, y: fy, z: fz }, r: { x: rx, y: ry, z: rz }, u: { x: ux, y: uy, z: uz } };
}

function project(point, cam, canvas) {
  const vx = point.x - cam.eye.x;
  const vy = point.y - cam.eye.y;
  const vz = point.z - cam.eye.z;
  const depth = vx * cam.f.x + vy * cam.f.y + vz * cam.f.z;
  const x = vx * cam.r.x + vy * cam.r.y + vz * cam.r.z;
  const y = vx * cam.u.x + vy * cam.u.y + vz * cam.u.z;
  const scale = 520 / Math.max(0.2, depth);
  return {
    sx: canvas.width / 2 + x * scale,
    sy: canvas.height / 2 - y * scale,
    depth,
    scale,
  };
}

function shade(hex, amount) {
  const value = hex.replace("#", "");
  const num = parseInt(value.length === 3 ? value.split("").map((ch) => ch + ch).join("") : value, 16);
  const mix = (channel) => Math.max(0, Math.min(255, Math.round(channel + (amount < 0 ? channel * amount : (255 - channel) * amount))));
  const r = mix((num >> 16) & 255);
  const g = mix((num >> 8) & 255);
  const b = mix(num & 255);
  return `rgb(${r},${g},${b})`;
}

function draw(raw) {
  const canvas = canvasOf();
  const hud = element.querySelector(".hud");
  if (!canvas) return;
  resize(canvas);
  const ctx = canvas.getContext("2d");
  const cam = camera();
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#fbfbfd";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const planes = LAYER_Y.map((y, layer) => {
    const spanX = extents().spanX;
    const spanZ = extents().spanZ;
    const corners = [
      { x: -spanX, y, z: -spanZ },
      { x: spanX, y, z: -spanZ },
      { x: spanX, y, z: spanZ },
      { x: -spanX, y, z: spanZ },
    ].map((point) => project(point, cam, canvas));
    const depth = corners.reduce((sum, item) => sum + item.depth, 0) / 4;
    return { layer, corners, depth, y };
  }).sort((a, b) => b.depth - a.depth);

  planes.forEach((plane) => {
    const [r, g, b] = PLANE[plane.layer];
    ctx.beginPath();
    plane.corners.forEach((point, index) => {
      if (index === 0) ctx.moveTo(point.sx, point.sy);
      else ctx.lineTo(point.sx, point.sy);
    });
    ctx.closePath();
    ctx.fillStyle = `rgba(${r},${g},${b},0.9)`;
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,0.85)";
    ctx.lineWidth = 2;
    ctx.stroke();
    const labelPoint = project({ x: -extents().spanX - 0.35, y: plane.y, z: 0 }, cam, canvas);
    ctx.fillStyle = "#243044";
    ctx.font = `${Math.max(13, 15 * (canvas.width / 1400))}px Microsoft YaHei, sans-serif`;
    ctx.textAlign = "right";
    ctx.fillText(LAYER_NAME[plane.layer], labelPoint.sx, labelPoint.sy);
  });

  const nodeMap = Object.fromEntries(runtime.nodes.map((node) => [node.id, node]));
  const projected = runtime.nodes.map((node) => {
    const point = project({ x: node.x, y: LAYER_Y[node.layer], z: node.z }, cam, canvas);
    return { node, ...point };
  });
  const byId = Object.fromEntries(projected.map((item) => [item.node.id, item]));

  runtime.edges.forEach((edge) => {
    const a = byId[edge.source];
    const b = byId[edge.target];
    if (!a || !b) return;
    ctx.save();
    ctx.strokeStyle = edge.color || "#8aa0b8";
    ctx.globalAlpha = 0.85;
    ctx.lineWidth = Math.max(1.2, 2.2 * Math.min(a.scale, b.scale) / 40);
    if (edge.dash) ctx.setLineDash([7, 6]);
    ctx.beginPath();
    ctx.moveTo(a.sx, a.sy);
    ctx.lineTo(b.sx, b.sy);
    ctx.stroke();
    ctx.restore();
  });

  projected.sort((a, b) => b.depth - a.depth).forEach((item) => {
    const radius = Math.max(8, 13 * item.scale / 34);
    const selected = runtime.selected === item.node.id;
    if (item.node.shape === "card") {
      ctx.font = `${Math.max(12, 13 * item.scale / 36)}px Microsoft YaHei, sans-serif`;
      const width = runtime.hideLabels ? radius * 2.4 : Math.max(74, ctx.measureText(item.node.label).width + 22);
      const height = radius * 2.1;
      ctx.fillStyle = item.node.color;
      roundRect(ctx, item.sx - width / 2, item.sy - height / 2, width, height, 10);
      ctx.fill();
      if (selected) {
        ctx.strokeStyle = "#111827";
        ctx.lineWidth = 3;
        roundRect(ctx, item.sx - width / 2, item.sy - height / 2, width, height, 10);
        ctx.stroke();
      }
      if (!runtime.hideLabels) {
        ctx.fillStyle = "white";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(item.node.label, item.sx, item.sy);
      }
      item.hit = Math.max(width, height) / 2;
      return;
    }
    const gradient = ctx.createRadialGradient(item.sx - radius * 0.35, item.sy - radius * 0.4, radius * 0.15, item.sx, item.sy, radius);
    gradient.addColorStop(0, "#ffffff");
    gradient.addColorStop(0.45, item.node.color);
    gradient.addColorStop(1, shade(item.node.color, -0.28));
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.arc(item.sx, item.sy, radius, 0, Math.PI * 2);
    ctx.fill();
    if (selected) {
      ctx.strokeStyle = "#111827";
      ctx.lineWidth = 3;
      ctx.stroke();
    }
    if (!runtime.hideLabels) {
      ctx.fillStyle = "#1f2937";
      ctx.font = `${Math.max(12, 14 * item.scale / 36)}px Microsoft YaHei, sans-serif`;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(item.node.label, item.sx + radius + 6, item.sy);
    }
    item.hit = radius;
  });
  runtime.projected = projected;

  const hideBox = element.querySelector(".hide-labels");
  if (hideBox) hideBox.checked = !!runtime.hideLabels;

  if (hud) {
    const picked = runtime.nodes.find((node) => node.id === runtime.selected);
    const lines = picked ? [picked.detail.title, ...(picked.detail.lines || [])] : [runtime.title || "拖动旋转，滚轮缩放，点击节点"];
    hud.innerHTML = lines.map((line) => `<div>${escapeHtml(line)}</div>`).join("");
  }
}

function roundRect(ctx, x, y, width, height, radius) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + width, y, x + width, y + height, radius);
  ctx.arcTo(x + width, y + height, x, y + height, radius);
  ctx.arcTo(x, y + height, x, y, radius);
  ctx.arcTo(x, y, x + width, y, radius);
  ctx.closePath();
}

function escapeHtml(text) {
  return String(text).replace(/[&<>]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[char]));
}

function hitTest(event) {
  const canvas = canvasOf();
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) * (canvas.width / rect.width);
  const y = (event.clientY - rect.top) * (canvas.height / rect.height);
  let best = null;
  let bestDist = Infinity;
  (runtime.projected || []).forEach((item) => {
    const dist = Math.hypot(item.sx - x, item.sy - y);
    const limit = Math.max(18, (item.hit || 16) * 1.25);
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
    element.setPointerCapture?.(event.pointerId);
  });
  element.addEventListener("pointermove", (event) => {
    if (!runtime.dragging) return;
    const dx = event.clientX - runtime.lastX;
    const dy = event.clientY - runtime.lastY;
    runtime.dragDistance += Math.hypot(dx, dy);
    runtime.yaw += dx * 0.008;
    runtime.pitch = Math.max(-0.2, Math.min(1.15, runtime.pitch + dy * 0.006));
    runtime.lastX = event.clientX;
    runtime.lastY = event.clientY;
    draw();
  });
  element.addEventListener("pointerup", (event) => {
    if (!runtime.dragging) return;
    runtime.dragging = false;
    if ((runtime.dragDistance || 0) < 5) {
      const hit = hitTest(event);
      runtime.selected = hit ? hit.node.id : null;
      draw();
    }
  });
  element.addEventListener("wheel", (event) => {
    if (event.target !== canvasOf()) return;
    event.preventDefault();
    runtime.userMoved = true;
    runtime.dist = Math.max(8, Math.min(80, runtime.dist + event.deltaY * 0.02));
    draw();
  }, { passive: false });
  element.addEventListener("change", (event) => {
    if (!event.target.classList || !event.target.classList.contains("hide-labels")) return;
    runtime.hideLabels = event.target.checked;
    draw();
  });
  element.addEventListener("click", (event) => {
    if (!event.target.classList || !event.target.classList.contains("reset")) return;
    runtime.yaw = -0.62;
    runtime.pitch = 0.48;
    runtime.userMoved = false;
    runtime.selected = null;
    fitCamera();
    draw();
  });
}

apply(props.value);
watch("value", () => apply(props.value));
