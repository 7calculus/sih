import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// Real elevation data from the actual DEM (terrain/dem_loader.py via the
// backend's /terrain-heightmap endpoint) is stretched vertically so relief
// is actually visible - flat DEM patches otherwise look like a plate at
// realistic 1:1 scale. This is a visualization exaggeration only; the
// underlying values served by the backend are the genuine measured
// elevations, unexaggerated.
const VERTICAL_EXAGGERATION = 3;

// Cache fetched heightmaps across component mounts/unmounts (e.g. toggling
// between the 2D and 3D view) so switching back doesn't refetch/rebuild.
const heightmapCache = new Map();

function closestIndex(arr, val) {
  // arr is monotonic (increasing or decreasing) - binary search for the
  // nearest grid line, used to sample terrain height under a world (x,y).
  let lo = 0, hi = arr.length - 1;
  const increasing = arr[hi] > arr[0];
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    const cond = increasing ? arr[mid] < val : arr[mid] > val;
    if (cond) lo = mid + 1; else hi = mid;
  }
  return lo;
}

export default function RoverTerrain3D({ apiBase, trail, position, uncertainty, mode, pathA = [], pathB = [], activePath = [], hazards = [], scanState = 'clear' }) {
  const mountRef = useRef(null);
  const sceneStateRef = useRef(null);
  const lastPositionRef = useRef(position);
  const [status, setStatus] = useState('loading'); // 'loading' | 'ready' | 'error'
  const [errorMsg, setErrorMsg] = useState('');

  // ---- one-time scene setup + real DEM heightmap fetch ----
  useEffect(() => {
    const mountEl = mountRef.current;
    if (!mountEl) return;
    let cancelled = false;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x03040a);

    const camera = new THREE.PerspectiveCamera(50, mountEl.clientWidth / Math.max(mountEl.clientHeight, 1), 0.1, 100000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mountEl.clientWidth, mountEl.clientHeight);
    mountEl.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.autoRotate = false;
    controls.minDistance = 5;
    controls.maxDistance = 5000;

    // Lighting: a low, warm "sun" (grazing polar illumination is realistic
    // for the lunar south pole this DEM covers) plus a cool ambient fill
    // so the unlit side of craters isn't pure black.
    const sun = new THREE.DirectionalLight(0xfff2d9, 1.5);
    sun.position.set(-1, 0.4, 0.6);
    scene.add(sun);
    scene.add(new THREE.AmbientLight(0x30405a, 0.7));
    scene.add(new THREE.HemisphereLight(0x223355, 0x0a0a0a, 0.4));

    // Starfield backdrop (decorative only, not real astrometric data)
    const starGeo = new THREE.BufferGeometry();
    const starCount = 2000;
    const starPos = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount; i++) {
      const r = 3000 + Math.random() * 3000;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      starPos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      starPos[i * 3 + 1] = Math.abs(r * Math.cos(phi)) + 200;
      starPos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0xffffff, size: 1.6, sizeAttenuation: false }));
    scene.add(stars);

    const s = {
      scene, camera, renderer, controls,
      roverMesh: null, uncertaintyRing: null, trailLine: null,
      routeA: null, routeB: null, activeRoute: null, hazardMeshes: [],
      xCoords: null, yCoords: null, elevation: null,
      sampleHeight: () => 0,
      targetPos: new THREE.Vector3(),
      currentPos: new THREE.Vector3(),
      cameraTarget: new THREE.Vector3(),
      heading: new THREE.Vector3(1, 0, 0),
      animId: null,
      ready: false,
    };
    sceneStateRef.current = s;

    const onResize = () => {
      if (!mountEl) return;
      camera.aspect = mountEl.clientWidth / Math.max(mountEl.clientHeight, 1);
      camera.updateProjectionMatrix();
      renderer.setSize(mountEl.clientWidth, mountEl.clientHeight);
    };
    const resizeObserver = new ResizeObserver(onResize);
    resizeObserver.observe(mountEl);

    const buildTerrain = (data) => {
      const { rows, cols, elevation, x_coords, y_coords } = data;

      const elevFlat = elevation.flat();
      const elevMean = elevFlat.reduce((a, b) => a + b, 0) / elevFlat.length;

      const geo = new THREE.PlaneGeometry(1, 1, cols - 1, rows - 1);
      const posAttr = geo.attributes.position;
      const elevationMin = Math.min(...elevFlat);
      const elevationMax = Math.max(...elevFlat);
      const colorAttr = new Float32Array(elevFlat.length * 3);
      let vi = 0;
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const worldX = x_coords[c];
          const worldY = y_coords[r];
          const h = (elevation[r][c] - elevMean) * VERTICAL_EXAGGERATION;
          // three.js is Y-up: elevation goes on Y, the plane itself spans world X/Z.
          posAttr.setXYZ(vi, worldX, h, worldY);
          const normalized = (elevation[r][c] - elevationMin) / Math.max(elevationMax - elevationMin, 1);
          const shade = 0.22 + normalized * 0.58;
          colorAttr[vi * 3] = shade;
          colorAttr[vi * 3 + 1] = shade * 0.96;
          colorAttr[vi * 3 + 2] = shade * 0.88;
          vi++;
        }
      }
      posAttr.needsUpdate = true;
      geo.setAttribute('color', new THREE.BufferAttribute(colorAttr, 3));
      geo.computeVertexNormals();

      const mat = new THREE.MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 1.0, metalness: 0.0 });
      const mesh = new THREE.Mesh(geo, mat);
      scene.add(mesh);

      const sampleHeight = (wx, wy) => {
        const c = closestIndex(x_coords, wx);
        const r = closestIndex(y_coords, wy);
        return (elevation[r][c] - elevMean) * VERTICAL_EXAGGERATION;
      };

      s.xCoords = x_coords;
      s.yCoords = y_coords;
      s.elevation = elevation;
      s.sampleHeight = sampleHeight;

      const spanX = Math.abs(x_coords[cols - 1] - x_coords[0]);
      const spanY = Math.abs(y_coords[rows - 1] - y_coords[0]);
      const span = Math.max(spanX, spanY, 10);
      const centerX = (x_coords[0] + x_coords[cols - 1]) / 2;
      const centerY = (y_coords[0] + y_coords[rows - 1]) / 2;

      const initialHeight = sampleHeight(position.x, position.y);
      camera.position.set(position.x - 45, initialHeight + 24, position.y - 45);
      controls.target.set(position.x + 35, initialHeight, position.y + 35);
      controls.update();

      // Rover marker - a small lander-like cone, easy to read against the terrain.
      const markerSize = 6;
      const roverGroup = new THREE.Group();
      const body = new THREE.Mesh(new THREE.BoxGeometry(7, 2.5, 10), new THREE.MeshStandardMaterial({ color: 0xd7dde5, metalness: 0.55, roughness: 0.6 }));
      body.position.y = 3;
      roverGroup.add(body);
      const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.7, 5, 12), new THREE.MeshStandardMaterial({ color: 0x22d3ee, emissive: 0x075985, emissiveIntensity: 0.8 }));
      mast.position.y = 6.5;
      roverGroup.add(mast);
      const wheelMat = new THREE.MeshStandardMaterial({ color: 0x202733, roughness: 0.9 });
      for (const x of [-4.2, 4.2]) {
        for (const z of [-3.2, 3.2]) {
          const wheel = new THREE.Mesh(new THREE.CylinderGeometry(1.8, 1.8, 1.1, 16), wheelMat);
          wheel.rotation.z = Math.PI / 2;
          wheel.position.set(x, 1.8, z);
          roverGroup.add(wheel);
        }
      }
      scene.add(roverGroup);
      s.roverMesh = roverGroup;

      const routeLine = (points, color, dashed = false) => {
        const geometry = new THREE.BufferGeometry().setFromPoints(points.map(([x, y]) => new THREE.Vector3(x, sampleHeight(x, y) + 1.2, y)));
        const material = dashed
          ? new THREE.LineDashedMaterial({ color, dashSize: 5, gapSize: 3, linewidth: 1 })
          : new THREE.LineBasicMaterial({ color, linewidth: 2 });
        const line = new THREE.Line(geometry, material);
        if (dashed) line.computeLineDistances();
        scene.add(line);
        return line;
      };
      s.routeA = routeLine(pathA, 0xa78bfa, true);
      s.routeB = routeLine(pathB, 0xf97316, true);
      s.activeRoute = routeLine(activePath, 0x22d3ee, false);

      // Uncertainty envelope - a flat ring lying on the terrain around the rover, pulses gently.
      const ringGeo = new THREE.RingGeometry(0.9, 1.0, 48);
      ringGeo.rotateX(-Math.PI / 2);
      const modeColor = scanState === 'hazard' ? 0xef4444 : scanState === 'scanning' ? 0x38bdf8 : 0x22c55e;
      const ringMat = new THREE.MeshBasicMaterial({ color: modeColor, transparent: true, opacity: 0.55, side: THREE.DoubleSide });
      const ring = new THREE.Mesh(ringGeo, ringMat);
      ring.userData.baseRadius = 1;
      scene.add(ring);
      s.uncertaintyRing = ring;

      // Trail line, populated by the trail-sync effect below.
      const trailGeo = new THREE.BufferGeometry();
      const trailMat = new THREE.LineBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.85 });
      const line = new THREE.Line(trailGeo, trailMat);
      scene.add(line);
      s.trailLine = line;

      s.currentPos.set(position.x, sampleHeight(position.x, position.y) + markerSize, position.y);
      s.roverMesh.position.copy(s.currentPos);
      s.targetPos.copy(s.currentPos);
      s.cameraTarget.set(position.x + 35, sampleHeight(position.x, position.y), position.y + 35);

      s.ready = true;
    };

    const cacheKey = `${apiBase}/terrain-heightmap?frame=local-v2`;
    const cached = heightmapCache.get(cacheKey);
    const loadTerrain = cached
      ? Promise.resolve(cached)
      : fetch(`${apiBase}/terrain-heightmap?grid_size=128&frame=local-v2`)
          .then(res => {
            if (!res.ok) throw new Error(`status ${res.status}`);
            return res.json();
          })
          .then(data => {
            if (data.error) throw new Error(data.error);
            heightmapCache.set(cacheKey, data);
            return data;
          });

    loadTerrain
      .then(data => {
        if (cancelled) return;
        buildTerrain(data);
        setStatus('ready');
      })
      .catch(err => {
        console.error('terrain heightmap fetch failed', err);
        if (!cancelled) { setStatus('error'); setErrorMsg(String(err.message || err)); }
      });

    const clock = new THREE.Clock();
    let pulseT = 0;
    const animate = () => {
      const dt = Math.min(clock.getDelta(), 0.1);
      pulseT += dt;

      if (s.ready && s.roverMesh) {
        // Smoothly glide toward the latest telemetry position rather than
        // snapping - telemetry only arrives ~1x/second, so this is what
        // makes the rover's motion actually read as animated.
        s.currentPos.lerp(s.targetPos, Math.min(1, dt * 2.2));
        s.roverMesh.position.copy(s.currentPos);
        s.roverMesh.rotation.y += dt * 0.6;

        // Keep the view at rover scale: the camera looks forward from the
        // rover instead of showing the entire 608 km DEM as an unreadable dot.
        const cameraOffset = s.heading.clone().multiplyScalar(-45);
        const cameraPosition = new THREE.Vector3(
          s.currentPos.x + cameraOffset.x,
          s.currentPos.y + 24,
          s.currentPos.z + cameraOffset.z,
        );
        camera.position.lerp(cameraPosition, Math.min(1, dt * 2.5));
        s.cameraTarget.set(
          s.currentPos.x + s.heading.x * 45,
          s.currentPos.y - 4,
          s.currentPos.z + s.heading.z * 45,
        );
        controls.target.lerp(s.cameraTarget, Math.min(1, dt * 3));

        if (s.uncertaintyRing) {
          s.uncertaintyRing.position.set(s.currentPos.x, s.currentPos.y + 0.4, s.currentPos.z);
          const pulse = 1 + 0.08 * Math.sin(pulseT * 2.2);
          const r = s.uncertaintyRing.userData.baseRadius * pulse;
          s.uncertaintyRing.scale.set(r, r, r);
        }
      }

      controls.update();
      renderer.render(scene, camera);
      s.animId = requestAnimationFrame(animate);
    };
    animate();

    return () => {
      cancelled = true;
      if (s.animId) cancelAnimationFrame(s.animId);
      resizeObserver.disconnect();
      controls.dispose();
      renderer.dispose();
      scene.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
          else obj.material.dispose();
        }
      });
      if (mountEl.contains(renderer.domElement)) mountEl.removeChild(renderer.domElement);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

  // ---- push new telemetry into the scene without rebuilding it ----
  useEffect(() => {
    const s = sceneStateRef.current;
    if (!s || !s.ready) return;
    const previous = lastPositionRef.current;
    const dx = position.x - previous.x;
    const dz = position.y - previous.y;
    if (Math.hypot(dx, dz) > 0.01) s.heading.set(dx, 0, dz).normalize();
    lastPositionRef.current = position;
    const groundH = s.sampleHeight(position.x, position.y);
    s.targetPos.set(position.x, groundH + 2, position.y);
    if (s.uncertaintyRing) {
      s.uncertaintyRing.userData.baseRadius = Math.max(uncertainty, 2);
    }
  }, [position.x, position.y, uncertainty]);

  // ---- rebuild the trail line whenever trail history grows ----
  useEffect(() => {
    const s = sceneStateRef.current;
    if (!s || !s.ready || !s.trailLine || trail.length < 2) return;
    const pts = trail.map(p => new THREE.Vector3(p.x, s.sampleHeight(p.x, p.y) + 1.2, p.y));
    s.trailLine.geometry.dispose();
    s.trailLine.geometry = new THREE.BufferGeometry().setFromPoints(pts);
  }, [trail]);

  useEffect(() => {
    const s = sceneStateRef.current;
    if (!s || !s.ready) return;
    const updateLine = (line, points) => {
      if (!line) return;
      line.geometry.dispose();
      line.geometry = new THREE.BufferGeometry().setFromPoints(
        points.map(([x, y]) => new THREE.Vector3(x, s.sampleHeight(x, y) + 1.2, y)),
      );
      if (line.computeLineDistances) line.computeLineDistances();
    };
    updateLine(s.routeA, pathA);
    updateLine(s.routeB, pathB);
    updateLine(s.activeRoute, activePath);

    s.hazardMeshes.forEach(mesh => {
      s.scene.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
    });
    s.hazardMeshes = hazards.map(hazard => {
      const marker = new THREE.Mesh(
        new THREE.ConeGeometry(2.8, 7, 8),
        new THREE.MeshStandardMaterial({ color: 0xef4444, emissive: 0x7f1d1d, emissiveIntensity: 0.8 }),
      );
      marker.position.set(hazard.x, s.sampleHeight(hazard.x, hazard.y) + 3.5, hazard.y);
      s.scene.add(marker);
      return marker;
    });
  }, [pathA, pathB, activePath, hazards]);

  return (
    <div className="relative w-full h-full">
      <div ref={mountRef} className="w-full h-full" />
      {status === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/70 text-[10px] text-cyan-300 tracking-widest text-center px-4">
          LOADING REAL DEM TERRAIN MESH FROM BACKEND...
        </div>
      )}
      {status === 'error' && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/70 text-[10px] text-red-400 tracking-widest text-center px-4">
          TERRAIN LOAD FAILED: {errorMsg}<br />
          Check that data/Lunar_Map.tiff exists on the backend and /terrain-heightmap responds.
        </div>
      )}
      {status === 'ready' && (
        <div className="absolute bottom-1 right-2 text-[7px] text-gray-500 tracking-widest pointer-events-none">
          REAL DEM &middot; ELEVATION EXAGGERATED {VERTICAL_EXAGGERATION}&times; FOR VISIBILITY
        </div>
      )}
    </div>
  );
}
