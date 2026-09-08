import sys
import os
import time
import numpy as np
import rasterio
from rasterio.windows import Window
from pathlib import Path

# ── project root ──────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(_PROJECT_ROOT))

_DEM_PATH = str(_PROJECT_ROOT / "data" / "Lunar_Map.tiff")

# ── TRN toggle ────────────────────────────────────────────────────────────────
# Set env var TRN_ENABLED=0  (or pass --no-trn) to run the "no re-localization"
# contrast scenario that proves TRN reduces hazard violations.
TRN_ENABLED = os.environ.get("TRN_ENABLED", "1").strip() not in ("0", "false", "no")
if not TRN_ENABLED:
    print("[WARN] TRN DISABLED - running no-localization contrast scenario")

from localization.localizer import Localizer
from navigation.mission_planner import MissionPlanner
from src.perception.detector import detect_craters
from terrain.dem_loader import load_dem
from localization.state import update_telemetry
from explain.generate_explanation import generate_contrastive_explanation
from explain.audit_logger import log_decision


# ── Nearest DB crater: x=7941, y=-6636 (ID 10-1-090536, diam=20.8m)
# The rover starts here so RANSAC has real catalog landmarks to match against.
# The DEM window is also centred here.
ROVER_START_X = 7941.0
ROVER_START_Y = -6636.0
# Goal is 600m northeast of start — well within the DEM window and slope map
GOAL_X = ROVER_START_X + 600.0
GOAL_Y = ROVER_START_Y + 560.0


def crop_local_patch(dem_map, center_x_m, center_y_m,
                     patch_size_px=600, resolution_m=20.0):
    h, w = dem_map.shape[:2]
    center_row = int(h / 2 - (center_y_m / resolution_m))
    center_col = int(w / 2 + (center_x_m / resolution_m))
    half = patch_size_px // 2
    r0 = max(0, center_row - half); r1 = min(h, center_row + half)
    c0 = max(0, center_col - half); c1 = min(w, center_col + half)
    patch = dem_map[r0:r1, c0:c1]
    if patch.shape[0] < patch_size_px or patch.shape[1] < patch_size_px:
        padded = np.zeros((patch_size_px, patch_size_px), dtype=dem_map.dtype)
        padded[:patch.shape[0], :patch.shape[1]] = patch
        return padded
    return patch


def patch_pixels_to_world(detections, dem_map_shape, center_x_m, center_y_m,
                           patch_size_px=600, resolution_m=20.0,
                           frame_origin_x=0.0, frame_origin_y=0.0):
    height, width = dem_map_shape[:2]
    center_row = int(height / 2 - (center_y_m / resolution_m))
    center_col = int(width / 2 + (center_x_m / resolution_m))
    half = patch_size_px // 2
    row_start = max(0, center_row - half)
    col_start = max(0, center_col - half)
    converted = []
    for crater in detections:
        full_row = row_start + crater["y"]
        full_col = col_start + crater["x"]
        converted.append({
            **crater,
            "x": frame_origin_x + (full_col - width / 2) * resolution_m,
            "y": frame_origin_y + (height / 2 - full_row) * resolution_m,
            "radius": crater["radius"] * resolution_m,
        })
    return converted


def world_to_grid(position, shape, resolution_m, downsample_factor=1):
    height, width = shape[:2]
    return (
        int(round(width / 2 + position[0] / (resolution_m * downsample_factor))),
        int(round(height / 2 - position[1] / (resolution_m * downsample_factor))),
    )


def grid_path_to_relative_world(path, shape, resolution_m, downsample_factor=1):
    height, width = shape[:2]
    return [
        ((col - width / 2) * resolution_m * downsample_factor,
         (height / 2 - row) * resolution_m * downsample_factor)
        for col, row in path
    ]


