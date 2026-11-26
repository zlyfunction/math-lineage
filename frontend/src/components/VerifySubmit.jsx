import React, { useEffect, useState } from "react";
import { api } from "../api";
import { buildGitHubSubmissionIssueUrl } from "../localEngine";

const EXAMPLES = [
  { label: "Oxford DOI", id: "10.5287/ora-2ryxmqqqk" },
  { label: "HAL Thesis", id: "tel-05583740" },
  { label: "theses.fr", id: "2026LYO10146" },
];

export default function VerifySubmit({ onSubmitted, onSelectScholar }) {
  const [identifier, setIdentifier] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [candidate, setCandidate] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });
  const [submissions, setSubmissions] = useState([]);
  const [showQueue, setShowQueue] = useState(false);

  const loadQueue = async () => {
    try {
      const list = await api.listSubmissions("all");
      setSubmissions(list);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadQueue();
  }, []);

  const handleVerify = async (override) => {
    const target = (override ?? identifier).trim();
    if (!target) return;
    if (override) setIdentifier(override);
    setVerifying(true);
    setMessage({ type: "", text: "" });
    setCandidate(null);
    try {
      const res = await api.verifyDissertation(target);
      setCandidate(res);
    } catch (err) {
      setMessage({ type: "err", text: err.message });
    } finally {
      setVerifying(false);
    }
  };

  const handleSubmit = async () => {
    if (!candidate) return;
    if (!candidate.advisors?.length) {
      setMessage({ type: "err", text: "Official record lacks an advisor field and cannot be admitted." });
      return;
    }
    setSubmitting(true);
    setMessage({ type: "", text: "" });
    try {
      const created = await api.createSubmission({
        scholar_name: candidate.scholar_name,
        advisors: candidate.advisors,
        university: candidate.university || "",
        country: candidate.country || "",
        degree: candidate.degree || "Ph.D.",
        year: candidate.year || null,
        thesis_title: candidate.thesis_title,
        thesis_title_en: candidate.thesis_title_en || "",
        source_repo: candidate.source_repo,
        source_record_id: candidate.source_record_id,
        doi: candidate.doi || "",
        landing_url: candidate.landing_url,
        pdf_url: candidate.pdf_url || "",
        raw_metadata_json: JSON.stringify(candidate.raw_metadata || {}),
        submitter_note: "",
      });
      setMessage({
        type: "ok",
        text: `Added ${created.scholar_name} to the pending review list below.`,
      });
      setShowQueue(true);
      await loadQueue();
      onSubmitted?.();
    } catch (err) {
      setMessage({ type: "err", text: err.message });
    } finally {
      setSubmitting(false);
    }
  };

  const handleReview = async (id, action) => {
    try {
      const res = await api.reviewSubmission(id, action, "Verified against official thesis");
      setMessage({
        type: "ok",
        text: action === "approve" ? `Approved and added to the genealogy (#${res.scholar_id}).` : "Submission rejected.",
      });
      await loadQueue();
      onSubmitted?.();
    } catch (err) {
      setMessage({ type: "err", text: err.message });
    }
  };

  const pendingCount = submissions.filter((s) => s.status === "pending").length;

  return (
    <div style={{ maxWidth: 760, margin: "0 auto" }}>
      <section className="index-hero" style={{ marginBottom: 20 }}>
        <h1 className="index-title">Submit a Verified Dissertation</h1>
        <p className="index-subtitle">
          Every new entry is verified directly against an official dissertation record (DOI, HAL, theses.fr, MIT Handle, or thesis PDF).
        </p>
      </section>

      <section className="parchment-panel">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleVerify();
          }}
        >
          <label className="picker-label" htmlFor="verify-id-input">
            Official Dissertation Identifier or URL
          </label>
          <div className="search-box-row">
            <input
              id="verify-id-input"
              type="text"
              className="parchment-input"
              placeholder="e.g. 10.5287/ora-2ryxmqqqk, tel-05583740, or 2026LYO10146"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
            />
            <button type="submit" className="btn btn-seal" disabled={verifying} id="btn-run-verify">
              {verifying ? "Checking…" : "Verify"}
            </button>
          </div>
        </form>

        <div className="notable-line" style={{ marginTop: 12, marginBottom: 0 }}>
          <span style={{ fontStyle: "italic", marginRight: 6 }}>Try:</span>
          {EXAMPLES.map((ex, i) => (
            <React.Fragment key={ex.id}>
              <button type="button" className="notable-name" style={{ fontSize: "0.92rem" }} onClick={() => handleVerify(ex.id)}>
                {ex.label} ({ex.id})
              </button>
              {i < EXAMPLES.length - 1 && <span>·</span>}
            </React.Fragment>
          ))}
        </div>

        {message.text && (
          <div className={`notice notice-${message.type === "err" ? "err" : "ok"}`}>{message.text}</div>
        )}

        {candidate && (
          <div style={{ marginTop: 20, paddingTop: 18, borderTop: "1px solid var(--rule-strong)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
              <h2 style={{ fontFamily: "var(--font-heading)", fontSize: "1.45rem", margin: 0 }}>
                {candidate.scholar_name}
              </h2>
              <span className="verified-mark">✦ {candidate.source_repo}</span>
            </div>

            <div style={{ fontSize: "0.94rem", color: "var(--ink-muted)", marginTop: 4 }}>
              {candidate.degree || "Ph.D."}
              {candidate.university ? ` · ${candidate.university}` : ""}
              {candidate.year ? `, ${candidate.year}` : ""}
            </div>

            <div style={{ fontStyle: "italic", fontSize: "1.02rem", margin: "8px 0" }}>
              “{candidate.thesis_title}”
            </div>

            <div style={{ fontSize: "0.94rem", marginBottom: 12 }}>
              <strong>Advisor(s):</strong>{" "}
              {candidate.advisors?.length ? candidate.advisors.join(", ") : "None listed in metadata"}
            </div>

            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <a href={candidate.landing_url} target="_blank" rel="noreferrer" className="btn btn-xs">
                Inspect Thesis ↗
              </a>
              <button
                type="button"
                className="btn btn-xs btn-verdigris"
                disabled={submitting || candidate.already_ingested || !candidate.advisors?.length}
                onClick={handleSubmit}
                id="btn-submit-verified-candidate"
              >
                {candidate.already_ingested ? "Already Recorded" : submitting ? "Submitting…" : "Add to Queue"}
              </button>
              <a
                href={buildGitHubSubmissionIssueUrl(candidate)}
                target="_blank"
                rel="noreferrer"
                className="btn btn-xs"
              >
                Submit via GitHub ↗
              </a>
            </div>
          </div>
        )}
      </section>

      {submissions.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <button
            className="text-link-btn"
            style={{ fontFamily: "var(--font-display)", fontSize: "0.76rem", letterSpacing: "0.1em", textTransform: "uppercase" }}
            onClick={() => setShowQueue((v) => !v)}
          >
            {showQueue ? "▾" : "▸"} Review Queue ({pendingCount} pending / {submissions.length} total)
          </button>

          {showQueue && (
            <div className="parchment-panel" style={{ marginTop: 10 }}>
              {submissions.map((sub) => (
                <div key={sub.id} className="advisor-row">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                    <strong style={{ fontFamily: "var(--font-heading)", fontSize: "1.15rem" }}>
                      {sub.scholar_name}
                    </strong>
                    {sub.status === "pending" ? (
                      <div style={{ display: "flex", gap: 8 }}>
                        <button className="btn btn-xs btn-verdigris" onClick={() => handleReview(sub.id, "approve")}>
                          Approve
                        </button>
                        <button className="btn btn-xs" onClick={() => handleReview(sub.id, "reject")}>
                          Reject
                        </button>
                      </div>
                    ) : sub.matched_scholar_id ? (
                      <button className="text-link-btn" onClick={() => onSelectScholar(sub.matched_scholar_id)}>
                        View Entry →
                      </button>
                    ) : (
                      <span style={{ fontSize: "0.82rem", color: "var(--ink-muted)", fontStyle: "italic" }}>{sub.status}</span>
                    )}
                  </div>
                  <div style={{ fontStyle: "italic", fontSize: "0.9rem", color: "var(--ink-muted)" }}>
                    “{sub.thesis_title}” · Advisor(s): {(sub.advisors || []).join(", ")} ·{" "}
                    <a href={sub.landing_url} target="_blank" rel="noreferrer">Source ↗</a>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
