import React, { useEffect, useMemo, useRef, useState } from "react";

/**
 * Interactive Parchment Family Tree SVG Canvas.
 * Full mobile & desktop gesture support:
 * - Single-finger touch drag to pan (native non-passive touch listeners for iOS/Android)
 * - Two-finger pinch-to-zoom centered at the midpoint
 * - Clean tap-vs-drag detection (< 10px movement opens node)
 * - Desktop mouse drag + wheel zoom + SVG export
 */
export default function GenealogyGraph({
  graph,
  onSelectScholar,
  ancestorDepth,
  descendantDepth,
  onDepthChange,
}) {
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [hoveredId, setHoveredId] = useState(null);
  const containerRef = useRef(null);
  const svgRef = useRef(null);
  const transformRef = useRef(transform);
  transformRef.current = transform;

  const gestureRef = useRef({
    mode: null, // 'mouse' | 'pan' | 'pinch'
    startX: 0,
    startY: 0,
    tx: 0,
    ty: 0,
    moved: 0,
    tappedNodeId: null,
    pinchDist: 0,
    pinchK: 1,
    pinchMidX: 0,
    pinchMidY: 0,
  });

  const onSelectRef = useRef(onSelectScholar);
  onSelectRef.current = onSelectScholar;

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
    const nodeW = 204;
    const nodeH = 64;
    const gapX = 26;
    const gapY = 86;

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

    const canvasW = Math.max(920, maxRowWidth + 140);
    const canvasH = Math.max(480, sortedLevels.length * (nodeH + gapY) + 120);
    const posMap = new Map();

    sortedLevels.forEach((lvl, rowIdx) => {
      const arr = byLevel.get(lvl);
      const rowW = arr.length * (nodeW + gapX) - gapX;
      const startX = (canvasW - rowW) / 2;
      const y = 56 + rowIdx * (nodeH + gapY);
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

  const centerOnFocus = () => {
    const el = containerRef.current;
    if (!el || !layout.focusPos) return;
    const vw = el.clientWidth || 860;
    const vh = el.clientHeight || 500;
    const isMobile = vw < 640;
    const k = isMobile ? 0.78 : layout.nodes.length > 24 ? 0.85 : 0.96;
    setTransform({
      x: vw / 2 - layout.focusPos.x * k,
      y: vh * 0.56 - layout.focusPos.y * k,
      k,
    });
  };

  useEffect(() => {
    centerOnFocus();
  }, [layout]);

  // Native non-passive touch & wheel listeners for buttery-smooth mobile drag & pinch zoom
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const getDist = (t1, t2) => Math.hypot(t2.clientX - t1.clientX, t2.clientY - t1.clientY);

    const onTouchStart = (e) => {
      if (e.touches.length === 1) {
        const t = e.touches[0];
        const nodeEl = e.target.closest?.("[data-node-id]");
        gestureRef.current = {
          mode: "pan",
          startX: t.clientX,
          startY: t.clientY,
          tx: transformRef.current.x,
          ty: transformRef.current.y,
          moved: 0,
          tappedNodeId: nodeEl ? Number(nodeEl.getAttribute("data-node-id")) : null,
          pinchDist: 0,
          pinchK: transformRef.current.k,
          pinchMidX: 0,
          pinchMidY: 0,
        };
      } else if (e.touches.length === 2) {
        e.preventDefault();
        const [t1, t2] = [e.touches[0], e.touches[1]];
        const rect = el.getBoundingClientRect();
        gestureRef.current = {
          mode: "pinch",
          startX: 0,
          startY: 0,
          tx: transformRef.current.x,
          ty: transformRef.current.y,
          moved: 999,
          tappedNodeId: null,
          pinchDist: Math.max(10, getDist(t1, t2)),
          pinchK: transformRef.current.k,
          pinchMidX: (t1.clientX + t2.clientX) / 2 - rect.left,
          pinchMidY: (t1.clientY + t2.clientY) / 2 - rect.top,
        };
      }
    };

    const onTouchMove = (e) => {
      const g = gestureRef.current;
      if (g.mode === "pan" && e.touches.length === 1) {
        e.preventDefault();
        const t = e.touches[0];
        const dx = t.clientX - g.startX;
        const dy = t.clientY - g.startY;
        g.moved = Math.max(g.moved, Math.hypot(dx, dy));
        setTransform((prev) => ({ ...prev, x: g.tx + dx, y: g.ty + dy }));
      } else if (g.mode === "pinch" && e.touches.length === 2) {
        e.preventDefault();
        const [t1, t2] = [e.touches[0], e.touches[1]];
        const dist = getDist(t1, t2);
        const nextK = Math.max(0.32, Math.min(2.2, g.pinchK * (dist / g.pinchDist)));
        const scaleRatio = nextK / g.pinchK;
        setTransform({
          k: nextK,
          x: g.pinchMidX - (g.pinchMidX - g.tx) * scaleRatio,
          y: g.pinchMidY - (g.pinchMidY - g.ty) * scaleRatio,
        });
      }
    };

    const onTouchEnd = (e) => {
      const g = gestureRef.current;
      if (g.mode === "pan" && g.moved < 10 && g.tappedNodeId) {
        onSelectRef.current?.(g.tappedNodeId);
      }
      if (e.touches.length === 0) {
        g.mode = null;
      }
    };

    const onWheel = (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.1 : 0.91;
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      setTransform((prev) => {
        const nextK = Math.max(0.32, Math.min(2.2, prev.k * factor));
        return {
          k: nextK,
          x: mx - ((mx - prev.x) * nextK) / prev.k,
          y: my - ((my - prev.y) * nextK) / prev.k,
        };
      });
    };

    el.addEventListener("touchstart", onTouchStart, { passive: false });
    el.addEventListener("touchmove", onTouchMove, { passive: false });
    el.addEventListener("touchend", onTouchEnd, { passive: true });
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", onTouchEnd);
      el.removeEventListener("wheel", onWheel);
    };
  }, []);

  const handleMouseDown = (e) => {
    const nodeEl = e.target.closest?.("[data-node-id]");
    gestureRef.current = {
      ...gestureRef.current,
      mode: "mouse",
      startX: e.clientX,
      startY: e.clientY,
      tx: transform.x,
      ty: transform.y,
      moved: 0,
      tappedNodeId: nodeEl ? Number(nodeEl.getAttribute("data-node-id")) : null,
    };
  };

  const handleMouseMove = (e) => {
    const g = gestureRef.current;
    if (g.mode !== "mouse") return;
    const dx = e.clientX - g.startX;
    const dy = e.clientY - g.startY;
    g.moved = Math.max(g.moved, Math.hypot(dx, dy));
    setTransform((prev) => ({ ...prev, x: g.tx + dx, y: g.ty + dy }));
  };

  const handleMouseUp = () => {
    const g = gestureRef.current;
    if (g.mode === "mouse" && g.moved < 6 && g.tappedNodeId) {
      onSelectScholar(g.tappedNodeId);
    }
    g.mode = null;
  };

  const handleExportSvg = () => {
    if (!svgRef.current) return;
    const raw = new XMLSerializer().serializeToString(svgRef.current);
    const blob = new Blob([raw], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `genealogy-${graph?.focus_id || "tree"}.svg`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const getNodeStyle = (n) => {
    if (n.is_focus) {
      return {
        fill: "#6D2323",
        stroke: "#461414",
        innerStroke: "rgba(248, 242, 226, 0.35)",
        text: "#FAF2DF",
        sub: "#E6D4B8",
      };
    }
    if (n.verification_status === "verified_dissertation") {
      return {
        fill: "#F9F4E6",
        stroke: "#265944",
        innerStroke: "rgba(38, 89, 68, 0.24)",
        text: "#241B12",
        sub: "#265944",
      };
    }
    return {
      fill: "#FAF4E4",
      stroke: "#8C7355",
      innerStroke: "rgba(140, 115, 85, 0.26)",
      text: "#241B12",
      sub: "#6E5C47",
    };
  };

  const truncate = (str, n) => (str && str.length > n ? str.slice(0, n - 1) + "…" : str || "");

  return (
    <section className="tree-frame" aria-label="Academic Family Tree">
      <div className="tree-toolbar">
        <span className="tree-toolbar-title">Pedigree Chart</span>
        <div className="tree-controls">
          <label style={{ fontSize: "0.82rem", color: "var(--ink-muted)" }}>
            Ancestors{" "}
            <select
              className="parchment-select"
              style={{ padding: "3px 6px", fontSize: "0.82rem" }}
              value={ancestorDepth}
              onChange={(e) => onDepthChange(Number(e.target.value), descendantDepth)}
            >
              {[2, 4, 6, 8, 12].map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: "0.82rem", color: "var(--ink-muted)" }}>
            Descendants{" "}
            <select
              className="parchment-select"
              style={{ padding: "3px 6px", fontSize: "0.82rem" }}
              value={descendantDepth}
              onChange={(e) => onDepthChange(ancestorDepth, Number(e.target.value))}
            >
              {[1, 2, 3, 4].map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </label>
          <button
            className="btn btn-xs"
            onClick={() => setTransform((p) => ({ ...p, k: Math.min(2.2, p.k * 1.18) }))}
            aria-label="Zoom in"
          >
            +
          </button>
          <button
            className="btn btn-xs"
            onClick={() => setTransform((p) => ({ ...p, k: Math.max(0.32, p.k * 0.85) }))}
            aria-label="Zoom out"
          >
            −
          </button>
          <button className="btn btn-xs" onClick={centerOnFocus}>
            Center
          </button>
          <button className="btn btn-xs" onClick={handleExportSvg}>
            SVG
          </button>
        </div>
      </div>

      <div
        ref={containerRef}
        className="tree-viewport"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {layout.nodes.length === 0 ? (
          <div style={{ padding: 48, textAlign: "center", color: "var(--ink-muted)", fontStyle: "italic" }}>
            No recorded lineage connections yet.
          </div>
        ) : (
          <svg ref={svgRef} width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
            <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`}>
              {/* Organic Sepia Ink Family Tree Branches */}
              {layout.edges.map((e, idx) => {
                const x1 = e.src.cx;
                const y1 = e.src.y + e.src.h;
                const x2 = e.tgt.cx;
                const y2 = e.tgt.y;
                const midY = (y1 + y2) / 2;
                const isVerified = e.source_type === "dissertation_verified";
                const isHighlighted = hoveredId && (e.source === hoveredId || e.target === hoveredId);
                return (
                  <g key={`${e.source}-${e.target}-${idx}`}>
                    <path
                      d={`M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`}
                      fill="none"
                      stroke={isVerified ? "#265944" : isHighlighted ? "#6D2323" : "#8A7152"}
                      strokeWidth={isHighlighted ? 2.2 : isVerified ? 1.75 : 1.3}
                      opacity={hoveredId && !isHighlighted ? 0.3 : 0.88}
                    />
                    <circle
                      cx={x2}
                      cy={y2}
                      r={2.4}
                      fill={isVerified ? "#265944" : "#8A7152"}
                      opacity={hoveredId && !isHighlighted ? 0.3 : 0.9}
                    />
                  </g>
                );
              })}

              {/* Engraved Pedigree Cartouche Nodes */}
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
                  >
                    {/* Outer plaque */}
                    <rect
                      width={n.w}
                      height={n.h}
                      rx={4}
                      fill={st.fill}
                      stroke={isHov ? "#6D2323" : st.stroke}
                      strokeWidth={n.is_focus || isHov ? 1.8 : 1.15}
                    />
                    {/* Hairline engraved inner frame */}
                    <rect
                      x={3.5}
                      y={3.5}
                      width={n.w - 7}
                      height={n.h - 7}
                      rx={2}
                      fill="none"
                      stroke={st.innerStroke}
                      strokeWidth={0.8}
                    />
                    {/* Verified dissertation seal dot */}
                    {n.verification_status === "verified_dissertation" && !n.is_focus && (
                      <circle cx={n.w - 13} cy={14} r={3.5} fill="#265944" />
                    )}
                    <text
                      x={n.w / 2}
                      y={26}
                      textAnchor="middle"
                      fontSize="14"
                      fontWeight="600"
                      fontFamily="Cormorant Garamond, Georgia, serif"
                      fill={st.text}
                    >
                      {truncate(n.name, 25)}
                    </text>
                    <text
                      x={n.w / 2}
                      y={43}
                      textAnchor="middle"
                      fontSize="11"
                      fontStyle="italic"
                      fontFamily="EB Garamond, Georgia, serif"
                      fill={st.sub}
                    >
                      {truncate(n.university || "Institution unrecorded", 28)}
                    </text>
                    <text
                      x={n.w / 2}
                      y={56}
                      textAnchor="middle"
                      fontSize="10"
                      fontFamily="EB Garamond, Georgia, serif"
                      fill={st.sub}
                      opacity={0.9}
                    >
                      {n.year ? n.year : "—"}
                      {n.student_count > 0 ? ` · ${n.student_count} ${n.student_count === 1 ? "student" : "students"}` : ""}
                    </text>
                  </g>
                );
              })}
            </g>
          </svg>
        )}
      </div>

      <div className="tree-legend-bar">
        <div className="legend-items">
          <span>
            <span className="legend-swatch" style={{ background: "#6D2323" }} />
            Selected Scholar
          </span>
          <span>
            <span className="legend-swatch" style={{ background: "#265944" }} />
            Thesis-Verified
          </span>
          <span>
            <span className="legend-swatch" style={{ background: "#8C7355" }} />
            Historical Record
          </span>
        </div>
        <span style={{ fontStyle: "italic" }}>
          Drag to pan · Pinch or scroll to zoom · Tap any name
        </span>
      </div>
    </section>
  );
}
