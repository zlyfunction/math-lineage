import React, { useEffect, useState } from "react";
import { api } from "../api";
import GenealogyGraph from "./GenealogyGraph";
import { VerificationBadge } from "./Header";

export default function ScholarDetail({ scholarId, onSelectScholar, onBack, onOpenPathWith }) {
  const [detail, setDetail] = useState(null);
  const [graph, setGraph] = useState(null);
  const [ancestorDepth, setAncestorDepth] = useState(6);
  const [descendantDepth, setDescendantDepth] = useState(2);
  const [showRawJson, setShowRawJson] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setShowRawJson(false);

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
      <div className="surface-card" style={{ padding: 48, textAlign: "center", color: "var(--ink-muted)" }}>
        正在加载学者档案与师承图谱…
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="surface-card" style={{ padding: 32 }}>
        <div className="alert-box alert-error">{error || "未找到该学者记录"}</div>
        <button className="btn" onClick={onBack}>← 返回检索列表</button>
      </div>
    );
  }

  const { scholar, dissertations, advisors, students, direct_students_count, total_descendants_count } = detail;

  return (
    <div>
      <div className="back-bar" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <button className="btn btn-sm" onClick={onBack} id="btn-back-directory">
          ← 返回学者检索
        </button>
        <button
          className="btn btn-sm"
          onClick={() => onOpenPathWith(scholar)}
          id="btn-trace-path-from-scholar"
        >
          查找与另一位学者的最短学术路径 →
        </button>
      </div>

      {/* Scholar Profile Header */}
      <section className="profile-header-card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <VerificationBadge
            status={scholar.verification_status}
            repo={dissertations[0]?.source_repo}
          />
          {scholar.mgp_id && (
            <a
              className="badge badge-repo"
              href={`https://www.genealogy.math.ndsu.nodak.edu/id.php?id=${scholar.mgp_id}`}
              target="_blank"
              rel="noreferrer"
            >
              MGP #{scholar.mgp_id} ↗
            </a>
          )}
          {scholar.wikidata_id && (
            <a
              className="badge badge-repo"
              href={`https://www.wikidata.org/wiki/${scholar.wikidata_id}`}
              target="_blank"
              rel="noreferrer"
            >
              Wikidata {scholar.wikidata_id} ↗
            </a>
          )}
          {scholar.orcid && (
            <a
              className="badge badge-repo"
              href={`https://orcid.org/${scholar.orcid}`}
              target="_blank"
              rel="noreferrer"
            >
              ORCID {scholar.orcid} ↗
            </a>
          )}
        </div>

        <h1 className="profile-title">
          {scholar.name}
          {scholar.name_zh && (
            <span style={{ fontSize: "1.3rem", fontWeight: 400, color: "var(--ink-muted)", marginLeft: 12 }}>
              {scholar.name_zh}
            </span>
          )}
        </h1>

        <div className="profile-submeta">
          <span><strong>{scholar.degree || "Ph.D."}</strong></span>
          {scholar.university && <span>{scholar.university}</span>}
          {scholar.country && <span>{scholar.country}</span>}
          {scholar.year && <span className="mono">{scholar.year}</span>}
          {scholar.bio_summary && <span style={{ color: "var(--ink-muted)" }}>— {scholar.bio_summary}</span>}
        </div>

        <div className="profile-kpis">
          <div className="kpi-item">
            <span className="kpi-num">{advisors.length}</span>
            <span className="kpi-lbl">博士导师 · Advisors</span>
          </div>
          <div className="kpi-item">
            <span className="kpi-num">{direct_students_count}</span>
            <span className="kpi-lbl">直接博士生 · Students</span>
          </div>
          <div className="kpi-item">
            <span className="kpi-num">{total_descendants_count}</span>
            <span className="kpi-lbl">学术后代总数 · Descendants</span>
          </div>
          <div className="kpi-item">
            <span className="kpi-num" style={{ color: dissertations.length > 0 ? "var(--proof-emerald)" : "var(--ink-muted)" }}>
              {dissertations.length}
            </span>
            <span className="kpi-lbl">可核验论文原件 · Thesis Proofs</span>
          </div>
        </div>
      </section>

      {/* Interactive Genealogy Graph */}
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

      {/* Two-Column Dissertation Provenance + Advisors */}
      <div className="detail-grid">
        {/* Dissertation Provenance Card */}
        <section className="surface-card">
          <h2 className="card-heading">
            <span>博士论文与原文溯源 · Dissertation Provenance</span>
          </h2>

          {dissertations.length > 0 ? (
            dissertations.map((d) => (
              <div key={d.id} className="evidence-box">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span className="badge badge-verified">✓ 官方论文库实时核验</span>
                  <span className="badge badge-repo">{d.source_repo} · {d.source_record_id}</span>
                </div>

                <div className="evidence-title">“{d.title}”</div>
                {d.title_en && (
                  <div style={{ fontSize: "0.88rem", color: "var(--ink-secondary)", fontStyle: "italic", marginBottom: 6 }}>
                    English Title: {d.title_en}
                  </div>
                )}

                <div style={{ fontSize: "0.84rem", color: "var(--ink-secondary)", lineHeight: 1.7 }}>
                  <div><strong>论文登记作者：</strong>{d.author_raw}</div>
                  <div><strong>论文登记导师：</strong>{(d.advisors_raw || []).join("；")}</div>
                  <div>
                    <strong>授予机构：</strong>{d.institution || scholar.university || "—"}
                    {d.department ? `（${d.department}）` : ""}
                    {d.year ? ` · ${d.year}` : ""}
                  </div>
                  {d.doi && (
                    <div>
                      <strong>DOI：</strong><span className="mono">{d.doi}</span>
                    </div>
                  )}
                  <div className="mono" style={{ fontSize: "0.75rem", color: "var(--ink-muted)", marginTop: 4 }}>
                    核验入库时间：{d.verified_at} UTC
                  </div>
                </div>

                <div className="evidence-links">
                  <a className="evidence-link-btn" href={d.landing_url} target="_blank" rel="noreferrer">
                    访问官方论文页面 ↗
                  </a>
                  {d.pdf_url && (
                    <a className="evidence-link-btn" href={d.pdf_url} target="_blank" rel="noreferrer">
                      下载/查看论文 PDF ↗
                    </a>
                  )}
                  <button
                    className="btn btn-sm"
                    onClick={() => setShowRawJson((v) => !v)}
                  >
                    {showRawJson ? "收起原始元数据 JSON" : "查看官方原始元数据 JSON"}
                  </button>
                </div>

                {showRawJson && (
                  <pre className="raw-meta-pre">
                    {JSON.stringify(d.raw_metadata, null, 2)}
                  </pre>
                )}
              </div>
            ))
          ) : (
            <div style={{ color: "var(--ink-secondary)", fontSize: "0.92rem" }}>
              {scholar.thesis_title ? (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: "0.8rem", color: "var(--ink-muted)", marginBottom: 4 }}>历史登记论文题目</div>
                  <div style={{ fontFamily: "var(--font-serif)", fontStyle: "italic", fontSize: "1.06rem", color: "var(--ink-primary)" }}>
                    “{scholar.thesis_title}”
                  </div>
                </div>
              ) : null}
              <p style={{ margin: "0 0 12px", color: "var(--ink-muted)" }}>
                该学者目前属于历史谱系底座或由其学生的已核验论文反向关联，尚未绑定官方学位论文库直链。
                如果你能检索到其博士论文的 DOI、MIT Handle、HAL 或 theses.fr 编号，可前往「论文核验录入」补充原文证据。
              </p>
            </div>
          )}
        </section>

        {/* Advisors Card */}
        <section className="surface-card">
          <h2 className="card-heading">
            <span>博士导师 · Doctoral Advisors ({advisors.length})</span>
          </h2>
          {advisors.length === 0 ? (
            <p style={{ color: "var(--ink-muted)", fontSize: "0.9rem", margin: 0 }}>
              当前库中未记录上溯导师（可能为历史谱系起点或待核验补充）。
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {advisors.map((adv) => (
                <div
                  key={adv.id}
                  style={{
                    padding: "12px 14px",
                    border: "1px solid var(--border-hairline)",
                    borderRadius: "var(--radius-md)",
                    background: "var(--bg-page)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                    <button
                      className="link-btn"
                      style={{ fontFamily: "var(--font-serif)", fontSize: "1.08rem", fontWeight: 600 }}
                      onClick={() => onSelectScholar(adv.id)}
                    >
                      {adv.name} {adv.name_zh ? `(${adv.name_zh})` : ""}
                    </button>
                    <span className={`badge ${adv.source_type === "dissertation_verified" ? "badge-verified" : "badge-historical"}`}>
                      {adv.source_type === "dissertation_verified" ? "✓ 论文实证" : "Wikidata P184"}
                    </span>
                  </div>
                  <div style={{ fontSize: "0.82rem", color: "var(--ink-secondary)", marginTop: 4 }}>
                    {adv.university || "Institution n/a"} {adv.year ? `· ${adv.year}` : ""}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Students Table (Classic MGP Style, Upgraded) */}
      <section className="surface-card">
        <h2 className="card-heading">
          <span>指导博士生列表 · Doctoral Students ({students.length})</span>
          <span style={{ fontSize: "0.82rem", fontFamily: "var(--font-sans)", fontWeight: 400, color: "var(--ink-muted)" }}>
            总学术后代：{total_descendants_count} 人
          </span>
        </h2>

        {students.length === 0 ? (
          <p style={{ color: "var(--ink-muted)", fontSize: "0.9rem", margin: 0 }}>
            当前库中暂无该学者指导的博士生记录。
          </p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>学生姓名 Name</th>
                  <th>毕业院校 School</th>
                  <th>年份 Year</th>
                  <th>学术后代 Descendants</th>
                  <th>溯源状态 Provenance</th>
                </tr>
              </thead>
              <tbody>
                {students.map((st) => (
                  <tr key={st.id}>
                    <td>
                      <button
                        className="link-btn"
                        style={{ fontFamily: "var(--font-serif)", fontSize: "1rem", fontWeight: 600 }}
                        onClick={() => onSelectScholar(st.id)}
                      >
                        {st.name}
                      </button>
                      {st.name_zh && (
                        <span style={{ marginLeft: 6, fontSize: "0.8rem", color: "var(--ink-muted)" }}>
                          {st.name_zh}
                        </span>
                      )}
                      {st.thesis_title && (
                        <div style={{ fontSize: "0.78rem", color: "var(--ink-muted)", fontStyle: "italic", marginTop: 2 }}>
                          {st.thesis_title.length > 90 ? st.thesis_title.slice(0, 89) + "…" : st.thesis_title}
                        </div>
                      )}
                    </td>
                    <td>{st.university || "—"}</td>
                    <td className="mono">{st.year || "—"}</td>
                    <td className="mono">{st.total_descendants}</td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <VerificationBadge status={st.verification_status} repo={st.source_repo} />
                        {st.dissertation_url && (
                          <a href={st.dissertation_url} target="_blank" rel="noreferrer" style={{ fontSize: "0.78rem" }}>
                            原文 ↗
                          </a>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
