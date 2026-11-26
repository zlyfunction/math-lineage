/**
 * Dual-mode API client for MathLineage:
 * - Automatically detects if FastAPI backend (`/api/stats`) is available.
 * - Falls back seamlessly to GitHub Pages Live Mode (`localEngine` + direct CORS verification).
 */

import { localEngine } from "./localEngine";

const BASE = "./api";
let _modePromise = null;
let _runtimeMode = "detecting"; // 'backend' | 'static'

export function getRuntimeMode() {
  return _runtimeMode;
}

async function detectMode() {
  if (!_modePromise) {
    _modePromise = (async () => {
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 1600);
        const res = await fetch("/api/stats", { signal: controller.signal });
        clearTimeout(timer);
        if (res.ok) {
          const ct = res.headers.get("content-type") || "";
          if (ct.includes("application/json")) {
            _runtimeMode = "backend";
            return "backend";
          }
        }
      } catch {
        // fall through to static mode
      }
      _runtimeMode = "static";
      return "static";
    })();
  }
  return _modePromise;
}

async function backendRequest(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      msg = data.detail || msg;
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
  return res.json();
}

export const api = {
  detectMode,

  async getStats() {
    if ((await detectMode()) === "backend") return backendRequest("/stats");
    return localEngine.getStats();
  },

  async searchScholars(params) {
    if ((await detectMode()) === "backend") {
      const qs = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
      });
      return backendRequest(`/scholars?${qs.toString()}`);
    }
    return localEngine.searchScholars(params);
  },

  async autocomplete(q) {
    if ((await detectMode()) === "backend") {
      return backendRequest(`/scholars/autocomplete?q=${encodeURIComponent(q)}&limit=8`);
    }
    return localEngine.autocomplete(q);
  },

  async getScholar(id) {
    if ((await detectMode()) === "backend") return backendRequest(`/scholars/${id}`);
    return localEngine.getScholar(id);
  },

  async getLineage(id, ancestorDepth = 6, descendantDepth = 2) {
    if ((await detectMode()) === "backend") {
      return backendRequest(`/scholars/${id}/lineage?ancestor_depth=${ancestorDepth}&descendant_depth=${descendantDepth}`);
    }
    return localEngine.getLineage(id, ancestorDepth, descendantDepth);
  },

  async findPath(fromId, toId) {
    if ((await detectMode()) === "backend") {
      return backendRequest(`/path?from_id=${fromId}&to_id=${toId}`);
    }
    return localEngine.findPath(fromId, toId);
  },

  async verifyDissertation(identifier, sourceHint = null) {
    if ((await detectMode()) === "backend") {
      return backendRequest("/verify-dissertation", {
        method: "POST",
        body: JSON.stringify({ identifier, source_hint: sourceHint }),
      });
    }
    return localEngine.verifyDissertation(identifier);
  },

  async searchLiveRepos(query, source = "all", limit = 8) {
    if ((await detectMode()) === "backend") {
      return backendRequest("/verify-dissertation/search", {
        method: "POST",
        body: JSON.stringify({ query, source, limit }),
      });
    }
    return localEngine.searchLiveRepos(query, source, limit);
  },

  async listSubmissions(status = "all") {
    if ((await detectMode()) === "backend") return backendRequest(`/submissions?status=${status}`);
    return localEngine.listSubmissions(status);
  },

  async createSubmission(payload) {
    if ((await detectMode()) === "backend") {
      return backendRequest("/submissions", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    return localEngine.createSubmission(payload);
  },

  async reviewSubmission(id, action, reviewNote = "") {
    if ((await detectMode()) === "backend") {
      return backendRequest(`/submissions/${id}/review`, {
        method: "POST",
        body: JSON.stringify({ action, review_note: reviewNote }),
      });
    }
    return localEngine.reviewSubmission(id, action, reviewNote);
  },

  async listHarvestRuns() {
    if ((await detectMode()) === "backend") return backendRequest("/harvest/runs");
    return localEngine.listHarvestRuns();
  },

  async triggerHarvest(source, query = "", limit = 25) {
    if ((await detectMode()) === "backend") {
      return backendRequest("/harvest", {
        method: "POST",
        body: JSON.stringify({ source, query, limit }),
      });
    }
    return localEngine.triggerHarvest(source, query, limit);
  },
};
