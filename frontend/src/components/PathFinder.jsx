import React, { useEffect, useState } from "react";
import { api } from "../api";
import { VerificationBadge } from "./Header";

function ScholarPicker({ label, value, onChange, inputId }) {
  const [text, setText] = useState(value ? value.name : "");
  const [options, setOptions] = useState([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (value) setText(value.name);
  }, [value]);

  useEffect(() => {
    if (!text.trim() || (value && text === value.name)) {
      setOptions([]);
      return;
    }
    let active = true;
    const t = setTimeout(async () => {
      try {
        const res = await api.autocomplete(text);
        if (active) setOptions(res);
      } catch {
        // ignore
      }
    }, 180);
    return () => {
      active = false;
      clearTimeout(t);
    };
  }, [text, value]);

  return (
    <div className="autocomplete-wrap">
      <label className="form-label" htmlFor={inputId}>{label}</label>
      <input
        id={inputId}
        type="text"
        className="search-input"
        placeholder="输入数学家姓名搜索（如 Gauss、Hilbert、Euler）…"
        value={text}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 180)}
        onChange={(e) => {
          setText(e.target.value);
          onChange(null);
          setOpen(true);
        }}
      />
      {open && options.length > 0 && (
        <div className="autocomplete-dropdown">
          {options.map((opt) => (
            <button
              key={opt.id}
              type="button"
              className="autocomplete-item"
              onMouseDown={(e) => {
                e.preventDefault();
                onChange(opt);
                setText(opt.name);
                setOpen(false);
              }}
            >
              <div style={{ fontWeight: 600, fontFamily: "var(--font-serif)" }}>
                {opt.name} {opt.name_zh ? <span style={{ color: "var(--ink-muted)", fontWeight: 400 }}>{opt.name_zh}</span> : null}
              </div>
              <div style={{ fontSize: "0.76rem", color: "var(--ink-muted)" }}>
                {opt.university || "—"} {opt.year ? `· ${opt.year}` : ""}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const PRESETS = [
  { label: "Leyi Zhu ↔ Carl Friedrich Gauss", a: "Leyi Zhu", b: "Carl Friedrich Gauss" },
  { label: "Leyi Zhu ↔ David Hilbert", a: "Leyi Zhu", b: "David Hilbert" },
  { label: "Leyi Zhu ↔ Pat Hanrahan", a: "Leyi Zhu", b: "Pat Hanrahan" },
  { label: "Carl Friedrich Gauss ↔ David Hilbert", a: "Carl Friedrich Gauss", b: "David Hilbert" },
];

export default function PathFinder({ initialFrom, onSelectScholar }) {
  const [fromScholar, setFromScholar] = useState(initialFrom || null);
  const [toScholar, setToScholar] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (initialFrom) setFromScholar(initialFrom);
  }, [initialFrom]);

  const runPreset = async (preset) => {
    setLoading(true);
    setError("");
    try {
      const [ra, rb] = await Promise.all([api.autocomplete(preset.a), api.autocomplete(preset.b)]);
      const a = ra[0];
      const b = rb[0];
      if (!a || !b) {
        setError("预设学者未在当前库中匹配到。");
        return;
      }
      setFromScholar(a);
      setToScholar(b);
      const data = await api.findPath(a.id, b.id);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleCompute = async (e) => {
    e.preventDefault();
    if (!fromScholar || !toScholar) {
      setError("请从下拉列表中分别选择起点与终点两位学者。");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await api.findPath(fromScholar.id, toScholar.id);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <section className="hero-section" style={{ paddingTop: 6 }}>
        <div className="hero-eyebrow">SHORTEST ACADEMIC LINEAGE · BFS GRAPH TRAVERSAL</div>
        <h1 className="hero-heading">任意两位数学家的最短学术路径</h1>
        <p className="hero-lead">
          沿博士师承关系（导师 ↔ 学生）计算两位数学家之间的最短学术连接路径，并标注每一步师承关系是否具有可核验的官方博士论文依据。
        </p>
      </section>

      <section className="surface-card">
        <form onSubmit={handleCompute} className="path-inputs-grid">
          <ScholarPicker
            label="起点学者 · Scholar A"
            value={fromScholar}
            onChange={setFromScholar}
            inputId="path-from-input"
          />
          <div style={{ paddingBottom: 12, textAlign: "center", color: "var(--ink-muted)", fontWeight: 600 }}>↔</div>
          <ScholarPicker
            label="终点学者 · Scholar B"
            value={toScholar}
            onChange={setToScholar}
            inputId="path-to-input"
          />
          <button type="submit" className="btn btn-primary" disabled={loading} id="btn-find-path" style={{ height: 46 }}>
            {loading ? "计算中…" : "计算最短路径"}
          </button>
        </form>

        <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <span style={{ fontSize: "0.78rem", color: "var(--ink-muted)" }}>一键经典学术路径示例：</span>
          {PRESETS.map((p) => (
            <button key={p.label} type="button" className="btn btn-sm" onClick={() => runPreset(p)} disabled={loading}>
              {p.label}
            </button>
          ))}
        </div>

        {error && <div className="alert-box alert-error" style={{ marginTop: 14, marginBottom: 0 }}>{error}</div>}
      </section>

      {result && (
        <section style={{ marginTop: 22 }}>
          {!result.found ? (
            <div className="surface-card" style={{ textAlign: "center", padding: 36, color: "var(--ink-secondary)" }}>
              在当前已收录的师承图中，<strong>{fromScholar?.name}</strong> 与 <strong>{toScholar?.name}</strong> 之间尚未连通。
              <div style={{ marginTop: 8, fontSize: "0.84rem", color: "var(--ink-muted)" }}>
                你可以在「论文核验录入」中补充中间代际的官方博士论文，让两个分支自然相连。
              </div>
            </div>
          ) : (
            <div>
              <div className="alert-box alert-success">
                已找到最短学术路径：共 <strong>{result.distance}</strong> 步师承连接（经过 {result.nodes.length} 位学者）。
              </div>

              <div className="path-chain">
                {result.nodes.map((node, idx) => {
                  const step = result.steps[idx];
                  return (
                    <React.Fragment key={node.id}>
                      <div className="path-node-card">
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                          <div>
                            <button
                              className="link-btn"
                              style={{ fontFamily: "var(--font-serif)", fontSize: "1.18rem", fontWeight: 600 }}
                              onClick={() => onSelectScholar(node.id)}
                            >
                              {idx + 1}. {node.name}
                            </button>
                            {node.name_zh && (
                              <span style={{ marginLeft: 8, color: "var(--ink-muted)", fontSize: "0.9rem" }}>{node.name_zh}</span>
                            )}
                          </div>
                          <VerificationBadge status={node.verification_status} />
                        </div>
                        <div style={{ fontSize: "0.84rem", color: "var(--ink-secondary)", marginTop: 4 }}>
                          {node.university || "Institution n/a"} {node.year ? `· ${node.year}` : ""}
                          {node.thesis_title ? ` — “${node.thesis_title}”` : ""}
                        </div>
                      </div>

                      {step && (
                        <div className={`path-edge-connector ${step.source_type === "dissertation_verified" ? "verified" : ""}`}>
                          <span style={{ fontWeight: 600 }}>
                            {step.relation === "advised" ? "↓ 指导博士生 (advised)" : "↑ 师从博士导师 (advised by)"}
                          </span>
                          <span className={`badge ${step.source_type === "dissertation_verified" ? "badge-verified" : "badge-historical"}`}>
                            {step.source_type === "dissertation_verified" ? "✓ 官方论文实证" : "Wikidata P184"}
                          </span>
                          {step.dissertation?.landing_url && (
                            <a href={step.dissertation.landing_url} target="_blank" rel="noreferrer">
                              查看论文依据 ({step.dissertation.source_repo}) ↗
                            </a>
                          )}
                        </div>
                      )}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
