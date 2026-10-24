"""ResiliNet | Boston Hospital Cascade — weekly epidemic -> hospital dependency
-> rerouting -> access simulator.

All code is authored through Kiro. The authoritative specification is in
``architecture.md``, ``docs/mathematical-model.md``,
``docs/weekly-state-machine.md``, and ``contracts/``. The implementation follows
the APPROVED defaults (need-state SEIR, risk_weight on hospitalization, weekly
cohort LOS, deterministic allocation priority, requested-load FDNA).
"""

__all__ = ["__version__", "ALGORITHM_VERSION"]

__version__ = "0.1.0"
# Bumped whenever a change alters numeric results; feeds into ``run_id``.
ALGORITHM_VERSION = "resilinet-engine-2026.10.24"
