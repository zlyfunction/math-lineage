import React, { useEffect, useState } from "react";
import { api } from "../api";

export default function HomeSearch({ stats, onSelectScholar }) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [repoFilter, setRepoFilter] = useState("all");
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
          sort: "relevance",
          page,
          page_size: 20,
        });
        if (active) setResults(data);
      } catch (err) {
        if (active) setError(err.message);
      } finally {
        if (active) setLoading(false);
      }
    }, 150);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query, statusFilter, repoFilter, page]);

  const totalPages = Math.max(1, Math.ceil((results.total || 0) / (results.page_size || 20)));

  return (
    <div>
      <section className="index-hero">
        <h1 className="index-title">Index of Mathematical Lineages</h1>
        <p className="index-subtitle">
          {stats
            ? `${stats.total_scholars.toLocaleString()} scholars · ${stats.total_dissertations.toLocaleString()} verified doctoral theses · ${stats.total_edges.toLocaleString()} advisor–student links`
            : "Trace doctoral advisors, students, and verified dissertations"}
        </p>

        <div className="search-box-row">
          <input
            id="scholar-search-input"
            type="search"
            className="parchment-input"
            placeholder="Search by mathematician, university, or dissertation title…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
          />
        </div>

        <div className="filter-inline">
          <select
            className="parchment-select"
            aria-label="Filter by source tier"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="all">All Scholars</option>
            <option value="verified_dissertation">Thesis-Verified Only</option>
            <option value="historical_wikidata">Historical Archive (MGP / Wikidata)</option>
          </select>

          <select
            className="parchment-select"
            aria-label="Filter by thesis archive"
            value={repoFilter}
            onChange={(e) => {
              setRepoFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="all">All Archives</option>
            <option value="NYU Courant">NYU Courant</option>
            <option value="MIT DSpace">MIT DSpace</option>
            <option value="HAL/TEL">HAL / TEL</option>
            <option value="theses.fr">theses.fr</option>
            <option value="DataCite">DataCite (Oxford / Cambridge / LMU)</option>
          </select>

          {(query || statusFilter !== "all" || repoFilter !== "all") && (
            <button
              className="btn btn-xs"
              onClick={() => {
                setQuery("");
                setStatusFilter("all");
                setRepoFilter("all");
                setPage(1);
              }}
            >
              Clear
            </button>
          )}
        </div>
      </section>

      {stats?.featured_scholars?.length > 0 && !query && (
        <div className="notable-line">
          <span style={{ fontStyle: "italic", marginRight: 6 }}>Explore lineages:</span>
          {stats.featured_scholars.map((s, idx) => (
            <React.Fragment key={s.id}>
              <button className="notable-name" onClick={() => onSelectScholar(s.id)}>
                {s.name}
              </button>
              {idx < stats.featured_scholars.length - 1 && <span>·</span>}
            </React.Fragment>
          ))}
        </div>
      )}

      {error && <div className="notice notice-err">{error}</div>}

      <section className="ledger-shell" aria-label="Scholars Register">
        <div className="ledger-meta-bar">
          <span>
            {results.total.toLocaleString()} {results.total === 1 ? "entry" : "entries"}
            {query ? ` matching “${query}”` : ""}
          </span>
          <span>
            Page {page} of {totalPages}
          </span>
        </div>

        {loading ? (
          <div style={{ padding: 40, textAlign: "center", fontStyle: "italic", color: "var(--ink-muted)" }}>
            Consulting the register…
          </div>
        ) : results.items.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", fontStyle: "italic", color: "var(--ink-muted)" }}>
            No matching scholars found in the register.
          </div>
        ) : (
          <div>
            {results.items.map((item) => (
              <article
                key={item.id}
                className="ledger-entry"
                onClick={() => onSelectScholar(item.id)}
              >
                <div className="ledger-entry-top">
                  <h2 className="entry-name">{item.name}</h2>
                  <span className="entry-sub">
                    {item.degree || "Ph.D."}
                    {item.university ? ` · ${item.university}` : ""}
                    {item.year ? `, ${item.year}` : ""}
                  </span>
                </div>

                {item.thesis_title && (
                  <div className="entry-thesis">“{item.thesis_title}”</div>
                )}

                <div className="entry-foot">
                  <span>
                    {item.advisors?.length > 0
                      ? `Advisor${item.advisors.length > 1 ? "s" : ""}: ${item.advisors.map((a) => a.name).join(", ")}`
                      : "Origin / Advisor unrecorded"}
                    {item.direct_students > 0
                      ? ` · ${item.direct_students} ${item.direct_students === 1 ? "student" : "students"}`
                      : ""}
                  </span>

                  <span
                    style={{ display: "inline-flex", gap: 12, alignItems: "center" }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {item.dissertation_url && (
                      <a
                        href={item.dissertation_url}
                        target="_blank"
                        rel="noreferrer"
                        className="verified-mark"
                      >
                        ✦ Thesis ({item.source_repo}) ↗
                      </a>
                    )}
                    <button className="text-link-btn" onClick={() => onSelectScholar(item.id)}>
                      View Tree →
                    </button>
                  </span>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {totalPages > 1 && (
        <div className="pagination-bar">
          <button className="btn btn-xs" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            ← Previous
          </button>
          <span>
            {page} / {totalPages}
          </span>
          <button className="btn btn-xs" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
