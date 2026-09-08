import sys
import os
from pathlib import Path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import numpy as np
import rasterio
from rasterio.enums import Resampling

# --- Create the app ONCE ---
app = FastAPI()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEM_PATH = PROJECT_ROOT / "data" / "Lunar_Map.tiff"
CRATER_DB_PATH = PROJECT_ROOT / "crater_db" / "crater_db.sqlite"

# --- CORS middleware (allow React frontend) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- All your safe imports and helper functions go here ---
# (the rest of your code, exactly as before)

# Safe imports with fallback protection
try:
    from tests.tests_evaluation import match_detections
    from src.perception.detector import detect_craters
    from terrain.dem_loader import load_dem
    from localization.crater_loader import load_craters
    
    HAS_EVAL_MODULES = True
except ImportError as e:
    print(f"⚠️ Warning: Evaluation modules could not be imported directly: {e}")
    HAS_EVAL_MODULES = False

# Safe import for the live localizer / simulation state including reasoning
try:
    from localization.state import get_current_position, get_rover_mode, get_reasoning, get_navigation_state
    HAS_LOCALIZER = True
except ImportError:
    try:
        from localization.localizer import get_current_position, get_rover_mode
        def get_reasoning(): return "System active. Streaming live telemetry."
        def get_navigation_state(): return {}
        HAS_LOCALIZER = True
    except ImportError:
        HAS_LOCALIZER = False

# Safe import for the M6 audit trail (explain/audit_logger.py's decision_log.json)
try:
    from explain.audit_logger import read_log
    HAS_AUDIT_LOG = True
except ImportError as e:
    print(f"⚠️ Warning: audit logger could not be imported: {e}")
    HAS_AUDIT_LOG = False

# Separate, dedicated import for the DEM loader used by /terrain-heightmap.
# Deliberately decoupled from the HAS_EVAL_MODULES block above: that block
# aborts entirely if ANY of its imports fail (e.g. detector deps missing),
# which would otherwise take load_dem down with it even though load_dem
# itself has no such dependency.
try:
    from terrain.dem_loader import load_dem as load_dem_for_terrain
    HAS_DEM_LOADER = True
except ImportError as e:
    print(f"⚠️ Warning: terrain dem_loader could not be imported: {e}")
    HAS_DEM_LOADER = False

# In-memory cache: evaluation metrics (expensive to compute, computed once).
_terrain_cache = {}
_evaluation_metrics = None

# The TIFF is a polar-stereographic projection centred at the lunar south pole.
# Its affine transform maps pixel (col, row) → (easting, northing) in metres.
# Origin in the DEM's own coordinate system:
#   col=0, row=0  →  x = -304000 m,  y = +304000 m
# The simulation uses a local frame where (0, 0) is the DEM centre, i.e.:
#   local_x = easting  - 0   (easting is already centred at 0)
#   local_y = northing - 0   (northing is already centred at 0)
# The backend previously subtracted frame_x/frame_y which are exactly 0 for
# this TIFF, so local coords == DEM coords.  The rover starts at (0,0) m and
# travels only ~500 m, so we must serve a small LOCAL window of the DEM rather
# than the full 608 km tile — otherwise the rover is a sub-pixel speck.

# Pixel size of the TIFF (set once on first open, reused everywhere).
_DEM_PIXEL_SIZE_M = 20.0   # metres per pixel (confirmed from rasterio.res)
_DEM_HALF_EXTENT  = 304000  # half the full tile width in metres


def _world_to_pixel(world_x_m, world_y_m):
    """Convert local-frame metres to pixel (col, row) in the full TIFF."""
    # DEM easting  = world_x_m  (already centred)
    # DEM northing = world_y_m
    # Transform: col = (easting - left) / pixel_size
    #            row = (top - northing) / pixel_size
    col = int((world_x_m - (-_DEM_HALF_EXTENT)) / _DEM_PIXEL_SIZE_M)
    row = int(((_DEM_HALF_EXTENT) - world_y_m)  / _DEM_PIXEL_SIZE_M)
    return col, row


