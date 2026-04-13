"""
Simulation API routes.
Handles simulation creation, execution, action querying, and agent interviews.
"""

import json
import logging
import threading
import traceback
import uuid
from datetime import datetime

from flask import request, jsonify

from . import simulation_bp
from ..config import Config
from ..models.database import get_db
from ..utils.task_manager import TaskManager, TASK_PROCESSING, TASK_COMPLETED, TASK_FAILED
from ..services.profile_generator import ProfileGenerator
from ..services.sim_config_generator import SimConfigGenerator
from ..services.simulation_runner import SimulationRunner
from ..services.graph_builder import GraphBuilderService

logger = logging.getLogger('mirofish.api.simulation')


# ============== Create Simulation ==============

@simulation_bp.route('/create', methods=['POST'])
def create_simulation():
    """
    Create a new simulation from a project.
    Generates profiles + config in background.
    Accepts {project_id}.
    Returns {success, simulation_id, task_id}.
    """
    try:
        data = request.get_json(silent=True) or {}
        project_id = data.get('project_id')
        if not project_id:
            return jsonify({"success": False, "error": "project_id is required"}), 400

        project = _load_project(project_id)
        if not project:
            return jsonify({"success": False, "error": f"Project not found: {project_id}"}), 404

        graph_id = project.get("graph_id")
        if not graph_id:
            return jsonify({"success": False, "error": "Project has no graph. Build graph first."}), 400

        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat()
        max_rounds = Config.DEFAULT_MAX_ROUNDS

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO simulations "
                "(id, project_id, graph_id, status, total_rounds, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (simulation_id, project_id, graph_id, "preparing", max_rounds, now, now),
            )
            conn.commit()
        finally:
            conn.close()

        task_mgr = TaskManager()
        task_id = task_mgr.create_task("simulation_prepare", {"simulation_id": simulation_id})

        thread = threading.Thread(
            target=_prepare_simulation_worker,
            args=(task_id, simulation_id, project, graph_id, max_rounds),
            daemon=True,
        )
        thread.start()

        return jsonify({
            "success": True,
            "simulation_id": simulation_id,
            "task_id": task_id,
        })

    except Exception as exc:
        logger.error("Create simulation failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


def _prepare_simulation_worker(
    task_id: str,
    simulation_id: str,
    project: dict,
    graph_id: str,
    max_rounds: int,
) -> None:
    """Background worker: generate profiles + config."""
    task_mgr = TaskManager()
    try:
        task_mgr.update_task(task_id, status=TASK_PROCESSING, progress=10, message="Loading graph data")

        builder = GraphBuilderService()
        graph_data = builder.get_graph_data(graph_id)
        entities = graph_data.get("nodes", [])

        requirement = project.get("simulation_requirement", "")
        ontology = json.loads(project.get("ontology_json", "{}") or "{}")
        entity_types = [et.get("name") for et in ontology.get("entity_types", [])]

        task_mgr.update_task(task_id, progress=30, message="Generating agent profiles")

        profiler = ProfileGenerator()
        profiles = profiler.generate_profiles(entities, requirement, entity_types)

        task_mgr.update_task(task_id, progress=60, message="Generating simulation config")

        config_gen = SimConfigGenerator()
        config = config_gen.generate_config(requirement, entities, profiles, max_rounds)

        task_mgr.update_task(task_id, progress=80, message="Saving to database")

        conn = get_db()
        try:
            conn.execute(
                "UPDATE simulations SET config_json = ?, profiles_json = ?, "
                "status = 'ready', updated_at = ? WHERE id = ?",
                (
                    json.dumps(config, ensure_ascii=False),
                    json.dumps(profiles, ensure_ascii=False),
                    datetime.utcnow().isoformat(),
                    simulation_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        task_mgr.complete_task(task_id, {
            "simulation_id": simulation_id,
            "profiles_count": len(profiles),
            "config": config,
        })

    except Exception as exc:
        logger.error("Prepare simulation failed: %s", exc)
        task_mgr.fail_task(task_id, str(exc))

        conn = get_db()
        try:
            conn.execute(
                "UPDATE simulations SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                (str(exc), datetime.utcnow().isoformat(), simulation_id),
            )
            conn.commit()
        finally:
            conn.close()


# ============== Get Simulation ==============

@simulation_bp.route('/<simulation_id>', methods=['GET'])
def get_simulation(simulation_id: str):
    """Return simulation state."""
    sim = _load_simulation(simulation_id)
    if not sim:
        return jsonify({"success": False, "error": f"Simulation not found: {simulation_id}"}), 404

    result = dict(sim)
    result["config"] = json.loads(result.pop("config_json", "null") or "null")
    result["profiles"] = json.loads(result.pop("profiles_json", "null") or "null")

    # Merge runtime status if running
    runtime = SimulationRunner.get_status(simulation_id)
    if runtime.get("running"):
        result["status"] = runtime.get("status", result.get("status"))
        result["current_round"] = runtime.get("current_round", result.get("current_round"))

    return jsonify({"success": True, "data": result})


# ============== Start / Stop Simulation ==============

@simulation_bp.route('/<simulation_id>/start', methods=['POST'])
def start_simulation(simulation_id: str):
    """Start simulation via SimulationRunner."""
    try:
        sim = _load_simulation(simulation_id)
        if not sim:
            return jsonify({"success": False, "error": f"Simulation not found: {simulation_id}"}), 404

        if sim["status"] not in ("ready", "stopped", "completed"):
            return jsonify({
                "success": False,
                "error": f"Cannot start simulation in status: {sim['status']}",
            }), 400

        result = SimulationRunner.start_simulation(simulation_id)
        return jsonify({"success": True, "data": result})

    except Exception as exc:
        logger.error("Start simulation failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@simulation_bp.route('/<simulation_id>/stop', methods=['POST'])
def stop_simulation(simulation_id: str):
    """Stop running simulation."""
    try:
        result = SimulationRunner.stop_simulation(simulation_id)
        return jsonify({"success": True, "data": result})
    except Exception as exc:
        logger.error("Stop simulation failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ============== Actions & Timeline ==============

@simulation_bp.route('/<simulation_id>/actions', methods=['GET'])
def get_actions(simulation_id: str):
    """
    Query simulation actions.
    Query params: platform, agent_id, min_round, max_round, limit.
    """
    try:
        platform = request.args.get('platform')
        agent_id = request.args.get('agent_id')
        min_round = request.args.get('min_round', type=int)
        max_round = request.args.get('max_round', type=int)
        limit = request.args.get('limit', 100, type=int)

        conn = get_db()
        try:
            query = "SELECT * FROM agent_actions WHERE simulation_id = ?"
            params: list = [simulation_id]

            if platform:
                query += " AND platform = ?"
                params.append(platform)
            if agent_id:
                query += " AND agent_id = ?"
                params.append(agent_id)
            if min_round is not None:
                query += " AND round_num >= ?"
                params.append(min_round)
            if max_round is not None:
                query += " AND round_num <= ?"
                params.append(max_round)

            query += " ORDER BY round_num, timestamp LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            actions = [dict(r) for r in rows]
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "data": actions,
            "count": len(actions),
        })

    except Exception as exc:
        logger.error("Get actions failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@simulation_bp.route('/<simulation_id>/timeline', methods=['GET'])
def get_timeline(simulation_id: str):
    """Return actions grouped by round."""
    try:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM agent_actions WHERE simulation_id = ? ORDER BY round_num, timestamp",
                (simulation_id,),
            ).fetchall()
        finally:
            conn.close()

        rounds: dict = {}
        for row in rows:
            rn = row["round_num"]
            if rn not in rounds:
                rounds[rn] = {"round_num": rn, "actions": []}
            rounds[rn]["actions"].append(dict(row))

        timeline = [rounds[rn] for rn in sorted(rounds.keys())]

        return jsonify({
            "success": True,
            "data": timeline,
            "total_rounds": len(timeline),
        })

    except Exception as exc:
        logger.error("Get timeline failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ============== Agent Stats ==============

@simulation_bp.route('/<simulation_id>/agent-stats', methods=['GET'])
def get_agent_stats(simulation_id: str):
    """Return per-agent statistics."""
    try:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT agent_id, agent_name, action_type, COUNT(*) as cnt "
                "FROM agent_actions WHERE simulation_id = ? "
                "GROUP BY agent_id, agent_name, action_type",
                (simulation_id,),
            ).fetchall()
        finally:
            conn.close()

        stats: dict = {}
        for row in rows:
            aid = row["agent_id"]
            if aid not in stats:
                stats[aid] = {
                    "agent_id": aid,
                    "agent_name": row["agent_name"],
                    "total": 0,
                    "by_type": {},
                }
            stats[aid]["total"] += row["cnt"]
            stats[aid]["by_type"][row["action_type"]] = row["cnt"]

        return jsonify({
            "success": True,
            "data": list(stats.values()),
        })

    except Exception as exc:
        logger.error("Get agent stats failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ============== Interview ==============

@simulation_bp.route('/<simulation_id>/interview', methods=['POST'])
def interview_agent(simulation_id: str):
    """
    Interview an agent.
    Accepts {agent_id, question}.
    Returns interview response.
    """
    try:
        data = request.get_json(silent=True) or {}
        agent_id = data.get('agent_id')
        question = data.get('question')

        if not agent_id:
            return jsonify({"success": False, "error": "agent_id is required"}), 400
        if not question:
            return jsonify({"success": False, "error": "question is required"}), 400

        result = SimulationRunner.interview_agent(simulation_id, agent_id, question)

        return jsonify({"success": True, "data": result})

    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.error("Interview failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ============== Status (keep backward compat) ==============

@simulation_bp.route('/status', methods=['GET'])
def simulation_service_status():
    """Service health check."""
    return jsonify({'status': 'simulation service ready'})


# ============== Internal Helpers ==============

def _load_project(project_id: str):
    """Load project row from DB."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _load_simulation(simulation_id: str):
    """Load simulation row from DB."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM simulations WHERE id = ?", (simulation_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
