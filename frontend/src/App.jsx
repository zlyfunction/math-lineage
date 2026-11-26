import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import Header from "./components/Header";
import HomeSearch from "./components/HomeSearch";
import PathFinder from "./components/PathFinder";
import ReviewPipeline from "./components/ReviewPipeline";
import ScholarDetail from "./components/ScholarDetail";
import VerifySubmit from "./components/VerifySubmit";

function parseHash() {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h.startsWith("scholar/")) {
    const id = Number(h.split("/")[1]);
    if (!Number.isNaN(id) && id > 0) return { page: "scholar", id };
  }
  if (h === "path") return { page: "path" };
  if (h === "verify") return { page: "verify" };
  if (h === "review") return { page: "review" };
  return { page: "home" };
}

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const [stats, setStats] = useState(null);
  const [pathInitialFrom, setPathInitialFrom] = useState(null);

  const loadStats = useCallback(async () => {
    try {
      const s = await api.getStats();
      setStats(s);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadStats();
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [loadStats]);

  const navigate = (page, id = null) => {
    if (page === "scholar" && id) {
      window.location.hash = `#/scholar/${id}`;
    } else if (page === "home") {
      window.location.hash = "#/";
    } else {
      window.location.hash = `#/${page}`;
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="app-shell">
      <Header
        route={route}
        onNavigate={(p) => navigate(p)}
        pendingCount={stats?.pending_submissions || 0}
      />

      <main className="main-content">
        <div className="container">
          {route.page === "home" && (
            <HomeSearch
              stats={stats}
              onSelectScholar={(id) => navigate("scholar", id)}
              onNavigate={(p) => navigate(p)}
            />
          )}

          {route.page === "scholar" && (
            <ScholarDetail
              scholarId={route.id}
              onSelectScholar={(id) => navigate("scholar", id)}
              onBack={() => navigate("home")}
              onOpenPathWith={(scholar) => {
                setPathInitialFrom(scholar);
                navigate("path");
              }}
            />
          )}

          {route.page === "path" && (
            <PathFinder
              initialFrom={pathInitialFrom}
              onSelectScholar={(id) => navigate("scholar", id)}
            />
          )}

          {route.page === "verify" && (
            <VerifySubmit
              onSubmitted={loadStats}
              onSelectScholar={(id) => navigate("scholar", id)}
            />
          )}

          {route.page === "review" && (
            <ReviewPipeline
              onDataChanged={loadStats}
              onSelectScholar={(id) => navigate("scholar", id)}
            />
          )}
        </div>
      </main>

      <footer className="site-footer">
        <div className="container footer-inner">
          <div>
            <strong>MathLineage</strong> · Rebuilt Open Mathematics Genealogy — 每条新增记录均强制溯源至公开可检索的官方博士论文。
            {" "}
            <a href="https://github.com/zlyfunction/math-lineage" target="_blank" rel="noreferrer">
              GitHub 开源仓库 ↗
            </a>
          </div>
          <div className="mono" style={{ fontSize: "0.76rem" }}>
            Sources: Wikidata (P549/P184) · NYU Courant · MIT DSpace · HAL/TEL · theses.fr · DataCite
          </div>
        </div>
      </footer>
    </div>
  );
}