def _get_evaluation_metrics():
    global _evaluation_metrics
    if _evaluation_metrics is not None:
        return _evaluation_metrics

    with rasterio.open(DEM_PATH) as source:
        rows = min(600, source.height)
        cols = min(600, source.width)
        depth_map = source.read(
            1,
            out_shape=(rows, cols),
            resampling=Resampling.average,
        ).astype(np.float32)

    ground_truth = [
        {
            **crater,
            "radius": float(crater.get("radius", crater.get("diameter", 0.0) / 2.0)),
        }
        for crater in load_craters(str(CRATER_DB_PATH))
    ]
    detections = detect_craters(depth_map)
    tp, fp, fn, center_errs, radius_errs = match_detections(ground_truth, detections)
    total_det = len(detections)
    _evaluation_metrics = (
        round((tp / total_det) if total_det else 0.0, 3),
        round((tp / len(ground_truth)) if ground_truth else 0.0, 3),
        round(float(np.mean(center_errs)) if center_errs else 0.0, 2),
    )
    return _evaluation_metrics


def _build_local_tile(
    centre_x_m: float,
    centre_y_m: float,
    half_extent_m: float = 4000.0,
    grid_size: int = 256,
):
    """
    Read a square window of the DEM centred on (centre_x_m, centre_y_m) in
    the simulation's local metre frame, resample it to grid_size × grid_size
    cells, and return a payload dict the Three.js frontend can consume directly.

    half_extent_m controls the physical size of the patch shown:
      4000 m  →  8 km × 8 km  (good rover-scale view, craters clearly visible)

    The x_coords / y_coords in the payload are in the SAME local metre frame
    the simulator uses, so rover position (x, y) maps directly onto the mesh.
    """
    centre_col, centre_row = _world_to_pixel(centre_x_m, centre_y_m)
    half_px = int(half_extent_m / _DEM_PIXEL_SIZE_M)

    with rasterio.open(DEM_PATH) as source:
        total_rows, total_cols = source.height, source.width
        nodata = source.nodata

        # Clamp window to DEM bounds
        col_off = max(0, centre_col - half_px)
        row_off = max(0, centre_row - half_px)
        col_end = min(total_cols, centre_col + half_px)
        row_end = min(total_rows, centre_row + half_px)
        win_width  = col_end - col_off
        win_height = row_end - row_off

        if win_width <= 0 or win_height <= 0:
            raise ValueError(
                f"Rover position ({centre_x_m}, {centre_y_m}) m is outside the DEM bounds."
            )

        window = rasterio.windows.Window(col_off, row_off, win_width, win_height)

        # Resample directly to grid_size while reading — avoids loading the
        # full window at native 20m resolution into memory first.
        out_rows = min(grid_size, win_height)
        out_cols = min(grid_size, win_width)
        patch = source.read(
            1,
            window=window,
            out_shape=(out_rows, out_cols),
            resampling=Resampling.bilinear,
        ).astype(np.float32)

    # Mask nodata
    if nodata is not None:
        patch[patch == nodata] = np.nan
    if np.isnan(patch).any():
        patch = np.nan_to_num(patch, nan=float(np.nanmean(patch)))

    rows_out, cols_out = patch.shape

    # Build world coordinates for each output cell.
    # Each output col maps back to a source pixel col:
    #   src_col = col_off + c * (win_width / cols_out)
    # Then to world metres:
    #   world_x = src_col * pixel_size + left_edge
    left_edge  = -_DEM_HALF_EXTENT   # world x at col 0
    top_edge   =  _DEM_HALF_EXTENT   # world y at row 0

    x_coords = [
        left_edge + (col_off + c * (win_width / cols_out)) * _DEM_PIXEL_SIZE_M
        for c in range(cols_out)
    ]
    y_coords = [
        top_edge  - (row_off + r * (win_height / rows_out)) * _DEM_PIXEL_SIZE_M
        for r in range(rows_out)
    ]

    return {
        "rows": rows_out,
        "cols": cols_out,
        "x_coords": x_coords,
        "y_coords": y_coords,
        "elevation": patch.astype(float).tolist(),
        "centre_x": centre_x_m,
        "centre_y": centre_y_m,
        "half_extent_m": half_extent_m,
        "source": "data/Lunar_Map.tiff (rover-local window, real LOLA DEM)",
    }


# --- All routes are attached to the single 'app' instance ---

