"""
Simulation config generator service.
Uses ClaudeClient to produce simulation parameters
(time, events, platform, topic, expected dynamics).
"""

import logging
from typing import Dict, Any, List, Optional

from ..utils.claude_client import ClaudeClient

logger = logging.getLogger('mirofish')

CONFIG_SYSTEM_PROMPT = """You are a social-media simulation architect.
Given a simulation requirement, entity summary, and agent profiles,
generate detailed simulation configuration parameters.

IMPORTANT: Output valid JSON only. No markdown, no explanation.

## Output Schema

{
  "time_config": {
    "total_hours": 72,
    "hours_per_round": 1,
    "start_hour": 8,
    "peak_hours": [19, 20, 21, 22],
    "activity_pattern": "Description of daily activity rhythm"
  },
  "event_config": {
    "trigger_events": [
      {
        "round": 1,
        "description": "Event description",
        "affected_agents": ["agent_001", "agent_002"]
      }
    ],
    "event_effects": "Description of how events ripple through the simulation"
  },
  "platform_config": {
    "enable_posts": true,
    "enable_comments": true,
    "enable_reactions": true
  },
  "simulation_topic": "Main topic or question being simulated",
  "expected_dynamics": "What is expected to happen during the simulation"
}

## Design Rules

1. total_hours: realistic duration (24-168 hours depending on topic).
2. hours_per_round: 1-4 hours per simulation round.
3. peak_hours: when most social-media activity occurs.
4. trigger_events: 2-5 events that drive discussion shifts.
5. affected_agents: reference actual agent_ids from the profiles.
6. simulation_topic: concise topic/question (1-2 sentences).
7. expected_dynamics: realistic prediction of opinion evolution.
"""


class SimConfigGenerator:
    """Generate simulation configuration from requirements and profiles."""

    def __init__(self):
        self.client = ClaudeClient()

    def generate_config(
        self,
        simulation_requirement: str,
        entities: List[Dict[str, Any]],
        profiles: List[Dict[str, Any]],
        max_rounds: int = 10,
    ) -> Dict[str, Any]:
        """Generate full simulation config via Claude."""
        user_msg = self._build_prompt(
            simulation_requirement, entities, profiles, max_rounds
        )
        messages = [{"role": "user", "content": user_msg}]

        result = self.client.chat_json(
            messages=messages,
            system_prompt=CONFIG_SYSTEM_PROMPT,
        )

        validated = self._validate(result, profiles, max_rounds)
        logger.info("Generated simulation config: %d rounds", max_rounds)
        return validated

    def _build_prompt(
        self,
        requirement: str,
        entities: List[Dict],
        profiles: List[Dict],
        max_rounds: int,
    ) -> str:
        """Build user prompt with requirement, entities, and profiles."""
        entity_summary = self._summarize_entities(entities)
        profile_summary = self._summarize_profiles(profiles)
        agent_ids = [p.get("agent_id", "") for p in profiles]

        return (
            f"## Simulation Requirement\n\n{requirement}\n\n"
            f"## Entity Summary\n\n{entity_summary}\n\n"
            f"## Agent Profiles\n\n{profile_summary}\n\n"
            f"## Available Agent IDs\n\n{', '.join(agent_ids)}\n\n"
            f"## Constraints\n\n"
            f"- Maximum rounds: {max_rounds}\n"
            f"- Reference only the agent IDs listed above in trigger_events.\n"
            f"- Generate 2-5 trigger events spread across rounds 1 to {max_rounds}."
        )

    def _summarize_entities(self, entities: List[Dict]) -> str:
        """Compact entity list for prompt."""
        lines = []
        for ent in entities[:30]:
            name = ent.get("name", "?")
            etype = ent.get("type", "Entity")
            lines.append(f"- [{etype}] {name}")

        return "\n".join(lines) if lines else "(no entities)"

    def _summarize_profiles(self, profiles: List[Dict]) -> str:
        """Compact profile list for prompt."""
        lines = []
        for p in profiles:
            agent_id = p.get("agent_id", "?")
            name = p.get("name", "?")
            role = p.get("role", "?")
            stance = p.get("stance", "neutral")
            lines.append(f"- {agent_id}: {name} ({role}, {stance})")

        return "\n".join(lines) if lines else "(no profiles)"

    def _validate(
        self,
        result: Dict[str, Any],
        profiles: List[Dict],
        max_rounds: int,
    ) -> Dict[str, Any]:
        """Validate and sanitize config output."""
        time_cfg = self._validate_time_config(
            result.get("time_config", {}), max_rounds
        )
        event_cfg = self._validate_event_config(
            result.get("event_config", {}), profiles, max_rounds
        )
        platform_cfg = self._validate_platform_config(
            result.get("platform_config", {})
        )

        return {
            "time_config": time_cfg,
            "event_config": event_cfg,
            "platform_config": platform_cfg,
            "simulation_topic": result.get("simulation_topic", ""),
            "expected_dynamics": result.get("expected_dynamics", ""),
        }

    def _validate_time_config(
        self, cfg: Dict, max_rounds: int
    ) -> Dict[str, Any]:
        """Ensure time config has valid values."""
        total_hours = max(1, int(cfg.get("total_hours", max_rounds)))
        hours_per_round = max(1, min(4, int(cfg.get("hours_per_round", 1))))

        return {
            "total_hours": total_hours,
            "hours_per_round": hours_per_round,
            "start_hour": max(0, min(23, int(cfg.get("start_hour", 8)))),
            "peak_hours": cfg.get("peak_hours", [19, 20, 21, 22]),
            "activity_pattern": cfg.get("activity_pattern", "Standard daily cycle"),
        }

    def _validate_event_config(
        self,
        cfg: Dict,
        profiles: List[Dict],
        max_rounds: int,
    ) -> Dict[str, Any]:
        """Validate trigger events reference valid agents and rounds."""
        valid_ids = {p.get("agent_id", "") for p in profiles}
        raw_events = cfg.get("trigger_events", [])
        validated_events = []

        for evt in raw_events[:5]:
            round_num = max(1, min(max_rounds, int(evt.get("round", 1))))
            affected = [
                aid for aid in evt.get("affected_agents", [])
                if aid in valid_ids
            ]
            validated_events.append({
                "round": round_num,
                "description": evt.get("description", ""),
                "affected_agents": affected,
            })

        return {
            "trigger_events": validated_events,
            "event_effects": cfg.get("event_effects", ""),
        }

    @staticmethod
    def _validate_platform_config(cfg: Dict) -> Dict[str, bool]:
        """Ensure platform config has boolean toggles."""
        return {
            "enable_posts": bool(cfg.get("enable_posts", True)),
            "enable_comments": bool(cfg.get("enable_comments", True)),
            "enable_reactions": bool(cfg.get("enable_reactions", True)),
        }
