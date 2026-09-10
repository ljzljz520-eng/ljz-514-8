/* 学生端逻辑:加载地图、选择起终点/途经点、查询并展示无障碍路线 */
const SVGNS = "http://www.w3.org/2000/svg";
const KIND_ICON = { walkway: "🚶", ramp: "🛤️", elevator: "🛗", stairs: "⚠️", slope_path: "⛰️" };
const TYPE_ICON = { dormitory: "🏠", teaching: "🏫", cafeteria: "🍚", library: "📚" };

let graph = null;      // {nodes, edges}
let locations = [];    // 可选地点

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || ("请求失败 " + res.status));
  return data;
}

/* ---------- 地图渲染 ---------- */
function drawMap() {
  const svg = document.getElementById("map");
  svg.innerHTML = "";
  const gEdges = document.createElementNS(SVGNS, "g");
  const gRoute = document.createElementNS(SVGNS, "g");
  gRoute.id = "route-layer";
  const gNodes = document.createElementNS(SVGNS, "g");
  svg.append(gEdges, gRoute, gNodes);

  for (const e of graph.edges) {
    const a = graph.nodes[e.from], b = graph.nodes[e.to];
    if (!a || !b) continue;
    const line = document.createElementNS(SVGNS, "line");
    line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
    line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    line.setAttribute("class", "edge " + e.kind);
    line.dataset.eid = e.id;
    const title = document.createElementNS(SVGNS, "title");
    title.textContent = `${e.id}: ${e.kind} ${e.distance}m 坡度${(e.slope*100).toFixed(1)}%`;
    line.appendChild(title);
    gEdges.appendChild(line);
  }

  for (const [nid, n] of Object.entries(graph.nodes)) {
    const g = document.createElementNS(SVGNS, "g");
    g.dataset.nid = nid;
    if (n.type === "junction") {
      const c = document.createElementNS(SVGNS, "circle");
      c.setAttribute("cx", n.x); c.setAttribute("cy", n.y);
      c.setAttribute("r", 5); c.setAttribute("class", "node-jct");
      g.appendChild(c);
      const t = document.createElementNS(SVGNS, "text");
      t.setAttribute("x", n.x); t.setAttribute("y", n.y + 18);
      t.setAttribute("class", "node-label"); t.setAttribute("font-size", "10");
      t.textContent = n.name;
      g.appendChild(t);
    } else {
      const r = document.createElementNS(SVGNS, "rect");
      r.setAttribute("x", n.x - 26); r.setAttribute("y", n.y - 26);
      r.setAttribute("width", 52); r.setAttribute("height", 52);
      r.setAttribute("rx", 10); r.setAttribute("class", "node-bldg");
      g.appendChild(r);
      const icon = document.createElementNS(SVGNS, "text");
      icon.setAttribute("x", n.x); icon.setAttribute("y", n.y + 7);
      icon.setAttribute("class", "node-icon");
      icon.textContent = TYPE_ICON[n.type] || "📍";
      g.appendChild(icon);
      const t = document.createElementNS(SVGNS, "text");
      t.setAttribute("x", n.x); t.setAttribute("y", n.y + 44);
      t.setAttribute("class", "node-label");
      t.textContent = n.name;
      g.appendChild(t);
    }
    gNodes.appendChild(g);
  }
}

function highlightRoute(edgeIds, nodeIds) {
  const layer = document.getElementById("route-layer");
  layer.innerHTML = "";
  document.querySelectorAll(".node-hl").forEach(el => el.classList.remove("node-hl"));
  const edgeMap = Object.fromEntries(graph.edges.map(e => [e.id, e]));
  for (const eid of edgeIds) {
    const e = edgeMap[eid];
    if (!e) continue;
    const a = graph.nodes[e.from], b = graph.nodes[e.to];
    const line = document.createElementNS(SVGNS, "line");
    line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
    line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    line.setAttribute("class", "edge route");
    layer.appendChild(line);
  }
  for (const nid of nodeIds) {
    const g = document.querySelector(`g[data-nid="${nid}"] rect`);
    if (g) g.classList.add("node-hl");
  }
}

/* ---------- 表单 ---------- */
function fillSelect(sel, includeJunction) {
  sel.innerHTML = "";
  for (const loc of locations) {
    if (!includeJunction && loc.type === "junction") continue;
    const o = document.createElement("option");
    o.value = loc.id; o.textContent = loc.name;
    sel.appendChild(o);
  }
}

function addVia(value) {
  const row = document.createElement("div");
  row.className = "via-row";
  const sel = document.createElement("select");
  fillSelect(sel, false);
  if (value) sel.value = value;
  const btn = document.createElement("button");
  btn.type = "button"; btn.className = "via-remove"; btn.textContent = "✕";
  btn.onclick = () => row.remove();
  row.append(sel, btn);
  document.getElementById("via-container").appendChild(row);
}

/* ---------- 查询 ---------- */
async function search() {
  const errBox = document.getElementById("error");
  errBox.hidden = true;
  const waypoints = [document.getElementById("start").value];
  document.querySelectorAll("#via-container select").forEach(s => waypoints.push(s.value));
  waypoints.push(document.getElementById("end").value);
  const profile = document.querySelector("input[name=profile]:checked").value;
  try {
    const r = await api("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ waypoints, profile })
    });
    renderResult(r);
    highlightRoute(r.path.edges, r.path.nodes);
  } catch (e) {
    errBox.textContent = e.message;
    errBox.hidden = false;
    document.getElementById("result").hidden = true;
    highlightRoute([], []);
  }
}

function renderResult(r) {
  document.getElementById("result").hidden = false;
  const names = r.node_names;
  document.getElementById("summary").innerHTML = `
    <div class="stat"><b>${r.total_distance}</b><span>总距离(米)</span></div>
    <div class="stat"><b>${r.estimated_minutes}</b><span>预计时间(分钟)</span></div>
    <div class="stat"><b>${r.barrier_free ? "全程无楼梯" : "含楼梯"}</b><span>无障碍情况</span></div>`;
  const fc = r.facility_counts;
  const label = { walkway: "平缓通道", ramp: "无障碍坡道", elevator: "电梯", stairs: "楼梯", slope_path: "坡道路段" };
  document.getElementById("badges").innerHTML = Object.entries(fc).map(([k, v]) =>
    `<span class="badge ${k === "stairs" || k === "slope_path" ? "warn" : ""}">${KIND_ICON[k] || ""} ${label[k] || k} × ${v}</span>`
  ).join("");
  document.getElementById("steps").innerHTML = r.steps.map(s =>
    `<li>从 <b>${names[s.from]}</b> 出发,经${KIND_ICON[s.kind] || ""}<b>${s.desc}</b>前行 <b>${s.distance}m</b>,到达 <b>${names[s.to]}</b></li>`
  ).join("");
}

/* ---------- 初始化 ---------- */
(async function init() {
  const [locData, graphData] = await Promise.all([api("/api/locations"), api("/api/graph")]);
  locations = locData.locations;
  graph = graphData;
  drawMap();
  fillSelect(document.getElementById("start"), false);
  fillSelect(document.getElementById("end"), false);
  document.getElementById("end").selectedIndex = 1;
  document.getElementById("add-via").onclick = () => addVia();
  document.getElementById("search").onclick = search;
})();