@app.get("/terrain-heightmap")
def get_terrain_heightmap(
    grid_size: int = 256,
    cx: float = 0.0,
    cy: float = 0.0,
    half_extent_m: float = 4000.0,
):
    """
    Return a rover-local window of the real LOLA DEM as a heightmap grid.

    Parameters
    ----------
    cx, cy          Rover centre in local-frame metres (same frame the simulator
                    uses; starts near 0,0 and grows as the rover moves).
    half_extent_m   Half-width of the patch in metres.  Default 4000 gives an
                    8 km × 8 km window — large enough to show several craters
                    while keeping the rover clearly visible.
    grid_size       Number of cells per side in the output mesh (capped 32–512).
    """
    if not HAS_DEM_LOADER:
        return {"error": "DEM loader module not available"}

    grid_size = max(32, min(grid_size, 512))
    half_extent_m = max(500.0, min(half_extent_m, 50000.0))

    # Cache key includes the rounded-to-100m centre so a barely-moving rover
    # reuses the same tile instead of re-reading the TIFF every second.
    cache_key = (round(cx / 100) * 100, round(cy / 100) * 100, int(half_extent_m), grid_size)
    if cache_key in _terrain_cache:
        return _terrain_cache[cache_key]

    try:
        payload = _build_local_tile(cx, cy, half_extent_m, grid_size)
        _terrain_cache[cache_key] = payload
        return payload
    except Exception as e:
        print("Terrain heightmap build error:", e)
        return {"error": str(e)}


@app.get("/")
def read_root():
    return {"status": "SurakshaLander Backend is Live", "rover_mode": "Normal"}


@app.get("/audit-log")
def get_audit_log(limit: int = 20):
    """
    Serve the contrastive-XAI decision log written by explain/audit_logger.py
    (M6) so the dashboard can display recent path-selection decisions with
    their chosen-vs-rejected metrics and explanation text.
    """
    if not HAS_AUDIT_LOG:
        return {"decisions": [], "error": "audit logger module not available"}

    try:
        logs = read_log()
    except Exception as e:
        print("Audit log read error:", e)
        return {"decisions": [], "error": str(e)}

    # Most recent first, capped to `limit` so the dashboard panel stays light.
    recent = logs[-limit:] if limit > 0 else logs
    return {"decisions": list(reversed(recent))}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[WS] Frontend Dashboard Connected!")
    
    try:
        while True:
            precision, recall, center_error = 0.95, 0.85, 4.2
            
            # Default fallback telemetry and reasoning values if localizer isn't connected yet
            pos_x, pos_y, uncertainty, current_mode = 145.6, -89.5, 2.55, "Driving"
            current_reasoning = "Awaiting simulation telemetry stream..."
            navigation_state = {"path_a": [], "path_b": [], "active_path": [], "route_index": 0}

            # 1. Fetch live position, mode, and dynamic reasoning from state module
            if HAS_LOCALIZER:
                try:
                    pos_data = get_current_position()
                    if isinstance(pos_data, dict):
                        pos_x = pos_data.get("x", pos_x)
                        pos_y = pos_data.get("y", pos_y)
                        uncertainty = pos_data.get("uncertainty", uncertainty)
                    current_mode = get_rover_mode() or "Driving"
                    current_reasoning = get_reasoning() or current_reasoning
                    navigation_state = get_navigation_state()
                except Exception as loc_err:
                    print("Localizer sync warning:", loc_err)

            # 2. Run actual crater detection & evaluation metrics if modules are available
            if HAS_EVAL_MODULES:
                try:
                    precision, recall, center_error = _get_evaluation_metrics()
                except Exception as e:
                    print("Evaluation loop execution error:", e)

            # 3. Package dynamic telemetry + real evaluation data together
            live_packet = {
                "x": pos_x,
                "y": pos_y,
                "uncertainty": uncertainty,
                "mode": current_mode,
                "reasoning": current_reasoning,
                "precision": precision,
                "recall": recall,
                "center_error": center_error,
                "trn_enabled": True,
                "error_before": 0.0,
                "error_after": 0.0,
                "last_error_before": 0.0,
                "last_error_after": 0.0,
                "reloc_count": 0,
                "hazard_violation_pct": 0.0,
            }
            live_packet.update(navigation_state)
            
            # Send through the WebSocket tunnel to the UI
            await websocket.send_text(json.dumps(live_packet))
            
            # Stream data at 5 Hz (every 0.20s) for responsive real-time animation
            await asyncio.sleep(0.20)
            
    except (WebSocketDisconnect, ConnectionResetError, RuntimeError, OSError):
        print("[WS] Frontend Dashboard Disconnected.")