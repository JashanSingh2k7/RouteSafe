"""
services/smoke_dose.py

Cumulative Smoke Dose Calculator

THE HEADLINE FEATURE — what makes RouteSafe unique.

The problem: Route A spikes to AQI 200 for 15 minutes. Route B sits at
AQI 120 for 3 hours. Every other app says Route A is worse (higher peak).
But Route B actually puts MORE smoke in your lungs. Nobody calculates this.

The science:
    dose (µg) = PM2.5 concentration (µg/m³) × breathing rate (m³/hr) × time (hr)

    1 cigarette ≈ inhaling 22 µg/m³ of PM2.5 for 24 hours at rest
                = 22 × 0.5 m³/hr × 24 hr = 264 µg total inhaled
    (Source: Berkeley Earth, 2015)

    So: cigarette_equivalents = total_dose_µg / 264

This module also supports health profiles — a child with asthma gets a
higher effective dose from the same air than a healthy adult, because of
different breathing rates and sensitivity multipliers.

Used by: services/route_scorer.py
"""

import math
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH PROFILES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HealthProfile:
    """
    Defines how a person's body responds to smoke.

    breathing_rate_m3h: How much air they inhale per hour (m³/hr).
        - Driving is light activity (~1.0 m³/hr), not resting.
    sensitivity:        Multiplier for health impact. 1.0 = healthy adult.
        - Asthmatics experience ~2x the health effect per µg inhaled.
        - Children breathe faster per kg body weight and lungs are developing.
    label:              Human-readable name for the frontend.
    """
    breathing_rate_m3h: float
    sensitivity:        float
    label:              str


# Pre-defined profiles — frontend sends the key, we look it up
PROFILES: dict[str, HealthProfile] = {
    "default": HealthProfile(
        breathing_rate_m3h=1.0,
        sensitivity=1.0,
        label="Healthy adult (driving)",
    ),
    "child": HealthProfile(
        breathing_rate_m3h=0.35,
        sensitivity=1.6,
        label="Child (under 12)",
    ),
    "asthma": HealthProfile(
        breathing_rate_m3h=1.0,
        sensitivity=2.0,
        label="Asthma / respiratory condition",
    ),
    "elderly": HealthProfile(
        breathing_rate_m3h=0.45,
        sensitivity=1.4,
        label="Elderly (65+)",
    ),
    "pregnant": HealthProfile(
        breathing_rate_m3h=1.15,
        sensitivity=1.3,
        label="Pregnant",
    ),
    "outdoor_worker": HealthProfile(
        breathing_rate_m3h=1.8,
        sensitivity=1.0,
        label="Outdoor / truck worker (heavy breathing)",
    ),
}

# Cigarette equivalence constant: 1 cigarette = 264 µg inhaled PM2.5
# Derived from: 22 µg/m³ × 24 hours × 0.5 m³/hr resting breathing rate
MICROGRAMS_PER_CIGARETTE = 264.0


# ─────────────────────────────────────────────────────────────────────────────
# SEVERITY → PM2.5 CONVERSION
# ─────────────────────────────────────────────────────────────────────────────

# Maps our 0.0–1.0 severity score to estimated PM2.5 concentration (µg/m³)
# Based on EPA AQI breakpoints and our L2 severity model
SEVERITY_TO_PM25 = [
    (0.00,   0.0),
    (0.10,   8.0),      # good air
    (0.15,  12.0),      # AQI ~50
    (0.30,  35.4),      # AQI ~100 (moderate)
    (0.45,  55.4),      # AQI ~150 (unhealthy for sensitive groups)
    (0.60, 100.0),      # AQI ~200 (unhealthy)
    (0.80, 200.0),      # AQI ~300 (very unhealthy)
    (1.00, 350.0),      # AQI ~400+ (hazardous)
]


