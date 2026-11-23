"""One application-facing mixin; maintenance internals remain independently testable."""

from .maintenance import MaintenanceRules
from .maintenance_arrivals import MaintenanceArrivals
from .maintenance_budget import MaintenanceBudgets
from .maintenance_dispatch import MaintenanceDispatch
from .maintenance_execution import MaintenanceExecution
from .maintenance_workers import MaintenanceWorkers
from .maintenance_scans import MaintenanceScans
from .maintenance_scheduler import MaintenanceScheduler
from .maintenance_configuration import MaintenanceConfiguration


class MaintenanceWorkflows(
    MaintenanceRules,
    MaintenanceArrivals,
    MaintenanceBudgets,
    MaintenanceDispatch,
    MaintenanceExecution,
    MaintenanceWorkers,
    MaintenanceScans,
    MaintenanceScheduler,
    MaintenanceConfiguration,
):
    pass
