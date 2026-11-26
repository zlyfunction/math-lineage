import React, { useEffect, useState } from "react";
import { api } from "../api";
import { VerificationBadge } from "./Header";

export default function HomeSearch({ stats, onSelectScholar, onNavigate }) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [repoFilter, setRepoFilter] = useState("all");
  const [sortBy, setSortBy] = useState("relevance");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [page, setPage] = useState(1);

  const [results, setResults] = useState({ total: 0, items: [], page: 1, page_size: 20 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const timer = setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const data = await api.searchScholars({
          q: query,
          status: statusFilter,
          repo: repoFilter,
          sort: sortBy,
          year_from: yearFrom,
          year_to: yearTo,
          page,
          page_size: 20,
        });
        if (active) setResults(data);
      } catch (err) {
        if (active) setError(err.message);
      } finally {
        if (active) setLoading(false);
      }
    }, 180);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query, statusFilter, repoFilter, sortBy, yearFrom, yearTo, page]);

  const totalPages = Math.max(1, Math.ceil((results.total || 0) / (results.page_size || 20)));

  return (
    <div>
      {/* Editorial Hero */}
      <section className="hero-section">
        <div className="hero-eyebrow">OPEN MATHEMATICS GENEALOGY · DISSERTATION-FIRST VERIFICATION</div>
        <h1 className="hero-heading">重建数学学术谱系，以可检索博士论文为准</h1>
        <p className="hero-lead">
          融合 Wikidata 历史数学家谱系底座（MGP P549 / P184）与全球开放学位论文库（MIT DSpace、HAL/TEL、theses.fr、DataCite
          Oxford/Cambridge/LMU）的实时核验数据。每一条新增记录均附带官方论文原文链接、导师字段与原始元数据溯源。
        </p>

        {stats && (
          <div className="stats-strip">
            <div className="stat-tile">
              <div className="stat-value">{stats.total_scholars.toLocaleString()}</div>
              <div className="stat-label">收录数学学者 · Scholars</div>
            </div>
            <div className="stat-tile">
              <div className="stat-value emerald">{stats.total_dissertations.toLocaleString()}</div>
              <div className="stat-label">官方论文原文核验 · Verified Theses</div>
            </div>
            <div className="stat-tile">
              <div className="stat-value">{stats.total_edges.toLocaleString()}</div>
              <div className="stat-label">师承关系边 · Advisor–Student Edges</div>
            </div>
            <div className="stat-tile">
              <div className="stat-value">{stats.repo_breakdown?.length || 0}</div>
              <div className="stat-label">已接入论文数据源 · Active Repositories</div>
            </div>
          </div>
        )}

        {stats?.repo_breakdown?.length > 0 && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 14, alignItems: "center" }}>
            <span style={{ fontSize: "0.76rem", color: "var(--ink-muted)", fontFamily: "var(--font-mono)" }}>
              各论文库实证分布：
            </span>
            {stats.repo_breakdown.map((rb) => (
              <button
                key={rb.source_repo}
                type="button"
                className="featured-chip"
                style={{
                  padding: "4px 10px",
                  fontSize: "0.78rem",
                  borderColor: repoFilter === rb.source_repo ? "var(--proof-emerald)" : undefined,
                  background: repoFilter === rb.source_repo ? "var(--proof-emerald-soft)" : undefined,
                }}
                onClick={() => {
                  setRepoFilter(repoFilter === rb.source_repo ? "all" : rb.source_repo);
                  setPage(1);
                }}
              >
                <span>{rb.source_repo}</span>
                <span className="chip-meta">{rb.count}</span>
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Featured Historical & Modern Lineages */}
      {stats?.featured_scholars?.length > 0 && (
        <section className="featured-section">
          <div className="section-label">经典师承起点 · Explore Landmark Lineages</div>
          <div className="featured-chips">
            {stats.featured_scholars.map((s) => (
              <button
                key={s.id}
                className="featured-chip"
                onClick={() => onSelectScholar(s.id)}
              >
                <span style={{ fontFamily: "var(--font-serif)", fontWeight: 600 }}>{s.name}</span>
                {s.name_zh && <span style={{ color: "var(--ink-muted)", fontSize: "0.78rem" }}>{s.name_zh}</span>}
                <span className="chip-meta">{s.direct_students} 学生</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Search & Multi-Facet Filter Bar */}
      <section className="search-panel" aria-label="Scholar Search">
        <div className="search-row">
          <div className="search-input-wrap">
            <input
              id="scholar-search-input"
              type="search"
              className="search-input"
              placeholder="检索数学家姓名（中/英）、毕业院校、博士论文题目或 MGP ID（如 Gauss、MIT、Topology、2026）…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <button
            className="btn btn-emerald"
            onClick={() => onNavigate("verify")}
            id="cta-verify-dissertation"
          >
            ＋ 论文核验录入
          </button>
        </div>

        <div className="filter-bar">
          <select
            className="filter-select"
            aria-label="Verification status"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="all">全部核验层级 (All)</option>
            <option value="verified_dissertation">✓ 仅看论文直链核验 (Dissertation Verified)</option>
            <option value="historical_wikidata">历史谱系底座 (Wikidata / MGP)</option>
            <option value="advisor_inferred">导师关联节点 (Advisor Nodes)</option>
          </select>

          <select
            className="filter-select"
            aria-label="Dissertation repository"
            value={repoFilter}
            onChange={(e) => {
              setRepoFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="all">全部论文库 (All Repositories)</option>
            <option value="NYU Courant">NYU Courant (纽约大学库朗所)</option>
            <option value="MIT DSpace">MIT DSpace (麻省理工)</option>
            <option value="HAL/TEL">HAL / TEL (法国/欧洲)</option>
            <option value="theses.fr">theses.fr (法国 ABES 官方)</option>
            <option value="DataCite">DataCite (Oxford / Cambridge / LMU / ETH)</option>
          </select>

          <select
            className="filter-select"
            aria-label="Sort order"
            value={sortBy}
            onChange={(e) => {
              setSortBy(e.target.value);
              setPage(1);
            }}
          >
            <option value="relevance">排序：已核验与最新优先</option>
            <option value="year_desc">年份：从新到旧 (2026 →)</option>
            <option value="year_asc">年份：从早到晚</option>
            <option value="students_desc">直接学生数：从多到少</option>
            <option value="name_asc">姓名：A → Z</option>
          </select>

          <input
            type="number"
            className="filter-num"
            placeholder="起始年"
            value={yearFrom}
            onChange={(e) => {
              setYearFrom(e.target.value);
              setPage(1);
            }}
          />
          <span style={{ color: "var(--ink-muted)", fontSize: "0.82rem" }}>–</span>
          <input
            type="number"
            className="filter-num"
            placeholder="结束年"
            value={yearTo}
            onChange={(e) => {
              setYearTo(e.target.value);
              setPage(1);
            }}
          />

          {(query || statusFilter !== "all" || repoFilter !== "all" || yearFrom || yearTo) && (
            <button
              className="btn btn-sm"
              onClick={() => {
                setQuery("");
                setStatusFilter("all");
                setRepoFilter("all");
                setYearFrom("");
                setYearTo("");
                setPage(1);
              }}
            >
              重置筛选
            </button>
          )}
        </div>
      </section>

      {error && <div className="alert-box alert-error">{error}</div>}

      <div className="results-header">
        <span>
          共找到 <strong>{results.total.toLocaleString()}</strong> 位学者
          {query ? `（关键词：“${query}”）` : ""}
        </span>
        <span className="mono" style={{ fontSize: "0.78rem" }}>
          Page {page} / {totalPages}
        </span>
      </div>

      {loading ? (
        <div className="surface-card" style={{ textAlign: "center", padding: 48, color: "var(--ink-muted)" }}>
          正在检索学术谱系数据库…
        </div>
      ) : results.items.length === 0 ? (
        <div className="surface-card" style={{ textAlign: "center", padding: 48 }}>
          <p style={{ margin: "0 0 12px", color: "var(--ink-secondary)" }}>当前本地数据库中未找到匹配的学者记录。</p>
          <button className="btn btn-primary" onClick={() => onNavigate("verify")}>
            去「论文核验录入」实时搜索全球官方学位论文库 →
          </button>
        </div>
      ) : (
        <div className="scholar-list">
          {results.items.map((item) => (
            <article
              key={item.id}
              className="scholar-row-card"
              onClick={() => onSelectScholar(item.id)}
            >
              <div className="scholar-row-top">
                <div>
                  <h2 className="scholar-name-heading">
                    <span>{item.name}</span>
                    {item.name_zh && <span className="scholar-name-zh">{item.name_zh}</span>}
                  </h2>
                  <div className="scholar-meta-line">
                    <span>{item.degree || "Ph.D."}</span>
                    {item.university && <span>· {item.university}</span>}
                    {item.country && <span>({item.country})</span>}
                    {item.year && <span className="mono">· {item.year}</span>}
                    {item.mgp_id && <span className="mono" style={{ color: "var(--ink-muted)" }}>MGP #{item.mgp_id}</span>}
                  </div>
                </div>

                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <VerificationBadge status={item.verification_status} repo={item.source_repo} />
                </div>
              </div>

              {item.thesis_title && (
                <div className="scholar-thesis-line">
                  “{item.thesis_title}”
                </div>
              )}

              <div className="scholar-row-footer">
                <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
                  <span>
                    导师：
                    {item.advisors?.length > 0
                      ? item.advisors.map((a) => a.name).join("、")
                      : <span style={{ color: "var(--ink-muted)" }}>待补充</span>}
                  </span>
                  <span>直接学生：<strong className="mono">{item.direct_students}</strong></span>
                </div>

                <div style={{ display: "flex", gap: 12, alignItems: "center" }} onClick={(e) => e.stopPropagation()}>
                  {item.dissertation_url && (
                    <a
                      href={item.dissertation_url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ color: "var(--proof-emerald)", fontWeight: 600 }}
                    >
                      论文原文 ↗
                    </a>
                  )}
                  {item.pdf_url && (
                    <a
                      href={item.pdf_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mono"
                      style={{ fontSize: "0.78rem" }}
                    >
                      PDF ↗
                    </a>
                  )}
                  <button className="link-btn" onClick={() => onSelectScholar(item.id)}>
                    查看谱系 →
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="pagination">
          <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            ← 上一页
          </button>
          <span className="mono" style={{ fontSize: "0.84rem", color: "var(--ink-secondary)" }}>
            第 {page} / {totalPages} 页
          </span>
          <button className="btn btn-sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            下一页 →
          </button>
        </div>
      )}
    </div>
  );
}
