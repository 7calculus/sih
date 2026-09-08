import json
import os

STATE_FILE = os.environ.get(
    "TELEMETRY_FILE",
    os.path.join(os.path.dirname(__file__), "telemetry.json")
)

default_telemetry = {
    "x": 0, "y": 0, "uncertainty": 0,
    "mode": "connecting",
    "reasoning": "System initialized. Awaiting live telemetry stream.",
    "path_a": [], "path_b": [], "active_path": [], "route_index": 0,
    "hazard_path": [],
    "hazards": [], "decision_id": 0, "path_choice": "A", "scan_state": "clear",
    # route_phase drives the color drama:
    # cyan → hazard (red) → candidates (purple/yellow) → green → cyan
    "route_phase": "cyan",
    "trn_enabled": True,
    "error_before": 0.0, "error_after": 0.0,
    "last_error_before": 0.0, "last_error_after": 0.0,
    "reloc_count": 0,
    "hazard_violation_pct": 0.0,
    "path_metrics_a": {}, "path_metrics_b": {}, "route_explanation": "",
}

def _read_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return default_telemetry.copy()

def _write_state(data):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"State write error: {e}")

def update_telemetry(x, y, uncertainty, mode, reasoning,
                     path_a=None, path_b=None, active_path=None,
                     hazard_path=None,
                     route_index=0, hazards=None, decision_id=0,
                     path_choice="A", scan_state="clear",
                     route_phase="cyan",
                     trn_enabled=True,
                     error_before=0.0, error_after=0.0, reloc_count=0,
                     hazard_violation_pct=0.0, path_metrics_a=None,
                     path_metrics_b=None, route_explanation=None):
    data = _read_state()
    data["x"]          = round(float(x), 2)
    data["y"]          = round(float(y), 2)
    data["uncertainty"] = round(float(uncertainty), 2)
    data["mode"]       = mode
    data["reasoning"]  = reasoning
    if path_a      is not None: data["path_a"]      = path_a
    if path_b      is not None: data["path_b"]      = path_b
    if active_path is not None: data["active_path"] = active_path
    if hazard_path is not None: data["hazard_path"] = hazard_path
    data["route_index"]          = int(route_index)
    data["hazards"]              = hazards if hazards is not None else data.get("hazards", [])
    data["decision_id"]          = int(decision_id)
    data["path_choice"]          = path_choice
    data["scan_state"]           = scan_state
    data["route_phase"]          = route_phase
    data["trn_enabled"]          = bool(trn_enabled)
    data["error_before"]         = float(error_before)
    data["error_after"]          = float(error_after)
    data["last_error_before"]    = float(error_before)
    data["last_error_after"]     = float(error_after)
    data["reloc_count"]          = int(reloc_count)
    data["hazard_violation_pct"] = float(hazard_violation_pct)
    if path_metrics_a is not None: data["path_metrics_a"] = path_metrics_a
    if path_metrics_b is not None: data["path_metrics_b"] = path_metrics_b
    if route_explanation is not None: data["route_explanation"] = route_explanation
    _write_state(data)

def get_current_position():
    data = _read_state()
    return {"x": data["x"], "y": data["y"], "uncertainty": data["uncertainty"]}

def get_rover_mode():
    return _read_state()["mode"]

def get_reasoning():
    return _read_state()["reasoning"]

def get_navigation_state():
    data = _read_state()
    return {
        "path_a":               data.get("path_a", []),
        "path_b":               data.get("path_b", []),
        "active_path":          data.get("active_path", []),
        "hazard_path":          data.get("hazard_path", []),
        "route_index":          data.get("route_index", 0),
        "hazards":              data.get("hazards", []),
        "decision_id":          data.get("decision_id", 0),
        "path_choice":          data.get("path_choice", "A"),
        "scan_state":           data.get("scan_state", "clear"),
        "route_phase":          data.get("route_phase", "cyan"),
        "trn_enabled":          data.get("trn_enabled", True),
        "error_before":         data.get("error_before", 0.0),
        "error_after":          data.get("error_after", 0.0),
        "last_error_before":    data.get("last_error_before", data.get("error_before", 0.0)),
        "last_error_after":     data.get("last_error_after", data.get("error_after", 0.0)),
        "reloc_count":          data.get("reloc_count", 0),
        "hazard_violation_pct": data.get("hazard_violation_pct", 0.0),
        "path_metrics_a":       data.get("path_metrics_a", {}),
        "path_metrics_b":       data.get("path_metrics_b", {}),
        "route_explanation":    data.get("route_explanation", ""),
    }
