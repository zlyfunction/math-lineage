/**
 * Client-side Genealogy & Direct-CORS Dissertation Verification Engine.
 * Powers MathLineage seamlessly on GitHub Pages (zero backend required!)
 * while preserving full search, interactive lineage graphs, BFS shortest paths,
 * live CORS verification against DataCite / HAL / theses.fr, and local review queue.
 */

const LS_SUBMISSIONS_KEY = "mathlineage_local_submissions_v1";
const LS_ADDED_KEY = "mathlineage_local_added_v1";
export const GITHUB_REPO_URL = "https://github.com/zlyfunction/math-lineage";

let _storePromise = null;
let _store = null;

function stripAccents(str) {
  return (str || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
}

function cleanPersonName(raw) {
  if (!raw) return "";
  let s = String(raw).trim().replace(/[\s.;:]+$/, "");
  s = s.replace(/,?\s*\b\d{4}\s*-\s*(\d{4})?\b/g, "");
  s = s.replace(/\([^)]*\)/g, "");
  s = s.replace(/\s+/g, " ").replace(/^[\s,.;:]+|[\s,.;:]+$/g, "");
  if (s.includes(",")) {
    const parts = s.split(",").map((p) => p.trim()).filter(Boolean);
    if (parts.length === 2) s = `${parts[1]} ${parts[0]}`;
  }
  return s.replace(/^(prof\.?|professor|dr\.?)\s+/i, "").trim();
}

