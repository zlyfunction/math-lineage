import React, { useEffect, useState } from "react";
import { api } from "../api";

export default function ReviewPipeline({ onDataChanged, onSelectScholar }) {
  const [tab, setTab] = useState("queue"); // 'queue' | 'harvester'
  const [submissions, setSubmissions] = useState([]);
  const [harvestRuns, setHarvestRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState(null);
  const [notice, setNotice] = useState({ type: "", text: "" });

  // Live Harvester form state
  const [source, setSource] = useState("theses_fr");
  const [harvestQuery, setHarvestQuery] = useState("");
  const [harvestLimit, setHarvestLimit] = useState(25);
  const [harvesting, setHarvesting] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [subs, runs] = await Promise.all([
        api.listSubmissions("all"),
        api.listHarvestRuns(),
      ]);
      setSubmissions(subs);
      setHarvestRuns(runs);
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const handleReview = async (id, action) => {
    setActionBusy(id);
    setNotice({ type: "", text: "" });
    try {
      const res = await api.reviewSubmission(id, action, action === "approve" ? "Verified against official thesis repository" : "Rejected during review");
      setNotice({
        type: "success",
        text:
          action === "approve"
            ? `提交 #${id} 已批准并正式写入数学谱系数据库（学者 ID #${res.scholar_id}）！`
            : `提交 #${id} 已驳回。`,
      });
      await loadAll();
      onDataChanged?.();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    } finally {
      setActionBusy(null);
    }
  };

  const handleRunHarvest = async (e) => {
    e.preventDefault();
    setHarvesting(true);
    setNotice({ type: "", text: "" });
    try {
      const res = await api.triggerHarvest(source, harvestQuery, Number(harvestLimit));
      setNotice({
        type: "success",
        text: `实时采集完成（${res.source_repo}）：抓取 ${res.fetched_count} 篇论文，新增学者 ${res.added_scholars} 人、新增论文实证 ${res.added_dissertations} 篇、新增师承关系 ${res.added_edges} 条。`,
      });
      await loadAll();
      onDataChanged?.();
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    } finally {
      setHarvesting(false);
    }
  };

  const pendingCount = submissions.filter((s) => s.status === "pending").length;

  return (
    <div>
      <section className="hero-section" style={{ paddingTop: 6 }}>
        <div className="hero-eyebrow">DATA GOVERNANCE · AUDITABLE INGESTION PIPELINE</div>
        <h1 className="hero-heading">论文提交审核与自动采集管线</h1>
        <p className="hero-lead">
          所有用户通过论文核验提交的条目都在此经过原文复核后方可写入正式图谱；你也可以随时按关键词触发官方开放学位论文库的增量抓取，并审计每一次入库日志。
        </p>
      </section>

      <div className="tabs-bar">
        <button
          className={`tab-btn ${tab === "queue" ? "active" : ""}`}
          onClick={() => setTab("queue")}
          id="tab-review-queue"
        >
          待审核提交队列 · Submissions ({pendingCount} 待审)
        </button>
        <button
          className={`tab-btn ${tab === "harvester" ? "active" : ""}`}
          onClick={() => setTab("harvester")}
          id="tab-live-harvester"
        >
          官方论文库实时采集与审计日志 · Harvester ({harvestRuns.length})
        </button>
      </div>

      {notice.text && (
        <div className={`alert-box alert-${notice.type === "error" ? "error" : "success"}`}>
          {notice.text}
        </div>
      )}

      {tab === "queue" ? (
        <section>
          {loading ? (
            <div className="surface-card" style={{ padding: 40, textAlign: "center", color: "var(--ink-muted)" }}>加载中…</div>
          ) : submissions.length === 0 ? (
            <div className="surface-card" style={{ padding: 40, textAlign: "center", color: "var(--ink-muted)" }}>
              当前暂无提交记录。你可以前往「论文核验录入」核验一篇真实博士论文后提交至此审核。
            </div>
          ) : (
            <div className="scholar-list">
              {submissions.map((sub) => (
                <article key={sub.id} className="surface-card">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
                    <div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <span className="mono" style={{ fontSize: "0.78rem", color: "var(--ink-muted)" }}>#{sub.id}</span>
                        <span
                          className={`badge ${
                            sub.status === "approved"
                              ? "badge-verified"
                              : sub.status === "pending"
                              ? "badge-historical"
                              : "badge-inferred"
                          }`}
                        >
                          {sub.status === "pending" ? "待审核 Pending" : sub.status === "approved" ? "✓ 已批准入库" : "已驳回 Rejected"}
                        </span>
                        <span className="badge badge-repo">{sub.source_repo} · {sub.source_record_id}</span>
                      </div>
                      <h3 className="scholar-name-heading" style={{ marginTop: 8 }}>
                        {sub.scholar_name}
                      </h3>
                      <div className="scholar-meta-line">
                        <span>{sub.university || "—"}</span>
                        {sub.year && <span className="mono">· {sub.year}</span>}
                        <span>· 导师：<strong>{(sub.advisors || []).join("；")}</strong></span>
                      </div>
                    </div>

                    {sub.status === "pending" ? (
                      <div style={{ display: "flex", gap: 8 }}>
                        <button
                          className="btn btn-sm btn-emerald"
                          disabled={actionBusy === sub.id}
                          onClick={() => handleReview(sub.id, "approve")}
                          id={`btn-approve-${sub.id}`}
                        >
                          ✓ 批准写入图谱
                        </button>
                        <button
                          className="btn btn-sm btn-danger"
                          disabled={actionBusy === sub.id}
                          onClick={() => handleReview(sub.id, "reject")}
                          id={`btn-reject-${sub.id}`}
                        >
                          驳回
                        </button>
                      </div>
                    ) : sub.matched_scholar_id ? (
                      <button
                        className="btn btn-sm"
                        onClick={() => onSelectScholar(sub.matched_scholar_id)}
                      >
                        查看已入库学者 #{sub.matched_scholar_id} →
                      </button>
                    ) : null}
                  </div>

                  <div className="scholar-thesis-line" style={{ marginTop: 10 }}>
                    “{sub.thesis_title}”
                  </div>

                  <div className="scholar-row-footer">
                    <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                      <a href={sub.landing_url} target="_blank" rel="noreferrer" style={{ color: "var(--proof-emerald)", fontWeight: 600 }}>
                        核对官方论文原文 ↗
                      </a>
                      {sub.pdf_url && (
                        <a href={sub.pdf_url} target="_blank" rel="noreferrer" className="mono">PDF ↗</a>
                      )}
                      {sub.submitter_note && <span>备注：{sub.submitter_note}</span>}
                    </div>
                    <span className="mono" style={{ fontSize: "0.75rem", color: "var(--ink-muted)" }}>
                      提交于 {sub.created_at}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <section className="surface-card">
            <h2 className="card-heading">触发实时论文库增量采集 · Live Repository Harvest</h2>
            <p style={{ margin: "0 0 14px", fontSize: "0.88rem", color: "var(--ink-secondary)" }}>
              仅采集同时包含「有效论文原文 URL/DOI + 明确博士导师字段」的数学博士论文；缺少导师字段的记录将被严格跳过。
            </p>
            <form onSubmit={handleRunHarvest} className="search-row">
              <select className="filter-select" value={source} onChange={(e) => setSource(e.target.value)} id="harvest-source-select">
                <option value="nyu_courant">NYU Courant (纽约大学库朗所官方 Ph.D. 论文库 + PDF 核验)</option>
                <option value="theses_fr">theses.fr (法国 ABES 官方博士论文注册库)</option>
                <option value="hal">HAL / TEL (法国/欧洲开放学位论文 + PDF)</option>
                <option value="mit_dspace">MIT DSpace (麻省理工数学系 Ph.D.)</option>
                <option value="datacite">DataCite (Oxford / Cambridge / LMU / ETH)</option>
              </select>
              <div className="search-input-wrap">
                <input
                  type="text"
                  className="search-input"
                  placeholder="可选主题或导师关键词（如 algebra、PDE、geometry，留空则采集最新数学博士论文）"
                  value={harvestQuery}
                  onChange={(e) => setHarvestQuery(e.target.value)}
                />
              </div>
              <input
                type="number"
                className="filter-num"
                min={5}
                max={80}
                value={harvestLimit}
                onChange={(e) => setHarvestLimit(e.target.value)}
                title="抓取上限"
              />
              <button type="submit" className="btn btn-primary" disabled={harvesting} id="btn-trigger-harvest">
                {harvesting ? "正在实时抓取与核验…" : "开始采集 Harvest"}
              </button>
              <a
                className="btn"
                href="https://github.com/zlyfunction/math-lineage/actions"
                target="_blank"
                rel="noreferrer"
              >
                GitHub Actions 自动采集 ↗
              </a>
            </form>
          </section>

          <section className="surface-card">
            <h2 className="card-heading">采集审计日志 · Harvest Audit Log</h2>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>官方数据源</th>
                    <th>查询范围</th>
                    <th>抓取数</th>
                    <th>新增学者</th>
                    <th>新增论文实证</th>
                    <th>新增师承边</th>
                    <th>状态与时间</th>
                  </tr>
                </thead>
                <tbody>
                  {harvestRuns.map((r) => (
                    <tr key={r.id}>
                      <td className="mono">#{r.id}</td>
                      <td><span className="badge badge-repo">{r.source_repo}</span></td>
                      <td style={{ maxWidth: 240, fontSize: "0.82rem" }}>{r.query || "—"}</td>
                      <td className="mono">{r.fetched_count}</td>
                      <td className="mono">+{r.added_scholars}</td>
                      <td className="mono" style={{ color: "var(--proof-emerald)", fontWeight: 600 }}>+{r.added_dissertations}</td>
                      <td className="mono">+{r.added_edges}</td>
                      <td className="mono" style={{ fontSize: "0.76rem", color: r.status === "completed" ? "var(--proof-emerald)" : "var(--danger-crimson)" }}>
                        {r.status} · {r.finished_at}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