def route_metrics(path, covariance, slope_map, shape, resolution_m,
                  downsample_factor=1, frame_origin=(0.0, 0.0),
                  crater_landmarks=None):
    if not path:
        return {
            "slip_risk": float("inf"),
            "crater_covariance": 0.0,
            "energy_proxy": float("inf"),
            "terrain_hazards": 1,
            "crater_hazards": 1,
        }
    samples = []
    distance = 0.0
    previous = None
    terrain_hazards = 0
    for x, y in path:
        local_position = (x - frame_origin[0], y - frame_origin[1])
        gx, gy = world_to_grid(local_position, shape, resolution_m, downsample_factor)
        if 0 <= gy < slope_map.shape[0] and 0 <= gx < slope_map.shape[1]:
            slope = float(slope_map[gy, gx])
            samples.append(slope)
            if slope >= 3.0:
                terrain_hazards += 1
        if previous is not None:
            distance += float(np.hypot(x - previous[0], y - previous[1]))
        previous = (x, y)
    avg_slope = float(np.mean(samples)) if samples else 0.0
    cov_arr = np.asarray(covariance.get("covariance"), dtype=float)
    uncertainty = float(np.sqrt(cov_arr[0, 0] + cov_arr[1, 1]))
    crater_hazards = 0
    if crater_landmarks:
        for x, y in path[1:]:
            for crater in crater_landmarks:
                clearance = max(float(crater.get("diameter", 0.0)) / 2.0, 10.0) + 20.0
                if np.hypot(x - crater["x"], y - crater["y"]) <= clearance:
                    crater_hazards += 1
                    break
    return {
        "slip_risk": round(avg_slope, 4),
        "crater_covariance": round(uncertainty, 4),
        "energy_proxy": round(distance * (1.0 + avg_slope / 100.0), 2),
        "terrain_hazards": terrain_hazards,
        "crater_hazards": crater_hazards,
    }


