"""
Report generator service.
Builds structured analysis reports from simulation data via ClaudeClient.
Supports section-by-section generation and interactive chat.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

from ..models.database import get_db
from ..utils.claude_client import ClaudeClient

logger = logging.getLogger('mirofish.report')


OUTLINE_SYSTEM_PROMPT = """You are a social-simulation research analyst.
Given simulation data (actions, config, agent profiles), plan a structured report.

IMPORTANT: Output valid JSON only. No markdown, no explanation.

## Output Schema

{
  "sections": [
    {
      "title": "Section Title",
      "description": "What this section should cover",
      "data_focus": "Which data to emphasize (actions, agents, timeline, etc.)"
    }
  ]
}

## Rules
1. Plan 5-7 sections covering: executive summary, simulation overview,
   key findings, agent behavior analysis, sentiment evolution, conclusions.
2. Each section title should be concise and descriptive.
3. data_focus helps determine which subset of data to send for that section.
"""


SECTION_SYSTEM_PROMPT = """You are writing one section of a social-simulation analysis report.
Write clear, insightful markdown content based on the data provided.

## Rules
1. Use markdown formatting (headers, bullet points, bold for emphasis).
2. Reference specific agent names and actions when making points.
3. Be analytical, not just descriptive -- draw insights and patterns.
4. Keep the section focused on its designated topic.
5. 200-500 words per section.
"""


CHAT_SYSTEM_PROMPT = """You are an AI research assistant that has generated a simulation report.
You have access to the full report and underlying simulation data.
Answer questions about the findings, provide deeper analysis, or explain methodology.
Be concise but thorough. Reference specific data points when possible."""


class ReportGenerator:
    """Generate structured analysis reports from simulation data."""

    def __init__(self, simulation_id: str):
        self.simulation_id = simulation_id
        self.client = ClaudeClient()

    def generate_report(
        self, progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """Generate full report with sections."""
        if progress_callback:
            progress_callback(5, "Loading simulation data")

        sim_data = self._load_simulation_data()
        actions = self._load_actions()
        config = json.loads(sim_data.get("config_json", "{}"))
        profiles = json.loads(sim_data.get("profiles_json", "[]"))

        if progress_callback:
            progress_callback(15, "Planning report outline")

        outline = self._plan_outline(config, profiles, actions)
        sections_plan = outline.get("sections", [])

        if progress_callback:
            progress_callback(20, f"Generating {len(sections_plan)} sections")

        completed_sections = []
        for idx, section_plan in enumerate(sections_plan):
            pct = 20 + int(((idx + 1) / len(sections_plan)) * 70)
            section_title = section_plan.get("title", f"Section {idx + 1}")

            if progress_callback:
                progress_callback(pct, f"Writing: {section_title}")

            content = self._generate_section(
                section_plan, config, profiles, actions, completed_sections
            )

            completed_sections.append({
                "title": section_title,
                "content": content,
                "order": idx,
            })

        report_id = f"rpt_{uuid.uuid4().hex[:12]}"

        if progress_callback:
            progress_callback(95, "Saving report")

        self._save_report(report_id, completed_sections, outline)

        if progress_callback:
            progress_callback(100, "Report complete")

        return {
            "report_id": report_id,
            "simulation_id": self.simulation_id,
            "sections": completed_sections,
            "outline": outline,
        }

    def chat(
        self,
        report_id: str,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Chat with report agent about findings."""
        report_data = self._load_report(report_id)
        sim_data = self._load_simulation_data()

        context = self._build_chat_context(report_data, sim_data)

        messages = list(history or [])
        messages.append({
            "role": "user",
            "content": f"{context}\n\nUser question: {message}",
        })

        return self.client.chat(
            messages=messages,
            system_prompt=CHAT_SYSTEM_PROMPT,
        )

    # -- internal helpers --

    def _load_simulation_data(self) -> Dict[str, Any]:
        """Load simulation record from DB."""
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM simulations WHERE id = ?",
                (self.simulation_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Simulation not found: {self.simulation_id}")
            return dict(row)
        finally:
            conn.close()

    def _load_actions(self) -> List[Dict[str, Any]]:
        """Load all actions for the simulation."""
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM agent_actions WHERE simulation_id = ? ORDER BY round_num",
                (self.simulation_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _plan_outline(
        self,
        config: Dict,
        profiles: List[Dict],
        actions: List[Dict],
    ) -> Dict[str, Any]:
        """Use Claude to plan report outline."""
        summary = self._build_data_summary(config, profiles, actions)
        messages = [{
            "role": "user",
            "content": (
                f"Plan a report outline for this simulation:\n\n{summary}\n\n"
                f"Total actions: {len(actions)}, "
                f"Total agents: {len(profiles)}, "
                f"Total rounds: {config.get('time_config', {}).get('total_hours', 10)}"
            ),
        }]

        return self.client.chat_json(
            messages=messages,
            system_prompt=OUTLINE_SYSTEM_PROMPT,
        )

    def _generate_section(
        self,
        section_plan: Dict,
        config: Dict,
        profiles: List[Dict],
        actions: List[Dict],
        previous_sections: List[Dict],
    ) -> str:
        """Generate one report section."""
        data_focus = section_plan.get("data_focus", "general")
        relevant_data = self._select_relevant_data(
            data_focus, config, profiles, actions
        )

        prev_titles = [s["title"] for s in previous_sections]
        prev_context = (
            f"Previously written sections: {', '.join(prev_titles)}"
            if prev_titles else ""
        )

        messages = [{
            "role": "user",
            "content": (
                f"## Section to Write\n\n"
                f"Title: {section_plan.get('title', 'Untitled')}\n"
                f"Description: {section_plan.get('description', '')}\n\n"
                f"{prev_context}\n\n"
                f"## Relevant Data\n\n{relevant_data}"
            ),
        }]

        return self.client.chat(
            messages=messages,
            system_prompt=SECTION_SYSTEM_PROMPT,
        )

    def _select_relevant_data(
        self,
        data_focus: str,
        config: Dict,
        profiles: List[Dict],
        actions: List[Dict],
    ) -> str:
        """Select and format data subset for a section."""
        focus_lower = data_focus.lower()
        parts = []

        parts.append(f"Topic: {config.get('simulation_topic', 'N/A')}")
        parts.append(f"Total rounds: {len(set(a.get('round_num') for a in actions))}")
        parts.append(f"Total actions: {len(actions)}")

        if "agent" in focus_lower or "behavior" in focus_lower:
            parts.append(self._format_agent_summary(profiles, actions))

        if "timeline" in focus_lower or "evolution" in focus_lower:
            parts.append(self._format_timeline_summary(actions))

        if "action" in focus_lower or "general" in focus_lower:
            parts.append(self._format_actions_sample(actions, limit=20))

        if "config" in focus_lower or "overview" in focus_lower:
            parts.append(f"Config: {json.dumps(config, indent=2)[:2000]}")

        return "\n\n".join(parts)

    def _format_agent_summary(
        self, profiles: List[Dict], actions: List[Dict]
    ) -> str:
        """Format per-agent statistics."""
        stats: Dict[str, Dict] = {}
        for act in actions:
            aid = act.get("agent_id", "?")
            aname = act.get("agent_name", "?")
            atype = act.get("action_type", "?")

            if aid not in stats:
                stats[aid] = {"name": aname, "total": 0, "types": {}}
            stats[aid]["total"] += 1
            stats[aid]["types"][atype] = stats[aid]["types"].get(atype, 0) + 1

        lines = ["## Agent Activity Summary"]
        for aid, s in stats.items():
            types_str = ", ".join(f"{k}:{v}" for k, v in s["types"].items())
            lines.append(f"- {s['name']} ({aid}): {s['total']} actions ({types_str})")

        return "\n".join(lines)

    def _format_timeline_summary(self, actions: List[Dict]) -> str:
        """Format actions by round."""
        rounds: Dict[int, int] = {}
        for act in actions:
            rn = act.get("round_num", 0)
            rounds[rn] = rounds.get(rn, 0) + 1

        lines = ["## Timeline Summary"]
        for rn in sorted(rounds.keys()):
            lines.append(f"- Round {rn}: {rounds[rn]} actions")

        return "\n".join(lines)

    def _format_actions_sample(
        self, actions: List[Dict], limit: int = 20
    ) -> str:
        """Format a sample of actions."""
        sample = actions[:limit]
        lines = [f"## Actions Sample (first {len(sample)})"]

        for act in sample:
            atype = act.get("action_type", "?")
            name = act.get("agent_name", "?")
            content = (act.get("content", "") or "")[:80]
            rn = act.get("round_num", 0)
            lines.append(f"- R{rn} {name} [{atype}]: {content}")

        return "\n".join(lines)

    def _build_data_summary(
        self, config: Dict, profiles: List[Dict], actions: List[Dict]
    ) -> str:
        """Build compact data summary for outline planning."""
        topic = config.get("simulation_topic", "N/A")
        agent_names = [p.get("name", "?") for p in profiles[:15]]
        action_types = {}
        for act in actions:
            at = act.get("action_type", "?")
            action_types[at] = action_types.get(at, 0) + 1

        return (
            f"Topic: {topic}\n"
            f"Agents: {', '.join(agent_names)}\n"
            f"Action breakdown: {json.dumps(action_types)}\n"
            f"Total actions: {len(actions)}"
        )

    def _build_chat_context(
        self, report_data: Optional[Dict], sim_data: Dict
    ) -> str:
        """Build context for report chat."""
        parts = ["## Report Context"]

        if report_data:
            sections = json.loads(report_data.get("sections_json", "[]"))
            for sec in sections:
                parts.append(f"### {sec.get('title', 'Untitled')}")
                parts.append(sec.get("content", "")[:500])

        config = json.loads(sim_data.get("config_json", "{}"))
        parts.append(f"\nTopic: {config.get('simulation_topic', 'N/A')}")

        return "\n\n".join(parts)

    def _save_report(
        self,
        report_id: str,
        sections: List[Dict],
        outline: Dict,
    ) -> None:
        """Save report to DB."""
        conn = get_db()
        now = datetime.utcnow().isoformat()
        try:
            conn.execute(
                "INSERT INTO reports (id, simulation_id, status, sections_json, outline, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    report_id,
                    self.simulation_id,
                    "completed",
                    json.dumps(sections, ensure_ascii=False),
                    json.dumps(outline, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _load_report(self, report_id: str) -> Optional[Dict]:
        """Load report from DB."""
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM reports WHERE id = ?", (report_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
