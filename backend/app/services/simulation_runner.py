"""
Simulation runner -- manages background execution of simulations.
Spawns background threads, tracks state, supports interview and stop.
"""

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from ..models.database import get_db
from ..utils.claude_client import ClaudeClient
from ..utils.task_manager import TaskManager, TASK_PROCESSING, TASK_COMPLETED, TASK_FAILED
from .simulation_engine import SimulationEngine

logger = logging.getLogger('mirofish.runner')


class SimulationRunner:
    """Manages background simulation execution."""

    _instances: Dict[str, Dict[str, Any]] = {}
    _lock = threading.Lock()

    @classmethod
    def start_simulation(cls, simulation_id: str) -> Dict[str, Any]:
        """Start simulation in background thread."""
        with cls._lock:
            if simulation_id in cls._instances:
                state = cls._instances[simulation_id]
                if state.get("running"):
                    return {"status": "already_running", "simulation_id": simulation_id}

        sim_data = cls._load_simulation(simulation_id)
        if not sim_data:
            raise ValueError(f"Simulation not found: {simulation_id}")

        config = json.loads(sim_data["config_json"] or "{}")
        profiles = json.loads(sim_data["profiles_json"] or "[]")
        graph_data = cls._load_graph_data(sim_data["graph_id"])

        engine = SimulationEngine(simulation_id, config, profiles, graph_data)
        total_rounds = engine._get_total_rounds()

        initial_state = {
            "simulation_id": simulation_id,
            "engine": engine,
            "running": True,
            "stop_requested": False,
            "current_round": 0,
            "total_rounds": total_rounds,
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
        }

        with cls._lock:
            cls._instances[simulation_id] = initial_state

        cls._update_sim_status(simulation_id, "running")

        thread = threading.Thread(
            target=cls._run_simulation_loop,
            args=(simulation_id,),
            daemon=True,
        )
        thread.start()

        return {
            "status": "started",
            "simulation_id": simulation_id,
            "total_rounds": total_rounds,
        }

    @classmethod
    def _run_simulation_loop(cls, simulation_id: str) -> None:
        """Background loop: run rounds until complete or stopped."""
        state = cls._instances.get(simulation_id)
        if not state:
            return

        engine: SimulationEngine = state["engine"]
        total_rounds = state["total_rounds"]

        try:
            for round_num in range(1, total_rounds + 1):
                if state.get("stop_requested"):
                    logger.info("Simulation %s stopped at round %d", simulation_id, round_num)
                    break

                logger.info("Simulation %s round %d/%d", simulation_id, round_num, total_rounds)
                actions = engine.run_round(round_num)

                cls._save_round_actions(simulation_id, actions)
                cls._update_round_progress(simulation_id, round_num, total_rounds)

                time.sleep(0.5)

            final_status = "stopped" if state.get("stop_requested") else "completed"
            cls._finalize_simulation(simulation_id, final_status)

        except Exception as exc:
            logger.error("Simulation %s failed: %s", simulation_id, exc)
            cls._finalize_simulation(simulation_id, "failed", str(exc))

    @classmethod
    def get_status(cls, simulation_id: str) -> Dict[str, Any]:
        """Get current run status."""
        with cls._lock:
            state = cls._instances.get(simulation_id)

        if state:
            return {
                "simulation_id": simulation_id,
                "status": state.get("status", "unknown"),
                "current_round": state.get("current_round", 0),
                "total_rounds": state.get("total_rounds", 0),
                "running": state.get("running", False),
                "started_at": state.get("started_at"),
            }

        # Fall back to DB
        sim = cls._load_simulation(simulation_id)
        if sim:
            return {
                "simulation_id": simulation_id,
                "status": sim["status"],
                "current_round": sim["current_round"],
                "total_rounds": sim["total_rounds"],
                "running": False,
            }

        return {"simulation_id": simulation_id, "status": "not_found"}

    @classmethod
    def stop_simulation(cls, simulation_id: str) -> Dict[str, Any]:
        """Stop running simulation."""
        with cls._lock:
            state = cls._instances.get(simulation_id)
            if not state or not state.get("running"):
                return {"status": "not_running", "simulation_id": simulation_id}
            state["stop_requested"] = True

        return {"status": "stop_requested", "simulation_id": simulation_id}

    @classmethod
    def interview_agent(
        cls,
        simulation_id: str,
        agent_id: str,
        question: str,
    ) -> Dict[str, Any]:
        """Interview an agent mid or post simulation."""
        sim_data = cls._load_simulation(simulation_id)
        if not sim_data:
            raise ValueError(f"Simulation not found: {simulation_id}")

        profiles = json.loads(sim_data["profiles_json"] or "[]")
        profile = cls._find_profile(profiles, agent_id)
        if not profile:
            raise ValueError(f"Agent not found: {agent_id}")

        agent_actions = cls._load_agent_actions(simulation_id, agent_id)
        context = cls._build_interview_context(profile, agent_actions)

        client = ClaudeClient()
        system_prompt = (
            f"You are {profile.get('name', 'Agent')}, a {profile.get('role', 'participant')}. "
            f"Personality: {profile.get('personality', '')}. "
            f"Background: {profile.get('background', '')}. "
            f"Stance: {profile.get('stance', 'neutral')}. "
            "Answer the interviewer's question in character, based on your "
            "experiences and actions during the simulation. "
            "Respond in plain text (not JSON)."
        )

        messages = [{"role": "user", "content": f"{context}\n\nQuestion: {question}"}]
        response = client.chat(messages=messages, system_prompt=system_prompt)

        return {
            "agent_id": agent_id,
            "agent_name": profile.get("name", "Unknown"),
            "question": question,
            "answer": response,
        }

    # -- internal DB helpers --

    @classmethod
    def _load_simulation(cls, simulation_id: str) -> Optional[Dict]:
        """Load simulation row from DB."""
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM simulations WHERE id = ?", (simulation_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @classmethod
    def _load_graph_data(cls, graph_id: str) -> Dict[str, Any]:
        """Load graph nodes and edges from DB."""
        conn = get_db()
        try:
            nodes = conn.execute(
                "SELECT id, name, entity_type, attributes_json, summary "
                "FROM graph_nodes WHERE graph_id = ?",
                (graph_id,),
            ).fetchall()

            edges = conn.execute(
                "SELECT id, source_node_id, target_node_id, edge_type, fact "
                "FROM graph_edges WHERE graph_id = ?",
                (graph_id,),
            ).fetchall()

            return {
                "nodes": [dict(n) for n in nodes],
                "edges": [dict(e) for e in edges],
            }
        finally:
            conn.close()

    @classmethod
    def _save_round_actions(
        cls, simulation_id: str, actions: List[Dict[str, Any]]
    ) -> None:
        """Persist actions from one round to agent_actions table."""
        if not actions:
            return

        conn = get_db()
        try:
            for act in actions:
                conn.execute(
                    "INSERT INTO agent_actions "
                    "(id, simulation_id, round_num, agent_id, agent_name, "
                    "platform, action_type, content, target_id, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        act.get("id", f"act_{uuid.uuid4().hex[:12]}"),
                        simulation_id,
                        act.get("round_num", 0),
                        act.get("agent_id", ""),
                        act.get("agent_name", ""),
                        act.get("platform", "forum"),
                        act.get("action_type", ""),
                        act.get("content", ""),
                        act.get("target_id"),
                        act.get("timestamp", datetime.utcnow().isoformat()),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def _update_round_progress(
        cls, simulation_id: str, round_num: int, total_rounds: int
    ) -> None:
        """Update in-memory state and DB with round progress."""
        with cls._lock:
            state = cls._instances.get(simulation_id)
            if state:
                state["current_round"] = round_num

        conn = get_db()
        try:
            conn.execute(
                "UPDATE simulations SET current_round = ?, updated_at = ? WHERE id = ?",
                (round_num, datetime.utcnow().isoformat(), simulation_id),
            )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def _update_sim_status(cls, simulation_id: str, status: str) -> None:
        """Update simulation status in DB."""
        conn = get_db()
        try:
            conn.execute(
                "UPDATE simulations SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.utcnow().isoformat(), simulation_id),
            )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def _finalize_simulation(
        cls, simulation_id: str, status: str, error: Optional[str] = None
    ) -> None:
        """Mark simulation as finished."""
        with cls._lock:
            state = cls._instances.get(simulation_id)
            if state:
                state["running"] = False
                state["status"] = status

        conn = get_db()
        try:
            if error:
                conn.execute(
                    "UPDATE simulations SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                    (status, error, datetime.utcnow().isoformat(), simulation_id),
                )
            else:
                conn.execute(
                    "UPDATE simulations SET status = ?, updated_at = ? WHERE id = ?",
                    (status, datetime.utcnow().isoformat(), simulation_id),
                )
            conn.commit()
        finally:
            conn.close()

        logger.info("Simulation %s finalized: %s", simulation_id, status)

    @classmethod
    def _load_agent_actions(
        cls, simulation_id: str, agent_id: str
    ) -> List[Dict]:
        """Load actions for a specific agent."""
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM agent_actions "
                "WHERE simulation_id = ? AND agent_id = ? "
                "ORDER BY round_num",
                (simulation_id, agent_id),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def _find_profile(
        cls, profiles: List[Dict], agent_id: str
    ) -> Optional[Dict]:
        """Find agent profile by ID."""
        for p in profiles:
            if p.get("agent_id") == agent_id:
                return p
        return None

    @classmethod
    def _build_interview_context(
        cls, profile: Dict, actions: List[Dict]
    ) -> str:
        """Build context string for agent interview."""
        lines = [f"Your actions during the simulation:"]
        for act in actions[-20:]:
            atype = act.get("action_type", "?")
            content = act.get("content", "")
            rn = act.get("round_num", 0)
            lines.append(f"  Round {rn}: {atype} - {content[:100]}")

        return "\n".join(lines)

    @classmethod
    def register_cleanup(cls) -> None:
        """Register cleanup to stop all simulations on shutdown."""
        import atexit

        def _cleanup():
            with cls._lock:
                for sid, state in cls._instances.items():
                    if state.get("running"):
                        state["stop_requested"] = True
                        logger.info("Cleanup: stopping simulation %s", sid)

        atexit.register(_cleanup)
