"""Evaluation harness. Only this package may read synthetic ground truth (PRD 12.6); M3 extends it."""

from .diagnosis_eval import DiagnosisEval, evaluate_diagnosis, format_diagnosis_report, write_report
from .identification_eval import IdentificationEval, evaluate_identification, format_report, load_ground_truth

__all__ = [
    "DiagnosisEval", "IdentificationEval", "evaluate_diagnosis", "evaluate_identification", "format_diagnosis_report",
    "format_report", "load_ground_truth", "write_report",
]  # fmt: skip
