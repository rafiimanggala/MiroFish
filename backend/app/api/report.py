"""
Report API routes.
Handles report generation, status, retrieval, and interactive chat.
"""

import json
import logging
import threading
import traceback
from datetime import datetime

from flask import request, jsonify

from . import report_bp
from ..models.database import get_db
from ..utils.task_manager import TaskManager, TASK_PROCESSING, TASK_COMPLETED, TASK_FAILED
from ..services.report_generator import ReportGenerator

logger = logging.getLogger('mirofish.api.report')


# ============== Generate Report ==============

@report_bp.route('/generate', methods=['POST'])
def generate_report():
    """
    Start report generation in background.
    Accepts {simulation_id}.
    Returns {success, report_id, task_id}.
    """
    try:
        data = request.get_json(silent=True) or {}
        simulation_id = data.get('simulation_id')

        if not simulation_id:
            return jsonify({"success": False, "error": "simulation_id is required"}), 400

        sim = _load_simulation(simulation_id)
        if not sim:
            return jsonify({"success": False, "error": f"Simulation not found: {simulation_id}"}), 404

        # Check for existing completed report
        existing = _load_report_by_simulation(simulation_id)
        if existing and existing.get("status") == "completed":
            force = data.get("force_regenerate", False)
            if not force:
                return jsonify({
                    "success": True,
                    "data": {
                        "report_id": existing["id"],
                        "simulation_id": simulation_id,
                        "status": "completed",
                        "already_generated": True,
                    },
                })

        task_mgr = TaskManager()
        task_id = task_mgr.create_task("report_generate", {"simulation_id": simulation_id})

        thread = threading.Thread(
            target=_generate_report_worker,
            args=(task_id, simulation_id),
            daemon=True,
        )
        thread.start()

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "task_id": task_id,
                "status": "generating",
            },
        })

    except Exception as exc:
        logger.error("Generate report failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


def _generate_report_worker(task_id: str, simulation_id: str) -> None:
    """Background worker for report generation."""
    task_mgr = TaskManager()
    try:
        task_mgr.update_task(task_id, status=TASK_PROCESSING, progress=5, message="Starting report generation")

        generator = ReportGenerator(simulation_id)

        def on_progress(pct: int, msg: str):
            task_mgr.update_task(task_id, progress=pct, message=msg)

        result = generator.generate_report(progress_callback=on_progress)

        task_mgr.complete_task(task_id, {
            "report_id": result["report_id"],
            "simulation_id": simulation_id,
            "sections_count": len(result.get("sections", [])),
        })

    except Exception as exc:
        logger.error("Report generation failed: %s", exc)
        task_mgr.fail_task(task_id, str(exc))


# ============== Report Status ==============

@report_bp.route('/status/<task_id>', methods=['GET'])
def get_report_status(task_id: str):
    """Return report generation progress."""
    task = TaskManager().get_task(task_id)
    if not task:
        return jsonify({"success": False, "error": "Task not found"}), 404

    return jsonify({"success": True, "data": task})


# ============== Get Report ==============

@report_bp.route('/<report_id>', methods=['GET'])
def get_report(report_id: str):
    """Return full report."""
    report = _load_report(report_id)
    if not report:
        return jsonify({"success": False, "error": f"Report not found: {report_id}"}), 404

    result = dict(report)
    result["sections"] = json.loads(result.pop("sections_json", "[]") or "[]")
    result["outline"] = json.loads(result.pop("outline", "null") or "null")

    return jsonify({"success": True, "data": result})


@report_bp.route('/by-simulation/<simulation_id>', methods=['GET'])
def get_report_by_simulation(simulation_id: str):
    """Return report for a simulation."""
    report = _load_report_by_simulation(simulation_id)
    if not report:
        return jsonify({"success": False, "error": f"No report found for simulation: {simulation_id}"}), 404

    result = dict(report)
    result["sections"] = json.loads(result.pop("sections_json", "[]") or "[]")
    result["outline"] = json.loads(result.pop("outline", "null") or "null")

    return jsonify({"success": True, "data": result})


# ============== Chat with Report ==============

@report_bp.route('/<report_id>/chat', methods=['POST'])
def chat_with_report(report_id: str):
    """
    Chat with report agent about findings.
    Accepts {message, history}.
    Returns chat response.
    """
    try:
        data = request.get_json(silent=True) or {}
        message = data.get('message')
        history = data.get('history', [])

        if not message:
            return jsonify({"success": False, "error": "message is required"}), 400

        report = _load_report(report_id)
        if not report:
            return jsonify({"success": False, "error": f"Report not found: {report_id}"}), 404

        simulation_id = report["simulation_id"]
        generator = ReportGenerator(simulation_id)
        response = generator.chat(report_id, message, history)

        return jsonify({
            "success": True,
            "data": {
                "report_id": report_id,
                "message": message,
                "response": response,
            },
        })

    except Exception as exc:
        logger.error("Report chat failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ============== Status (keep backward compat) ==============

@report_bp.route('/status', methods=['GET'])
def report_service_status():
    """Service health check."""
    return jsonify({'status': 'report service ready'})


# ============== Internal Helpers ==============

def _load_simulation(simulation_id: str):
    """Load simulation row from DB."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM simulations WHERE id = ?", (simulation_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _load_report(report_id: str):
    """Load report row from DB."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _load_report_by_simulation(simulation_id: str):
    """Load latest report for a simulation."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM reports WHERE simulation_id = ? ORDER BY created_at DESC LIMIT 1",
            (simulation_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
