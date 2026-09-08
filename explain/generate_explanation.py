from .path_metrics import compute_path_metrics


def _metric_reason(label, chosen_value, rejected_value, chosen_label, rejected_label,
                   lower_is_better=True):
    difference = rejected_value - chosen_value
    magnitude = abs(difference)

    if difference == 0:
        return (
            f"{label} was equal "
            f"(chosen {chosen_value:.2f}, rejected {rejected_value:.2f})"
        )

    chosen_is_better = difference > 0 if lower_is_better else difference < 0
    direction = "lower" if difference > 0 else "higher"
    preference = "favored" if chosen_is_better else "penalized"

    return (
        f"{label} {direction} by {magnitude:.2f} "
        f"(chosen {chosen_value:.2f}, rejected {rejected_value:.2f}), "
        f"which {preference} {chosen_label}"
    )


def _path_score(metrics_a, metrics_b):
    """Compare unlike metric units on a pair-relative 0..1 scale."""
    hazard_a = metrics_a.get("terrain_hazards", 0) + metrics_a.get("crater_hazards", 0)
    hazard_b = metrics_b.get("terrain_hazards", 0) + metrics_b.get("crater_hazards", 0)
    if hazard_a != hazard_b:
        return (float(hazard_a), 0.0), (float(hazard_b), 0.0)
    score_a = 0.0
    score_b = 0.0
    for key in ("slip_risk", "crater_covariance", "energy_proxy"):
        scale = max(float(metrics_a[key]), float(metrics_b[key]), 1e-9)
        score_a += float(metrics_a[key]) / scale
        score_b += float(metrics_b[key]) / scale
    return (0.0, score_a), (0.0, score_b)


def generate_contrastive_explanation(
    path_a,
    path_b,
    covariance_a,
    covariance_b,
    metrics_override_a=None,
    metrics_override_b=None,
):
    """
    Compare two candidate paths and explain why Path A
    is preferred over Path B.
    """

    metrics_a = metrics_override_a or compute_path_metrics(path_a, covariance_a)
    metrics_b = metrics_override_b or compute_path_metrics(path_b, covariance_b)

    score_a, score_b = _path_score(metrics_a, metrics_b)
    if score_b < score_a:
        chosen_label, rejected_label = "Path B", "Path A"
        chosen_metrics, rejected_metrics = metrics_b, metrics_a
    else:
        chosen_label, rejected_label = "Path A", "Path B"
        chosen_metrics, rejected_metrics = metrics_a, metrics_b

    reasons = [
        _metric_reason(
            "Slip Risk",
            chosen_metrics["slip_risk"],
            rejected_metrics["slip_risk"],
            chosen_label,
            rejected_label,
        ),
        _metric_reason(
            "Crater Covariance",
            chosen_metrics["crater_covariance"],
            rejected_metrics["crater_covariance"],
            chosen_label,
            rejected_label,
        ),
        _metric_reason(
            "Energy Proxy",
            chosen_metrics["energy_proxy"],
            rejected_metrics["energy_proxy"],
            chosen_label,
            rejected_label,
        ),
    ]
    for label, key in (("Terrain Hazards", "terrain_hazards"), ("Crater Hazards", "crater_hazards")):
        if key in metrics_a or key in metrics_b:
            reasons.append(_metric_reason(
                label,
                chosen_metrics.get(key, 0),
                rejected_metrics.get(key, 0),
                chosen_label,
                rejected_label,
            ))

    explanation = f"Chose {chosen_label} over {rejected_label} because: " + ", ".join(reasons)

    return {
        "chosen_path": chosen_label[-1],
        "rejected_path": rejected_label[-1],
        "metrics_a": metrics_a,
        "metrics_b": metrics_b,
        "explanation": explanation,
    }
