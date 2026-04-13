"""
Profile generator service.
Converts graph entities into diverse agent profiles
for social-media simulation via ClaudeClient.
"""

import logging
from typing import Dict, Any, List, Optional

from ..utils.claude_client import ClaudeClient

logger = logging.getLogger('mirofish')

PROFILE_SYSTEM_PROMPT = """You are an expert social-simulation designer.
Given a list of entities from a knowledge graph and a simulation requirement,
generate diverse agent profiles representing market personas and stakeholders.

IMPORTANT: Output valid JSON only. No markdown, no explanation.

## Output Schema

{
  "profiles": [
    {
      "agent_id": "agent_001",
      "name": "Display Name",
      "role": "Short role title",
      "personality": "2-3 sentence personality description",
      "background": "2-3 sentence professional/social background",
      "interests": ["topic1", "topic2"],
      "activity_level": 0.7,
      "posting_frequency": 3,
      "interaction_tendency": 0.6,
      "stance": "supportive | skeptical | neutral | opposing | observer",
      "key_concerns": ["concern1", "concern2"]
    }
  ]
}

## Profile Design Rules

1. Profiles must be DIVERSE: include supporters, skeptics, neutrals, industry experts, end users.
2. activity_level: 0.0 (inactive) to 1.0 (hyperactive).
3. posting_frequency: 1 (rare) to 5 (very frequent).
4. interaction_tendency: 0.0 (lurker) to 1.0 (highly interactive).
5. stance: one of supportive, skeptical, neutral, opposing, observer.
6. Each profile should feel like a distinct, realistic person with clear motivations.
7. Base profiles on the entities provided, but create realistic human personas around them.
"""

MIN_AGENTS = 5
MAX_AGENTS = 15


class ProfileGenerator:
    """Generate diverse agent profiles from graph entities."""

    def __init__(self):
        self.client = ClaudeClient()

    def generate_profiles(
        self,
        entities: List[Dict[str, Any]],
        simulation_requirement: str,
        entity_types: Optional[List[str]] = None,
        num_agents: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Generate agent profiles based on entities and requirement."""
        agent_count = self._determine_count(entities, num_agents)
        user_msg = self._build_prompt(
            entities, simulation_requirement, entity_types, agent_count
        )
        messages = [{"role": "user", "content": user_msg}]

        result = self.client.chat_json(
            messages=messages,
            system_prompt=PROFILE_SYSTEM_PROMPT,
        )

        profiles = result.get("profiles", [])
        validated = [self._validate_profile(p, idx) for idx, p in enumerate(profiles)]
        logger.info("Generated %d agent profiles", len(validated))
        return validated

    def _determine_count(
        self,
        entities: List[Dict],
        num_agents: Optional[int],
    ) -> int:
        """Auto-determine agent count if not specified."""
        if num_agents is not None:
            return max(MIN_AGENTS, min(MAX_AGENTS, num_agents))

        entity_count = len(entities)
        if entity_count <= 5:
            return MIN_AGENTS
        if entity_count >= 20:
            return MAX_AGENTS
        return min(MAX_AGENTS, max(MIN_AGENTS, entity_count))

    def _build_prompt(
        self,
        entities: List[Dict],
        requirement: str,
        entity_types: Optional[List[str]],
        agent_count: int,
    ) -> str:
        """Build user prompt for profile generation."""
        entity_lines = self._format_entities(entities)
        types_str = ", ".join(entity_types) if entity_types else "N/A"

        return (
            f"## Simulation Requirement\n\n{requirement}\n\n"
            f"## Entity Types in Graph\n\n{types_str}\n\n"
            f"## Entities (from knowledge graph)\n\n{entity_lines}\n\n"
            f"## Instructions\n\n"
            f"Generate exactly {agent_count} agent profiles.\n"
            f"Ensure diversity: supporters, skeptics, neutrals, experts, end users.\n"
            f"Base profiles on the entities above but create realistic human personas."
        )

    def _format_entities(self, entities: List[Dict]) -> str:
        """Format entity list for prompt consumption."""
        lines = []
        for ent in entities[:50]:  # cap at 50 to stay within prompt limits
            name = ent.get("name", "Unknown")
            etype = ent.get("type", "Entity")
            summary = ent.get("summary", "")
            lines.append(f"- [{etype}] {name}: {summary}")

        return "\n".join(lines) if lines else "(no entities provided)"

    def _validate_profile(
        self, profile: Dict[str, Any], idx: int
    ) -> Dict[str, Any]:
        """Ensure profile has all required fields with valid ranges."""
        return {
            "agent_id": profile.get("agent_id", f"agent_{idx + 1:03d}"),
            "name": profile.get("name", f"Agent {idx + 1}"),
            "role": profile.get("role", "participant"),
            "personality": profile.get("personality", ""),
            "background": profile.get("background", ""),
            "interests": list(profile.get("interests", [])),
            "activity_level": self._clamp(
                float(profile.get("activity_level", 0.5)), 0.0, 1.0
            ),
            "posting_frequency": self._clamp(
                int(profile.get("posting_frequency", 3)), 1, 5
            ),
            "interaction_tendency": self._clamp(
                float(profile.get("interaction_tendency", 0.5)), 0.0, 1.0
            ),
            "stance": profile.get("stance", "neutral"),
            "key_concerns": list(profile.get("key_concerns", [])),
        }

    @staticmethod
    def _clamp(value, lo, hi):
        """Clamp numeric value between lo and hi."""
        return max(lo, min(hi, value))
