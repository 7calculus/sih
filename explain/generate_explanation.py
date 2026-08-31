from .path_metrics import compute_path_metrics


def generate_contrastive_explanation(
    path_a,
    path_b,
    covariance_a,
    covariance_b
):
    """
    Compare two candidate paths and explain why Path A
    is preferred over Path B.
    """

    metrics_a = compute_path_metrics(path_a, covariance_a)
    metrics_b = compute_path_metrics(path_b, covariance_b)

    slip_difference = metrics_b["slip_risk"] - metrics_a["slip_risk"]
    covariance_difference = (
        metrics_b["crater_covariance"]
        - metrics_a["crater_covariance"]
    )
    energy_difference = (
        metrics_b["energy_proxy"]
        - metrics_a["energy_proxy"]
    )

    reasons = []

    if slip_difference > 0:
        reasons.append(
            f"Slip Risk {abs(slip_difference):.2f} lower"
        )
    elif slip_difference < 0:
        reasons.append(
            f"Slip Risk {abs(slip_difference):.2f} higher"
        )
    else:
        reasons.append("Slip Risk was similar")

    if covariance_difference > 0:
        reasons.append(
            f"Crater Covariance {abs(covariance_difference):.2f} safer"
        )
    elif covariance_difference < 0:
        reasons.append(
            f"Crater Covariance {abs(covariance_difference):.2f} higher"
        )
    else:
        reasons.append("Crater Covariance was similar")

    if energy_difference > 0:
        reasons.append(
            f"Energy Proxy {abs(energy_difference):.2f} lower"
        )
    elif energy_difference < 0:
        reasons.append(
            f"Energy Proxy {abs(energy_difference):.2f} higher"
        )
    else:
        reasons.append("Energy Proxy was similar")

    explanation = "Chose Path A over Path B because: " + ", ".join(reasons)

    return {
        "chosen_path": "A",
        "rejected_path": "B",
        "metrics_a": metrics_a,
        "metrics_b": metrics_b,
        "explanation": explanation,
    }