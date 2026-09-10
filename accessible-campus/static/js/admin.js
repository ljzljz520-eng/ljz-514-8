/* 管理端逻辑:节点/通道(边)的增删改查 + 算法权重设置 */
const KIND_LABEL = { walkway: "平缓通道", ramp: "无障碍坡道", elevator: "电梯", stairs: "楼梯", slope_path: "坡道" };
const TYPE_LABEL = { dormitory: "宿舍", teaching: "教学楼", cafeteria: "食堂", library: "图书馆", junction: "路口/途经点" };
const SURFACE_LABEL = { smooth: "平整", rough: "颠簸" };

let campus = { nodes: {}, edges: [] };
let weights = null;

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || ("请求失败 " + res.status));
  return data;
}
function toast(msg, isErr) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  t.hidden = false;
  setTimeout(() => t.hidden = true, 2500);
}
const jsonOpts = (method, obj) => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(obj)
});

/* ================= 标签页 ================= */
document.querySelectorAll(".tab").forEach(btn => btn.onclick = () => {
  document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  document.querySelectorAll(".tab-panel").forEach(p => p.hidden = true);
  document.getElementById("tab-" + btn.dataset.tab).hidden = false;
});

/* ================= 节点管理 ================= */
async function loadCampus() {
  campus = await api("/api/graph");
  renderNodes(); renderEdges(); fillEdgeNodeSelects();
}
function renderNodes() {
  const tb = document.querySelector("#node-table tbody");
  tb.innerHTML = "";
  for (const [nid, n] of Object.entries(campus.nodes)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${nid}</td><td>${n.name}</td><td>${TYPE_LABEL[n.type] || n.type}</td>
      <td>${n.x}</td><td>${n.y}</td><td></td>`;
    const td = tr.lastElementChild;
    const edit = document.createElement("button");
    edit.className = "btn btn-sm btn-edit"; edit.textContent = "编辑";
    edit.onclick = () => fillNodeForm(nid, n);
    const del = document.createElement("button");
    del.className = "btn btn-sm btn-del"; del.textContent = "删除";
    del.onclick = () => delNode(nid);
    td.append(edit, del);
    tb.appendChild(tr);
  }
}
function fillNodeForm(nid, n) {
  document.getElementById("node-editing").value = nid;
  document.getElementById("node-id").value = nid;
  document.getElementById("node-id").disabled = true;
  document.getElementById("node-name").value = n.name;
  document.getElementById("node-type").value = n.type;
  document.getElementById("node-x").value = n.x;
  document.getElementById("node-y").value = n.y;
}
function resetNodeForm() {
  document.getElementById("node-form").reset();
  document.getElementById("node-editing").value = "";
  document.getElementById("node-id").disabled = false;
}
async function delNode(nid) {
  if (!confirm(`删除节点 ${nid} 将同时删除与其相连的所有通道,确认?`)) return;
  try {
    await api("/api/admin/nodes/" + nid, { method: "DELETE" });
    toast("节点已删除"); loadCampus();
  } catch (e) { toast(e.message, true); }
}
document.getElementById("node-form").onsubmit = async ev => {
  ev.preventDefault();
  const editing = document.getElementById("node-editing").value;
  const body = {
    id: document.getElementById("node-id").value.trim(),
    name: document.getElementById("node-name").value.trim(),
    type: document.getElementById("node-type").value,
    x: +document.getElementById("node-x").value,
    y: +document.getElementById("node-y").value
  };
  try {
    if (editing) await api("/api/admin/nodes/" + editing, jsonOpts("PUT", body));
    else await api("/api/admin/nodes", jsonOpts("POST", body));
    toast("节点已保存"); resetNodeForm(); loadCampus();
  } catch (e) { toast(e.message, true); }
};
document.getElementById("node-reset").onclick = resetNodeForm;

/* ================= 边管理 ================= */
function fillEdgeNodeSelects() {
  for (const id of ["edge-from", "edge-to"]) {
    const sel = document.getElementById(id);
    sel.innerHTML = "";
    for (const [nid, n] of Object.entries(campus.nodes)) {
      const o = document.createElement("option");
      o.value = nid; o.textContent = `${n.name} (${nid})`;
      sel.appendChild(o);
    }
  }
}
function renderEdges() {
  const tb = document.querySelector("#edge-table tbody");
  tb.innerHTML = "";
  const nameOf = id => (campus.nodes[id] || {}).name || id;
  for (const e of campus.edges) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${e.id}</td><td>${nameOf(e.from)}</td><td>${nameOf(e.to)}</td>
      <td>${e.distance}m</td><td>${KIND_LABEL[e.kind] || e.kind}</td>
      <td>${(e.slope * 100).toFixed(1)}%</td><td>${SURFACE_LABEL[e.surface] || e.surface}</td><td></td>`;
    const td = tr.lastElementChild;
    const edit = document.createElement("button");
    edit.className = "btn btn-sm btn-edit"; edit.textContent = "编辑";
    edit.onclick = () => fillEdgeForm(e);
    const del = document.createElement("button");
    del.className = "btn btn-sm btn-del"; del.textContent = "删除";
    del.onclick = () => delEdge(e.id);
    td.append(edit, del);
    tb.appendChild(tr);
  }
}
function fillEdgeForm(e) {
  document.getElementById("edge-editing").value = e.id;
  document.getElementById("edge-id").value = e.id;
  document.getElementById("edge-id").disabled = true;
  document.getElementById("edge-from").value = e.from;
  document.getElementById("edge-to").value = e.to;
  document.getElementById("edge-distance").value = e.distance;
  document.getElementById("edge-kind").value = e.kind;
  document.getElementById("edge-slope").value = e.slope;
  document.getElementById("edge-surface").value = e.surface;
}
function resetEdgeForm() {
  document.getElementById("edge-form").reset();
  document.getElementById("edge-editing").value = "";
  document.getElementById("edge-id").disabled = false;
}
async function delEdge(eid) {
  if (!confirm(`确认删除通道 ${eid}?`)) return;
  try {
    await api("/api/admin/edges/" + eid, { method: "DELETE" });
    toast("通道已删除"); loadCampus();
  } catch (e) { toast(e.message, true); }
}
document.getElementById("edge-form").onsubmit = async ev => {
  ev.preventDefault();
  const editing = document.getElementById("edge-editing").value;
  const body = {
    id: document.getElementById("edge-id").value.trim(),
    from: document.getElementById("edge-from").value,
    to: document.getElementById("edge-to").value,
    distance: +document.getElementById("edge-distance").value,
    kind: document.getElementById("edge-kind").value,
    slope: +document.getElementById("edge-slope").value,
    surface: document.getElementById("edge-surface").value
  };
  try {
    if (editing) await api("/api/admin/edges/" + editing, jsonOpts("PUT", body));
    else await api("/api/admin/edges", jsonOpts("POST", body));
    toast("通道已保存"); resetEdgeForm(); loadCampus();
  } catch (e) { toast(e.message, true); }
};
document.getElementById("edge-reset").onclick = resetEdgeForm;

