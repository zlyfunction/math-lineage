import React, { useEffect, useState } from "react";
import { api } from "../api";

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
    }, 160);
    return () => {
      active = false;
      clearTimeout(t);
    };
  }, [text, value]);

  return (
    <div className="picker-wrap">
      <label className="picker-label" htmlFor={inputId}>{label}</label>
      <input
        id={inputId}
        type="text"
        className="parchment-input"
        placeholder="Type a mathematician's name…"
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
        <div className="picker-menu">
          {options.map((opt) => (
            <button
              key={opt.id}
              type="button"
              className="picker-item"
              onMouseDown={(e) => {
                e.preventDefault();
                onChange(opt);
                setText(opt.name);
                setOpen(false);
              }}
            >
              <div style={{ fontFamily: "var(--font-heading)", fontWeight: 600, fontSize: "1.06rem" }}>
                {opt.name}
              </div>
              <div style={{ fontSize: "0.8rem", color: "var(--ink-muted)", fontStyle: "italic" }}>
                {opt.university || "Institution unrecorded"}{opt.year ? `, ${opt.year}` : ""}
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
  { label: "Pat Hanrahan ↔ Hermann von Helmholtz", a: "Pat Hanrahan", b: "Hermann Ludwig Ferdinand von Helmholtz" },
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
        setError("Could not locate one of the scholars.");
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
      setError("Please select both scholars from the suggestions.");
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
      <section className="index-hero" style={{ marginBottom: 20 }}>
        <h1 className="index-title">Lineage Path</h1>
        <p className="index-subtitle">
          Trace the shortest chain of doctoral mentorship between any two mathematicians.
        </p>
      </section>

      <section className="parchment-panel">
        <form onSubmit={handleCompute} className="path-grid">
          <ScholarPicker label="From Scholar" value={fromScholar} onChange={setFromScholar} inputId="path-from-input" />
          <div style={{ textAlign: "center", paddingBottom: 10, color: "var(--ink-muted)" }}>↔</div>
          <ScholarPicker label="To Scholar" value={toScholar} onChange={setToScholar} inputId="path-to-input" />
          <button type="submit" className="btn btn-seal" disabled={loading} id="btn-find-path" style={{ height: 43 }}>
            {loading ? "Tracing…" : "Trace"}
          </button>
        </form>

        <div className="notable-line" style={{ marginBottom: 0, marginTop: 14 }}>
          <span style={{ fontStyle: "italic", marginRight: 6 }}>Examples:</span>
          {PRESETS.map((p, i) => (
            <React.Fragment key={p.label}>
              <button type="button" className="notable-name" style={{ fontSize: "0.94rem" }} onClick={() => runPreset(p)} disabled={loading}>
                {p.label}
              </button>
              {i < PRESETS.length - 1 && <span>·</span>}
            </React.Fragment>
          ))}
        </div>

        {error && <div className="notice notice-err">{error}</div>}
      </section>

      {result && (
        <section className="lineage-scroll">
          {!result.found ? (
            <div className="parchment-panel" style={{ textAlign: "center", fontStyle: "italic", color: "var(--ink-muted)" }}>
              No recorded academic connection between {fromScholar?.name} and {toScholar?.name}.
            </div>
          ) : (
            <div>
              <div className="ornament-rule">
                <span>{result.distance} {result.distance === 1 ? "generation" : "generations"}</span>
              </div>

              {result.nodes.map((node, idx) => {
                const step = result.steps[idx];
                return (
                  <React.Fragment key={node.id}>
                    <div className="scroll-step-node">
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                        <button
                          className="text-link-btn"
                          style={{ fontFamily: "var(--font-heading)", fontSize: "1.24rem", fontWeight: 600 }}
                          onClick={() => onSelectScholar(node.id)}
                        >
                          {node.name}
                        </button>
                        <span style={{ fontSize: "0.88rem", color: "var(--ink-muted)" }}>
                          {node.university || ""}{node.year ? `, ${node.year}` : ""}
                        </span>
                      </div>
                      {node.thesis_title && (
                        <div style={{ fontStyle: "italic", fontSize: "0.9rem", color: "var(--ink-muted)", marginTop: 2 }}>
                          “{node.thesis_title}”
                        </div>
                      )}
                    </div>

                    {step && (
                      <div className={`scroll-step-link ${step.source_type === "dissertation_verified" ? "verified" : ""}`}>
                        <span>
                          {step.relation === "advised" ? "↓ advised" : "↑ advised by"}
                        </span>
                        {step.dissertation?.landing_url ? (
                          <a href={step.dissertation.landing_url} target="_blank" rel="noreferrer" className="verified-mark">
                            ✦ Thesis ({step.dissertation.source_repo}) ↗
                          </a>
                        ) : (
                          <span>(MGP Record)</span>
                        )}
                      </div>
                    )}
                  </React.Fragment>
                );
              })}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
