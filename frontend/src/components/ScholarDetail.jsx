import React, { useEffect, useState } from "react";
import { api } from "../api";
import GenealogyGraph from "./GenealogyGraph";

export default function ScholarDetail({ scholarId, onSelectScholar, onBack, onOpenPathWith }) {
  const [detail, setDetail] = useState(null);
  const [graph, setGraph] = useState(null);
  const [ancestorDepth, setAncestorDepth] = useState(6);
  const [descendantDepth, setDescendantDepth] = useState(2);
  const [showMeta, setShowMeta] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setShowMeta(false);

    Promise.all([
      api.getScholar(scholarId),
      api.getLineage(scholarId, ancestorDepth, descendantDepth),
    ])
      .then(([d, g]) => {
        if (!active) return;
        setDetail(d);
        setGraph(g);
      })
      .catch((err) => {
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [scholarId, ancestorDepth, descendantDepth]);

  if (loading && !detail) {
    return (
      <div style={{ padding: 48, textAlign: "center", fontStyle: "italic", color: "var(--ink-muted)" }}>
        Unrolling lineage scroll…
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="parchment-panel">
        <div className="notice notice-err">{error || "Scholar record not found."}</div>
        <button className="btn btn-xs" onClick={onBack}>← Back to Index</button>
      </div>
    );
  }

  const { scholar, dissertations, advisors, students, direct_students_count, total_descendants_count } = detail;
  const primaryDiss = dissertations[0] || null;
  const thesisTitle = primaryDiss?.title || scholar.thesis_title;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, gap: 10, flexWrap: "wrap" }}>
        <button className="btn btn-xs" onClick={onBack} id="btn-back-directory">
          ← Index
        </button>
        <button className="btn btn-xs" onClick={() => onOpenPathWith(scholar)} id="btn-trace-path-from-scholar">
          Trace Lineage Path →
        </button>
      </div>

      {/* Engraved Scholar Plate */}
      <section className="scholar-plate">
        <h1 className="plate-name">{scholar.name}</h1>

        <div className="plate-degree">
          {scholar.degree || "Ph.D."}
          {scholar.university ? ` · ${scholar.university}` : ""}
          {scholar.country ? `, ${scholar.country}` : ""}
          {scholar.year ? ` · ${scholar.year}` : ""}
        </div>

        {scholar.msc_code && (
          <div className="plate-msc">
            MSC {scholar.msc_code}{scholar.msc_label ? ` — ${scholar.msc_label}` : ""}
          </div>
        )}

        {thesisTitle && (
          <div className="plate-thesis">“{thesisTitle}”</div>
        )}

        <div className="plate-links">
          {primaryDiss && (
            <a href={primaryDiss.landing_url} target="_blank" rel="noreferrer" className="verified-mark">
              ✦ Official Thesis ({primaryDiss.source_repo}) ↗
            </a>
          )}
          {primaryDiss?.pdf_url && primaryDiss.pdf_url !== primaryDiss.landing_url && (
            <a href={primaryDiss.pdf_url} target="_blank" rel="noreferrer">
              PDF ↗
            </a>
          )}
          {scholar.mgp_id && (
            <a
              href={`https://www.genealogy.math.ndsu.nodak.edu/id.php?id=${scholar.mgp_id}`}
              target="_blank"
              rel="noreferrer"
            >
              MGP #{scholar.mgp_id} ↗
            </a>
          )}
          {scholar.orcid && (
            <a href={`https://orcid.org/${scholar.orcid}`} target="_blank" rel="noreferrer">
              ORCID ↗
            </a>
          )}
          {primaryDiss && (
            <button className="text-link-btn" style={{ fontSize: "0.86rem", color: "var(--ink-muted)" }} onClick={() => setShowMeta((v) => !v)}>
              {showMeta ? "Hide Record" : "Source Record"}
            </button>
          )}
        </div>

        {showMeta && primaryDiss && (
          <pre className="metadata-pre">
            {JSON.stringify(primaryDiss.raw_metadata || { source: primaryDiss.source_repo, id: primaryDiss.source_record_id }, null, 2)}
          </pre>
        )}

        <div className="plate-tally">
          <span><strong>{advisors.length}</strong> {advisors.length === 1 ? "Advisor" : "Advisors"}</span>
          <span>·</span>
          <span><strong>{direct_students_count}</strong> {direct_students_count === 1 ? "Student" : "Students"}</span>
          <span>·</span>
          <span><strong>{total_descendants_count}</strong> {total_descendants_count === 1 ? "Descendant" : "Descendants"}</span>
        </div>
      </section>

      {/* Centerpiece Family Tree Scroll */}
      <GenealogyGraph
        graph={graph}
        onSelectScholar={onSelectScholar}
        ancestorDepth={ancestorDepth}
        descendantDepth={descendantDepth}
        onDepthChange={(a, d) => {
          setAncestorDepth(a);
          setDescendantDepth(d);
        }}
      />

      {/* Minimal Advisors & Students Ledger */}
      <div className="lineage-columns">
        <section className="parchment-panel">
          <h2 className="panel-heading">Doctoral Advisors ({advisors.length})</h2>
          {advisors.length === 0 ? (
            <p style={{ margin: 0, fontStyle: "italic", color: "var(--ink-muted)" }}>
              No advisor recorded.
            </p>
          ) : (
            advisors.map((adv) => (
              <div key={adv.id} className="advisor-row">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
                  <button
                    className="text-link-btn"
                    style={{ fontFamily: "var(--font-heading)", fontSize: "1.2rem", fontWeight: 600 }}
                    onClick={() => onSelectScholar(adv.id)}
                  >
                    {adv.name}
                  </button>
                  <span style={{ fontSize: "0.78rem", fontStyle: "italic", color: adv.source_type === "dissertation_verified" ? "var(--seal-verdigris)" : "var(--ink-muted)" }}>
                    {adv.source_type === "dissertation_verified" ? "✦ Thesis" : "MGP"}
                  </span>
                </div>
                <div style={{ fontSize: "0.88rem", color: "var(--ink-muted)" }}>
                  {adv.university || "Institution unrecorded"}{adv.year ? `, ${adv.year}` : ""}
                </div>
              </div>
            ))
          )}
        </section>

        <section className="parchment-panel">
          <h2 className="panel-heading">Doctoral Students ({students.length})</h2>
          {students.length === 0 ? (
            <p style={{ margin: 0, fontStyle: "italic", color: "var(--ink-muted)" }}>
              No doctoral students recorded yet.
            </p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="ledger-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Institution</th>
                    <th>Year</th>
                    <th>Desc.</th>
                  </tr>
                </thead>
                <tbody>
                  {students.map((st) => (
                    <tr key={st.id}>
                      <td>
                        <button
                          className="text-link-btn"
                          style={{ fontFamily: "var(--font-heading)", fontSize: "1.08rem", fontWeight: 600 }}
                          onClick={() => onSelectScholar(st.id)}
                        >
                          {st.name}
                        </button>
                        {st.dissertation_url && (
                          <a
                            href={st.dissertation_url}
                            target="_blank"
                            rel="noreferrer"
                            className="verified-mark"
                            style={{ marginLeft: 7, fontSize: "0.76rem" }}
                            title="View official dissertation"
                          >
                            ✦
                          </a>
                        )}
                      </td>
                      <td style={{ fontSize: "0.88rem", color: "var(--ink-muted)" }}>{st.university || "—"}</td>
                      <td style={{ fontSize: "0.88rem" }}>{st.year || "—"}</td>
                      <td style={{ fontSize: "0.88rem", color: "var(--ink-muted)" }}>{st.total_descendants || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
