import React, { useEffect, useMemo, useRef, useState } from "react";

/**
 * Interactive layered SVG Genealogy Graph (Ancestors above, Focus centered, Descendants below).
 * Supports smooth pan, mouse-wheel zoom, zoom controls, node hover highlight, and click-to-navigate.
 */
export default function GenealogyGraph({ graph, onSelectScholar, ancestorDepth, descendantDepth, onDepthChange }) {
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [dragging, setDragging] = useState(false);
  const [hoveredId, setHoveredId] = useState(null);
  const dragStart = useRef({ x: 0, y: 0, tx: 0, ty: 0 });
  const containerRef = useRef(null);
  const svgRef = useRef(null);

  const handleExportSvg = () => {
    if (!svgRef.current) return;
    const serializer = new XMLSerializer();
    const raw = serializer.serializeToString(svgRef.current);
    const blob = new Blob([raw], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mathlineage-graph-${graph?.focus_id || "tree"}.svg`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const layout = useMemo(() => {
    if (!graph || !graph.nodes || graph.nodes.length === 0) {
      return { nodes: [], edges: [], width: 900, height: 480, focusPos: { x: 450, y: 240 } };
    }

    const byLevel = new Map();
    for (const n of graph.nodes) {
      if (!byLevel.has(n.level)) byLevel.set(n.level, []);
      byLevel.get(n.level).push(n);
    }

    const sortedLevels = Array.from(byLevel.keys()).sort((a, b) => a - b);
    const nodeW = 196;
    const nodeH = 62;
    const gapX = 28;
    const gapY = 92;

    // Sort within each level by year then name for clean, stable ordering
    let maxRowWidth = 0;
    for (const lvl of sortedLevels) {
      const arr = byLevel.get(lvl);
      arr.sort((a, b) => {
        if (a.is_focus) return -1;
        if (b.is_focus) return 1;
        return (a.year || 9999) - (b.year || 9999) || a.name.localeCompare(b.name);
      });
      const rowW = arr.length * (nodeW + gapX) - gapX;
      if (rowW > maxRowWidth) maxRowWidth = rowW;
    }

    const canvasW = Math.max(920, maxRowWidth + 120);
    const canvasH = Math.max(460, sortedLevels.length * (nodeH + gapY) + 100);
    const posMap = new Map();

    sortedLevels.forEach((lvl, rowIdx) => {
      const arr = byLevel.get(lvl);
      const rowW = arr.length * (nodeW + gapX) - gapX;
      const startX = (canvasW - rowW) / 2;
      const y = 52 + rowIdx * (nodeH + gapY);
      arr.forEach((n, i) => {
        const x = startX + i * (nodeW + gapX);
        posMap.set(n.id, { ...n, x, y, w: nodeW, h: nodeH, cx: x + nodeW / 2, cy: y + nodeH / 2 });
      });
    });

    const positionedNodes = Array.from(posMap.values());
    const positionedEdges = (graph.edges || [])
      .map((e) => {
        const src = posMap.get(e.source);
        const tgt = posMap.get(e.target);
        if (!src || !tgt) return null;
        return { ...e, src, tgt };
      })
      .filter(Boolean);

    const focusNode = posMap.get(graph.focus_id) || positionedNodes[0];
    return {
      nodes: positionedNodes,
      edges: positionedEdges,
      width: canvasW,
      height: canvasH,
      focusPos: focusNode ? { x: focusNode.cx, y: focusNode.cy } : { x: canvasW / 2, y: canvasH / 2 },
    };
  }, [graph]);

  // Center graph on focus scholar whenever graph changes
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !layout.focusPos) return;
    const vw = el.clientWidth || 900;
    const vh = el.clientHeight || 490;
    const k = layout.nodes.length > 20 ? 0.85 : 0.96;
    setTransform({
      x: vw / 2 - layout.focusPos.x * k,
      y: vh / 2 - layout.focusPos.y * k,
      k,
    });
  }, [layout]);

  const handleMouseDown = (e) => {
    if (e.target.closest("[data-node-id]")) return;
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, tx: transform.x, ty: transform.y };
  };

  const handleMouseMove = (e) => {
    if (!dragging) return;
    setTransform((prev) => ({
      ...prev,
      x: dragStart.current.tx + (e.clientX - dragStart.current.x),
      y: dragStart.current.ty + (e.clientY - dragStart.current.y),
    }));
  };

  const handleMouseUp = () => setDragging(false);

  const handleWheel = (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.91;
    setTransform((prev) => {
      const nextK = Math.max(0.35, Math.min(2.2, prev.k * factor));
      const rect = containerRef.current.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      return {
        k: nextK,
        x: mx - ((mx - prev.x) * nextK) / prev.k,
        y: my - ((my - prev.y) * nextK) / prev.k,
      };
    });
  };

  const resetView = () => {
    const el = containerRef.current;
    const vw = el?.clientWidth || 900;
    const vh = el?.clientHeight || 490;
    setTransform({
      x: vw / 2 - layout.focusPos.x * 0.92,
      y: vh / 2 - layout.focusPos.y * 0.92,
      k: 0.92,
    });
  };

  const getNodeStyle = (n) => {
    if (n.is_focus) {
      return { fill: "#1B4965", stroke: "#13354A", text: "#FFFFFF", sub: "#D5E6F0" };
    }
    if (n.verification_status === "verified_dissertation") {
      return { fill: "#F1F9F5", stroke: "#1E6B52", text: "#18191C", sub: "#1E6B52" };
    }
    if (n.verification_status === "historical_wikidata") {
      return { fill: "#FFFBF2", stroke: "#C98D3B", text: "#18191C", sub: "#6E5734" };
    }
    return { fill: "#FFFFFF", stroke: "#C5BEB1", text: "#18191C", sub: "#5A5E66" };
  };

  const truncate = (str, n) => (str && str.length > n ? str.slice(0, n - 1) + "…" : str || "");

  return (
    <section className="graph-card" aria-label="Interactive Academic Genealogy Graph">
      <div className="graph-toolbar">
        <div>
          <strong style={{ fontFamily: "var(--font-serif)", fontSize: "1.06rem" }}>
            交互式学术师承图谱 · Lineage Graph
          </strong>
          <div className="graph-legend" style={{ marginTop: 4 }}>
            <span>
              <span className="legend-dot" style={{ background: "#1B4965" }} />
              当前学者 Focus
            </span>
            <span>
              <span className="legend-dot" style={{ background: "#1E6B52" }} />
              论文直链核验 Verified
            </span>
            <span>
              <span className="legend-dot" style={{ background: "#C98D3B" }} />
              历史谱系 Wikidata
            </span>
            <span>
              <span className="legend-dot" style={{ background: "#A39B8F" }} />
              导师关联节点
            </span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <label style={{ fontSize: "0.78rem", color: "var(--ink-secondary)" }}>
            上溯
            <select
              className="filter-select"
              style={{ marginLeft: 4, padding: "4px 7px" }}
              value={ancestorDepth}
              onChange={(e) => onDepthChange(Number(e.target.value), descendantDepth)}
            >
              {[2, 4, 6, 8, 12].map((d) => (
                <option key={d} value={d}>{d} 代</option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: "0.78rem", color: "var(--ink-secondary)" }}>
            下延
            <select
              className="filter-select"
              style={{ marginLeft: 4, padding: "4px 7px" }}
              value={descendantDepth}
              onChange={(e) => onDepthChange(ancestorDepth, Number(e.target.value))}
            >
              {[1, 2, 3, 4].map((d) => (
                <option key={d} value={d}>{d} 代</option>
              ))}
            </select>
          </label>
          <button className="btn btn-sm" onClick={() => setTransform((p) => ({ ...p, k: Math.min(2.2, p.k * 1.18) }))}>
            ＋
          </button>
          <button className="btn btn-sm" onClick={() => setTransform((p) => ({ ...p, k: Math.max(0.35, p.k * 0.85) }))}>
            －
          </button>
          <button className="btn btn-sm" onClick={resetView}>
            居中 Reset
          </button>
          <button className="btn btn-sm" onClick={handleExportSvg} title="导出矢量师承图 SVG">
            导出 SVG
          </button>
        </div>
      </div>

      <div
        ref={containerRef}
        className="graph-canvas-wrap"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
      >
        {layout.nodes.length === 0 ? (
          <div style={{ padding: 48, textAlign: "center", color: "var(--ink-muted)" }}>
            暂无关联的师承关系边。
          </div>
        ) : (
          <svg ref={svgRef} width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <marker id="arrow-verified" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 1 L 10 5 L 0 9 z" fill="#1E6B52" />
              </marker>
              <marker id="arrow-historical" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 1 L 10 5 L 0 9 z" fill="#B0A696" />
              </marker>
            </defs>

            <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`}>
              {/* Curved cubic Bezier advisor -> student edges */}
              {layout.edges.map((e, idx) => {
                const x1 = e.src.cx;
                const y1 = e.src.y + e.src.h;
                const x2 = e.tgt.cx;
                const y2 = e.tgt.y;
                const midY = (y1 + y2) / 2;
                const isVerified = e.source_type === "dissertation_verified";
                const isHighlighted = hoveredId && (e.source === hoveredId || e.target === hoveredId);
                return (
                  <path
                    key={`${e.source}-${e.target}-${idx}`}
                    d={`M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2 - 2}`}
                    fill="none"
                    stroke={isVerified ? "#1E6B52" : isHighlighted ? "#1B4965" : "#BDB4A5"}
                    strokeWidth={isHighlighted ? 2.4 : isVerified ? 1.85 : 1.35}
                    strokeDasharray={isVerified ? "none" : "5 3"}
                    opacity={hoveredId && !isHighlighted ? 0.35 : 0.92}
                    markerEnd={isVerified ? "url(#arrow-verified)" : "url(#arrow-historical)"}
                  />
                );
              })}

              {/* Scholar Nodes */}
              {layout.nodes.map((n) => {
                const st = getNodeStyle(n);
                const isHov = hoveredId === n.id;
                return (
                  <g
                    key={n.id}
                    data-node-id={n.id}
                    transform={`translate(${n.x}, ${n.y})`}
                    style={{ cursor: "pointer" }}
                    onMouseEnter={() => setHoveredId(n.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    onClick={() => onSelectScholar(n.id)}
                  >
                    <rect
                      width={n.w}
                      height={n.h}
                      rx={8}
                      fill={st.fill}
                      stroke={isHov ? "#1B4965" : st.stroke}
                      strokeWidth={n.is_focus || isHov ? 2.2 : 1.3}
                    />
                    <text
                      x={12}
                      y={23}
                      fontSize="12.5"
                      fontWeight="600"
                      fontFamily="Newsreader, Georgia, serif"
                      fill={st.text}
                    >
                      {truncate(n.name, 24)}
                    </text>
                    <text
                      x={12}
                      y={40}
                      fontSize="10.2"
                      fontFamily="Inter, sans-serif"
                      fill={st.sub}
                    >
                      {truncate(n.university || (n.name_zh ? n.name_zh : "Institution n/a"), 27)}
                    </text>
                    <text
                      x={12}
                      y={54}
                      fontSize="9.6"
                      fontFamily="JetBrains Mono, monospace"
                      fill={st.sub}
                      opacity={0.9}
                    >
                      {n.year ? `${n.year}` : "—"}
                      {n.verification_status === "verified_dissertation" ? " · ✓ Dissertation" : ""}
                      {n.student_count > 0 ? ` · ${n.student_count} stu` : ""}
                    </text>
                  </g>
                );
              })}
            </g>
          </svg>
        )}

        <div className="graph-hint">
          拖拽平移 · 滚轮缩放 · 点击任意学者跳转详情（共 {layout.nodes.length} 节点 / {layout.edges.length} 关系边）
        </div>
      </div>
    </section>
  );
}
