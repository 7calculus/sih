import { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// Vertical exaggeration so crater relief is readable.
// The LOLA DEM has ~2000 m relief over an 8 km window → realistic, but small
// on screen.  5× makes craters immediately obvious without distorting shapes.
const VERTICAL_EXAGGERATION = 5;

// How far (metres) the rover must travel from the tile centre before we
// re-fetch a new tile centred on the new position.  4000 m = half the default
// window, so the rover will always be close to the tile centre.
const RETILE_THRESHOLD_M = 500;

// Size of the local DEM window to request (metres each side of rover centre).
const HALF_EXTENT_M = 4000;

// Height of the rover's centre of mass above the terrain surface.
const ROVER_GROUND_CLEARANCE = 4.5;

const heightmapCache = new Map();

function closestIndex(arr, val) {
  let lo = 0, hi = arr.length - 1;
  const increasing = arr[hi] >= arr[0];
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (increasing ? arr[mid] < val : arr[mid] > val) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Fetch a rover-local DEM tile from the backend. */
function fetchTile(apiBase, cx, cy) {
  const url = `${apiBase}/terrain-heightmap?grid_size=256&cx=${cx.toFixed(1)}&cy=${cy.toFixed(1)}&half_extent_m=${HALF_EXTENT_M}`;
  const cached = heightmapCache.get(url);
  if (cached) return Promise.resolve(cached);
  return fetch(url)
    .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(d => { if (d.error) throw new Error(d.error); heightmapCache.set(url, d); return d; });
}

/** Build or rebuild the terrain mesh geometry from a tile payload. */
function buildTerrainGeo(data) {
  const { rows, cols, elevation, x_coords, y_coords } = data;
  const elevFlat = elevation.flat();
  const elevMean = elevFlat.reduce((a, b) => a + b, 0) / elevFlat.length;
  const elevMin  = Math.min(...elevFlat);
  const elevMax  = Math.max(...elevFlat);
  const elevRange = Math.max(elevMax - elevMin, 1);

  const geo = new THREE.PlaneGeometry(1, 1, cols - 1, rows - 1);
  const posAttr  = geo.attributes.position;
  const colorBuf = new Float32Array(cols * rows * 3);

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const vi = r * cols + c;
      const wx = x_coords[c];
      const wz = y_coords[r];
      const h  = (elevation[r][c] - elevMean) * VERTICAL_EXAGGERATION;
      posAttr.setXYZ(vi, wx, h, wz);

      // Darker in crater floors, brighter on raised rims/ridges
      const norm  = (elevation[r][c] - elevMin) / elevRange;
      const base  = 0.20 + norm * 0.55;
      colorBuf[vi * 3]     = base * (1 - 0.07 * (1 - norm));  // slight red dip in craters
      colorBuf[vi * 3 + 1] = base * (1 - 0.04 * (1 - norm));
      colorBuf[vi * 3 + 2] = base * (1 + 0.10 * (1 - norm));  // blue tint in shadow
    }
  }

  posAttr.needsUpdate = true;
  geo.setAttribute('color', new THREE.BufferAttribute(colorBuf, 3));
  geo.computeVertexNormals();

  const sampleHeight = (wx, wz) => {
    const c = Math.max(0, Math.min(cols - 1, closestIndex(x_coords, wx)));
    const r = Math.max(0, Math.min(rows - 1, closestIndex(y_coords, wz)));
    return (elevation[r][c] - elevMean) * VERTICAL_EXAGGERATION;
  };

  return { geo, sampleHeight };
}