/* ================= 权重设置 ================= */
async function loadWeights() {
  weights = await api("/api/weights");
  renderWeights();
}
function numInput(path, val, step) {
  return `<input type="number" step="${step || "0.1"}" data-path="${path}" value="${val}">`;
}
function renderWeights() {
  const box = document.getElementById("weights-container");
  box.innerHTML = "";
  for (const [pname, p] of Object.entries(weights.profiles)) {
    const card = document.createElement("div");
    card.className = "weight-card";
    const tmRows = Object.entries(p.type_multiplier).map(([k, v]) =>
      `<div><label>${KIND_LABEL[k] || k} 倍率(留空=禁行)</label>
       <input type="number" step="0.05" min="0" data-path="profiles.${pname}.type_multiplier.${k}" value="${v === null ? "" : v}"></div>`
    ).join("");
    const slopeRows = p.slope_penalties.map(([lim, pen], i) => {
      const limTxt = lim === null ? "∞(以上)" : (lim * 100).toFixed(2) + "%";
      return `<tr><td>坡度 ≤ ${limTxt}</td>
        <td><input type="number" step="0.5" min="0" data-path="profiles.${pname}.slope_penalties.${i}.1" value="${pen}"></td></tr>`;
    }).join("");
    const smRows = Object.entries(p.surface_multiplier).map(([k, v]) =>
      `<div><label>${SURFACE_LABEL[k] || k}路面倍率</label>${numInput(`profiles.${pname}.surface_multiplier.${k}`, v)}</div>`
    ).join("");
    card.innerHTML = `
      <h3>${p.label} <small>(${pname})</small></h3>
      <p>${p.description || ""}</p>
      <div class="weight-grid">${tmRows}${smRows}
        <div><label>电梯固定成本(等效米)</label>${numInput(`profiles.${pname}.elevator_fixed_cost`, p.elevator_fixed_cost, 1)}</div>
        <div><label>坡度硬上限(小数,留空=不限)</label>
          <input type="number" step="0.01" min="0" max="0.5" data-path="profiles.${pname}.slope_hard_limit" value="${p.slope_hard_limit === null ? "" : p.slope_hard_limit}"></div>
        <div><label>移动速度(m/s)</label>${numInput(`profiles.${pname}.speed_mps`, p.speed_mps)}</div>
      </div>
      <table class="slope-table"><tbody>${slopeRows}</tbody></table>`;
    box.appendChild(card);
  }
}
function setPath(obj, path, value) {
  const keys = path.split(".");
  let cur = obj;
  for (let i = 0; i < keys.length - 1; i++) cur = cur[isNaN(+keys[i]) ? keys[i] : +keys[i]];
  const last = keys[keys.length - 1];
  cur[isNaN(+last) ? last : +last] = value;
}
document.getElementById("save-weights").onclick = async () => {
  const next = JSON.parse(JSON.stringify(weights));
  document.querySelectorAll("#weights-container input").forEach(inp => {
    const val = inp.value === "" ? null : parseFloat(inp.value);
    setPath(next, inp.dataset.path, val);
  });
  try {
    await api("/api/admin/weights", jsonOpts("PUT", next));
    weights = next;
    toast("权重已保存并即时生效");
  } catch (e) { toast(e.message, true); }
};
document.getElementById("reload-weights").onclick = loadWeights;

/* ================= 初始化 ================= */
loadCampus();
loadWeights();