function normalizeKey(name) {
  return stripAccents(cleanPersonName(name))
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function readLS(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeLS(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // ignore quota errors
  }
}

function buildIndices(bundle) {
  const scholarById = new Map();
  const dissByScholar = new Map();
  const dissById = new Map();
  const advToStu = new Map();
  const stuToAdv = new Map();

  for (const s of bundle.scholars) {
    scholarById.set(s.id, s);
  }
  for (const d of bundle.dissertations) {
    dissById.set(d.id, d);
    if (!dissByScholar.has(d.scholar_id)) dissByScholar.set(d.scholar_id, []);
    dissByScholar.get(d.scholar_id).push(d);
  }
  for (const e of bundle.edges) {
    if (!advToStu.has(e.advisor_id)) advToStu.set(e.advisor_id, []);
    advToStu.get(e.advisor_id).push(e);
    if (!stuToAdv.has(e.student_id)) stuToAdv.set(e.student_id, []);
    stuToAdv.get(e.student_id).push(e);
  }

  // Precompute direct students & total descendants
  const descCounts = new Map();
  for (const s of bundle.scholars) {
    const direct = advToStu.get(s.id) || [];
    if (direct.length === 0) {
      descCounts.set(s.id, [0, 0]);
      continue;
    }
    const visited = new Set([s.id]);
    const q = [];
    for (const e of direct) {
      if (!visited.has(e.student_id)) {
        visited.add(e.student_id);
        q.push(e.student_id);
      }
    }
    let head = 0;
    while (head < q.length) {
      const cur = q[head++];
      for (const e of advToStu.get(cur) || []) {
        if (!visited.has(e.student_id)) {
          visited.add(e.student_id);
          q.push(e.student_id);
        }
      }
    }
    descCounts.set(s.id, [direct.length, visited.size - 1]);
  }

  // Build normalized search haystack per scholar
  const searchRows = bundle.scholars.map((s) => {
    const dList = dissByScholar.get(s.id) || [];
    const primaryD = dList[0] || null;
    const advEdges = stuToAdv.get(s.id) || [];
    const advisors = advEdges
      .map((e) => scholarById.get(e.advisor_id))
      .filter(Boolean)
      .map((a) => ({ id: a.id, name: a.name }));
    const [directStudents] = descCounts.get(s.id) || [0, 0];
    const hay = stripAccents(
      `${s.name} ${s.name_zh || ""} ${s.university || ""} ${s.country || ""} ${s.thesis_title || ""} ${s.thesis_title_en || ""} ${s.mgp_id || ""} ${advisors.map((a) => a.name).join(" ")}`
    ).toLowerCase();

    return {
      ...s,
      direct_students: directStudents,
      advisor_count: advisors.length,
      advisors,
      source_repo: primaryD?.source_repo || null,
      dissertation_url: primaryD?.landing_url || null,
      pdf_url: primaryD?.pdf_url || null,
      doi: primaryD?.doi || null,
      _hay: hay,
      _nameLow: stripAccents(`${s.name} ${s.name_zh || ""}`).toLowerCase(),
    };
  });

  return {
    bundle,
    scholarById,
    dissByScholar,
    dissById,
    advToStu,
    stuToAdv,
    descCounts,
    searchRows,
  };
}

function mergeLocalAdditions(baseBundle) {
  const localAdded = readLS(LS_ADDED_KEY, { scholars: [], dissertations: [], edges: [] });
  return {
    ...baseBundle,
    scholars: [...baseBundle.scholars, ...(localAdded.scholars || [])],
    dissertations: [...baseBundle.dissertations, ...(localAdded.dissertations || [])],
    edges: [...baseBundle.edges, ...(localAdded.edges || [])],
  };
}

export async function ensureLocalStore(forceReload = false) {
  if (_store && !forceReload) return _store;
  if (!_storePromise || forceReload) {
    _storePromise = fetch("./data/genealogy-bundle.json")
      .then((r) => {
        if (!r.ok) throw new Error(`Failed to load genealogy bundle (HTTP ${r.status})`);
        return r.json();
      })
      .then((raw) => {
        const merged = mergeLocalAdditions(raw);
        _store = buildIndices(merged);
        return _store;
      });
  }
  return _storePromise;
}

function findMatchingScholar(store, rawName) {
  const norm = normalizeKey(rawName);
  if (!norm) return null;
  for (const s of store.bundle.scholars) {
    if (s.normalized_name === norm) return s;
  }
  const toks = norm.split(" ");
  if (toks.length === 2) {
    for (const s of store.bundle.scholars) {
      const st = (s.normalized_name || "").split(" ");
      if (st.length === 3 && st[0] === toks[0] && st[1].length === 1 && st[2] === toks[1]) {
        return s;
      }
    }
  }
  return null;
}

export const localEngine = {
  async getStats() {
    const st = await ensureLocalStore();
    const scholars = st.bundle.scholars;
    const diss = st.bundle.dissertations;
    const edges = st.bundle.edges;
    const subs = readLS(LS_SUBMISSIONS_KEY, []);

    const repoMap = new Map();
    const yearMap = new Map();
    for (const d of diss) {
      repoMap.set(d.source_repo, (repoMap.get(d.source_repo) || 0) + 1);
      if (d.year && d.year >= 2015) {
        yearMap.set(d.year, (yearMap.get(d.year) || 0) + 1);
      }
    }

    const featuredQids = new Set([
      "Q6722", "Q7604", "Q41585", "Q7099", "Q81082", "Q122992", "Q221265", "Q102116446",
    ]);
    const featured = st.searchRows
      .filter((s) => featuredQids.has(s.wikidata_id) || s.name === "Leyi Zhu")
      .sort((a, b) => (a.name === "Leyi Zhu" ? -1 : b.name === "Leyi Zhu" ? 1 : b.direct_students - a.direct_students))
      .slice(0, 9);

    return {
      total_scholars: scholars.length,
      verified_scholars: scholars.filter((s) => s.verification_status === "verified_dissertation").length,
      historical_scholars: scholars.filter((s) => s.verification_status === "historical_wikidata").length,
      total_dissertations: diss.length,
      total_edges: edges.length,
      verified_edges: edges.filter((e) => e.source_type === "dissertation_verified").length,
      pending_submissions: subs.filter((s) => s.status === "pending").length,
      repo_breakdown: Array.from(repoMap.entries())
        .map(([source_repo, count]) => ({ source_repo, count }))
        .sort((a, b) => b.count - a.count),
      recent_years: Array.from(yearMap.entries())
        .map(([year, count]) => ({ year, count }))
        .sort((a, b) => a.year - b.year),
      featured_scholars: featured,
    };
  },

  async searchScholars(params = {}) {
    const st = await ensureLocalStore();
    const q = (params.q || "").trim();
    const status = params.status || "all";
    const repo = params.repo || "all";
    const sort = params.sort || "relevance";
    const yearFrom = params.year_from ? Number(params.year_from) : null;
    const yearTo = params.year_to ? Number(params.year_to) : null;
    const page = Math.max(1, Number(params.page || 1));
    const pageSize = Math.max(1, Number(params.page_size || 20));

    const tokens = q ? stripAccents(q).toLowerCase().split(/\s+/).filter(Boolean) : [];
    const qLow = stripAccents(q).toLowerCase();

    let rows = st.searchRows.filter((r) => {
      if (status !== "all" && r.verification_status !== status) return false;
      if (repo !== "all" && r.source_repo !== repo) return false;
      if (yearFrom !== null && (!r.year || r.year < yearFrom)) return false;
      if (yearTo !== null && (!r.year || r.year > yearTo)) return false;
      if (tokens.length > 0 && !tokens.every((t) => r._hay.includes(t))) return false;
      return true;
    });

    const rankStatus = (v) => (v === "verified_dissertation" ? 0 : v === "historical_wikidata" ? 1 : 2);
    rows = rows.slice().sort((a, b) => {
      if (sort === "year_desc") return (b.year || -1) - (a.year || -1) || a.name.localeCompare(b.name);
      if (sort === "year_asc") return (a.year || 99999) - (b.year || 99999) || a.name.localeCompare(b.name);
      if (sort === "students_desc") return b.direct_students - a.direct_students || (b.year || 0) - (a.year || 0);
      if (sort === "name_asc") return a.name.localeCompare(b.name);

      // Relevance sort: prioritize name match when query present
      if (qLow) {
        const aNameHit = a._nameLow.includes(qLow) ? 0 : tokens.every((t) => a._nameLow.includes(t)) ? 1 : 2;
        const bNameHit = b._nameLow.includes(qLow) ? 0 : tokens.every((t) => b._nameLow.includes(t)) ? 1 : 2;
        if (aNameHit !== bNameHit) return aNameHit - bNameHit;
      }
      const rs = rankStatus(a.verification_status) - rankStatus(b.verification_status);
      if (rs !== 0) return rs;
      return (b.year || 0) - (a.year || 0) || a.id - b.id;
    });

    const total = rows.length;
    const start = (page - 1) * pageSize;
    return {
      total,
      page,
      page_size: pageSize,
      items: rows.slice(start, start + pageSize),
    };
  },

  async autocomplete(q) {
    const res = await this.searchScholars({ q, page: 1, page_size: 8, sort: "relevance" });
    return res.items;
  },

  async getScholar(id) {
    const st = await ensureLocalStore();
    const sid = Number(id);
    const scholar = st.scholarById.get(sid);
    if (!scholar) throw new Error("Scholar not found");

    const dissertations = st.dissByScholar.get(sid) || [];
    const advisors = (st.stuToAdv.get(sid) || [])
      .map((e) => {
        const a = st.scholarById.get(e.advisor_id);
        if (!a) return null;
        return { ...a, source_type: e.source_type, dissertation_id: e.dissertation_id };
      })
      .filter(Boolean);

    const students = (st.advToStu.get(sid) || [])
      .map((e) => {
        const s = st.scholarById.get(e.student_id);
        if (!s) return null;
        const [dCnt, totDesc] = st.descCounts.get(s.id) || [0, 0];
        const firstD = (st.dissByScholar.get(s.id) || [])[0];
        return {
          ...s,
          source_type: e.source_type,
          direct_students: dCnt,
          total_descendants: totDesc,
          dissertation_url: firstD?.landing_url || null,
          source_repo: firstD?.source_repo || null,
        };
      })
      .filter(Boolean)
      .sort((a, b) => (b.year || 0) - (a.year || 0) || a.name.localeCompare(b.name));

    const [direct_students_count, total_descendants_count] = st.descCounts.get(sid) || [0, 0];
    return {
      scholar,
      dissertations,
      advisors,
      students,
      direct_students_count,
      total_descendants_count,
    };
  },

  async getLineage(id, ancestorDepth = 6, descendantDepth = 2) {
    const st = await ensureLocalStore();
    const focusId = Number(id);
    if (!st.scholarById.has(focusId)) throw new Error("Scholar not found");

    const maxNodes = 140;
    const levels = new Map([[focusId, 0]]);
    const edgeKeys = new Set();
    const edges = [];

    // Upward BFS
    const qUp = [[focusId, 0]];
    let hUp = 0;
    while (hUp < qUp.length && levels.size < maxNodes) {
      const [cur, lvl] = qUp[hUp++];
      if (Math.abs(lvl) >= ancestorDepth) continue;
      for (const e of st.stuToAdv.get(cur) || []) {
        const key = `${e.advisor_id}->${cur}`;
        if (!edgeKeys.has(key)) {
          edgeKeys.add(key);
          edges.push({ source: e.advisor_id, target: cur, source_type: e.source_type, dissertation_id: e.dissertation_id });
        }
        if (!levels.has(e.advisor_id) && levels.size < maxNodes) {
          levels.set(e.advisor_id, lvl - 1);
          qUp.push([e.advisor_id, lvl - 1]);
        }
      }
    }

    // Downward BFS
    const qDown = [[focusId, 0]];
    let hDown = 0;
    while (hDown < qDown.length && levels.size < maxNodes) {
      const [cur, lvl] = qDown[hDown++];
      if (lvl >= descendantDepth) continue;
      for (const e of (st.advToStu.get(cur) || []).slice(0, 35)) {
        if (levels.size >= maxNodes && !levels.has(e.student_id)) continue;
        const key = `${cur}->${e.student_id}`;
        if (!edgeKeys.has(key)) {
          edgeKeys.add(key);
          edges.push({ source: cur, target: e.student_id, source_type: e.source_type, dissertation_id: e.dissertation_id });
        }
        if (!levels.has(e.student_id)) {
          levels.set(e.student_id, lvl + 1);
          qDown.push([e.student_id, lvl + 1]);
        }
      }
    }

    const nodes = [];
    for (const [nid, level] of levels.entries()) {
      const s = st.scholarById.get(nid);
      if (!s) continue;
      nodes.push({
        id: s.id,
        name: s.name,
        name_zh: s.name_zh,
        university: s.university,
        country: s.country,
        year: s.year,
        degree: s.degree,
        thesis_title: s.thesis_title,
        verification_status: s.verification_status,
        mgp_id: s.mgp_id,
        has_dissertation_proof: (st.dissByScholar.get(s.id) || []).length > 0,
        level,
        is_focus: s.id === focusId,
        student_count: (st.advToStu.get(s.id) || []).length,
        advisor_count: (st.stuToAdv.get(s.id) || []).length,
      });
    }

    return {
      focus_id: focusId,
      nodes,
      edges: edges.filter((e) => levels.has(e.source) && levels.has(e.target)),
    };
  },

  async findPath(fromId, toId) {
    const st = await ensureLocalStore();
    const f = Number(fromId);
    const t = Number(toId);
    if (f === t) {
      const s = st.scholarById.get(f);
      return { found: Boolean(s), distance: 0, nodes: s ? [s] : [], steps: [] };
    }

    const adj = new Map();
    for (const e of st.bundle.edges) {
      if (!adj.has(e.advisor_id)) adj.set(e.advisor_id, []);
      if (!adj.has(e.student_id)) adj.set(e.student_id, []);
      adj.get(e.advisor_id).push({ nxt: e.student_id, relation: "advised", source_type: e.source_type, dissertation_id: e.dissertation_id });
      adj.get(e.student_id).push({ nxt: e.advisor_id, relation: "advised_by", source_type: e.source_type, dissertation_id: e.dissertation_id });
    }

    const visited = new Set([f]);
    const parent = new Map();
    const q = [f];
    let head = 0;
    let found = false;

    while (head < q.length) {
      const cur = q[head++];
      if (cur === t) {
        found = true;
        break;
      }
      for (const step of adj.get(cur) || []) {
        if (!visited.has(step.nxt)) {
          visited.add(step.nxt);
          parent.set(step.nxt, { prev: cur, ...step });
          if (step.nxt === t) {
            found = true;
            head = q.length;
            break;
          }
          q.push(step.nxt);
        }
      }
    }

    if (!found) return { found: false, distance: null, nodes: [], steps: [] };

    const pathIds = [];
    const stepsRev = [];
    let cur = t;
    while (cur !== f) {
      pathIds.push(cur);
      const p = parent.get(cur);
      const diss = p.dissertation_id ? st.dissById.get(p.dissertation_id) || null : null;
      stepsRev.push({
        from_id: p.prev,
        to_id: cur,
        relation: p.relation,
        source_type: p.source_type,
        dissertation_id: p.dissertation_id,
        dissertation: diss,
      });
      cur = p.prev;
    }
    pathIds.push(f);
    pathIds.reverse();

    return {
      found: true,
      distance: stepsRev.length,
      nodes: pathIds.map((pid) => st.scholarById.get(pid)).filter(Boolean),
      steps: stepsRev.reverse(),
    };
  },

  /** Direct browser CORS verification against DataCite, HAL/TEL, and theses.fr! */
  async verifyDissertation(identifier) {
    const st = await ensureLocalStore();
    const raw = (identifier || "").trim();
    let cand = null;

    if (/10\.\d{4,9}\//.test(raw)) {
      const doi = raw.match(/(10\.\d{4,9}\/[^\s]+)/)[1].replace(/[.,;)]$/, "");
      const r = await fetch(`https://api.datacite.org/dois/${encodeURIComponent(doi)}`);
      if (r.ok) {
        const { data } = await r.json();
        const a = data?.attributes || {};
        const creators = a.creators || [];
        const supervisors = (a.contributors || [])
          .filter((c) => c.contributorType === "Supervisor")
          .map((c) => cleanPersonName(c.name))
          .filter(Boolean);
        if (creators.length && a.titles?.length) {
          cand = {
            scholar_name: cleanPersonName(creators[0].name || `${creators[0].givenName || ""} ${creators[0].familyName || ""}`),
            advisors: Array.from(new Set(supervisors)),
            university: a.publisher || "",
            country: "",
            degree: "Ph.D.",
            year: a.publicationYear ? Number(a.publicationYear) : null,
            thesis_title: a.titles[0].title || "",
            thesis_title_en: "",
            source_repo: "DataCite",
            source_record_id: doi,
            doi,
            landing_url: a.url || `https://doi.org/${doi}`,
            pdf_url: "",
            raw_metadata: { doi, publisher: a.publisher, publicationYear: a.publicationYear, contributors: a.contributors },
          };
        }
      }
    } else if (/\b(tel|hal)-\d+/i.test(raw) || raw.includes("hal.science")) {
      let hid = raw.replace(/\/$/, "").split("/").pop().replace(/v\d+$/, "");
      const r = await fetch(
        `https://api.archives-ouvertes.fr/search/?q=${encodeURIComponent(`halId_s:"${hid}"`)}&fl=halId_s,title_s,en_title_s,authFullName_s,director_s,producedDateY_i,authorityInstitution_s,uri_s,fileMain_s,doiId_s&rows=1&wt=json`
      );
      if (r.ok) {
        const d = (await r.json())?.response?.docs?.[0];
        if (d && d.authFullName_s?.length && d.title_s?.length) {
          cand = {
            scholar_name: cleanPersonName(d.authFullName_s[0]),
            advisors: (d.director_s || []).map(cleanPersonName).filter(Boolean),
            university: d.authorityInstitution_s?.[0] || "",
            country: "France",
            degree: "Ph.D.",
            year: d.producedDateY_i || null,
            thesis_title: d.title_s[0],
            thesis_title_en: d.en_title_s?.[0] || "",
            source_repo: "HAL/TEL",
            source_record_id: d.halId_s,
            doi: d.doiId_s || "",
            landing_url: d.uri_s || `https://theses.hal.science/${d.halId_s}`,
            pdf_url: d.fileMain_s || "",
            raw_metadata: d,
          };
        }
      }
    } else if (raw.includes("theses.fr") || /^(s\d{5,}|\d{4}[A-Z]{2,}\w+)$/.test(raw)) {
      const tid = raw.includes("theses.fr/") ? raw.split("theses.fr/")[1].split(/[/?]/)[0] : raw;
      const r = await fetch(`https://theses.fr/api/v1/theses/recherche/?q=${encodeURIComponent(`id:"${tid}"`)}&nombre=1`);
      if (r.ok) {
        const rec = (await r.json())?.theses?.[0];
        if (rec && rec.auteurs?.length && rec.titrePrincipal) {
          const yrMatch = String(rec.dateSoutenance || rec.datePremiereInscriptionDoctorat || "").match(/\b(19\d{2}|20\d{2})\b/);
          cand = {
            scholar_name: cleanPersonName(`${rec.auteurs[0].prenom || ""} ${rec.auteurs[0].nom || ""}`),
            advisors: (rec.directeurs || []).map((d) => cleanPersonName(`${d.prenom || ""} ${d.nom || ""}`)).filter(Boolean),
            university: rec.etabSoutenanceN || "",
            country: "France",
            degree: "Ph.D.",
            year: yrMatch ? Number(yrMatch[1]) : null,
            thesis_title: rec.titrePrincipal,
            thesis_title_en: rec.titreEN || "",
            source_repo: "theses.fr",
            source_record_id: tid,
            doi: "",
            landing_url: `https://theses.fr/${tid}`,
            pdf_url: rec.accessible === "oui" ? `https://theses.fr/${tid}/document` : "",
            raw_metadata: rec,
          };
        }
      }
    } else {
      throw new Error("纯静态站点模式支持浏览器直连核验 DataCite DOI、HAL/TEL 编号与 theses.fr 编号；MIT Handle 与 PDF 扉页解析请运行本地/后端 FastAPI 模式，或通过 GitHub Issue 触发自动核验。");
    }

    if (!cand) {
      throw new Error("未能从官方论文库检索到该编号，请检查 DOI / HAL ID / theses.fr 编号是否正确。");
    }

    return _attachDbMatches(st, cand);
  },

  async searchLiveRepos(query, source = "all", limit = 8) {
    const st = await ensureLocalStore();
    const q = query.trim();
    const out = [];
    const srcs = source === "all" ? ["hal", "theses_fr", "datacite"] : [source];

    for (const s of srcs) {
      try {
        if (s === "hal") {
          const r = await fetch(
            `https://api.archives-ouvertes.fr/search/?q=${encodeURIComponent(`(docType_s:THESE AND domain_s:0.math AND director_s:*) AND (${q})`)}&fl=halId_s,title_s,en_title_s,authFullName_s,director_s,producedDateY_i,authorityInstitution_s,uri_s,fileMain_s,doiId_s&rows=4&sort=producedDateY_i+desc&wt=json`
          );
          if (r.ok) {
            for (const d of (await r.json())?.response?.docs || []) {
              if (!d.authFullName_s?.length || !d.director_s?.length || !d.title_s?.length) continue;
              out.push(_attachDbMatches(st, {
                scholar_name: cleanPersonName(d.authFullName_s[0]),
                advisors: d.director_s.map(cleanPersonName).filter(Boolean),
                university: d.authorityInstitution_s?.[0] || "",
                country: "France",
                degree: "Ph.D.",
                year: d.producedDateY_i || null,
                thesis_title: d.title_s[0],
                thesis_title_en: d.en_title_s?.[0] || "",
                source_repo: "HAL/TEL",
                source_record_id: d.halId_s,
                doi: d.doiId_s || "",
                landing_url: d.uri_s || `https://theses.hal.science/${d.halId_s}`,
                pdf_url: d.fileMain_s || "",
                raw_metadata: d,
              }));
            }
          }
        } else if (s === "theses_fr") {
          const r = await fetch(
            `https://theses.fr/api/v1/theses/recherche/?q=${encodeURIComponent(`(discipline:"Mathématiques" AND status:soutenue) AND (${q})`)}&nombre=4&tri=dateDesc`
          );
          if (r.ok) {
            for (const rec of (await r.json())?.theses || []) {
              if (!rec.auteurs?.length || !rec.directeurs?.length || !rec.titrePrincipal) continue;
              const yrMatch = String(rec.dateSoutenance || "").match(/\b(19\d{2}|20\d{2})\b/);
              out.push(_attachDbMatches(st, {
                scholar_name: cleanPersonName(`${rec.auteurs[0].prenom || ""} ${rec.auteurs[0].nom || ""}`),
                advisors: rec.directeurs.map((d) => cleanPersonName(`${d.prenom || ""} ${d.nom || ""}`)).filter(Boolean),
                university: rec.etabSoutenanceN || "",
                country: "France",
                degree: "Ph.D.",
                year: yrMatch ? Number(yrMatch[1]) : null,
                thesis_title: rec.titrePrincipal,
                thesis_title_en: rec.titreEN || "",
                source_repo: "theses.fr",
                source_record_id: rec.id,
                doi: "",
                landing_url: `https://theses.fr/${rec.id}`,
                pdf_url: rec.accessible === "oui" ? `https://theses.fr/${rec.id}/document` : "",
                raw_metadata: rec,
              }));
            }
          }
        } else if (s === "datacite") {
          const r = await fetch(
            `https://api.datacite.org/dois?resource-type-id=dissertation&query=${encodeURIComponent(`(${q}) AND contributors.contributorType:Supervisor`)}&page[size]=4&sort=-published`
          );
          if (r.ok) {
            for (const rec of (await r.json())?.data || []) {
              const a = rec.attributes || {};
              const sups = (a.contributors || []).filter((c) => c.contributorType === "Supervisor").map((c) => cleanPersonName(c.name)).filter(Boolean);
              if (!a.creators?.length || !sups.length || !a.titles?.length) continue;
              out.push(_attachDbMatches(st, {
                scholar_name: cleanPersonName(a.creators[0].name || ""),
                advisors: Array.from(new Set(sups)),
                university: a.publisher || "",
                country: "",
                degree: "Ph.D.",
                year: a.publicationYear ? Number(a.publicationYear) : null,
                thesis_title: a.titles[0].title || "",
                thesis_title_en: "",
                source_repo: "DataCite",
                source_record_id: a.doi,
                doi: a.doi,
                landing_url: a.url || `https://doi.org/${a.doi}`,
                pdf_url: "",
                raw_metadata: { doi: a.doi, publisher: a.publisher, contributors: a.contributors },
              }));
            }
          }
        }
      } catch {
        // continue to other sources
      }
    }
    return { query, source, count: out.length, items: out.slice(0, limit) };
  },

  async listSubmissions(status = "all") {
    const subs = readLS(LS_SUBMISSIONS_KEY, []);
    return status === "all" ? subs : subs.filter((s) => s.status === status);
  },

  async createSubmission(payload) {
    const subs = readLS(LS_SUBMISSIONS_KEY, []);
    const nextId = subs.reduce((m, s) => Math.max(m, s.id), 0) + 1;
    const item = {
      id: nextId,
      status: "pending",
      ...payload,
      created_at: new Date().toISOString().replace("T", " ").slice(0, 19),
      reviewed_at: null,
      matched_scholar_id: null,
    };
    subs.unshift(item);
    writeLS(LS_SUBMISSIONS_KEY, subs);
    return item;
  },

  async reviewSubmission(id, action, reviewNote = "") {
    const subs = readLS(LS_SUBMISSIONS_KEY, []);
    const idx = subs.findIndex((s) => s.id === Number(id));
    if (idx === -1) throw new Error("Submission not found");
    const sub = subs[idx];

    if (action === "reject") {
      sub.status = "rejected";
      sub.review_note = reviewNote;
      sub.reviewed_at = new Date().toISOString();
      writeLS(LS_SUBMISSIONS_KEY, subs);
      return { id: sub.id, status: "rejected" };
    }

    const st = await ensureLocalStore();
    const localAdded = readLS(LS_ADDED_KEY, { scholars: [], dissertations: [], edges: [] });
    let maxSid = Math.max(...st.bundle.scholars.map((s) => s.id), 10000);
    let maxDid = Math.max(...st.bundle.dissertations.map((d) => d.id), 10000);

    let existingScholar = findMatchingScholar(st, sub.scholar_name);
    let scholarId;
    if (existingScholar) {
      scholarId = existingScholar.id;
    } else {
      scholarId = ++maxSid;
      localAdded.scholars.push({
        id: scholarId,
        name: cleanPersonName(sub.scholar_name),
        name_zh: null,
        normalized_name: normalizeKey(sub.scholar_name),
        degree: sub.degree || "Ph.D.",
        university: sub.university || "",
        country: sub.country || "",
        year: sub.year || null,
        thesis_title: sub.thesis_title,
        thesis_title_en: sub.thesis_title_en || "",
        msc_code: "",
        mgp_id: null,
        wikidata_id: null,
        orcid: null,
        verification_status: "verified_dissertation",
        bio_summary: "",
      });
    }

    const dissId = ++maxDid;
    localAdded.dissertations.push({
      id: dissId,
      scholar_id: scholarId,
      title: sub.thesis_title,
      title_en: sub.thesis_title_en || "",
      author_raw: sub.scholar_name,
      advisors_raw: sub.advisors || [],
      institution: sub.university || "",
      department: "",
      degree: sub.degree || "Ph.D.",
      year: sub.year || null,
      source_repo: sub.source_repo,
      source_record_id: sub.source_record_id,
      doi: sub.doi || "",
      landing_url: sub.landing_url,
      pdf_url: sub.pdf_url || "",
      raw_metadata: (() => {
        try { return JSON.parse(sub.raw_metadata_json || "{}"); } catch { return {}; }
      })(),
      verified_at: new Date().toISOString().replace("T", " ").slice(0, 19),
    });

    for (const advName of sub.advisors || []) {
      let adv = findMatchingScholar(st, advName);
      let advId;
      if (adv) {
        advId = adv.id;
      } else {
        advId = ++maxSid;
        localAdded.scholars.push({
          id: advId,
          name: cleanPersonName(advName),
          name_zh: null,
          normalized_name: normalizeKey(advName),
          degree: "Ph.D.",
          university: sub.university || "",
          country: sub.country || "",
          year: null,
          thesis_title: "",
          thesis_title_en: "",
          msc_code: "",
          mgp_id: null,
          wikidata_id: null,
          orcid: null,
          verification_status: "advisor_inferred",
          bio_summary: "",
        });
      }
      if (advId !== scholarId) {
        localAdded.edges.push({
          advisor_id: advId,
          student_id: scholarId,
          source_type: "dissertation_verified",
          dissertation_id: dissId,
        });
      }
    }

    writeLS(LS_ADDED_KEY, localAdded);
    sub.status = "approved";
    sub.review_note = reviewNote;
    sub.matched_scholar_id = scholarId;
    sub.reviewed_at = new Date().toISOString();
    writeLS(LS_SUBMISSIONS_KEY, subs);

    await ensureLocalStore(true);
    return { id: sub.id, status: "approved", scholar_id: scholarId, dissertation_id: dissId };
  },

  async listHarvestRuns() {
    const st = await ensureLocalStore();
    return st.bundle.harvest_runs || [];
  },

  async triggerHarvest() {
    throw new Error("当前运行在 GitHub Pages 静态托管模式：批量采集已配置为 GitHub Actions 定期/手动自动运行，点击下方按钮即可在 GitHub Actions 触发增量采集并自动重新部署。");
  },
};

