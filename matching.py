from datetime import datetime


def calculate_match_score(
    food,
    receiver_location=None,
    preferred_category=None,
    requested_quantity=1
):
    """Explainable rule-based score out of 100."""
    score = 0
    reasons = []

    # Location: 40
    if receiver_location and food["location"]:
        if receiver_location.strip().lower() == food["location"].strip().lower():
            score += 40
            reasons.append("Location matches (+40)")
        else:
            reasons.append("Location differs (+0)")
    else:
        reasons.append("Location not provided (+0)")

    # Category: 30
    if preferred_category:
        if preferred_category.strip().lower() == food["category"].strip().lower():
            score += 30
            reasons.append("Category matches (+30)")
        else:
            reasons.append("Category differs (+0)")
    else:
        reasons.append("Any category (+0)")

    # Quantity: 20
    if int(food["quantity"]) >= int(requested_quantity):
        score += 20
        reasons.append("Enough quantity (+20)")
    else:
        reasons.append("Insufficient quantity (+0)")

    # Freshness: 10
    try:
        available_until = datetime.strptime(
            food["available_until"], "%Y-%m-%dT%H:%M"
        )
        hours_remaining = (available_until - datetime.now()).total_seconds() / 3600

        if hours_remaining > 0:
            score += 10
            reasons.append("Food is still available (+10)")
        else:
            reasons.append("Food has expired (+0)")
    except (ValueError, TypeError):
        reasons.append("Expiry time unavailable (+0)")

    return {
        "score": min(score, 100),
        "reasons": reasons
    }


def get_match_label(score):
    if score >= 80:
        return "Excellent Match"
    if score >= 50:
        return "Good Match"
    return "Low Match"
