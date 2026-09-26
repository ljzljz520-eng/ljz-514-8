/* 共享 API 封装 */
const Api = {
  async get(path) {
    const res = await fetch(path);
    return res.json();
  },
  async post(path, body, token) {
    const res = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });
    return res.json();
  },
  async del(path, token) {
    const res = await fetch(path, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    return res.json();
  },
  route(start, goal, mode = "accessible") {
    return this.get(`/api/route?start=${encodeURIComponent(start)}&goal=${encodeURIComponent(goal)}&mode=${mode}`);
  },
  graph() { return this.get("/api/graph"); },
  pois() { return this.get("/api/pois"); },
  weights() { return this.get("/api/weights"); },
};
