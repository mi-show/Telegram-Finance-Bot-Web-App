from dataclasses import dataclass


@dataclass(frozen=True)
class OCRQualityTargets:
    # Offline regression quality gates.
    amount_accuracy_min: float = 0.97
    item_extraction_ratio_min: float = 0.90
    false_high_confidence_max: float = 0.02
    latency_p95_seconds_max: float = 2.5


QUALITY_TARGETS = OCRQualityTargets()

# Runtime confidence cutoffs for safer auto-categorization.
MIN_AMOUNT_CONFIDENCE_AUTO = 0.70
MIN_ITEM_CONFIDENCE_AUTO = 0.60
MIN_RECEIPT_OVERALL_CONFIDENCE_AUTO = 0.65
 