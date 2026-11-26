import React from "react";

export default function Header({ route, onNavigate, pendingCount }) {
  const navItems = [
    { key: "home", label: "Index" },
    { key: "path", label: "Lineage Path" },
    { key: "verify", label: pendingCount > 0 ? `Submit (${pendingCount})` : "Submit" },
  ];

  return (
    <header className="masthead">
      <div className="container masthead-inner">
        <button className="brand-btn" onClick={() => onNavigate("home")} id="nav-brand-home">
          <span className="brand-name">The Mathematics Genealogy</span>
          <span className="brand-tagline">An open academic pedigree grounded in verifiable dissertations</span>
        </button>

        <nav className="nav-bar" aria-label="Primary Navigation">
          {navItems.map((item) => (
            <button
              key={item.key}
              id={`nav-tab-${item.key}`}
              className={`nav-link ${route.page === item.key ? "active" : ""}`}
              onClick={() => onNavigate(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}
