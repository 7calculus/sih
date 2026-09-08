import React, { useState, useEffect, useRef } from 'react';
import RoverTerrain3D from './RoverTerrain3D.jsx';

// The WS URL is like ws://host:8000/ws - derive the plain HTTP API base
// (http://host:8000) from it so REST endpoints (e.g. /audit-log) hit the
// same backend without needing a second env var.
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws';
const API_BASE = WS_URL.replace(/^ws/, 'http').replace(/\/ws\/?$/, '');

const MAX_TRAIL_POINTS = 400;

// Thin Corner Brackets
const CornerBrackets = () => (
  <>
    <div className="absolute top-0 left-0 w-3 h-3 border-t border-l border-white/80" />
    <div className="absolute top-0 right-0 w-3 h-3 border-t border-r border-white/80" />
    <div className="absolute bottom-0 left-0 w-3 h-3 border-b border-l border-white/80" />
    <div className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-white/80" />
  </>
);

// Fake Bar Chart for Header - Made slightly taller for the "BIG" look
const HeaderBarChart = () => (
  <div className="flex items-end gap-[3px] h-8">
    {[...Array(15)].map((_, i) => (
      <div 
        key={i} 
        className="w-[4px] bg-cyan-400/80 animate-pulse" 
        style={{ height: `${Math.random() * 80 + 20}%`, animationDelay: `${Math.random()}s` }} 
      />
    ))}
  </div>
);

// Glowing Geometric SVG
const GeometricOrb = () => (
  <svg className="w-12 h-12 text-cyan-400 drop-shadow-[0_0_10px_#22d3ee] animate-pulse" viewBox="0 0 100 100">
    <polygon points="50,10 90,30 90,70 50,90 10,70 10,30" fill="none" stroke="currentColor" strokeWidth="2" className="animate-[spin_8s_linear_infinite]" />
    <circle cx="50" cy="50" r="15" fill="currentColor" />
  </svg>
);

// Layered Circular SVGs (Gears/Radars)
const RadarGears = () => (
  <div className="absolute inset-0 right-0 w-full h-full flex justify-end items-center opacity-25 pointer-events-none pr-4">
    <svg viewBox="0 0 100 100" className="w-32 h-32 text-cyan-400/40 animate-[spin_10s_linear_infinite]">
      <circle cx="50" cy="50" r="40" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="5 5" />
      <circle cx="50" cy="50" r="20" fill="none" stroke="currentColor" strokeWidth="1" />
      {[...Array(8)].map((_, i) => (
        <line key={i} x1="50" y1="10" x2="50" y2="15" transform={`rotate(${i*45} 50 50)`} stroke="currentColor" strokeWidth="2" />
      ))}
    </svg>
    <svg viewBox="0 0 100 100" className="w-20 h-20 text-white/30 -ml-12 animate-[spin_12s_linear_infinite_reverse]">
      <circle cx="50" cy="50" r="45" fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="10 5" />
    </svg>
  </div>
);

// Wireframe Mountain/Grid SVG
const MountainGrid = () => (
  <div className="absolute inset-0 opacity-20 pointer-events-none mt-10">
    <svg viewBox="0 0 200 100" className="w-full h-full" preserveAspectRatio="none">
      <path d="M0,80 Q25,60 50,75 T100,60 T150,85 T200,70 L200,100 L0,100 Z" fill="none" stroke="#22d3ee" strokeWidth="0.5" />
      <path d="M0,85 Q25,70 50,85 T100,75 T150,95 T200,80" fill="none" stroke="#22d3ee" strokeWidth="0.3" />
      <path d="M0,90 Q25,80 50,95 T100,85 T150,100 T200,90" fill="none" stroke="#22d3ee" strokeWidth="0.3" />
      {[...Array(15)].map((_, i) => (
        <line key={i} x1={i*15} y1="50" x2={i*15} y2="100" stroke="#22d3ee" strokeWidth="0.1" />
      ))}
    </svg>
  </div>
);

// ================= 2D LIVE ROVER MAP =================
// Simple SVG "moving map": renders the accumulated trail as a polyline,
// the rover as a marker, and a circle sized to the current localization
// uncertainty (in meters). Auto-fits its view to whatever the rover has
// actually covered so far, so it works whether the run spans 50m or 5km.
const VIEW = 400; // svg viewBox is VIEW x VIEW user units
const MIN_WINDOW_M = 60;   // smallest camera window, in meters, so a barely-moving rover isn't zoomed in on nothing
const EDGE_MARGIN_FRAC = 0.25; // re-expand once the rover is within 25% of an edge
const GROWTH_FACTOR = 1.8;     // how much bigger the new window is when we do expand

