/* 管理端：登录鉴权 + 节点/边维护 + 权重配置 */
const A = {
  graph: null, token: localStorage.getItem("campus_admin_token") || null,
  editingEdge: null, editingNode: null,
};
let map;

const $ = (id) => document.getElementById(id);

async function boot() {
  if (A.token) {
    // 验证 token 是否仍有效：拉取公开图数据不验权，这里通过一次保存前校验逻辑隐式处理
    $("loginMask").hidden = true;
  }
  await reloadGraph();
  bindUI();
  const w = await Api.weights();
  $("weightsEditor").value = JSON.stringify(w.weights, null, 2);
}

async function reloadGraph() {
  const res = await Api.graph();
  A.graph = res.graph;
  if (!map) {
    map = new CampusMap($("map"), {
      showLabels: true,
      onNodeClick: (n) => fillNodeForm(n),
      onEdgeClick: (e) => fillEdgeForm(e),
    });
  }
  map.setGraph(A.graph);
  fillNodeSelects();
  renderTables();
}

// ------------------------------------------------------------- 登录
$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const res = await Api.post("/api/admin/login", {
    username: $("loginUser").value,
    password: $("loginPwd").value,
  });
  if (res.ok) {
    A.token = res.token;
    localStorage.setItem("campus_admin_token", res.token);
    $("loginMask").hidden = true;
    $("loginErr").textContent = "";
  } else {
    $("loginErr").textContent = res.error || "登录失败";
  }
});

// ---------------------------------------------------------------- tabs
function bindUI() {
  document.querySelectorAll(".tab").forEach((t) => {
    t.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
      t.classList.add("active");
      ["edge", "node", "weights"].forEach((name) => {
        $(`tab-${name}`).hidden = name !== t.dataset.tab;
      });
    });
  });

  $("edgeForm").addEventListener("submit", saveEdge);
  $("nodeForm").addEventListener("submit", saveNode);
  $("edgeDel").addEventListener("click", deleteEdge);
  $("nodeDel").addEventListener("click", deleteNode);
  $("edgeReset").addEventListener("click", () => fillEdgeForm(null));
  $("nodeReset").addEventListener("click", () => fillNodeForm(null));
  $("weightsSave").addEventListener("click", saveWeights);
  $("weightsReload").addEventListener("click", async () => {
    const w = await Api.weights();
    $("weightsEditor").value = JSON.stringify(w.weights, null, 2);
    toast("已重新载入");
  });
  $("resetGraph").addEventListener("click", async () => {
    if (!confirm("确定恢复为默认校园图？当前所有改动将丢失。")) return;
    const r = await Api.post("/api/admin/reset", {}, A.token);
    if (r.ok) { await reloadGraph(); toast("已恢复默认数据"); }
    else toast(r.error, true);
  });
}

// ----------------------------------------------------------- 节点维护
function fillNodeSelects() {
  const opts = A.graph.nodes.map((n) => `<option value="${n.id}">${n.name} (${n.id})</option>`).join("");
  $("e_a").innerHTML = opts;
  $("e_b").innerHTML = opts;
}

function fillNodeForm(n) {
  document.querySelector('.tab[data-tab="node"]').click();
  A.editingNode = n ? n.id : null;
  $("nodeFormTitle").textContent = n ? `编辑节点：${n.name}` : "新增地点";
  $("n_id").value = n ? n.id : "";
  $("n_name").value = n ? n.name : "";
  $("n_type").value = n ? n.type : "junction";
  $("n_building").value = n ? (n.building || "") : "";
  $("n_x").value = n ? n.x : "";
  $("n_y").value = n ? n.y : "";
  $("n_floor").value = n ? (n.floor || 0) : 0;
  $("n_id").disabled = !!n;
  $("nodeDel").style.visibility = n ? "visible" : "hidden";
}

async function saveNode(e) {
  e.preventDefault();
  const node = {
    id: $("n_id").value.trim(),
    name: $("n_name").value.trim(),
    type: $("n_type").value,
    building: $("n_building").value || undefined,
    x: parseFloat($("n_x").value),
    y: parseFloat($("n_y").value),
    floor: parseInt($("n_floor").value || "0", 10),
  };
  const r = await Api.post("/api/admin/node", { node }, A.token);
  if (r.ok) { toast("节点已保存"); await reloadGraph(); }
  else toast(r.error, true);
}

async function deleteNode() {
  if (!A.editingNode) return;
  if (!confirm("删除节点会同时删除与它相连的通道，确定？")) return;
  const r = await Api.del(`/api/admin/node?id=${encodeURIComponent(A.editingNode)}`, A.token);
  if (r.ok) { toast("节点已删除"); fillNodeForm(null); await reloadGraph(); }
  else toast(r.error, true);
}

