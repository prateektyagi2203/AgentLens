"""Evaluation harness. Only this package may read synthetic ground truth (PRD 12.6); M3 extends it."""

from .identification_eval import IdentificationEval, evaluate_identification, format_report, load_ground_truth

__all__ = ["IdentificationEval", "evaluate_identification", "format_report", "load_ground_truth"]