function _attachDbMatches(st, cand) {
  const notes = [];
  const existingScholar = findMatchingScholar(st, cand.scholar_name);
  if (existingScholar) {
    notes.push(`已匹配本地谱系学者 #${existingScholar.id} (${existingScholar.name})，批准后将补充论文原文证据。`);
  }
  const matchedAdvisors = (cand.advisors || []).map((adv) => {
    const m = findMatchingScholar(st, adv);
    if (m) {
      notes.push(`导师 “${adv}” 自动匹配已有谱系节点 #${m.id} (${m.name})。`);
      return { raw_name: adv, matched: true, scholar: m };
    }
    return { raw_name: adv, matched: false, scholar: null };
  });

  const dup = st.bundle.dissertations.find(
    (d) => d.source_repo === cand.source_repo && d.source_record_id === cand.source_record_id
  );
  if (dup) {
    notes.push(`该论文已在当前数据库中完成核验（学者 #${dup.scholar_id}）。`);
  }
  return {
    ...cand,
    existing_scholar_match: existingScholar,
    matched_advisors: matchedAdvisors,
    verification_notes: notes,
    already_ingested: Boolean(dup),
  };
}

export function buildGitHubSubmissionIssueUrl(cand) {
  const title = `[Verified Dissertation] ${cand.scholar_name} (${cand.year || "n/a"}) — ${cand.source_repo}`;
  const body = [
    "### Verified Doctoral Dissertation Submission",
    "",
    `- **Scholar**: ${cand.scholar_name}`,
    `- **Advisor(s)**: ${(cand.advisors || []).join(", ")}`,
    `- **University**: ${cand.university || "—"}`,
    `- **Year**: ${cand.year || "—"}`,
    `- **Thesis Title**: ${cand.thesis_title}`,
    `- **Official Repository**: ${cand.source_repo} (\`${cand.source_record_id}\`)`,
    `- **Official Thesis URL**: ${cand.landing_url}`,
    cand.pdf_url ? `- **Direct PDF URL**: ${cand.pdf_url}` : "",
    cand.doi ? `- **DOI**: ${cand.doi}` : "",
    "",
    "```json",
    JSON.stringify(
      {
        scholar_name: cand.scholar_name,
        advisors: cand.advisors,
        university: cand.university,
        country: cand.country,
        year: cand.year,
        thesis_title: cand.thesis_title,
        source_repo: cand.source_repo,
        source_record_id: cand.source_record_id,
        doi: cand.doi || "",
        landing_url: cand.landing_url,
        pdf_url: cand.pdf_url || "",
      },
      null,
      2
    ),
    "```",
  ]
    .filter(Boolean)
    .join("\n");

  return `${GITHUB_REPO_URL}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
}