// ------------------------------------------------------------ 边维护
function fillEdgeForm(ed) {
  document.querySelector('.tab[data-tab="edge"]').click();
  A.editingEdge = ed ? ed.id : null;
  $("edgeFormTitle").textContent = ed ? `编辑通道：${ed.id}` : "新增通道";
  $("e_id").value = ed ? ed.id : "";
  $("e_type").value = ed ? ed.type : "path";
  $("e_a").value = ed ? ed.a : "";
  $("e_b").value = ed ? ed.b : "";
  $("e_length").value = ed && ed.length != null ? ed.length : "";
  $("e_grade").value = ed && ed.grade != null ? ed.grade : "";
  $("e_width").value = ed && ed.width_m != null ? ed.width_m : "";
  $("e_surface").value = ed ? (ed.surface || "") : "";
  $("e_stair_count").value = ed && ed.stair_count != null ? ed.stair_count : "";
  $("e_floors").value = ed && ed.floors != null ? ed.floors : "";
  $("e_tactile").checked = ed ? !!ed.tactile : false;
  $("e_has_elev").checked = ed ? !!ed.has_elevator : false;
  $("e_blocked").checked = ed ? !!ed.blocked : false;
  $("e_heavy").checked = ed ? !!ed.heavy : false;
  $("e_id").disabled = !!ed;
  $("edgeDel").style.visibility = ed ? "visible" : "hidden";
}

function readEdgeForm() {
  const num = (v) => (v === "" ? undefined : parseFloat(v));
  const int = (v) => (v === "" ? undefined : parseInt(v, 10));
  return {
    id: $("e_id").value.trim(),
    a: $("e_a").value, b: $("e_b").value,
    type: $("e_type").value,
    length: num($("e_length").value),
    grade: num($("e_grade").value),
    width_m: num($("e_width").value),
    surface: $("e_surface").value || undefined,
    stair_count: int($("e_stair_count").value),
    floors: int($("e_floors").value),
    tactile: $("e_tactile").checked,
    has_elevator: $("e_has_elev").checked,
    blocked: $("e_blocked").checked,
    heavy: $("e_heavy").checked,
  };
}

async function saveEdge(e) {
  e.preventDefault();
  const edge = readEdgeForm();
  if (edge.a === edge.b) return toast("通道的两个端点不能相同", true);
  const r = await Api.post("/api/admin/edge", { edge }, A.token);
  if (r.ok) { toast("通道已保存"); await reloadGraph(); }
  else toast(r.error, true);
}

async function deleteEdge() {
  if (!A.editingEdge) return;
  if (!confirm("确定删除该通道？")) return;
  const r = await Api.del(`/api/admin/edge?id=${encodeURIComponent(A.editingEdge)}`, A.token);
  if (r.ok) { toast("通道已删除"); fillEdgeForm(null); await reloadGraph(); }
  else toast(r.error, true);
}

// ------------------------------------------------------------ 表格
function renderTables() {
  const nodeName = Object.fromEntries(A.graph.nodes.map((n) => [n.id, n.name]));
  $("edgeTable").innerHTML = `
    <tr><th>ID</th><th>类型</th><th>端点</th><th>属性</th></tr>
    ${A.graph.edges.map((e) => `<tr data-id="${e.id}" class="edge-row">
      <td>${e.id}</td>
      <td><span class="tag tag-${e.type}">${e.type}</span></td>
      <td>${nodeName[e.a] || e.a} → ${nodeName[e.b] || e.b}</td>
      <td>${[
        e.grade ? `坡度${(e.grade * 100).toFixed(0)}%` : "",
        e.stair_count ? `${e.stair_count}级` : "",
        e.tactile ? "盲道" : "",
        e.blocked ? "封闭" : "",
      ].filter(Boolean).join(" / ")}</td>
    </tr>`).join("")}`;
  document.querySelectorAll(".edge-row").forEach((tr) => {
    tr.addEventListener("click", () => {
      const e = A.graph.edges.find((x) => x.id === tr.dataset.id);
      fillEdgeForm(e);
    });
  });

  $("nodeTable").innerHTML = `
    <tr><th>ID</th><th>名称</th><th>类型</th><th>楼层</th><th>坐标</th></tr>
    ${A.graph.nodes.map((n) => `<tr data-id="${n.id}" class="node-row">
      <td>${n.id}</td><td>${n.name}</td><td>${n.type}</td>
      <td>${n.floor || 0}F</td><td>${n.x},${n.y}</td>
    </tr>`).join("")}`;
  document.querySelectorAll(".node-row").forEach((tr) => {
    tr.addEventListener("click", () => {
      const n = A.graph.nodes.find((x) => x.id === tr.dataset.id);
      fillNodeForm(n);
    });
  });
}

// ------------------------------------------------------------ 权重
async function saveWeights() {
  let parsed;
  try {
    parsed = JSON.parse($("weightsEditor").value);
  } catch (err) {
    return toast("JSON 格式有误：" + err.message, true);
  }
  const r = await Api.post("/api/admin/weights", { weights: parsed }, A.token);
  if (r.ok) toast("权重已保存，新路线将立即生效");
  else toast(r.error, true);
}

function toast(msg, isErr) {
  const t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2400);
}

boot();