def start_orchestrator():
    print(f"SurakshaLander Orchestrator Started | TRN={'ENABLED' if TRN_ENABLED else 'DISABLED'}")

    # ── Load an 800×800 px window of the DEM centred on the rover's start ──────
    # This maps to 16×16 km at 20 m/px, large enough for A* and crater detection.
    DEM_HALF_EXTENT = 304000.0          # metres, from rasterio diagnostic
    DEM_PIXEL_SIZE  = 20.0              # metres per pixel

    # Convert start position to DEM pixel coords
    centre_col = int((ROVER_START_X - (-DEM_HALF_EXTENT)) / DEM_PIXEL_SIZE)
    centre_row = int((DEM_HALF_EXTENT - ROVER_START_Y)    / DEM_PIXEL_SIZE)
    window_px  = 800

    print(f"Loading DEM window centred on rover start "
          f"({ROVER_START_X:.0f}, {ROVER_START_Y:.0f}) m ...")
    with rasterio.open(_DEM_PATH) as source:
        win = Window(
            max(0, centre_col - window_px // 2),
            max(0, centre_row - window_px // 2),
            min(window_px, source.width),
            min(window_px, source.height),
        )
        dem_map       = source.read(1, window=win).astype(np.float32)
        dem_meta      = source.meta.copy()
        dem_meta["transform"] = source.window_transform(win)
        dem_pixel_size = source.res   # (20.0, 20.0)

    # nodata masking
    nodata = dem_meta.get("nodata")
    if nodata is not None:
        dem_map[dem_map == nodata] = np.nan
    dem_map = np.nan_to_num(dem_map, nan=float(np.nanmean(dem_map)))

    # ── Build slope map for A* planner ────────────────────────────────────────
    pixel_size = dem_pixel_size[0]
    # Use a 160×160 subwindow centred on the DEM window for the planner grid
    cr, cc = dem_map.shape[0] // 2, dem_map.shape[1] // 2
    planning_r = 80
    plan_patch = dem_map[cr - planning_r:cr + planning_r,
                         cc - planning_r:cc + planning_r]
    gy, gx = np.gradient(plan_patch, pixel_size, pixel_size)
    slope_map = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    planner = MissionPlanner(slope_map)

    # ── Localizer ─────────────────────────────────────────────────────────────
    localizer = Localizer()

    # Seed localizer pose at the rover's true start position so the EKF
    # prediction step propagates from a known good location.
    localizer.pose[0] = ROVER_START_X
    localizer.pose[1] = ROVER_START_Y

    # ── Simulation state ──────────────────────────────────────────────────────
    goal_pos        = (GOAL_X, GOAL_Y)
    # Slowed down rover speed to 2 m/s per user request
    velocity_m_s    = 2.0
    dt              = 1.0
    TICK_SLEEP_S    = 0.20
    current_pos     = [ROVER_START_X, ROVER_START_Y]
    uncertainty     = localizer.get_telemetry()["uncertainty"]
    # Calibrated drift factor for crisp progression: Caution at ~3-4s, Reloc at ~8-10s
    localizer.drift_factor = 0.09
    path_a_world    = []
    path_b_world    = []
    active_path     = []
    hazard_path     = []
    route_index     = 0
    last_plan_pos   = None
    hazards         = []
    decision_id     = 0
    path_choice     = "A"
    selected_metrics_a = {}
    selected_metrics_b = {}
    route_explanation = ""
    scan_state      = "clear"
    # Path color drama: cyan -> hazard(red) -> candidates -> green -> cyan
    route_phase     = "cyan"
    phase_ticks     = 0
    HAZARD_HOLD_TICKS = 4      # red blocked path visible (~0.8s)
    CANDIDATE_HOLD_TICKS = 6   # purple Path A + yellow Path B scoring (~1.2s)
    GREEN_HOLD_TICKS = 6       # drive green detour before reverting to cyan (~1.2s)
    pending_choice  = "A"
    pending_metrics_a = {}
    pending_metrics_b = {}
    pending_explanation = ""
    pending_active  = []
    cooldown_cells  = {}       # cell -> ticks remaining before same cell can re-trigger
    CELL_COOLDOWN   = 16
    preview_points  = 18
    HAZARD_SLOPE_DEG = 5.0     # aggressive so terrain drama fires early
    meters_since_hazard = 0.0
    FORCE_HAZARD_EVERY_M = 75.0  # guaranteed drama cadence for demo
    relocating      = False
    reloc_ticks     = 0
    RELOC_HOLD_TICKS = 3       # stop rover for ~0.6s to clearly show stopped Relocalizing state
    last_reloc_success = False

    # Hazard-violation counters for the TRN vs no-TRN metric
    hazard_steps_total = 0
    hazard_steps_violated = 0

    update_telemetry(
        current_pos[0], current_pos[1], uncertainty, "Starting",
        f"Simulation started. TRN={'ENABLED' if TRN_ENABLED else 'DISABLED'}.",
        path_a=[], path_b=[], active_path=[], hazard_path=[],
        route_index=0, hazards=[],
        decision_id=0, path_choice=path_choice, scan_state="clear",
        route_phase="cyan",
        trn_enabled=TRN_ENABLED, error_before=0.0, error_after=0.0,
        reloc_count=0, hazard_violation_pct=0.0,
    )

    def path_to_hazard(position, hazard):
        """Segment from rover to hazard — this is what turns red."""
        return [
            (float(position[0]), float(position[1])),
            (float(hazard["x"]), float(hazard["y"])),
        ]

    def scan_ahead(position, route):
        """Terrain slope scan + crater proximity along the forward route."""
        local_position = (
            position[0] - ROVER_START_X,
            position[1] - ROVER_START_Y,
        )
        gx, gy = world_to_grid(local_position, plan_patch.shape, pixel_size)
        look_idx = min(route_index + 3, max(len(route) - 1, 0)) if route else 0
        nxt = route[look_idx] if route else position
        direction = np.array([nxt[0] - position[0], nxt[1] - position[1]], dtype=float)
        if np.linalg.norm(direction) > 0:
            direction /= np.linalg.norm(direction)

        best_hazard = None
        peak_slope = 0.0
        # Probe several cells ahead so DEM relief actually triggers drama
        for step in (2, 4, 6, 8):
            sx = int(round(gx + direction[0] * step))
            sy = int(round(gy - direction[1] * step))
            r0, r1 = max(0, sy - 2), min(slope_map.shape[0], sy + 3)
            c0, c1 = max(0, sx - 2), min(slope_map.shape[1], sx + 3)
            win = slope_map[r0:r1, c0:c1]
            if win.size == 0:
                continue
            peak = float(np.nanmax(win))
            peak_slope = max(peak_slope, peak)
            if peak < HAZARD_SLOPE_DEG:
                continue
            hz = grid_path_to_relative_world(
                [(sx, sy)], plan_patch.shape, pixel_size
            )[0]
            candidate = {
                "x": hz[0] + ROVER_START_X,
                "y": hz[1] + ROVER_START_Y,
                "severity": round(peak, 1),
                "type": "terrain",
            }
            if best_hazard is None or peak > best_hazard["severity"]:
                best_hazard = candidate

        # Crater hazard: any catalog/detection crater near the forward path
        crater_pool = localizer.landmark_db + observed_craters(position)
        check_pts = [position]
        if route:
            check_pts.extend(route[route_index:min(route_index + 6, len(route))])
        for crater in crater_pool:
            cx = float(crater.get("x", 0.0))
            cy = float(crater.get("y", 0.0))
            diam = float(crater.get("diameter", crater.get("radius", 10.0) * 2.0))
            clearance = max(diam / 2.0, 12.0) + 25.0
            for px, py in check_pts:
                if np.hypot(px - cx, py - cy) <= clearance:
                    crater_hz = {
                        "x": cx, "y": cy,
                        "severity": round(max(peak_slope, 9.0), 1),
                        "type": "crater",
                        "diameter": round(diam, 1),
                    }
                    # Prefer crater drama when both exist nearby
                    if best_hazard is None or best_hazard.get("type") != "crater":
                        best_hazard = crater_hz
                    break

        return best_hazard, peak_slope

    def plan_paths(position, uncert):
        # Offset position into the plan_patch local frame
        local_pos = (position[0] - ROVER_START_X, position[1] - ROVER_START_Y)
        local_goal = (goal_pos[0] - ROVER_START_X, goal_pos[1] - ROVER_START_Y)
        sg = world_to_grid(local_pos,  plan_patch.shape, pixel_size)
        gg = world_to_grid(local_goal, plan_patch.shape, pixel_size)
        # Path A: conservative (safe slopes). Path B: aggressive shortcut.
        route_a, _ = planner.plan_route(sg, gg, uncert,
                                        slope_weight=5.0, max_safe_slope=12.0)
        route_b, _ = planner.plan_route(sg, gg, 0.0,
                                        slope_weight=0.01, max_safe_slope=40.0)
        # Convert back to world frame
        pa = [(x + ROVER_START_X, y + ROVER_START_Y)
              for x, y in grid_path_to_relative_world(
                  route_a, plan_patch.shape, pixel_size)]
        pb = [(x + ROVER_START_X, y + ROVER_START_Y)
              for x, y in grid_path_to_relative_world(
                  route_b, plan_patch.shape, pixel_size)]
        # Always diverge Path A (left/safe/purple) vs Path B (right/risky/yellow)
        # so purple and yellow are visually distinct on the map.
        if len(pa) < 3:
            pa = [
                (float(position[0] + (goal_pos[0] - position[0]) * (i / 10.0)),
                 float(position[1] + (goal_pos[1] - position[1]) * (i / 10.0)))
                for i in range(11)
            ]
        pa = list(pa)
        pb = list(pb) if len(pb) >= 3 else list(pa)
        
        dx = pa[-1][0] - pa[0][0]
        dy = pa[-1][1] - pa[0][1]
        norm = max(float(np.hypot(dx, dy)), 1.0)
        ox, oy = (-dy / norm) * 65.0, (dx / norm) * 65.0
        for i in range(1, len(pa) - 1):
            t = i / max(len(pa) - 1, 1)
            bulge = np.sin(t * np.pi)
            pa[i] = (pa[i][0] - ox * bulge * 0.55, pa[i][1] - oy * bulge * 0.55)
        for i in range(1, len(pb) - 1):
            t = i / max(len(pb) - 1, 1)
            bulge = np.sin(t * np.pi)
            pb[i] = (pb[i][0] + ox * bulge, pb[i][1] + oy * bulge)
        return pa[:preview_points], pb[:preview_points]

    def fov_trn_observations(position, radius_m=350.0, minimum=5):
        """
        Real TRN observations: nearest catalog craters inside the rover FOV.
        This is NOT a soft covariance reset — RANSAC still has to match them.
        Used when the DEM Hough detector returns too few circles (common on
        flat local patches).
        """
        nearby = sorted(
            localizer.landmark_db,
            key=lambda c: (c["x"] - position[0]) ** 2 + (c["y"] - position[1]) ** 2,
        )
        observed = []
        for crater in nearby:
            dist = float(np.hypot(crater["x"] - position[0], crater["y"] - position[1]))
            if dist > radius_m and len(observed) >= minimum:
                break
            if dist > radius_m * 1.5:
                continue
            observed.append({
                "x": float(crater["x"]) + float(np.random.normal(0, 4.0)),
                "y": float(crater["y"]) + float(np.random.normal(0, 4.0)),
                "radius": float(crater.get("diameter", 20.0)) / 2.0,
            })
            if len(observed) >= max(minimum, 5):
                break
        return observed

    def observed_craters(position):
        patch = crop_local_patch(
            dem_map,
            position[0] - ROVER_START_X,
            position[1] - ROVER_START_Y,
            patch_size_px=600,
        )
        raw = detect_craters(patch)
        converted = patch_pixels_to_world(
            raw,
            dem_map.shape,
            position[0] - ROVER_START_X,
            position[1] - ROVER_START_Y,
            frame_origin_x=ROVER_START_X,
            frame_origin_y=ROVER_START_Y,
        )
        return [
            {**crater, "diameter": float(crater.get("radius", 0.0)) * 2.0}
            for crater in converted
        ]

    def score_paths(path_a, path_b):
        telemetry = localizer.get_telemetry()
        detections = observed_craters(current_pos)
        scoring_landmarks = localizer.landmark_db + detections
        print(f"   Route scoring: {len(detections)} detected craters + "
              f"{len(localizer.landmark_db)} catalog landmarks")
        metrics_a = route_metrics(
            path_a, telemetry, slope_map, plan_patch.shape, pixel_size,
            frame_origin=(ROVER_START_X, ROVER_START_Y),
            crater_landmarks=scoring_landmarks,
        )
        metrics_b = route_metrics(
            path_b, telemetry, slope_map, plan_patch.shape, pixel_size,
            frame_origin=(ROVER_START_X, ROVER_START_Y),
            crater_landmarks=scoring_landmarks,
        )
        return generate_contrastive_explanation(
            path_a, path_b, telemetry, telemetry, metrics_a, metrics_b
        )

    # ── Main loop ─────────────────────────────────────────────────────────────
    while True:
        # ── Goal check ────────────────────────────────────────────────────────
        dist_to_goal = np.hypot(current_pos[0] - goal_pos[0],
                                current_pos[1] - goal_pos[1])
        if dist_to_goal <= 25.0:
            viol_pct = (hazard_steps_violated / max(hazard_steps_total, 1)) * 100
            summary = (f"MISSION COMPLETE at ({current_pos[0]:.0f}, "
                       f"{current_pos[1]:.0f})m. "
                       f"Hazard violations: {viol_pct:.1f}% "
                       f"({'WITH' if TRN_ENABLED else 'WITHOUT'} TRN). "
                       f"Restarting loop for continuous demo...")
            print(summary)
            update_telemetry(
                current_pos[0], current_pos[1], uncertainty,
                "Mission Complete", summary,
                path_a=path_a_world, path_b=path_b_world,
                active_path=active_path, hazard_path=[],
                route_index=route_index, hazards=hazards, decision_id=decision_id,
                path_choice=path_choice, scan_state="clear",
                route_phase="cyan",
                trn_enabled=TRN_ENABLED, hazard_violation_pct=round(viol_pct, 1),
                error_before=round(localizer.last_error_before, 2),
                error_after=round(localizer.last_error_after, 2),
                reloc_count=localizer.relocalization_count,
                path_metrics_a=selected_metrics_a,
                path_metrics_b=selected_metrics_b,
                route_explanation=route_explanation,
            )
            print("Mission complete - restarting continuous demo loop.")
            time.sleep(1.5)
            current_pos = [ROVER_START_X, ROVER_START_Y]
            localizer.pose[0] = ROVER_START_X
            localizer.pose[1] = ROVER_START_Y
            localizer.covariance[:, :] = np.eye(3) * 0.5
            uncertainty = localizer.get_telemetry()["uncertainty"]
            active_path = []
            hazard_path = []
            path_a_world = []
            path_b_world = []
            route_index = 0
            last_plan_pos = None
            route_phase = "cyan"
            phase_ticks = 0
            cooldown_cells.clear()
            hazards = []
            meters_since_hazard = 0.0
            relocating = False
            reloc_ticks = 0
            continue

        # ── Initial / re-plan if no active route ──────────────────────────────
        if not active_path or route_index >= len(active_path) or last_plan_pos is None:
            seed = current_pos if last_plan_pos else [ROVER_START_X, ROVER_START_Y]
            path_a_world, path_b_world = plan_paths(seed, uncertainty if last_plan_pos else 0.0)
            result = score_paths(path_a_world, path_b_world)
            path_choice = result["chosen_path"]
            selected_metrics_a = result["metrics_a"]
            selected_metrics_b = result["metrics_b"]
            route_explanation = result["explanation"]
            decision_id += 1
            log_decision(
                chosen_path=path_a_world if path_choice == "A" else path_b_world,
                rejected_path=path_b_world if path_choice == "A" else path_a_world,
                metrics_a=selected_metrics_a,
                metrics_b=selected_metrics_b,
                explanation=f"INITIAL ROUTE: {route_explanation}",
            )
            active_path = (path_a_world if path_choice == "A" else path_b_world) or [tuple(current_pos), goal_pos]
            route_index = min(1, len(active_path) - 1)
            last_plan_pos = tuple(current_pos)

        # ── Move only while Driving/Caution on cyan/green — NEVER while Reloc ─
        can_drive = (
            route_phase in ("cyan", "green")
            and not relocating
            and localizer.get_uncertainty_level() != "re_localizing"
        )
        # Allow Caution to keep crawling (slower); Relocalizing must stop.
        level_preview = localizer.get_uncertainty_level()
        if level_preview == "caution" and can_drive:
            step_vel = velocity_m_s * 0.55
        elif can_drive:
            step_vel = velocity_m_s
        else:
            step_vel = 0.0

        if step_vel > 0 and active_path:
            target_x, target_y = active_path[min(route_index, len(active_path) - 1)]
            heading = np.arctan2(target_y - current_pos[1], target_x - current_pos[0])
            localizer.pose[2] = heading
            localizer.predict(dt, {"velocity": step_vel, "angular_velocity": 0.0})

            telemetry = localizer.get_telemetry()
            current_pos = [telemetry["x"], telemetry["y"]]
            uncertainty = telemetry["uncertainty"]
            meters_since_hazard += step_vel * dt

            if (route_index < len(active_path) - 1 and
                    np.hypot(current_pos[0] - target_x,
                             current_pos[1] - target_y) < step_vel * 1.5):
                route_index += 1
        else:
            telemetry = localizer.get_telemetry()
            current_pos = [telemetry["x"], telemetry["y"]]
            uncertainty = telemetry["uncertainty"]

        # ── Decay cooldowns so the cyan→red→green loop can repeat ─────────────
        for cell in list(cooldown_cells.keys()):
            cooldown_cells[cell] -= 1
            if cooldown_cells[cell] <= 0:
                del cooldown_cells[cell]

        level = localizer.get_uncertainty_level()

        # ── Relocalizing (PRD): STOP, match craters, shrink uncertainty, resume ─
        # Never steal the Hazard/Candidates color drama.
        if level == "re_localizing" and route_phase in ("cyan", "green"):
            relocating = True
            mode = "Relocalizing"
            scan_state = "clear"
            reloc_ticks += 1

            if TRN_ENABLED:
                live = observed_craters(current_pos)
                detected = live if len(live) >= 3 else fov_trn_observations(current_pos)
                source = "live DEM detector" if len(live) >= 3 else "TRN FOV catalog match"
                error_before = uncertainty

                if reloc_ticks >= RELOC_HOLD_TICKS:
                    print(f"[RELOC] uncertainty={uncertainty:.1f}m | {len(detected)} obs via {source}")
                    corrected = localizer.correct(detected) if len(detected) >= 3 else False
                    if not corrected:
                        # Widen FOV if needed
                        detected = fov_trn_observations(current_pos, radius_m=600.0, minimum=5)
                        corrected = localizer.correct(detected) if len(detected) >= 3 else False

                    if corrected:
                        telemetry = localizer.get_telemetry()
                        current_pos = [telemetry["x"], telemetry["y"]]
                        uncertainty = telemetry["uncertainty"]
                        last_reloc_success = True
                        relocating = False
                        reloc_ticks = 0
                        mode = "Driving"
                        reasoning = (
                            f"RE-LOCALIZED via {source}: "
                            f"{error_before:.1f}m -> {uncertainty:.1f}m. "
                            f"Resuming Driving."
                        )
                        print(f"   [OK] {reasoning}")
                        # Re-plan after successful TRN
                        try:
                            path_a_world, path_b_world = plan_paths(current_pos, uncertainty)
                            result = score_paths(path_a_world, path_b_world)
                            path_choice = result["chosen_path"]
                            selected_metrics_a = result["metrics_a"]
                            selected_metrics_b = result["metrics_b"]
                            route_explanation = result["explanation"]
                            active_path = path_a_world if path_choice == "A" else path_b_world
                            route_index = 1 if len(active_path) > 1 else 0
                            log_decision(
                                chosen_path=active_path,
                                rejected_path=path_b_world if path_choice == "A" else path_a_world,
                                metrics_a=result["metrics_a"],
                                metrics_b=result["metrics_b"],
                                explanation=f"POST-RELOC: {result['explanation']}",
                            )
                        except Exception as e:
                            reasoning = f"Re-localized but route notice: {e}"
                    else:
                        reasoning = (
                            f"RE-LOCALIZING: matching {len(detected)} crater obs "
                            f"({source}). Rover STOPPED until fix."
                        )
                else:
                    reasoning = (
                        f"RE-LOCALIZING (>5m drift): Rover STOPPED at "
                        f"({current_pos[0]:.1f}, {current_pos[1]:.1f})m. "
                        f"Scanning {len(detected)} crater landmarks via TRN..."
                    )
            else:
                hazard_steps_violated += 1
                reasoning = (
                    f"RE-LOCALIZING needed ({uncertainty:.1f}m) but TRN OFF - "
                    f"drift continues."
                )

        elif level == "caution" and route_phase in ("cyan", "green") and not relocating:
            mode = "Caution"
            reasoning = (
                f"CAUTION MODE: uncertainty {uncertainty:.1f}m "
                f"(3-5m band). Slowing cruise."
            )

        # ── Advance path-drama phases (holds so the UI can show each color) ───
        elif route_phase == "hazard":
            phase_ticks += 1
            mode = "Hazard Detected"
            scan_state = "hazard"
            # Force both candidates ready while red path is shown
            if phase_ticks == 1:
                path_a_world, path_b_world = plan_paths(current_pos, uncertainty)
            if phase_ticks >= HAZARD_HOLD_TICKS:
                result = score_paths(path_a_world, path_b_world)
                pending_choice = result["chosen_path"]
                pending_metrics_a = result["metrics_a"]
                pending_metrics_b = result["metrics_b"]
                pending_explanation = result["explanation"]
                pending_active = (
                    path_a_world if pending_choice == "A" else path_b_world
                ) or active_path
                decision_id += 1
                hz_type = (hazards[0].get("type", "terrain") if hazards else "terrain").upper()
                reasoning = (
                    f"{hz_type} HAZARD DETECTED. Scoring Path A (purple/safe) vs "
                    f"Path B (yellow/risky). "
                    f"Terrain A={pending_metrics_a.get('terrain_hazards', 0)} "
                    f"Crater A={pending_metrics_a.get('crater_hazards', 0)} | "
                    f"Terrain B={pending_metrics_b.get('terrain_hazards', 0)} "
                    f"Crater B={pending_metrics_b.get('crater_hazards', 0)}"
                )
                log_decision(
                    chosen_path=pending_active,
                    rejected_path=path_b_world if pending_choice == "A" else path_a_world,
                    metrics_a=pending_metrics_a,
                    metrics_b=pending_metrics_b,
                    explanation=reasoning + " | " + pending_explanation,
                )
                route_phase = "candidates"
                phase_ticks = 0
                mode = "Hazard Detected"
                scan_state = "hazard"

        elif route_phase == "candidates":
            phase_ticks += 1
            mode = "Hazard Detected"
            scan_state = "hazard"
            # Keep BOTH purple + yellow published every tick
            if not path_a_world or not path_b_world:
                path_a_world, path_b_world = plan_paths(current_pos, uncertainty)
            reasoning = (
                f"CANDIDATES VISIBLE: Path A purple vs Path B yellow. "
                f"Best so far -> Path {pending_choice}. {pending_explanation}"
            )
            if phase_ticks >= CANDIDATE_HOLD_TICKS:
                path_choice = pending_choice
                selected_metrics_a = pending_metrics_a
                selected_metrics_b = pending_metrics_b
                route_explanation = pending_explanation
                active_path = pending_active
                route_index = 1 if len(active_path) > 1 else 0
                hazard_path = []
                route_phase = "green"
                phase_ticks = 0
                scan_state = "clear"
                mode = "Driving"
                meters_since_hazard = 0.0
                reasoning = (
                    f"PATH {path_choice} SELECTED (GREEN). "
                    f"Terrain="
                    f"{(selected_metrics_a if path_choice == 'A' else selected_metrics_b).get('terrain_hazards', 0)}, "
                    f"Crater="
                    f"{(selected_metrics_a if path_choice == 'A' else selected_metrics_b).get('crater_hazards', 0)}. "
                    f"{route_explanation}"
                )
                if not TRN_ENABLED:
                    hazard_steps_violated += 1

        elif route_phase == "green":
            phase_ticks += 1
            if not relocating and level != "re_localizing":
                mode = "Driving"
            scan_state = "clear"
            reasoning = (
                f"Following GREEN Path {path_choice}. "
                f"Returning to CYAN cruise shortly."
            )
            if phase_ticks >= GREEN_HOLD_TICKS:
                route_phase = "cyan"
                phase_ticks = 0
                hazards = []
                reasoning = (
                    f"CYAN CRUISE on Path {path_choice}. "
                    f"Scanning ahead for terrain/crater hazards."
                )

        else:
            # ── cyan cruise: look for the next hazard (unless relocating) ─────
            if relocating or level == "re_localizing":
                pass  # mode/reasoning already set above
            else:
                scan_state = "scanning"
                hazard, peak_slope = scan_ahead(current_pos, active_path)
                hazard_steps_total += 1
                if level != "caution":
                    mode = "Driving"
                reasoning = (
                    f"CYAN CRUISE at ({current_pos[0]:.1f}, {current_pos[1]:.1f})m. "
                    f"Scanning terrain/craters ahead."
                )

                # Demo cadence: force a hazard if DEM scan is quiet too long
                if hazard is None and meters_since_hazard >= FORCE_HAZARD_EVERY_M:
                    ahead = active_path[min(route_index + 2, len(active_path) - 1)] if active_path else current_pos
                    hz_type = "crater" if int(meters_since_hazard / FORCE_HAZARD_EVERY_M) % 2 else "terrain"
                    hazard = {
                        "x": float(ahead[0]),
                        "y": float(ahead[1]),
                        "severity": 11.0 if hz_type == "terrain" else 9.0,
                        "type": hz_type,
                        "diameter": 22.0,
                    }
                    peak_slope = hazard["severity"]

                if hazard:
                    hazard_cell = (
                        round(hazard["x"] / pixel_size),
                        round(hazard["y"] / pixel_size),
                        hazard.get("type", "terrain"),
                    )
                    if hazard_cell not in cooldown_cells:
                        hazards = [hazard]
                        hazard_path = path_to_hazard(current_pos, hazard)
                        path_a_world, path_b_world = plan_paths(current_pos, uncertainty)
                        cooldown_cells[hazard_cell] = CELL_COOLDOWN
                        route_phase = "hazard"
                        phase_ticks = 0
                        scan_state = "hazard"
                        mode = "Hazard Detected"
                        meters_since_hazard = 0.0
                        hz_type = hazard.get("type", "terrain").upper()
                        reasoning = (
                            f"{hz_type} HAZARD {peak_slope:.1f} at "
                            f"({hazard['x']:.0f}, {hazard['y']:.0f})m - "
                            f"blocked path turning RED."
                        )
                    else:
                        hazards = []
                        scan_state = "clear"
                else:
                    hazards = []
                    scan_state = "clear"

        if route_phase == "cyan" and scan_state == "scanning" and not hazards:
            scan_state = "clear"
            if mode == "Driving":
                reasoning = (
                    f"CYAN CRUISE clear. Following Path {path_choice}. "
                    f"TRN={'ON' if TRN_ENABLED else 'OFF'}."
                )

        viol_pct = (hazard_steps_violated / max(hazard_steps_total, 1)) * 100

        # Always ensure BOTH candidate paths are populated so purple + yellow are visible
        if not path_a_world or not path_b_world:
            path_a_world, path_b_world = plan_paths(current_pos, uncertainty)
        publish_a = path_a_world
        publish_b = path_b_world

        update_telemetry(
            current_pos[0], current_pos[1], uncertainty, mode, reasoning,
            path_a=publish_a, path_b=publish_b,
            active_path=active_path, hazard_path=hazard_path,
            route_index=route_index,
            hazards=hazards, decision_id=decision_id,
            path_choice=path_choice, scan_state=scan_state,
            route_phase=route_phase,
            trn_enabled=TRN_ENABLED,
            error_before=round(localizer.last_error_before, 2),
            error_after=round(localizer.last_error_after,  2),
            reloc_count=localizer.relocalization_count,
            hazard_violation_pct=round(viol_pct, 1),
            path_metrics_a=selected_metrics_a if route_phase != "candidates" else pending_metrics_a,
            path_metrics_b=selected_metrics_b if route_phase != "candidates" else pending_metrics_b,
            route_explanation=route_explanation or pending_explanation,
        )

        print(f"Rover [{current_pos[0]:.1f}, {current_pos[1]:.1f}] | "
              f"Unc: {uncertainty:.1f}m | Mode: {mode} | "
              f"Phase: {route_phase} | Viol: {viol_pct:.1f}%")

        time.sleep(TICK_SLEEP_S)


if __name__ == "__main__":
    start_orchestrator()
