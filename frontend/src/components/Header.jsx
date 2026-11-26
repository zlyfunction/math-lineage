import React from "react";

export function VerificationBadge({ status, repo }) {
  if (status === "verified_dissertation") {
    return (
      <span className="badge badge-verified" title="Backed by an official, verifiable doctoral dissertation record">
        ✓ 论文已核验{repo ? ` · ${repo}` : ""}
      </span>
    );
  }
  if (status === "historical_wikidata") {
    return (
      <span className="badge badge-historical" title="Historical lineage synced from Mathematics Genealogy Project & Wikidata">
        MGP / Wikidata 历史谱系
      </span>
    );
  }
  return (
    <span className="badge badge-inferred" title="Advisor referenced in a verified student dissertation">
      导师节点 · 论文溯源关联
    </span>
  );
}

export default function Header({ route, onNavigate, pendingCount }) {
  const navItems = [
    { key: "home", label: "学者检索 · Directory" },
    { key: "path", label: "学术路径 · Path Finder" },
    { key: "verify", label: "论文核验录入 · Verify & Submit" },
    { key: "review", label: "审核与采集管线 · Pipeline", badge: pendingCount },
  ];

  return (
    <header className="site-header">
      <div className="container header-inner">
        <button className="brand-mark" onClick={() => onNavigate("home")} id="nav-brand-home">
          <span className="brand-title">MathLineage</span>
          <span className="brand-subtitle">可核验数学学术谱系 · Verifiable MGP</span>
        </button>

        <nav className="nav-links" aria-label="Primary Navigation">
          {navItems.map((item) => (
            <button
              key={item.key}
              id={`nav-tab-${item.key}`}
              className={`nav-btn ${route.page === item.key ? "active" : ""}`}
              onClick={() => onNavigate(item.key)}
            >
              <span>{item.label}</span>
              {item.badge > 0 && <span className="nav-badge">{item.badge}</span>}
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}