const RoverMap = ({ trail, position, uncertainty, mode, pathA, pathB, activePath, hazardPath, pathChoice, hazards, scanState, routePhase }) => {
  // Sticky chase-camera: re-fitting to the *entire* trail every frame was
  // the bug here. Because the current position is always at (or near) the
  // extreme edge of everything recorded so far during steady motion, a
  // continuous best-fit pins the marker to the same relative spot on
  // screen forever - it never visibly moves even though the rover is.
  // Instead we keep a fixed view window and only jump/expand it once the
  // rover is about to leave it, so the marker actually slides across the
  // screen in between expansions.
  const [view, setView] = useState(() => {
    const routePoints = [...pathA, ...pathB, ...activePath];
    const routeHalf = routePoints.reduce((max, point) => Math.max(
      max,
      Math.abs(point[0] - position.x),
      Math.abs(point[1] - position.y),
    ), 0);
    const half = Math.max(uncertainty * 4, MIN_WINDOW_M / 2, routeHalf * 1.15);
    return { minX: position.x - half, maxX: position.x + half, minY: position.y - half, maxY: position.y + half };
  });

  useEffect(() => {
    setView(prev => {
      const spanX = prev.maxX - prev.minX, spanY = prev.maxY - prev.minY;
      const marginX = spanX * EDGE_MARGIN_FRAC, marginY = spanY * EDGE_MARGIN_FRAC;
      const uncertaintyOverflow = uncertainty * 2.5 > Math.max(spanX, spanY) / 2;
      const nearEdge =
        position.x < prev.minX + marginX || position.x > prev.maxX - marginX ||
        position.y < prev.minY + marginY || position.y > prev.maxY - marginY;

      if (!nearEdge && !uncertaintyOverflow) return prev; // stay put - this is what lets movement actually show

      const newHalf = Math.max(spanX, spanY, MIN_WINDOW_M, uncertainty * 5) * GROWTH_FACTOR / 2;
      return {
        minX: position.x - newHalf, maxX: position.x + newHalf,
        minY: position.y - newHalf, maxY: position.y + newHalf,
      };
    });
  }, [position.x, position.y, uncertainty]);

  useEffect(() => {
    const routePoints = [...pathA, ...pathB, ...activePath];
    if (!routePoints.length) return;
    const xs = routePoints.map(point => point[0]).concat(position.x);
    const ys = routePoints.map(point => point[1]).concat(position.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const half = Math.max(maxX - minX, maxY - minY, MIN_WINDOW_M) * 0.6;
    setView({
      minX: (minX + maxX) / 2 - half,
      maxX: (minX + maxX) / 2 + half,
      minY: (minY + maxY) / 2 - half,
      maxY: (minY + maxY) / 2 + half,
    });
  }, [pathA.length, pathB.length, activePath.length]);

  const scale = VIEW / Math.max(view.maxX - view.minX, view.maxY - view.minY);
  const cx = (view.minX + view.maxX) / 2, cy = (view.minY + view.maxY) / 2;

  const toSvg = (x, y) => ({
    sx: VIEW / 2 + (x - cx) * scale,
    // world Y increases "north"; SVG y increases downward.
    sy: VIEW / 2 - (y - cy) * scale,
  });

  const trailPts = trail.map(p => toSvg(p.x, p.y));
  const pathAPts = pathA.map(p => toSvg(p[0], p[1]));
  const pathBPts = pathB.map(p => toSvg(p[0], p[1]));
  const activePathPts = activePath.map(p => toSvg(p[0], p[1]));
  const hazardPathPts = (hazardPath || []).map(p => toSvg(p[0], p[1]));
  const hazardPts = hazards.map(hazard => toSvg(hazard.x, hazard.y));
  const roverPt = toSvg(position.x, position.y);
  const uncertaintyPx = Math.max(uncertainty * scale, 3);

  const gridLines = [...Array(9)].map((_, i) => (i + 1) * (VIEW / 10));

  // Mode colors (PRD Table 11 + Hazard Detected)
  const modeColor = (() => {
    const m = (mode || '').toLowerCase();
    if (m.includes('hazard') || m.includes('relocal')) return '#ef4444';
    if (m.includes('caution')) return '#facc15';
    if (m.includes('complete')) return '#22c55e';
    return '#22d3ee'; // Driving / Starting / cyan cruise
  })();

  // Path drama colors driven by route_phase
  // cyan -> hazard(red blocked) -> candidates(purple/yellow) -> green -> cyan
  const phase = routePhase || (scanState === 'hazard' ? 'hazard' : 'cyan');
  const pathAColor = '#c084fc'; // neon purple
  const pathBColor = '#facc15'; // bright yellow
  const isEvaluating = phase === 'candidates' || phase === 'hazard';

  return (
    <svg viewBox={`0 0 ${VIEW} ${VIEW}`} className="w-full h-full">
      {/* reference grid */}
      {gridLines.map(v => (
        <React.Fragment key={`g${v}`}>
          <line x1={v} y1={0} x2={v} y2={VIEW} stroke="white" strokeOpacity="0.06" strokeWidth="1" />
          <line x1={0} y1={v} x2={VIEW} y2={v} stroke="white" strokeOpacity="0.06" strokeWidth="1" />
        </React.Fragment>
      ))}

      {/* Red blocked path to hazard */}
      {hazardPathPts.length > 1 && (
        <polyline
          points={hazardPathPts.map(p => `${p.sx},${p.sy}`).join(' ')}
          fill="none"
          stroke="#ef4444"
          strokeOpacity="1"
          strokeWidth="4"
          strokeDasharray="4 2"
        />
      )}

      {/* Candidate Path A (Neon Purple - Safe Route) */}
      {pathAPts.length > 1 && (
        <polyline
          points={pathAPts.map(p => `${p.sx},${p.sy}`).join(' ')}
          fill="none"
          stroke={pathAColor}
          strokeOpacity={phase === 'green' && pathChoice !== 'A' ? 0.35 : 0.95}
          strokeWidth={isEvaluating ? '4' : '2.5'}
          strokeDasharray={isEvaluating ? '5 3' : '3 3'}
        />
      )}

      {/* Candidate Path B (Bright Yellow - Fast Shortcut) */}
      {pathBPts.length > 1 && (
        <polyline
          points={pathBPts.map(p => `${p.sx},${p.sy}`).join(' ')}
          fill="none"
          stroke={pathBColor}
          strokeOpacity={phase === 'green' && pathChoice !== 'B' ? 0.35 : 0.95}
          strokeWidth={isEvaluating ? '4' : '2.5'}
          strokeDasharray={isEvaluating ? '5 3' : '3 3'}
        />
      )}

      {/* Active cruise (cyan) or Selected Winner (green) */}
      {!isEvaluating && activePathPts.length > 1 && (
        <polyline
          points={activePathPts.map(p => `${p.sx},${p.sy}`).join(' ')}
          fill="none"
          stroke={phase === 'green' ? '#22c55e' : '#22d3ee'}
          strokeOpacity="0.9"
          strokeWidth={phase === 'green' ? '4.5' : '3'}
        />
      )}

      {/* Route Legend in top-left of the map */}
      <g className="select-none pointer-events-none">
        <rect x="8" y="8" width="128" height="40" fill="rgba(0,0,0,0.75)" stroke="rgba(255,255,255,0.2)" rx="3" />
        <line x1="16" y1="20" x2="34" y2="20" stroke="#c084fc" strokeWidth="3" strokeDasharray="3 2" />
        <text x="40" y="23" fill="#c084fc" fontSize="8" fontWeight="bold" letterSpacing="0.05em">PATH A (PURPLE/SAFE)</text>
        <line x1="16" y1="34" x2="34" y2="34" stroke="#facc15" strokeWidth="3" strokeDasharray="3 2" />
        <text x="40" y="37" fill="#facc15" fontSize="8" fontWeight="bold" letterSpacing="0.05em">PATH B (YELLOW/FAST)</text>
      </g>

      {hazardPts.map((point, index) => {
        const hz = hazards[index] || {};
        const isCrater = (hz.type || '') === 'crater';
        return (
          <g key={`hazard-${index}`}>
            <circle cx={point.sx} cy={point.sy} r="10" fill={isCrater ? '#a855f7' : '#ef4444'} fillOpacity="0.3" stroke={isCrater ? '#e9d5ff' : '#ef4444'} strokeWidth="2" />
            <path d={`M ${point.sx - 5} ${point.sy - 5} L ${point.sx + 5} ${point.sy + 5} M ${point.sx + 5} ${point.sy - 5} L ${point.sx - 5} ${point.sy + 5}`} stroke="#fecaca" strokeWidth="2" />
            <text x={point.sx + 12} y={point.sy - 8} fill={isCrater ? '#e9d5ff' : '#fecaca'} fontSize="8" className="normal-case">{isCrater ? 'CRATER' : 'TERRAIN'}</text>
          </g>
        );
      })}
      {trailPts.length > 1 && (
        <polyline
          points={trailPts.map(p => `${p.sx},${p.sy}`).join(' ')}
          fill="none"
          stroke="#22d3ee"
          strokeOpacity="0.55"
          strokeWidth="1.5"
        />
      )}

      {/* uncertainty envelope around current estimate */}
      <circle
        cx={roverPt.sx}
        cy={roverPt.sy}
        r={uncertaintyPx}
        fill={modeColor}
        fillOpacity="0.12"
        stroke={modeColor}
        strokeOpacity="0.6"
        strokeWidth="1"
        strokeDasharray="4 3"
      />

      {/* rover marker */}
      <circle cx={roverPt.sx} cy={roverPt.sy} r="5" fill={modeColor} className="drop-shadow-[0_0_6px_rgba(34,211,238,0.9)]" />
      <circle cx={roverPt.sx} cy={roverPt.sy} r="9" fill="none" stroke={modeColor} strokeOpacity="0.5" strokeWidth="1" />
    </svg>
  );
};

// ================= AUDIT TRAIL PANEL =================
// Polls GET /audit-log (backed by explain/audit_logger.py's decision_log.json)
// and shows the most recent contrastive path-selection decisions.
const AuditLogPanel = ({ entries, loading }) => {
  if (loading && entries.length === 0) {
    return <div className="text-[10px] text-gray-500 tracking-widest">LOADING AUDIT TRAIL...</div>;
  }
  if (entries.length === 0) {
    return <div className="text-[10px] text-gray-500 tracking-widest">NO LOGGED DECISIONS YET</div>;
  }
  return (
    <div className="flex flex-col gap-2 overflow-y-auto h-full pr-1">
      {entries.map((entry, i) => {
        const ma = entry.metrics?.path_a || entry.metrics?.chosen || {};
        const mb = entry.metrics?.path_b || entry.metrics?.rejected || {};
        return (
          <div key={i} className="border border-white/10 bg-black/50 p-2">
            <div className="flex justify-between text-[8px] text-gray-400 tracking-widest mb-1">
              <span>ROUTE DECISION #{entries.length - i}</span>
              <span>{entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : '--:--:--'}</span>
            </div>
            <p className="text-[10px] text-cyan-300 leading-snug normal-case mb-2">{entry.explanation}</p>
            <div className="grid grid-cols-2 gap-2 text-[8px] tracking-widest normal-case">
              <div className="border border-violet-400/30 bg-violet-950/30 p-1.5">
                <div className="text-violet-300 mb-1">PATH A</div>
                <div className="text-white">Terrain hz: <span className="text-red-300">{ma.terrain_hazards ?? 0}</span></div>
                <div className="text-white">Crater hz: <span className="text-purple-300">{ma.crater_hazards ?? 0}</span></div>
                <div className="text-gray-400">Slip: {Number(ma.slip_risk ?? 0).toFixed(1)}°</div>
              </div>
              <div className="border border-yellow-400/30 bg-yellow-950/20 p-1.5">
                <div className="text-yellow-300 mb-1">PATH B</div>
                <div className="text-white">Terrain hz: <span className="text-red-300">{mb.terrain_hazards ?? 0}</span></div>
                <div className="text-white">Crater hz: <span className="text-purple-300">{mb.crater_hazards ?? 0}</span></div>
                <div className="text-gray-400">Slip: {Number(mb.slip_risk ?? 0).toFixed(1)}°</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

function App() {
  const [agentLog, setAgentLog] = useState("Connecting to WebSocket backend...");
  const [telemetry, setTelemetry] = useState({
    mode: 'Connecting',
    position: { x: 0.0, y: 0.0 },
    uncertainty: 0.0,
    precision: 0.0,
    recall: 0.0,
    center_error: 0.0,
    trn_enabled: true,
    last_error_before: 0.0,
    last_error_after: 0.0,
    reloc_count: 0,
    hazard_violation_pct: 0.0,
    path_a: [], path_b: [], active_path: [], hazard_path: [], route_index: 0,
    hazards: [], scan_state: 'clear', path_choice: 'A', route_phase: 'cyan',
    path_metrics_a: {}, path_metrics_b: {},
  });
  const [trail, setTrail] = useState([]);
  const [auditLog, setAuditLog] = useState([]);
  const [auditLoading, setAuditLoading] = useState(true);
  const [mapMode, setMapMode] = useState('2d'); // '2d' | '3d'
  const lastTrailPoint = useRef(null);

  useEffect(() => {
    let ws;
    let reconnectTimer;
    let disposed = false;
    const connectWebSocket = () => {
      if (disposed) return;
      ws = new WebSocket(WS_URL);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.reasoning) setAgentLog(data.reasoning);
          setTelemetry({
            mode: data.mode || 'Driving',
            position: { x: data.x, y: data.y },
            uncertainty: data.uncertainty,
            precision: data.precision ?? 0.0,
            recall: data.recall ?? 0.0,
            center_error: data.center_error ?? 0.0,
            trn_enabled: data.trn_enabled ?? true,
            last_error_before: data.last_error_before ?? data.error_before ?? 0.0,
            last_error_after: data.last_error_after ?? data.error_after ?? 0.0,
            reloc_count: data.reloc_count ?? 0,
            hazard_violation_pct: data.hazard_violation_pct ?? 0.0,
            path_a: data.path_a || [], path_b: data.path_b || [],
            active_path: data.active_path || [], hazard_path: data.hazard_path || [],
            route_index: data.route_index || 0,
            hazards: data.hazards || [], scan_state: data.scan_state || 'clear',
            path_choice: data.path_choice || 'A',
            route_phase: data.route_phase || 'cyan',
            path_metrics_a: data.path_metrics_a || {},
            path_metrics_b: data.path_metrics_b || {},
          });

          // Accumulate position history for the trail/trajectory view.
          // Skip near-duplicate points (e.g. re-renders) so the polyline
          // doesn't fill up with a stationary point over and over.
          const last = lastTrailPoint.current;
          const moved = !last || Math.hypot(data.x - last.x, data.y - last.y) > 0.05;
          if (typeof data.x === 'number' && typeof data.y === 'number' && moved) {
            lastTrailPoint.current = { x: data.x, y: data.y };
            setTrail(prev => {
              const next = [...prev, { x: data.x, y: data.y }];
              return next.length > MAX_TRAIL_POINTS ? next.slice(next.length - MAX_TRAIL_POINTS) : next;
            });
          }
        } catch (e) {
          console.error("Failed to parse WS packet", e);
        }
      };

      ws.onclose = () => {
        if (!disposed) reconnectTimer = setTimeout(connectWebSocket, 2000);
      };
    };

    connectWebSocket();
    return () => {
      disposed = true;
      clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, []);

  // Poll the audit trail endpoint independently of the WS telemetry
  // stream - decisions only land occasionally (on re-localization),
  // so a slower interval is enough and keeps this decoupled from M2.
  useEffect(() => {
    let cancelled = false;
    const fetchAuditLog = async () => {
      try {
        const res = await fetch(`${API_BASE}/audit-log`);
        if (!res.ok) throw new Error(`status ${res.status}`);
        const data = await res.json();
        if (!cancelled) setAuditLog(data.decisions || []);
      } catch (e) {
        console.error("Failed to fetch audit log", e);
      } finally {
        if (!cancelled) setAuditLoading(false);
      }
    };

    fetchAuditLog();
    const interval = setInterval(fetchAuditLog, 5000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  return (
    <div 
      className="min-h-screen bg-cover bg-center font-mono text-white uppercase p-6 md:p-8 flex flex-col justify-between"
      style={{ backgroundImage: 'url(/moon-surface.png)' }} 
    >
      <div className="absolute inset-0 bg-black/30 z-0 pointer-events-none" />

      {/* ================= HEADER ================= */}
      <header className="relative z-10 flex flex-col md:flex-row justify-between items-start md:items-center w-full mb-6 border-b border-white/20 pb-4">
        <div>
          <h1 className="text-5xl tracking-[0.2em] font-bold text-white drop-shadow-md">SURAKSHA LANDER</h1>
          <h2 className="text-sm text-gray-400 tracking-[0.3em] mt-2">LUNAR TELEMETRY</h2>
        </div>

        {/* Center: live rover navigation status */}
        <div className="hidden lg:flex items-center gap-6 border border-white/40 px-8 py-4 bg-black/60 shadow-[0_0_20px_rgba(34,211,238,0.25)]">
          <div className="flex flex-col text-xs text-gray-200 tracking-widest text-right leading-relaxed">
            <span className="font-bold">DEM SOURCE: LUNAR_MAP.TIFF</span>
            <span>LOCAL FRAME: POLAR STEREOGRAPHIC</span>
            <span className="text-cyan-400">ROUTE CONTROL: ACTIVE</span>
          </div>
          <HeaderBarChart />
            <span className="text-lg tracking-widest font-bold text-white">ROVER TERRAIN NAVIGATION</span>
        </div>

        {/* Right: System Status */}
        <div className="relative border border-white/20 p-3 flex items-center gap-6 bg-black/40 mt-4 md:mt-0">
          <CornerBrackets />
          <GeometricOrb />
          <div className="flex flex-col items-end">
            <span className="text-xs tracking-widest text-white/70">SYSTEM STATUS</span>
            <div className="flex items-center gap-2 mt-1">
              <span className="w-3 h-3 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_8px_#22d3ee]" />
              <span className="text-xl font-bold text-cyan-400 tracking-widest">ONLINE</span>
            </div>
          </div>
        </div>
      </header>

      {/* ================= 3-COLUMN DATA PANELS ================= */}
      <div className="relative z-10 grid grid-cols-1 lg:grid-cols-3 gap-6 w-full mb-6 min-h-[300px] lg:h-[300px]">
        
        {/* 1. ROVER MODE */}
        <div className="relative bg-black/40 backdrop-blur-sm border border-white/20 p-5 flex flex-col justify-between overflow-hidden">
          <CornerBrackets />
          <RadarGears />
          
          <div className="relative z-10 flex flex-col h-full justify-between">
            {/* Moved UP: Title and Connecting/Driving Status */}
            <div>
              <div className="font-mono text-sm text-gray-200 tracking-widest mb-4">ROVER MODE</div>
              <div className="flex min-w-0 items-center gap-3">
                <div
                  className="h-5 w-5 shrink-0 rounded-full shadow-[0_0_15px_currentColor]"
                  style={{
                    backgroundColor:
                      /hazard|relocal/i.test(telemetry.mode) ? '#ef4444' :
                      /caution/i.test(telemetry.mode) ? '#facc15' :
                      /complete/i.test(telemetry.mode) ? '#22c55e' :
                      '#22d3ee',
                    color:
                      /hazard|relocal/i.test(telemetry.mode) ? '#ef4444' :
                      /caution/i.test(telemetry.mode) ? '#facc15' :
                      /complete/i.test(telemetry.mode) ? '#22c55e' :
                      '#22d3ee',
                  }}
                />
                <div
                  className="min-w-0 break-words text-3xl xl:text-4xl font-bold tracking-wide drop-shadow-[0_0_10px_rgba(34,211,238,0.5)]"
                  style={{
                    color:
                      /hazard|relocal/i.test(telemetry.mode) ? '#ef4444' :
                      /caution/i.test(telemetry.mode) ? '#facc15' :
                      /complete/i.test(telemetry.mode) ? '#22c55e' :
                      '#22d3ee',
                  }}
                >
                  {telemetry.mode}
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5 text-[8px] tracking-widest">
                {[
                  { label: 'DRIVING', color: '#22d3ee', active: /driving|starting|connecting/i.test(telemetry.mode) },
                  { label: 'CAUTION', color: '#facc15', active: /caution/i.test(telemetry.mode) },
                  { label: 'RE-LOCALIZING', color: '#ef4444', active: /relocal/i.test(telemetry.mode) },
                  { label: 'HAZARD', color: '#f87171', active: /hazard/i.test(telemetry.mode) },
                ].map(badge => (
                  <span
                    key={badge.label}
                    className="border px-2 py-0.5"
                    style={{
                      borderColor: badge.active ? badge.color : 'rgba(255,255,255,0.15)',
                      color: badge.active ? badge.color : 'rgba(255,255,255,0.35)',
                      backgroundColor: badge.active ? `${badge.color}22` : 'transparent',
                    }}
                  >
                    {badge.label}
                  </span>
                ))}
              </div>
              <div className="mt-2 text-[9px] tracking-widest text-gray-400">
                PHASE: <span className="text-white">{(telemetry.route_phase || 'cyan').toUpperCase()}</span>
                {' · '}CHOICE: <span className="text-white">PATH {telemetry.path_choice}</span>
              </div>
            </div>
            
            {/* CORRECTED: Spread Out Metrics across the full width */}
            <div className="w-full flex flex-col gap-1 bg-black/70 p-3 border border-white/10 mt-auto">
              <div className="flex justify-between items-end border-b border-white/20 pb-1 mb-1">
                <span className="text-[9px] font-bold text-gray-400">HAZARD METRICS (A vs B)</span>
                <span className="text-[8px] text-gray-400 tracking-widest">TERRAIN / CRATER</span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[9px]">
                <div>
                  <div className="text-violet-300 tracking-widest mb-0.5">PATH A</div>
                  <div className="text-red-300">Terrain: {telemetry.path_metrics_a?.terrain_hazards ?? 0}</div>
                  <div className="text-purple-300">Crater: {telemetry.path_metrics_a?.crater_hazards ?? 0}</div>
                </div>
                <div>
                  <div className="text-yellow-300 tracking-widest mb-0.5">PATH B</div>
                  <div className="text-red-300">Terrain: {telemetry.path_metrics_b?.terrain_hazards ?? 0}</div>
                  <div className="text-purple-300">Crater: {telemetry.path_metrics_b?.crater_hazards ?? 0}</div>
                </div>
              </div>
              <div className="flex justify-between items-center w-full mt-1 pt-1 border-t border-white/10">
                <div className="text-[9px] text-cyan-300">PRECISION: <span className="text-white">{telemetry.precision}</span></div>
                <div className="text-[9px] text-cyan-300">RECALL: <span className="text-white">{telemetry.recall}</span></div>
                <div className="text-[9px] text-cyan-300">CNTR ERR: <span className="text-white">{telemetry.center_error}px</span></div>
              </div>
            </div>
          </div>
        </div>

        {/* 2. POSITION */}
        <div className="relative bg-black/40 backdrop-blur-sm border border-white/20 p-5 flex flex-col overflow-hidden">
          <CornerBrackets />
          <MountainGrid />
          
          <div className="relative z-10 flex flex-col h-full">
            <div className="flex justify-between w-full mb-6">
              <div className="font-mono text-sm text-gray-200 tracking-widest">POSITION (X, Y)</div>
              <div className="text-[7px] text-gray-400 tracking-widest text-right leading-relaxed">
                LATERAL OFFSET: ACTIVE<br/>
                DROP DOWN MENU: INVERT<br/>
                TELEMETRY LOGS: ONLINE
              </div>
            </div>
            
            {/* Moved UP: X and Y Coordinates are immediately below the top text */}
            <div className="flex w-full min-w-0 justify-between gap-3 mt-2">
              <div className="min-w-0 flex-1 text-center">
                <div className="text-sm text-white/60 tracking-widest mb-2 border-b border-white/30 pb-1 px-4">X-COORDINATE</div>
                <div className="whitespace-nowrap text-4xl xl:text-5xl text-cyan-400 drop-shadow-[0_0_10px_rgba(34,211,238,0.8)] font-bold tabular-nums">{Number(telemetry.position.x).toFixed(2)}</div>
              </div>
              <div className="min-w-0 flex-1 text-center">
                <div className="text-sm text-white/60 tracking-widest mb-2 border-b border-white/30 pb-1 px-4">Y-COORDINATE</div>
                <div className="whitespace-nowrap text-4xl xl:text-5xl text-cyan-400 drop-shadow-[0_0_10px_rgba(34,211,238,0.8)] font-bold tabular-nums">{Number(telemetry.position.y).toFixed(2)}</div>
              </div>
            </div>

            {/* Empty space block to push everything upward naturally */}
            <div className="mt-auto"></div>
          </div>
        </div>

        {/* 3. UNCERTAINTY */}
        <div className="relative min-h-0 overflow-hidden bg-black/40 backdrop-blur-sm border border-white/20 p-5 flex flex-col justify-between">
          <CornerBrackets />
          
          <div className="flex justify-between items-start w-full">
            <div className="font-mono text-sm text-gray-200 tracking-widest mt-1">UNCERTAINTY</div>
            {/* Made BIGGER: Bold text, padded background, glowing cyan border */}
            <div className="text-xs md:text-sm text-cyan-300 font-bold tracking-widest text-right px-4 py-2 bg-black/80 border border-cyan-500/50 shadow-[0_0_15px_rgba(34,211,238,0.3)]">
              TARGET RECALL: &gt;= 0.80<br/>
              <span className="text-white">STATUS: EVALUATING</span>
            </div>
          </div>
          
          {/* CORRECTED: Spread Out Uncertainty Progress Bars full width */}
          <div className="w-full flex flex-col gap-1.5 mt-6">
             <div className="w-full h-1.5 bg-gray-700 relative"><div className="absolute right-0 h-full w-[85%] bg-cyan-400/80 shadow-[0_0_8px_#22d3ee]"></div></div>
             <div className="w-full h-1 bg-gray-700 relative"><div className="absolute right-0 h-full w-[60%] bg-white/60"></div></div>
             <div className="w-full h-1 bg-gray-700 relative"><div className="absolute right-0 h-full w-[75%] bg-white/40"></div></div>
          </div>

          <div className="flex items-baseline gap-3 mb-2 mt-auto">
            <span className="text-6xl xl:text-7xl text-cyan-400 drop-shadow-[0_0_10px_rgba(34,211,238,0.8)] tracking-tighter font-bold tabular-nums">
              {Number(telemetry.uncertainty).toFixed(2)}
            </span>
            <span className="text-base text-white/60 tracking-widest">METERS</span>
          </div>
          
          <div className="text-[10px] text-gray-400 tracking-widest">
            TEST EVAL: <span className="text-cyan-400 font-bold">{telemetry.recall >= 0.80 ? 'PASSED (>= 0.80)' : 'OPTIMIZING'}</span>
          </div>
          <div className="mt-3 border-t border-cyan-400/30 pt-2 text-[10px] tracking-widest">
            <div className="flex justify-between text-gray-400">
              <span>TRN STATUS</span>
              <span className={telemetry.trn_enabled ? 'text-cyan-300' : 'text-orange-300'}>
                {telemetry.trn_enabled ? 'ENABLED' : 'DISABLED'}
              </span>
            </div>
            <div className="flex justify-between text-gray-400 mt-1">
              <span>LAST RE-LOCALIZATION</span>
              <span className="text-white">{Number(telemetry.last_error_before).toFixed(2)}m <span className="text-cyan-300">→</span> {Number(telemetry.last_error_after).toFixed(2)}m</span>
            </div>
            <div className="flex justify-between text-gray-400 mt-1">
              <span>CORRECTIONS</span>
              <span className="text-white">{telemetry.reloc_count}</span>
            </div>
          </div>
        </div>

      </div>

      {/* ================= LIVE MAP + AUDIT TRAIL ================= */}
      <div className="relative z-10 grid grid-cols-1 lg:grid-cols-3 gap-6 w-full mb-6 h-[360px]">

        {/* LIVE MAP: rover position, uncertainty envelope, trail - 2D or 3D real-DEM view */}
        <div className="relative bg-black/40 backdrop-blur-sm border border-white/20 p-5 flex flex-col lg:col-span-2 overflow-hidden">
          <CornerBrackets />
          <div className="flex items-center justify-between mb-2">
            <div className="font-mono text-sm text-gray-200 tracking-widest">LIVE POSITION MAP</div>
            <div className="flex items-center gap-3">
              <div className="text-[8px] tracking-widest text-gray-400 hidden md:block">
                <span className="text-cyan-300">CYAN</span> / <span className="text-red-400">RED HZ</span> / <span className="text-violet-300">A PURPLE</span> / <span className="text-yellow-300">B YELLOW</span> / <span className="text-green-400">GREEN</span>
              </div>
              <div className="text-[8px] text-gray-400 tracking-widest hidden md:block">TRAIL: {trail.length} PTS</div>
              <div className="flex border border-white/20 text-[9px] tracking-widest">
                <button
                  onClick={() => setMapMode('2d')}
                  className={`px-3 py-1 ${mapMode === '2d' ? 'bg-cyan-400/80 text-black font-bold' : 'text-gray-300 hover:bg-white/10'}`}
                >
                  2D
                </button>
                <button
                  onClick={() => setMapMode('3d')}
                  className={`px-3 py-1 border-l border-white/20 ${mapMode === '3d' ? 'bg-cyan-400/80 text-black font-bold' : 'text-gray-300 hover:bg-white/10'}`}
                >
                  3D
                </button>
              </div>
            </div>
          </div>
          <div className="relative flex-1 min-h-0">
            {mapMode === '2d' ? (
              <RoverMap trail={trail} position={telemetry.position} uncertainty={telemetry.uncertainty} mode={telemetry.mode} pathA={telemetry.path_a} pathB={telemetry.path_b} activePath={telemetry.active_path} hazardPath={telemetry.hazard_path} pathChoice={telemetry.path_choice} hazards={telemetry.hazards} scanState={telemetry.scan_state} routePhase={telemetry.route_phase} />
            ) : (
              <RoverTerrain3D
                apiBase={API_BASE}
                trail={trail}
                position={telemetry.position}
                uncertainty={telemetry.uncertainty}
                mode={telemetry.mode}
                pathA={telemetry.path_a}
                pathB={telemetry.path_b}
                activePath={telemetry.active_path}
                hazardPath={telemetry.hazard_path}
                pathChoice={telemetry.path_choice}
                hazards={telemetry.hazards}
                scanState={telemetry.scan_state}
                routePhase={telemetry.route_phase}
              />
            )}
          </div>
        </div>

        {/* AUDIT TRAIL: recent logged XAI decisions from explain/audit_logger.py */}
        <div className="relative bg-black/40 backdrop-blur-sm border border-white/20 p-5 flex flex-col overflow-hidden">
          <CornerBrackets />
          <div className="flex items-center justify-between mb-2 border-b border-white/10 pb-2">
            <span className="font-mono text-sm text-gray-200 tracking-widest">AUDIT TRAIL</span>
            <span className="text-[8px] text-gray-400 tracking-widest">DECISION LOG</span>
          </div>
          <div className="flex-1 min-h-0">
            <AuditLogPanel entries={auditLog} loading={auditLoading} />
          </div>
        </div>

      </div>

      {/* ================= BOTTOM PANEL: LIVE TERMINAL ================= */}
      <div className="relative z-10 w-full bg-black/60 backdrop-blur-sm border border-white/20 p-5 flex flex-col justify-between h-[120px]">
        <CornerBrackets />
        
        <div className="flex items-center justify-between border-b border-white/10 pb-1">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-cyan-400 animate-ping"></div>
            <span className="text-xs tracking-widest text-cyan-400 font-bold">NAVIGATION REASONING</span>
          </div>
          <span className="text-[8px] text-gray-400">STATUS: STREAMING</span>
        </div>

        <div className="font-mono text-sm text-cyan-300 tracking-wide flex items-start gap-2 pt-2">
          <span className="text-white font-bold">&gt;</span>
          <p className="leading-relaxed animate-pulse">
            {agentLog}
          </p>
        </div>
      </div>
    </div>
  );
}

export default App;