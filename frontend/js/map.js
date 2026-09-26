/* SVG 校园地图渲染：节点 / 边 / 路线高亮，支持选点模式与编辑模式 */
(function (global) {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const FLOOR_DY = 26; // 每层楼的虚拟纵向偏移

  // 通道类型 -> 底图样式
  const EDGE_STYLE = {
    path:     { color: "#9aa7b1", width: 5,  dash: "" },
    corridor: { color: "#b6c2cc", width: 4,  dash: "" },
    ramp:     { color: "#2e9e63", width: 6,  dash: "2 2" },
    slope:    { color: "#d98b32", width: 5,  dash: "10 4" },
    stairs:   { color: "#c0392b", width: 4,  dash: "1 5" },
    elevator: { color: "#2468d8", width: 3,  dash: "2 3" },
    door:     { color: "#8e7cc3", width: 4,  dash: "" },
  };

  const NODE_STYLE = {
    entrance: { fill: "#f1c40f", r: 6 },
    indoor:   { fill: "#7f8c9b", r: 4 },
    elevator: { fill: "#2468d8", r: 6 },
    stairs:   { fill: "#c0392b", r: 6 },
    room:     { fill: "#16a085", r: 7 },
    junction: { fill: "#5d6d7e", r: 3.5 },
  };

  function el(name, attrs = {}, text) {
    const node = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    if (text != null) node.textContent = text;
    return node;
  }

  function pos(n) {
    return { x: n.x, y: n.y + (n.floor || 0) * FLOOR_DY };
  }

  class CampusMap {
    constructor(svgEl, opts = {}) {
      this.svg = svgEl;
      this.opts = opts;
      this.graph = null;
      this.nodeMap = {};
      this.onNodeClick = opts.onNodeClick || null;
      this.route = null;
      this.comparison = null;
      this.selected = new Set(opts.selected || []);
    }

    setGraph(graph) {
      this.graph = graph;
      this.nodeMap = Object.fromEntries(graph.nodes.map((n) => [n.id, n]));
      this.render();
    }

    setRoute(route, comparison = null) {
      this.route = route;
      this.comparison = comparison;
      this.render();
    }

    clearRoute() {
      this.route = null;
      this.comparison = null;
      this.render();
    }

    setSelected(ids) {
      this.selected = new Set(ids);
      this.render();
    }

    render() {
      if (!this.graph) return;
      this.svg.innerHTML = "";
      this._defs();

      // 建筑底块
      const buildings = this._buildingFootprints();
      buildings.forEach((b) => this.svg.appendChild(b));

      const gEdges = el("g", { class: "edges" });
      const gNodes = el("g", { class: "nodes" });
      this.svg.appendChild(gEdges);

      const edgeMap = Object.fromEntries(this.graph.edges.map((e) => [e.id, e]));
      const inRoute = new Set(this.route ? this.route.edge_ids : []);
      const inCmp = new Set(this.comparison ? this.comparison.edge_ids : []);

      this.graph.edges.forEach((e) => {
        const a = pos(this.nodeMap[e.a]);
        const b = pos(this.nodeMap[e.b]);
        const st = EDGE_STYLE[e.type] || EDGE_STYLE.path;
        const line = el("line", {
          x1: a.x, y1: a.y, x2: b.x, y2: b.y,
          stroke: st.color, "stroke-width": st.width,
          "stroke-linecap": "round",
          "stroke-dasharray": st.dash,
          class: "edge-line",
          "data-id": e.id,
        });
        if (e.tactile) line.setAttribute("stroke-dasharray", "8 3 1 3");
        const title = this._edgeTitle(e);
        line.appendChild(el("title", {}, title));
        if (this.opts.onEdgeClick) {
          line.style.cursor = "pointer";
          line.addEventListener("click", (ev) => {
            ev.stopPropagation();
            this.opts.onEdgeClick(e);
          });
        }
        gEdges.appendChild(line);
      });

      // 普通模式对比路线（蓝色虚线，在下层）
      (this.comparison ? this.comparison.edge_ids : []).forEach((eid) => {
        const e = edgeMap[eid];
        if (!e || inRoute.has(eid)) return;
        const a = pos(this.nodeMap[e.a]);
        const b = pos(this.nodeMap[e.b]);
        gEdges.appendChild(el("line", {
          x1: a.x, y1: a.y, x2: b.x, y2: b.y,
          stroke: "#2f6fed", "stroke-width": 6, "stroke-linecap": "round",
          "stroke-dasharray": "7 5", opacity: 0.65,
        }));
      });

      // 无障碍路线（绿色高亮，在上层）
      (this.route ? this.route.edge_ids : []).forEach((eid) => {
        const e = edgeMap[eid];
        if (!e) return;
        const a = pos(this.nodeMap[e.a]);
        const b = pos(this.nodeMap[e.b]);
        gEdges.appendChild(el("line", {
          x1: a.x, y1: a.y, x2: b.x, y2: b.y,
          stroke: "#1f9d55", "stroke-width": 9, "stroke-linecap": "round",
          opacity: 0.9,
        }));
      });

      // 节点
      this.graph.nodes.forEach((n) => {
        const p = pos(n);
        const st = NODE_STYLE[n.type] || NODE_STYLE.junction;
        const g = el("g", { class: "node-g", transform: `translate(${p.x},${p.y})` });
        const isRoom = n.type === "room";
        const shape = el(isRoom ? "rect" : "circle", isRoom
          ? { x: -7, y: -7, width: 14, height: 14, rx: 3, fill: st.fill, stroke: "#fff", "stroke-width": 1.5, class: "node-shape" }
          : { r: st.r, fill: st.fill, stroke: "#fff", "stroke-width": 1.5, class: "node-shape" });
        g.appendChild(shape);

        if (this.selected.has(n.id)) {
          g.appendChild(el("circle", { r: st.r + 5, fill: "none", stroke: "#e67e22", "stroke-width": 2.5 }));
        }
        if (n.floor && (n.type === "room")) {
          g.appendChild(el("text", { x: 0, y: 3, "font-size": 8, fill: "#fff", "text-anchor": "middle" }, `${n.floor}F`));
        }
        const label = n.name + (n.floor && n.type !== "room" ? ` ${n.floor}F` : "");
        g.appendChild(el("title", {}, label));
        if (this.opts.showLabels && ["room", "entrance", "junction"].includes(n.type)) {
          g.appendChild(el("text", {
            x: 9, y: 4, "font-size": 11, fill: "#33475b",
            "paint-order": "stroke", stroke: "#fff", "stroke-width": 3,
          }, label));
        }
        g.style.cursor = "pointer";
        g.addEventListener("click", (ev) => {
          ev.stopPropagation();
          if (this.onNodeClick) this.onNodeClick(n, g);
        });
        gNodes.appendChild(g);
      });

      this.svg.appendChild(gNodes);
    }

    _defs() {
      const defs = el("defs");
      const pattern = el("pattern", { id: "bld", width: 14, height: 14, patternUnits: "userSpaceOnUse" });
      pattern.appendChild(el("rect", { width: 14, height: 14, fill: "#eef2f6" }));
      defs.appendChild(pattern);
      this.svg.appendChild(defs);
    }

    _buildingFootprints() {
      // 按 building 字段把同楼节点围一个淡色底块（取外接矩形 + 边距）
      const groups = {};
      this.graph.nodes.forEach((n) => {
        if (!n.building) return;
        (groups[n.building] = groups[n.building] || []).push(pos(n));
      });
      const labels = { dorm: "1号宿舍楼", teach: "教学楼", canteen: "食堂", library: "图书馆" };
      return Object.entries(groups).map(([bid, ps]) => {
        const minX = Math.min(...ps.map((p) => p.x)) - 24;
        const maxX = Math.max(...ps.map((p) => p.x)) + 24;
        const minY = Math.min(...ps.map((p) => p.y)) - 30;
        const maxY = Math.max(...ps.map((p) => p.y)) + 18;
        const g = el("g");
        g.appendChild(el("rect", {
          x: minX, y: minY, width: maxX - minX, height: maxY - minY,
          rx: 12, fill: "url(#bld)", stroke: "#c6d0da", "stroke-width": 1.5,
          "stroke-dasharray": "6 4",
        }));
        g.appendChild(el("text", {
          x: minX + 10, y: minY + 16, "font-size": 13, "font-weight": "bold",
          fill: "#566573",
        }, labels[bid] || bid));
        return g;
      });
    }

    _edgeTitle(e) {
      const parts = [this._typeLabel(e.type)];
      if (e.grade) parts.push(`坡度 ${(e.grade * 100).toFixed(1)}%`);
      if (e.stair_count) parts.push(`${e.stair_count} 级台阶`);
      if (e.floors) parts.push(`${e.floors} 层`);
      if (e.width_m) parts.push(`净宽 ${e.width_m}m`);
      if (e.tactile) parts.push("有盲道");
      if (e.surface) parts.push({ asphalt: "沥青", concrete: "水泥", brick: "砖石", gravel: "碎石", cobble: "鹅卵石" }[e.surface]);
      return parts.join(" · ");
    }

    _typeLabel(t) {
      return { path: "平缓通道", corridor: "室内通道", ramp: "无障碍坡道", slope: "坡路", stairs: "台阶", elevator: "电梯", door: "出入口门" }[t] || t;
    }
  }

  global.CampusMap = CampusMap;
  global.EDGE_STYLE = EDGE_STYLE;
})(window);
