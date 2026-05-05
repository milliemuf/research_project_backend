"""
Repair pipeline module.

Wraps the multi-agent + consensus stages from `app.agents.agent_manager` with
the post-consensus steps the agent manager itself does not perform:
  * sandbox-validate the consensus-approved fix
  * (optionally) apply it to disk atomically with rollback on failure
  * emit metrics into the monitoring layer
  * record the repair in the knowledge graph

Author: Millicent Mufambi (H240624A)
"""
from app.repair.patch_applier import (
    PatchApplier,
    PatchApplyResult,
    PatchApplyStatus,
    patch_applier,
)
from app.repair.repair_pipeline import (
    RepairPipeline,
    RepairOutcome,
    RepairStage,
)
from app.repair.single_agent_pipeline import SingleAgentPipeline

__all__ = [
    "PatchApplier",
    "PatchApplyResult",
    "PatchApplyStatus",
    "patch_applier",
    "RepairPipeline",
    "RepairOutcome",
    "RepairStage",
    "SingleAgentPipeline",
]
