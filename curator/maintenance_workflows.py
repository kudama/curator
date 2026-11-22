"""One application-facing mixin; maintenance internals remain independently testable."""

from .maintenance import MaintenanceRules
from .maintenance_arrivals import MaintenanceArrivals
from .maintenance_budget import MaintenanceBudgets
from .maintenance_dispatch import MaintenanceDispatch
from .maintenance_execution import MaintenanceExecution
from .maintenance_workers import MaintenanceWorkers


class MaintenanceWorkflows(
    MaintenanceRules,
    MaintenanceArrivals,
    MaintenanceBudgets,
    MaintenanceDispatch,
    MaintenanceExecution,
    MaintenanceWorkers,
):
    pass