export default function RoverTerrain3D({
  apiBase, trail, position, uncertainty, mode = 'Driving',
  pathA = [], pathB = [], activePath = [], hazardPath = [],
  pathChoice = 'A', hazards = [], scanState = 'clear', routePhase = 'cyan',
}) {
  const mountRef        = useRef(null);
  const sceneStateRef   = useRef(null);
  const lastPositionRef = useRef(position);
  const tileCentreRef   = useRef({ x: null, y: null }); // centre of the current tile
  const [status,   setStatus]   = useState('loading');
  const [errorMsg, setErrorMsg] = useState('');

  // ── one-time Three.js scene setup ──────────────────────────────────────────
  useEffect(() => {
    const mountEl = mountRef.current;
    if (!mountEl) return;
    let cancelled = false;

    const scene    = new THREE.Scene();
    scene.background = new THREE.Color(0x02030a);
    scene.fog        = new THREE.FogExp2(0x02030a, 0.00003);

    const camera = new THREE.PerspectiveCamera(
      55, mountEl.clientWidth / Math.max(mountEl.clientHeight, 1), 0.5, 60000,
    );
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mountEl.clientWidth, mountEl.clientHeight);
    mountEl.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping  = true;
    controls.dampingFactor  = 0.10;
    controls.autoRotate     = false;
    controls.minDistance    = 5;
    controls.maxDistance    = 6000;

    // Grazing polar sunlight (low angle — realistic for lunar south pole)
    const sun = new THREE.DirectionalLight(0xfff5e0, 2.4);
    sun.position.set(-800, 350, 500);
    scene.add(sun);
    scene.add(new THREE.AmbientLight(0x283850, 1.0));
    scene.add(new THREE.HemisphereLight(0x304060, 0x050505, 0.5));

    // Starfield
    const starBuf = new Float32Array(3000 * 3);
    for (let i = 0; i < 3000; i++) {
      const rr = 15000 + Math.random() * 10000;
      const th = Math.random() * Math.PI * 2;
      const ph = Math.acos(2 * Math.random() - 1);
      starBuf[i*3]   = rr * Math.sin(ph) * Math.cos(th);
      starBuf[i*3+1] = Math.abs(rr * Math.cos(ph)) + 800;
      starBuf[i*3+2] = rr * Math.sin(ph) * Math.sin(th);
    }
    const starGeo = new THREE.BufferGeometry();
    starGeo.setAttribute('position', new THREE.BufferAttribute(starBuf, 3));
    scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0xffffff, size: 2, sizeAttenuation: false })));

    // ── Rover model ──────────────────────────────────────────────────────────
    const roverGroup = new THREE.Group();

    const chassisMat = new THREE.MeshStandardMaterial({ color: 0xc0ccd6, metalness: 0.45, roughness: 0.7 });
    const chassis = new THREE.Mesh(new THREE.BoxGeometry(9, 3, 14), chassisMat);
    chassis.position.y = ROVER_GROUND_CLEARANCE;
    roverGroup.add(chassis);

    const mastMat = new THREE.MeshStandardMaterial({ color: 0x22d3ee, emissive: 0x064e6e, emissiveIntensity: 1.1 });
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.7, 7, 10), mastMat);
    mast.position.y = ROVER_GROUND_CLEARANCE + 5;
    roverGroup.add(mast);

    const wheelMat = new THREE.MeshStandardMaterial({ color: 0x18202e, roughness: 0.9 });
    for (const xOff of [-5.5, 5.5]) {
      for (const zOff of [-5, 5]) {
        const wheel = new THREE.Mesh(new THREE.CylinderGeometry(2.2, 2.2, 1.5, 16), wheelMat);
        wheel.rotation.z = Math.PI / 2;
        wheel.position.set(xOff, ROVER_GROUND_CLEARANCE - 1.8, zOff);
        roverGroup.add(wheel);
      }
    }
    const solarMat = new THREE.MeshStandardMaterial({ color: 0x1a3a5c, metalness: 0.2, roughness: 0.5 });
    for (const xOff of [-8, 8]) {
      const panel = new THREE.Mesh(new THREE.BoxGeometry(5.5, 0.4, 9), solarMat);
      panel.position.set(xOff, ROVER_GROUND_CLEARANCE + 2, 0);
      roverGroup.add(panel);
    }
    scene.add(roverGroup);

    // ── Uncertainty ring ─────────────────────────────────────────────────────
    const ringGeo = new THREE.RingGeometry(0.85, 1.0, 64);
    ringGeo.rotateX(-Math.PI / 2);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0x22c55e, transparent: true, opacity: 0.5, side: THREE.DoubleSide,
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.userData.baseRadius = Math.max(uncertainty, 2);
    scene.add(ring);

    // ── Trail line ───────────────────────────────────────────────────────────
    const trailLine = new THREE.Line(
      new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.8 }),
    );
    scene.add(trailLine);

    // ── Route lines ──────────────────────────────────────────────────────────
    const makeRoute = (color, dashed) => {
      const mat = dashed
        ? new THREE.LineDashedMaterial({ color, dashSize: 10, gapSize: 6 })
        : new THREE.LineBasicMaterial({ color });
      const line = new THREE.Line(new THREE.BufferGeometry(), mat);
      scene.add(line);
      return line;
    };
    const routeA      = makeRoute(0xc084fc, true);  // neon purple
    const routeB      = makeRoute(0xfacc15, true);  // yellow
    const activeRoute = makeRoute(0x22d3ee, false); // cyan cruise default
    const hazardRoute = makeRoute(0xef4444, false); // red blocked path


    // Persistent scene state shared between effects
    const s = {
      scene, camera, renderer, controls,
      roverMesh: roverGroup, uncertaintyRing: ring,
      trailLine, routeA, routeB, activeRoute, hazardRoute,
      hazardMeshes: [],
      terrainMesh: null, wireMesh: null,
      sampleHeight: () => 0,
      targetPos:   new THREE.Vector3(),
      currentPos:  new THREE.Vector3(),
      cameraTarget: new THREE.Vector3(),
      heading: new THREE.Vector3(0, 0, 1),
      lastMovedT: 0,
      animId: null,
      ready: false,
    };
    sceneStateRef.current = s;

    const onResize = () => {
      camera.aspect = mountEl.clientWidth / Math.max(mountEl.clientHeight, 1);
      camera.updateProjectionMatrix();
      renderer.setSize(mountEl.clientWidth, mountEl.clientHeight);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mountEl);

    // ── applyTile: build/replace terrain mesh from a tile payload ────────────
    // This is called on the first load and again whenever the rover moves
    // far enough that a new tile is needed.
    s.applyTile = (data) => {
      // Remove old terrain
      if (s.terrainMesh) { scene.remove(s.terrainMesh); s.terrainMesh.geometry.dispose(); }
      if (s.wireMesh)    { scene.remove(s.wireMesh);    s.wireMesh.geometry.dispose(); }

      const { geo, sampleHeight } = buildTerrainGeo(data);

      const solidMat = new THREE.MeshStandardMaterial({
        vertexColors: true, flatShading: false, roughness: 0.95, metalness: 0.02,
      });
      s.terrainMesh = new THREE.Mesh(geo, solidMat);
      scene.add(s.terrainMesh);

      const wireMat = new THREE.MeshBasicMaterial({
        color: 0x3a5070, wireframe: true, transparent: true, opacity: 0.06,
      });
      s.wireMesh = new THREE.Mesh(geo, wireMat);
      scene.add(s.wireMesh);

      s.sampleHeight = sampleHeight;

      // Place rover on the new terrain
      const initH = sampleHeight(position.x, position.y);
      s.currentPos.set(position.x, initH + ROVER_GROUND_CLEARANCE, position.y);
      s.targetPos.copy(s.currentPos);
      s.roverMesh.position.copy(s.currentPos);

      // Seat the camera behind-and-above the rover if this is the first tile
      if (!s.ready) {
        camera.position.set(position.x - 80, initH + 40, position.y - 80);
        controls.target.set(position.x, initH, position.y);
        controls.update();
        s.ready = true;
      }
    };

    // ── animation loop ────────────────────────────────────────────────────────
    const clock = new THREE.Clock();
    let pulseT = 0;
    const animate = () => {
      const dt = Math.min(clock.getDelta(), 0.1);
      pulseT += dt;

      if (s.ready) {
        // Glide rover toward latest telemetry target
        s.currentPos.lerp(s.targetPos, Math.min(1, dt * 2.5));
        s.roverMesh.position.copy(s.currentPos);

        // Rotate rover to face direction of travel
        const targetYaw  = Math.atan2(s.heading.z, s.heading.x);
        const dyaw = Math.atan2(
          Math.sin(targetYaw - s.roverMesh.rotation.y),
          Math.cos(targetYaw - s.roverMesh.rotation.y),
        );
        s.roverMesh.rotation.y += dyaw * Math.min(1, dt * 4.5);

        // Follow-cam: re-engage after rover moves
        if (performance.now() - s.lastMovedT < 3000) {
          const back = s.heading.clone().multiplyScalar(-70);
          camera.position.lerp(
            new THREE.Vector3(s.currentPos.x + back.x, s.currentPos.y + 35, s.currentPos.z + back.z),
            Math.min(1, dt * 1.4),
          );
          s.cameraTarget.set(
            s.currentPos.x + s.heading.x * 50,
            s.currentPos.y - 2,
            s.currentPos.z + s.heading.z * 50,
          );
          controls.target.lerp(s.cameraTarget, Math.min(1, dt * 2));
        }

        // Uncertainty ring: follows rover, pulses
        if (ring) {
          ring.position.set(
            s.currentPos.x,
            s.currentPos.y - ROVER_GROUND_CLEARANCE + 0.4,
            s.currentPos.z,
          );
          const r = ring.userData.baseRadius * (1 + 0.06 * Math.sin(pulseT * 1.8));
          ring.scale.set(r, r, r);
        }
      }

      controls.update();
      renderer.render(scene, camera);
      s.animId = requestAnimationFrame(animate);
    };
    animate();

    // Initial tile fetch (centred on rover start position (0, 0))
    fetchTile(apiBase, position.x, position.y)
      .then(data => {
        if (cancelled) return;
        tileCentreRef.current = { x: position.x, y: position.y };
        s.applyTile(data);
        setStatus('ready');
      })
      .catch(err => {
        if (!cancelled) { setStatus('error'); setErrorMsg(String(err.message || err)); }
      });

    return () => {
      cancelled = true;
      if (s.animId) cancelAnimationFrame(s.animId);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      scene.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          (Array.isArray(obj.material) ? obj.material : [obj.material]).forEach(m => m.dispose());
        }
      });
      if (mountEl.contains(renderer.domElement)) mountEl.removeChild(renderer.domElement);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

  // ── Re-tile when rover moves > RETILE_THRESHOLD_M from current tile centre ─
  useEffect(() => {
    const s = sceneStateRef.current;
    if (!s || !s.ready) return;

    const tc = tileCentreRef.current;
    const distFromCentre = tc.x !== null
      ? Math.hypot(position.x - tc.x, position.y - tc.y)
      : Infinity;

    if (distFromCentre > RETILE_THRESHOLD_M) {
      fetchTile(apiBase, position.x, position.y)
        .then(data => {
          if (!sceneStateRef.current) return;
          tileCentreRef.current = { x: position.x, y: position.y };
          sceneStateRef.current.applyTile(data);
        })
        .catch(err => console.warn('Re-tile fetch failed:', err));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Math.round(position.x / 100), Math.round(position.y / 100)]);

  // ── Sync rover position + heading every telemetry tick ───────────────────
  useEffect(() => {
    const s = sceneStateRef.current;
    if (!s || !s.ready) return;

    const prev = lastPositionRef.current;
    const dx = position.x - prev.x;
    const dz = position.y - prev.y;
    if (Math.hypot(dx, dz) > 0.05) {
      s.heading.set(dx, 0, dz).normalize();
      s.lastMovedT = performance.now();
    }
    lastPositionRef.current = position;

    const groundH = s.sampleHeight(position.x, position.y);
    s.targetPos.set(position.x, groundH + ROVER_GROUND_CLEARANCE, position.y);

    if (s.uncertaintyRing) {
      s.uncertaintyRing.userData.baseRadius = Math.max(uncertainty, 2);
      const m = (mode || '').toLowerCase();
      const col =
        m.includes('hazard') || m.includes('relocal') ? 0xef4444 :
        m.includes('caution') ? 0xfacc15 :
        0x22d3ee;
      s.uncertaintyRing.material.color.setHex(col);
    }
  }, [position.x, position.y, uncertainty, scanState, mode]);

  // ── Rebuild trail ─────────────────────────────────────────────────────────
  useEffect(() => {
    const s = sceneStateRef.current;
    if (!s || !s.ready || !s.trailLine || trail.length < 2) return;
    const pts = trail.map(p => new THREE.Vector3(p.x, s.sampleHeight(p.x, p.y) + 1.5, p.y));
    s.trailLine.geometry.dispose();
    s.trailLine.geometry = new THREE.BufferGeometry().setFromPoints(pts);
  }, [trail]);

  // ── Rebuild route lines + hazard markers ─────────────────────────────────
  useEffect(() => {
    const s = sceneStateRef.current;
    if (!s || !s.ready) return;

    const updateLine = (line, pts, heightOffset = 2.0) => {
      if (!line) return;
      line.geometry.dispose();
      line.geometry = new THREE.BufferGeometry().setFromPoints(
        pts.map(([x, z]) => new THREE.Vector3(x, s.sampleHeight(x, z) + heightOffset, z)),
      );
      if (line.computeLineDistances) line.computeLineDistances();
      line.visible = pts.length > 1;
    };

    const phase = routePhase || (scanState === 'hazard' ? 'hazard' : 'cyan');
    const isEvaluating = phase === 'candidates' || phase === 'hazard';
    updateLine(s.routeA, pathA, 2.4);
    updateLine(s.routeB, pathB, 2.8);
    updateLine(s.activeRoute, isEvaluating ? [] : activePath, 3.2);
    updateLine(s.hazardRoute, hazardPath || [], 3.6);

    s.hazardMeshes.forEach(m => { s.scene.remove(m); m.geometry.dispose(); m.material.dispose(); });
    s.hazardMeshes = hazards.map(h => {
      const isCrater = (h.type || '') === 'crater';
      const cone = new THREE.Mesh(
        new THREE.ConeGeometry(3, 9, 8),
        new THREE.MeshStandardMaterial({
          color: isCrater ? 0xa855f7 : 0xef4444,
          emissive: isCrater ? 0x6b21a8 : 0x7f1d1d,
          emissiveIntensity: 0.9,
        }),
      );
      cone.position.set(h.x, s.sampleHeight(h.x, h.y) + 4.5, h.y);
      s.scene.add(cone);
      return cone;
    });

    const activeColor =
      phase === 'green' ? 0x22c55e :
      phase === 'hazard' ? 0xef4444 :
      0x22d3ee;
    s.routeA.material.color.set(0xc084fc);
    s.routeB.material.color.set(0xfacc15);
    s.activeRoute.material.color.set(activeColor);
    if (s.hazardRoute) s.hazardRoute.material.color.set(0xef4444);
    // Winner stays bright, alternative candidate dims gracefully
    if (phase === 'green') {
      s.routeA.material.opacity = pathChoice === 'A' ? 1.0 : 0.4;
      s.routeB.material.opacity = pathChoice === 'B' ? 1.0 : 0.4;
      s.routeA.material.transparent = true;
      s.routeB.material.transparent = true;
    } else {
      s.routeA.material.opacity = 0.95;
      s.routeB.material.opacity = 0.95;
    }
  }, [pathA, pathB, activePath, hazardPath, pathChoice, hazards, scanState, routePhase]);

  return (
    <div className="relative w-full h-full">
      <div ref={mountRef} className="w-full h-full" />

      {status === 'loading' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 text-[10px] text-cyan-300 tracking-widest text-center px-4 gap-3">
          <div className="w-6 h-6 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
          READING LOLA DEM TILE CENTRED ON ROVER POSITION...
        </div>
      )}

      {status === 'error' && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/80 text-[10px] text-red-400 tracking-widest text-center px-6">
          TERRAIN LOAD FAILED: {errorMsg}<br /><br />
          Ensure <span className="text-yellow-300">data/Lunar_Map.tiff</span> exists in{' '}
          <span className="text-yellow-300">sih/sih/</span> and the backend is running.
        </div>
      )}

      {status === 'ready' && (
        <div className="absolute bottom-1 right-2 text-[7px] text-gray-500 tracking-widest pointer-events-none">
          LOLA DEM · LOCAL {(HALF_EXTENT_M * 2 / 1000).toFixed(0)} km WINDOW · {VERTICAL_EXAGGERATION}× VERT · DRAG TO ORBIT
        </div>
      )}
    </div>
  );
}
