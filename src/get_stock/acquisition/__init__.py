"""Allowlisted acquisition service used by the stock-analysis Supervisor."""

from get_stock.acquisition.coordinator import DataAcquisitionCoordinator
from get_stock.acquisition.schemas import AcquisitionJob, AcquisitionRequest, AcquisitionResult

__all__ = [
    "AcquisitionJob",
    "AcquisitionRequest",
    "AcquisitionResult",
    "DataAcquisitionCoordinator",
]
