import React, { useState, useEffect } from 'react';

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

function App() {
  const [agentLog, setAgentLog] = useState("Connecting to WebSocket backend...");
  const [telemetry, setTelemetry] = useState({
    mode: 'Connecting',
    position: { x: 0.0, y: 0.0 },
    uncertainty: 0.0,
    precision: 0.0,
    recall: 0.0,
    center_error: 0.0
  });

  useEffect(() => {
    let ws;
    const connectWebSocket = () => {
      ws = new WebSocket('ws://localhost:8000/ws');

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
            center_error: data.center_error ?? 0.0
          });
        } catch (e) {
          console.error("Failed to parse WS packet", e);
        }
      };

      ws.onclose = () => {
        setTimeout(connectWebSocket, 2000);
      };
    };

    connectWebSocket();
    return () => { if (ws) ws.close(); };
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
          <h1 className="text-5xl tracking-[0.2em] font-bold text-white drop-shadow-md">LUNAR TELEMETRY</h1>
          <h2 className="text-sm text-gray-400 tracking-[0.3em] mt-2">SURAKSHA LANDER</h2>
        </div>

        {/* Center: Live Orbital Debris Tracker (Made BIGGER with larger text and padding) */}
        <div className="hidden lg:flex items-center gap-6 border border-white/40 px-8 py-4 bg-black/60 shadow-[0_0_20px_rgba(34,211,238,0.25)]">
          <div className="flex flex-col text-xs text-gray-200 tracking-widest text-right leading-relaxed">
            <span className="font-bold">COORDS HIGH: 9939.12</span>
            <span>CODE: EXECUTION 0.11U</span>
            <span className="text-cyan-400">DOCK OFFLOAD.</span>
          </div>
          <HeaderBarChart />
          <span className="text-lg tracking-widest font-bold text-white">LIVE ORBITAL DEBRIS TRACKER</span>
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
      <div className="relative z-10 grid grid-cols-1 lg:grid-cols-3 gap-6 w-full mb-6 h-[240px]">
        
        {/* 1. ROVER MODE */}
        <div className="relative bg-black/40 backdrop-blur-sm border border-white/20 p-5 flex flex-col justify-between overflow-hidden">
          <CornerBrackets />
          <RadarGears />
          
          <div className="relative z-10 flex flex-col h-full justify-between">
            {/* Moved UP: Title and Connecting/Driving Status */}
            <div>
              <div className="font-mono text-sm text-gray-200 tracking-widest mb-4">ROVER MODE</div>
              <div className="flex items-center gap-4">
                <div className="w-5 h-5 rounded-full bg-cyan-400 shadow-[0_0_15px_#22d3ee]"></div>
                <div className="text-cyan-400 text-6xl drop-shadow-[0_0_10px_rgba(34,211,238,0.8)] font-bold tracking-wide">{telemetry.mode}</div>
              </div>
            </div>
            
            {/* CORRECTED: Spread Out Metrics across the full width */}
            <div className="w-full flex flex-col gap-1 bg-black/70 p-3 border border-white/10 mt-auto">
              <div className="flex justify-between items-end border-b border-white/20 pb-1 mb-1">
                <span className="text-[9px] font-bold text-gray-400">DETECTION METRICS</span>
                <span className="text-[8px] text-gray-400 tracking-widest">SUB-TELEMETRY</span>
              </div>
              <div className="flex justify-between items-center w-full">
                <div className="text-[9px] text-cyan-300">PRECISION: <span className="text-white">{telemetry.precision}</span></div>
                <div className="text-[9px] text-cyan-300">RECALL: <span className="text-white">{telemetry.recall}</span></div>
                <div className="text-[9px] text-cyan-300">CNTR ERR: <span className="text-white">{telemetry.center_error}px</span></div>
              </div>
              <div className="flex items-end gap-[2px] h-4 mt-1">
                {[...Array(20)].map((_, i) => (
                  <div key={i} className="flex-1 bg-white/50 animate-pulse" style={{ height: `${Math.random() * 80 + 20}%`, animationDelay: `${Math.random()}s` }} />
                ))}
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
            <div className="flex justify-around w-full mt-2">
              <div className="text-center">
                <div className="text-sm text-white/60 tracking-widest mb-2 border-b border-white/30 pb-1 px-4">X-COORDINATE</div>
                <div className="text-6xl text-cyan-400 drop-shadow-[0_0_10px_rgba(34,211,238,0.8)] font-bold">{telemetry.position.x}</div>
              </div>
              <div className="text-center">
                <div className="text-sm text-white/60 tracking-widest mb-2 border-b border-white/30 pb-1 px-4">Y-COORDINATE</div>
                <div className="text-6xl text-cyan-400 drop-shadow-[0_0_10px_rgba(34,211,238,0.8)] font-bold">{telemetry.position.y}</div>
              </div>
            </div>

            {/* Empty space block to push everything upward naturally */}
            <div className="mt-auto"></div>
          </div>
        </div>

        {/* 3. UNCERTAINTY */}
        <div className="relative bg-black/40 backdrop-blur-sm border border-white/20 p-5 flex flex-col justify-between">
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
            <span className="text-7xl text-cyan-400 drop-shadow-[0_0_10px_rgba(34,211,238,0.8)] tracking-tighter font-bold">
              {telemetry.uncertainty}
            </span>
            <span className="text-base text-white/60 tracking-widest">METERS</span>
          </div>
          
          <div className="text-[10px] text-gray-400 tracking-widest">
            TEST EVAL: <span className="text-cyan-400 font-bold">{telemetry.recall >= 0.80 ? 'PASSED (>= 0.80)' : 'OPTIMIZING'}</span>
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