def severity_to_pm25(severity: float) -> float:
    """Convert a 0.0–1.0 severity score to estimated PM2.5 µg/m³.
    Uses linear interpolation between breakpoints."""
    if severity <= 0.0:
        return 0.0

    for i in range(1, len(SEVERITY_TO_PM25)):
        s_prev, pm_prev = SEVERITY_TO_PM25[i - 1]
        s_curr, pm_curr = SEVERITY_TO_PM25[i]

        if severity <= s_curr:
            ratio = (severity - s_prev) / (s_curr - s_prev) if s_curr != s_prev else 0
            return pm_prev + ratio * (pm_curr - pm_prev)

    return SEVERITY_TO_PM25[-1][1]


# ─────────────────────────────────────────────────────────────────────────────
# DOSE CALCULATION
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SegmentDose:
    """Smoke dose for one route segment."""
    segment_index:  int
    pm25_ugm3:      float       # estimated PM2.5 concentration on this segment
    time_hours:     float       # time spent on this segment
    raw_dose_ug:    float       # PM2.5 × breathing_rate × time
    effective_dose_ug: float    # raw_dose × sensitivity multiplier


@dataclass
class TripDose:
    """Aggregate smoke dose for the entire trip."""
    total_raw_dose_ug:       float
    total_effective_dose_ug: float
    cigarette_equivalents:   float
    profile_used:            str
    profile_label:           str
    segment_doses:           list[SegmentDose]
    peak_pm25_ugm3:          float
    avg_pm25_ugm3:           float
    time_in_smoke_min:       float      # minutes spent in PM2.5 > 12 µg/m³
    health_advisory:         str        # plain English summary


def calculate_trip_dose(
    segment_severities: list[tuple[int, float, float]],
    profile_key: str = "default",
) -> TripDose:
    """
    Calculate cumulative smoke dose for an entire trip.

    Args:
        segment_severities: List of (segment_index, risk_score, travel_time_min)
                           for each segment from the route scorer.
        profile_key:       Health profile key ("default", "child", "asthma", etc.)

    Returns:
        TripDose with total dose, cigarette equivalents, and per-segment breakdown.
    """
    profile = PROFILES.get(profile_key, PROFILES["default"])

    segment_doses: list[SegmentDose] = []
    total_raw = 0.0
    total_effective = 0.0
    peak_pm25 = 0.0
    weighted_pm25_sum = 0.0
    total_time_hours = 0.0
    smoke_time_min = 0.0

    for seg_index, severity, travel_time_min in segment_severities:
        time_hours = travel_time_min / 60.0
        pm25 = severity_to_pm25(severity)

        # Core dose formula: concentration × volume of air inhaled
        raw_dose = pm25 * profile.breathing_rate_m3h * time_hours
        effective_dose = raw_dose * profile.sensitivity

        segment_doses.append(SegmentDose(
            segment_index=seg_index,
            pm25_ugm3=round(pm25, 2),
            time_hours=round(time_hours, 4),
            raw_dose_ug=round(raw_dose, 2),
            effective_dose_ug=round(effective_dose, 2),
        ))

        total_raw += raw_dose
        total_effective += effective_dose
        peak_pm25 = max(peak_pm25, pm25)
        weighted_pm25_sum += pm25 * time_hours
        total_time_hours += time_hours

        # Track time spent breathing smoke (PM2.5 > 12 µg/m³ = above "good" threshold)
        if pm25 > 12.0:
            smoke_time_min += travel_time_min

    # Weighted average PM2.5 across the trip
    avg_pm25 = weighted_pm25_sum / total_time_hours if total_time_hours > 0 else 0.0

    # The headline number
    cigarettes = total_effective / MICROGRAMS_PER_CIGARETTE

    # Generate health advisory
    advisory = _generate_advisory(cigarettes, peak_pm25, smoke_time_min, profile)

    logger.info(
        "Dose calculated [%s]: %.1f µg raw, %.1f µg effective, %.2f cigarettes, "
        "peak PM2.5=%.1f, %.0f min in smoke",
        profile.label, total_raw, total_effective, cigarettes, peak_pm25, smoke_time_min,
    )

    return TripDose(
        total_raw_dose_ug=round(total_raw, 2),
        total_effective_dose_ug=round(total_effective, 2),
        cigarette_equivalents=round(cigarettes, 2),
        profile_used=profile_key,
        profile_label=profile.label,
        segment_doses=segment_doses,
        peak_pm25_ugm3=round(peak_pm25, 2),
        avg_pm25_ugm3=round(avg_pm25, 2),
        time_in_smoke_min=round(smoke_time_min, 1),
        health_advisory=advisory,
    )


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH ADVISORY GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

