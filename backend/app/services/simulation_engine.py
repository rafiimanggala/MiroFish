"""
Simulation engine -- the core.
Each agent is a separate `claude -p` call per round.
Replaces OASIS with pure LLM-driven agent simulation.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from ..utils.claude_client import ClaudeClient

logger = logging.getLogger('mirofish.engine')


AGENT_SYSTEM_PROMPT = """You are roleplaying as a social-media user in a simulation.
Stay in character at all times. Your response MUST be valid JSON.

## Response Schema

{
  "action_type": "CREATE_POST | COMMENT | REACT | QUOTE | DO_NOTHING",
  "content": "Your post or comment text (empty string for REACT or DO_NOTHING)",
  "target_id": "The action ID you are replying to / reacting to (null if CREATE_POST or DO_NOTHING)",
  "reaction": "like | dislike (only for REACT, otherwise null)"
}

## Rules
1. Pick exactly ONE action per turn.
2. CREATE_POST: share your opinion on the topic (content required, target_id null).
3. COMMENT: reply to a specific post (content + target_id required).
4. REACT: like or dislike a post (reaction required, target_id required, content empty).
5. QUOTE: quote another post with your commentary (content + target_id required).
6. DO_NOTHING: skip this turn (all fields null/empty).
7. Content should feel natural, 1-3 sentences, matching your personality.
8. Stay consistent with your stance and background.
"""


class SimulationEngine:
    """Core simulation engine. Each agent = one claude -p call per round."""

    def __init__(
        self,
        simulation_id: str,
        config: Dict[str, Any],
        profiles: List[Dict[str, Any]],
        graph_data: Dict[str, Any],
    ):
        self.simulation_id = simulation_id
        self.config = config
        self.profiles = list(profiles)
        self.graph_data = dict(graph_data)
        self.actions: List[Dict[str, Any]] = []
        self.round_num = 0
        self.client = ClaudeClient()

    def run_round(self, round_num: int) -> List[Dict[str, Any]]:
        """Run one simulation round. Each active agent takes an action."""
        self.round_num = round_num
        active_agents = self._select_active_agents(round_num)
        round_actions: List[Dict[str, Any]] = []

        for agent in active_agents:
            try:
                action = self._run_agent_turn(agent, round_num)
                if action:
                    round_actions.append(action)
                    self.actions.append(action)
            except Exception as exc:
                logger.error(
                    "Agent %s round %d failed: %s",
                    agent.get("name", "?"), round_num, exc,
                )

        return round_actions

    def get_all_actions(
        self,
        platform: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get filtered actions."""
        result = list(self.actions)
        if platform:
            result = [a for a in result if a.get("platform") == platform]
        if agent_id:
            result = [a for a in result if a.get("agent_id") == agent_id]
        return result

    def get_timeline(self) -> List[Dict[str, Any]]:
        """Get actions grouped by round."""
        rounds: Dict[int, List[Dict]] = {}
        for action in self.actions:
            rn = action.get("round_num", 0)
            rounds.setdefault(rn, []).append(action)

        return [
            {"round_num": rn, "actions": acts}
            for rn, acts in sorted(rounds.items())
        ]

    def get_agent_stats(self) -> Dict[str, Any]:
        """Get per-agent statistics."""
        stats: Dict[str, Dict[str, int]] = {}
        for action in self.actions:
            aid = action.get("agent_id", "unknown")
            name = action.get("agent_name", "unknown")
            atype = action.get("action_type", "UNKNOWN")

            if aid not in stats:
                stats[aid] = {"agent_name": name, "total": 0}

            stats[aid]["total"] += 1
            stats[aid][atype] = stats[aid].get(atype, 0) + 1

        return stats

    # -- internal helpers --

    def _select_active_agents(self, round_num: int) -> List[Dict[str, Any]]:
        """Determine which agents are active this round."""
        total_rounds = self.config.get("time_config", {}).get(
            "total_hours", 10
        )
        sim_hour = self._compute_sim_hour(round_num)
        peak_hours = self.config.get("time_config", {}).get(
            "peak_hours", [19, 20, 21, 22]
        )

        active = []
        for profile in self.profiles:
            level = float(profile.get("activity_level", 0.5))
            is_peak = sim_hour in peak_hours

            # Higher activity level -> higher chance of being active
            threshold = 0.3 if is_peak else 0.5
            if level >= threshold:
                active.append(profile)

        return active

    def _compute_sim_hour(self, round_num: int) -> int:
        """Compute simulated hour-of-day for a round."""
        time_cfg = self.config.get("time_config", {})
        start_hour = time_cfg.get("start_hour", 8)
        hours_per_round = time_cfg.get("hours_per_round", 1)
        return (start_hour + round_num * hours_per_round) % 24

    def _compute_timestamp(self, round_num: int) -> str:
        """Compute simulated datetime for a round."""
        time_cfg = self.config.get("time_config", {})
        hours_per_round = time_cfg.get("hours_per_round", 1)
        base = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        delta = timedelta(hours=round_num * hours_per_round)
        return (base + delta).isoformat()

    def _run_agent_turn(
        self, agent: Dict[str, Any], round_num: int
    ) -> Optional[Dict[str, Any]]:
        """Execute one agent's turn via claude -p."""
        prompt = self._build_agent_prompt(agent, round_num)
        messages = [{"role": "user", "content": prompt}]

        try:
            response = self.client.chat_json(
                messages=messages,
                system_prompt=AGENT_SYSTEM_PROMPT,
            )
        except (RuntimeError, ValueError) as exc:
            logger.warning("Agent %s parse error: %s", agent.get("name"), exc)
            return None

        return self._parse_agent_action(response, agent, round_num)

    def _build_agent_prompt(
        self, agent: Dict[str, Any], round_num: int
    ) -> str:
        """Build the prompt for one agent's turn."""
        topic = self.config.get("simulation_topic", "General discussion")
        total_rounds = self._get_total_rounds()
        sim_hour = self._compute_sim_hour(round_num)
        recent = self._format_recent_actions(round_num, limit=8)
        trigger_event = self._get_trigger_event(round_num)

        prompt = (
            f"You are {agent.get('name', 'Agent')}, "
            f"a {agent.get('role', 'participant')}.\n"
            f"Personality: {agent.get('personality', '')}\n"
            f"Background: {agent.get('background', '')}\n\n"
            f"Topic: {topic}\n"
            f"Round {round_num}/{total_rounds}. "
            f"Simulated time: {sim_hour}:00.\n"
            f"Your stance: {agent.get('stance', 'neutral')}. "
            f"Key concerns: {', '.join(agent.get('key_concerns', []))}.\n\n"
        )

        if trigger_event:
            prompt += f"BREAKING EVENT: {trigger_event}\n\n"

        if recent:
            prompt += f"Recent discussion:\n{recent}\n\n"
        else:
            prompt += "No discussion yet. You may start the conversation.\n\n"

        prompt += (
            "Choose ONE action: CREATE_POST, COMMENT, REACT, QUOTE, or DO_NOTHING.\n"
            "Respond as JSON."
        )

        return prompt

    def _get_total_rounds(self) -> int:
        """Get total rounds from config."""
        time_cfg = self.config.get("time_config", {})
        total_hours = time_cfg.get("total_hours", 10)
        hours_per_round = time_cfg.get("hours_per_round", 1)
        return max(1, total_hours // max(1, hours_per_round))

    def _format_recent_actions(self, round_num: int, limit: int = 8) -> str:
        """Format recent actions as context for agent prompt."""
        recent = [
            a for a in self.actions
            if a.get("round_num", 0) >= max(0, round_num - 3)
        ][-limit:]

        if not recent:
            return ""

        lines = []
        for act in recent:
            atype = act.get("action_type", "?")
            name = act.get("agent_name", "?")
            content = act.get("content", "")
            act_id = act.get("id", "?")

            if atype == "CREATE_POST":
                lines.append(f"[{act_id}] {name} posted: \"{content}\"")
            elif atype == "COMMENT":
                target = act.get("target_id", "?")
                lines.append(f"[{act_id}] {name} replied to {target}: \"{content}\"")
            elif atype == "REACT":
                target = act.get("target_id", "?")
                reaction = act.get("reaction", "like")
                lines.append(f"[{act_id}] {name} {reaction}d {target}")
            elif atype == "QUOTE":
                target = act.get("target_id", "?")
                lines.append(f"[{act_id}] {name} quoted {target}: \"{content}\"")

        return "\n".join(lines)

    def _get_trigger_event(self, round_num: int) -> Optional[str]:
        """Check if a trigger event fires this round."""
        event_cfg = self.config.get("event_config", {})
        triggers = event_cfg.get("trigger_events", [])

        for evt in triggers:
            if evt.get("round") == round_num:
                return evt.get("description", "")

        return None

    def _parse_agent_action(
        self,
        response: Dict[str, Any],
        agent: Dict[str, Any],
        round_num: int,
    ) -> Optional[Dict[str, Any]]:
        """Parse claude response into structured action."""
        action_type = response.get("action_type", "DO_NOTHING").upper()

        valid_types = {"CREATE_POST", "COMMENT", "REACT", "QUOTE", "DO_NOTHING"}
        if action_type not in valid_types:
            action_type = "DO_NOTHING"

        if action_type == "DO_NOTHING":
            return None

        return {
            "id": f"act_{uuid.uuid4().hex[:12]}",
            "round_num": round_num,
            "agent_id": agent.get("agent_id", "unknown"),
            "agent_name": agent.get("name", "Unknown"),
            "platform": "forum",
            "action_type": action_type,
            "content": str(response.get("content", "")),
            "target_id": response.get("target_id"),
            "reaction": response.get("reaction"),
            "timestamp": self._compute_timestamp(round_num),
        }
