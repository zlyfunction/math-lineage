import React, { useState } from "react";
import { api } from "../api";
import { buildGitHubSubmissionIssueUrl } from "../localEngine";

const EXAMPLES = [
  { label: "Oxford 2026 DOI (DataCite)", id: "10.5287/ora-2ryxmqqqk" },
  { label: "ENS Lyon 2026 (HAL/TEL)", id: "tel-05583740" },
  { label: "MIT Math PhD (DSpace Handle)", id: "1721.1/8641" },
  { label: "Lyon 2026 (theses.fr)", id: "2026LYO10146" },
];

export default function VerifySubmit({ onSubmitted, onSelectScholar }) {
  const [mode, setMode] = useState("identifier"); // 'identifier' | 'search'

  // Identifier mode
  const [identifier, setIdentifier] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [candidate, setCandidate] = useState(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });

  // Live search mode
  const [liveQuery, setLiveQuery] = useState("");
  const [liveSource, setLiveSource] = useState("all");
  const [liveLoading, setLiveLoading] = useState(false);
  const [liveResults, setLiveResults] = useState([]);

  const handleVerify = async (idOverride) => {
    const target = (idOverride ?? identifier).trim();
    if (!target) return;
    if (idOverride) setIdentifier(idOverride);
    setVerifying(true);
    setMessage({ type: "", text: "" });
    setCandidate(null);
    try {
      const res = await api.verifyDissertation(target);
      setCandidate(res);
    } catch (err) {
      setMessage({ type: "error", text: err.message });
    } finally {
      setVerifying(false);
    }
  };

  const handleLiveSearch = async (e) => {
    e.preventDefault();
    if (!liveQuery.trim()) return;
    setLiveLoading(true);
    setMessage({ type: "", text: "" });
    try {
      const res = await api.searchLiveRepos(liveQuery.trim(), liveSource, 10);
      setLiveResults(res.items || []);
      if ((res.items || []).length === 0) {
        setMessage({ type: "info", text: "未在开放论文库中找到同时包含“论文原文+导师字段”的匹配记录，请尝试英文关键词或更换数据源。" });
      }
    } catch (err) {
      setMessage({ type: "error", text: err.message });
    } finally {
      setLiveLoading(false);
    }
  };

  const submitCandidate = async (cand) => {
    if (!cand.advisors || cand.advisors.length === 0) {
      setMessage({ type: "error", text: "该论文元数据中缺少明确的导师字段，根据「严格以论文为准」规则不可直接入库。" });
      return;
    }
    setSubmitting(true);
    setMessage({ type: "", text: "" });
    try {
      const created = await api.createSubmission({
        scholar_name: cand.scholar_name,
        advisors: cand.advisors,
        university: cand.university || "",
        country: cand.country || "",
        degree: cand.degree || "Ph.D.",
        year: cand.year || null,
        thesis_title: cand.thesis_title,
        thesis_title_en: cand.thesis_title_en || "",
        source_repo: cand.source_repo,
        source_record_id: cand.source_record_id,
        doi: cand.doi || "",
        landing_url: cand.landing_url,
        pdf_url: cand.pdf_url || "",
        raw_metadata_json: JSON.stringify(cand.raw_metadata || {}),
        submitter_note: note,
      });
      setMessage({
        type: "success",
        text: `已提交审核队列 #${created.id}（${created.scholar_name}）！你可以立即前往「审核与采集管线」核对原文并批准入库。`,
      });
      setNote("");
      onSubmitted?.();
    } catch (err) {
      setMessage({ type: "error", text: err.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <section className="hero-section" style={{ paddingTop: 6 }}>
        <div className="hero-eyebrow">STRICT PROVENANCE GATE · ZERO UNVERIFIED ENTRIES</div>
        <h1 className="hero-heading">论文实时核验与谱系提交</h1>
        <p className="hero-lead">
          禁止凭记忆手填无依据条目。系统只接受能够从官方学位论文库实时核验的博士论文记录（DOI、HAL/TEL、theses.fr、MIT DSpace
          Handle），自动解析作者、导师、年份与原文链接后进入审核队列。
        </p>
      </section>

      <div className="tabs-bar">
        <button
          className={`tab-btn ${mode === "identifier" ? "active" : ""}`}
          onClick={() => setMode("identifier")}
          id="tab-verify-id"
        >
          按论文编号 / DOI 实时核验
        </button>
        <button
          className={`tab-btn ${mode === "search" ? "active" : ""}`}
          onClick={() => setMode("search")}
          id="tab-live-repo-search"
        >
          实时搜索全球开放论文库并导入
        </button>
      </div>

      {message.text && (
        <div className={`alert-box alert-${message.type === "error" ? "error" : message.type === "success" ? "success" : "info"}`}>
          {message.text}
        </div>
      )}

      {mode === "identifier" ? (
        <section className="surface-card">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleVerify();
            }}
          >
            <label className="form-label" htmlFor="verify-id-input">
              输入官方论文标识（支持 DataCite DOI、HAL ID、theses.fr 编号/URL、MIT DSpace Handle）
            </label>
            <div className="search-row">
              <div className="search-input-wrap">
                <input
                  id="verify-id-input"
                  type="text"
                  className="search-input mono"
                  placeholder="例如：10.5287/ora-2ryxmqqqk 或 tel-05583740 或 1721.1/8641 或 2026LYO10146"
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                />
              </div>
              <button type="submit" className="btn btn-primary" disabled={verifying} id="btn-run-verify">
                {verifying ? "正在请求官方论文库…" : "实时核验 Fetch & Verify"}
              </button>
            </div>
          </form>

          <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: "0.78rem", color: "var(--ink-muted)" }}>真实论文示例一键测试：</span>
            {EXAMPLES.map((ex) => (
              <button
                key={ex.id}
                type="button"
                className="btn btn-sm"
                onClick={() => handleVerify(ex.id)}
              >
                {ex.label}: <span className="mono">{ex.id}</span>
              </button>
            ))}
          </div>

          {candidate && (
            <div className="evidence-box" style={{ marginTop: 22 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span className="badge badge-verified">✓ 官方论文库核验通过</span>
                <span className="badge badge-repo">{candidate.source_repo} · {candidate.source_record_id}</span>
              </div>

              <div className="evidence-title" style={{ marginTop: 10 }}>“{candidate.thesis_title}”</div>
              {candidate.thesis_title_en && (
                <div style={{ fontSize: "0.86rem", color: "var(--ink-secondary)", fontStyle: "italic" }}>
                  EN: {candidate.thesis_title_en}
                </div>
              )}

              <div className="form-grid" style={{ marginTop: 14, fontSize: "0.88rem" }}>
                <div>
                  <strong>博士作者：</strong>{candidate.scholar_name}
                  {candidate.existing_scholar_match && (
                    <div style={{ fontSize: "0.78rem", color: "var(--accent-oxford)", marginTop: 2 }}>
                      已匹配本地库学者：
                      <button
                        type="button"
                        className="link-btn"
                        onClick={() => onSelectScholar(candidate.existing_scholar_match.id)}
                      >
                        {candidate.existing_scholar_match.name} (#{candidate.existing_scholar_match.id})
                      </button>
                    </div>
                  )}
                </div>
                <div>
                  <strong>论文导师：</strong>
                  {(candidate.advisors || []).length > 0 ? candidate.advisors.join("；") : "（缺失）"}
                  {candidate.matched_advisors?.map((ma, i) =>
                    ma.matched ? (
                      <div key={i} style={{ fontSize: "0.78rem", color: "var(--proof-emerald)", marginTop: 2 }}>
                        ✓ 导师「{ma.raw_name}」自动对接已有谱系节点 #{ma.scholar.id}
                      </div>
                    ) : null
                  )}
                </div>
                <div><strong>授予院校：</strong>{candidate.university || "—"} {candidate.country ? `(${candidate.country})` : ""}</div>
                <div><strong>年份与学位：</strong><span className="mono">{candidate.year || "—"}</span> · {candidate.degree}</div>
              </div>

              {candidate.verification_notes?.length > 0 && (
                <ul style={{ margin: "12px 0 0", paddingLeft: 18, fontSize: "0.82rem", color: "var(--ink-secondary)" }}>
                  {candidate.verification_notes.map((n, idx) => (
                    <li key={idx}>{n}</li>
                  ))}
                </ul>
              )}

              <div className="evidence-links">
                <a className="evidence-link-btn" href={candidate.landing_url} target="_blank" rel="noreferrer">
                  打开官方论文页面确认 ↗
                </a>
                {candidate.pdf_url && (
                  <a className="evidence-link-btn" href={candidate.pdf_url} target="_blank" rel="noreferrer">
                    查看论文 PDF ↗
                  </a>
                )}
              </div>

              <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--proof-emerald-border)" }}>
                <label className="form-label" htmlFor="submit-note-input">提交说明（可选，例如补充学科方向或与已有谱系的关联备注）</label>
                <div className="search-row">
                  <div className="search-input-wrap">
                    <input
                      id="submit-note-input"
                      type="text"
                      className="search-input"
                      placeholder="例如：已核对论文扉页导师信息一致"
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                    />
                  </div>
                  <button
                    type="button"
                    className="btn btn-emerald"
                    disabled={submitting || candidate.already_ingested || !candidate.advisors?.length}
                    onClick={() => submitCandidate(candidate)}
                    id="btn-submit-verified-candidate"
                  >
                    {candidate.already_ingested
                      ? "已在数据库中"
                      : submitting
                      ? "提交中…"
                      : "提交至审核队列 →"}
                  </button>
                  <a
                    className="btn"
                    href={buildGitHubSubmissionIssueUrl(candidate)}
                    target="_blank"
                    rel="noreferrer"
                    title="通过 GitHub Issue 提交永久收录请求"
                  >
                    同步提交 GitHub 永久收录 ↗
                  </a>
                </div>
              </div>
            </div>
          )}
        </section>
      ) : (
        <section className="surface-card">
          <form onSubmit={handleLiveSearch}>
            <label className="form-label" htmlFor="live-repo-query">
              跨库实时检索（直接调用 HAL/TEL、theses.fr、MIT DSpace、DataCite 官方接口，自动过滤无导师记录）
            </label>
            <div className="search-row">
              <div className="search-input-wrap">
                <input
                  id="live-repo-query"
                  type="text"
                  className="search-input"
                  placeholder="输入导师姓氏、研究方向或学者姓名（如 Villani、Symplectic、Stochastic、Strang）…"
                  value={liveQuery}
                  onChange={(e) => setLiveQuery(e.target.value)}
                />
              </div>
              <select
                className="filter-select"
                value={liveSource}
                onChange={(e) => setLiveSource(e.target.value)}
              >
                <option value="all">全部 5 个官方库</option>
                <option value="nyu_courant">NYU Courant</option>
                <option value="hal">HAL / TEL</option>
                <option value="theses_fr">theses.fr</option>
                <option value="mit_dspace">MIT DSpace</option>
                <option value="datacite">DataCite (Oxford/Cambridge/LMU)</option>
              </select>
              <button type="submit" className="btn btn-primary" disabled={liveLoading} id="btn-live-repo-search">
                {liveLoading ? "实时查询中…" : "实时检索"}
              </button>
            </div>
          </form>

          {liveResults.length > 0 && (
            <div className="scholar-list" style={{ marginTop: 18 }}>
              {liveResults.map((item, idx) => (
                <div key={`${item.source_repo}-${item.source_record_id}-${idx}`} className="scholar-row-card" style={{ cursor: "default" }}>
                  <div className="scholar-row-top">
                    <div>
                      <h3 className="scholar-name-heading" style={{ fontSize: "1.1rem" }}>
                        {item.scholar_name}
                      </h3>
                      <div className="scholar-meta-line">
                        <span>{item.university || "—"}</span>
                        {item.year && <span className="mono">· {item.year}</span>}
                        <span>· 导师：<strong>{(item.advisors || []).join("、")}</strong></span>
                      </div>
                    </div>
                    <span className="badge badge-repo">{item.source_repo}</span>
                  </div>
                  <div className="scholar-thesis-line">“{item.thesis_title}”</div>
                  <div className="scholar-row-footer">
                    <div style={{ display: "flex", gap: 12 }}>
                      <a href={item.landing_url} target="_blank" rel="noreferrer" style={{ color: "var(--proof-emerald)", fontWeight: 600 }}>
                        官方论文链接 ↗
                      </a>
                      {item.pdf_url && (
                        <a href={item.pdf_url} target="_blank" rel="noreferrer" className="mono">PDF ↗</a>
                      )}
                    </div>
                    <button
                      type="button"
                      className="btn btn-sm btn-emerald"
                      disabled={submitting || item.already_ingested}
                      onClick={() => submitCandidate(item)}
                    >
                      {item.already_ingested ? "已在库中" : "提交审核入库"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