def _generate_advisory(
    cigarettes: float,
    peak_pm25: float,
    smoke_time_min: float,
    profile: HealthProfile,
) -> str:
    """Generate a plain English health advisory based on dose results."""

    if cigarettes < 0.1:
        return "Air quality along this route is good. No precautions needed."

    if cigarettes < 0.5:
        base = "Low smoke exposure expected."
        if profile.sensitivity > 1.0:
            return f"{base} Consider having medication accessible as a precaution."
        return f"{base} Most people will not notice any effects."

    if cigarettes < 1.5:
        base = (
            f"Moderate smoke exposure — equivalent to about {cigarettes:.1f} cigarettes. "
            f"You'll be in smoky air for approximately {smoke_time_min:.0f} minutes."
        )
        if profile.sensitivity > 1.0:
            return (
                f"{base} Given your health profile ({profile.label}), "
                "consider an alternate route or delaying departure. "
                "Keep windows closed and use recirculated air in your vehicle."
            )
        return f"{base} Keep windows closed and set your vehicle AC to recirculate."

    if cigarettes < 3.0:
        return (
            f"High smoke exposure — equivalent to {cigarettes:.1f} cigarettes over "
            f"{smoke_time_min:.0f} minutes. Peak PM2.5 reaches {peak_pm25:.0f} µg/m³. "
            "Strongly recommend an alternate route or later departure time. "
            "If unavoidable, keep windows sealed, use recirculated air, "
            "and consider wearing an N95 mask."
        )

    return (
        f"Severe smoke exposure — equivalent to {cigarettes:.1f} cigarettes. "
        f"Peak PM2.5 of {peak_pm25:.0f} µg/m³ for {smoke_time_min:.0f} minutes. "
        "This route poses a serious health risk. "
        "DO NOT take this route if traveling with children, elderly, "
        "or anyone with respiratory conditions. "
        "Delay your trip or choose an alternate route."
    )


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Simulate a 20-segment route with varying smoke levels
    test_segments = []
    for i in range(20):
        # Segments 3–12 pass through smoke, rest are clean
        if 3 <= i <= 12:
            severity = 0.3 + 0.15 * math.sin(i * 0.5)  # varies 0.15–0.45
        else:
            severity = 0.0
        test_segments.append((i, severity, 6.0))  # 6 min each

    print("=" * 60)
    print("SMOKE DOSE CALCULATOR — TEST")
    print("=" * 60)

    for profile_key in ["default", "child", "asthma", "outdoor_worker"]:
        dose = calculate_trip_dose(test_segments, profile_key)
        print(f"\n[{dose.profile_label}]")
        print(f"  Total dose:    {dose.total_effective_dose_ug:.1f} µg")
        print(f"  Cigarettes:    {dose.cigarette_equivalents:.2f}")
        print(f"  Peak PM2.5:    {dose.peak_pm25_ugm3:.1f} µg/m³")
        print(f"  Avg PM2.5:     {dose.avg_pm25_ugm3:.1f} µg/m³")
        print(f"  Time in smoke: {dose.time_in_smoke_min:.0f} min")
        print(f"  Advisory:      {dose.health_advisory[:80]}...")