"""
Graph API routes.
Handles ontology generation, graph building, project CRUD, and graph data retrieval.
"""

import os
import json
import uuid
import logging
import threading
import traceback
from datetime import datetime

from flask import request, jsonify

from . import graph_bp
from ..config import Config
from ..models.database import get_db
from ..utils.claude_client import ClaudeClient
from ..utils.file_parser import parse_file, split_text
from ..utils.task_manager import TaskManager, TASK_PROCESSING, TASK_COMPLETED, TASK_FAILED
from ..services.ontology_generator import OntologyGenerator
from ..services.graph_builder import GraphBuilderService

logger = logging.getLogger('mirofish.api.graph')


# ============== Ontology Generation ==============

@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    """
    Generate ontology from uploaded files or text + requirement.
    Accepts multipart (files + requirement) or JSON (text + requirement).
    Creates project in DB, returns ontology.
    """
    try:
        project_id = f"proj_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat()

        if request.content_type and 'multipart' in request.content_type:
            return _handle_file_upload(project_id, now)

        return _handle_text_input(project_id, now)

    except Exception as exc:
        logger.error("Ontology generation failed: %s", exc)
        return jsonify({
            "success": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }), 500


def _handle_file_upload(project_id: str, now: str):
    """Process multipart file upload for ontology generation."""
    requirement = request.form.get('requirement', '')
    if not requirement:
        return jsonify({"success": False, "error": "requirement is required"}), 400

    files = request.files.getlist('files')
    if not files:
        return jsonify({"success": False, "error": "No files uploaded"}), 400

    upload_dir = os.path.join(Config.UPLOAD_DIR, 'projects', project_id, 'files')
    os.makedirs(upload_dir, exist_ok=True)

    saved_files = []
    document_texts = []

    for f in files:
        if not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower().lstrip('.')
        if ext not in Config.ALLOWED_EXTENSIONS:
            continue

        safe_name = f"{uuid.uuid4().hex[:8]}{os.path.splitext(f.filename)[1]}"
        filepath = os.path.join(upload_dir, safe_name)
        f.save(filepath)

        text = parse_file(filepath)
        document_texts.append(text)
        saved_files.append({
            "original": f.filename,
            "saved": safe_name,
            "path": filepath,
            "size": os.path.getsize(filepath),
        })

    if not document_texts:
        return jsonify({"success": False, "error": "No valid files parsed"}), 400

    return _generate_and_save(project_id, now, requirement, document_texts, saved_files)


def _handle_text_input(project_id: str, now: str):
    """Process JSON text input for ontology generation."""
    data = request.get_json(silent=True) or {}
    requirement = data.get('requirement', '')
    text = data.get('text', '')

    if not requirement:
        return jsonify({"success": False, "error": "requirement is required"}), 400
    if not text:
        return jsonify({"success": False, "error": "text is required"}), 400

    return _generate_and_save(project_id, now, requirement, [text], [])


def _generate_and_save(
    project_id: str,
    now: str,
    requirement: str,
    document_texts: list,
    files: list,
):
    """Generate ontology and save project to DB."""
    generator = OntologyGenerator()
    ontology = generator.generate(document_texts, requirement)

    combined_text = "\n\n---\n\n".join(document_texts)

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO projects (id, name, status, simulation_requirement, "
            "ontology_json, files_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                f"Project {project_id[:8]}",
                "ontology_generated",
                requirement,
                json.dumps(ontology, ensure_ascii=False),
                json.dumps(files, ensure_ascii=False),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Save extracted text for later graph building
    text_dir = os.path.join(Config.UPLOAD_DIR, 'projects', project_id)
    os.makedirs(text_dir, exist_ok=True)
    text_path = os.path.join(text_dir, 'extracted_text.txt')
    with open(text_path, 'w', encoding='utf-8') as f:
        f.write(combined_text)

    return jsonify({
        "success": True,
        "project_id": project_id,
        "ontology": ontology,
        "files": files,
    })


# ============== Graph Building ==============

@graph_bp.route('/build', methods=['POST'])
def build_graph():
    """
    Start background graph building.
    Accepts {project_id, chunk_size?, chunk_overlap?}.
    Returns {success, task_id}.
    """
    try:
        data = request.get_json(silent=True) or {}
        project_id = data.get('project_id')
        if not project_id:
            return jsonify({"success": False, "error": "project_id is required"}), 400

        project = _load_project(project_id)
        if not project:
            return jsonify({"success": False, "error": f"Project not found: {project_id}"}), 404

        ontology = json.loads(project["ontology_json"] or "{}")
        if not ontology.get("entity_types"):
            return jsonify({"success": False, "error": "No ontology found. Generate ontology first."}), 400

        text = _load_extracted_text(project_id)
        if not text:
            return jsonify({"success": False, "error": "No extracted text found"}), 400

        chunk_size = data.get('chunk_size', Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', Config.DEFAULT_CHUNK_OVERLAP)

        task_mgr = TaskManager()
        task_id = task_mgr.create_task("graph_build", {"project_id": project_id})

        thread = threading.Thread(
            target=_build_graph_worker,
            args=(task_id, project_id, text, ontology, chunk_size, chunk_overlap),
            daemon=True,
        )
        thread.start()

        return jsonify({"success": True, "task_id": task_id})

    except Exception as exc:
        logger.error("Graph build failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


def _build_graph_worker(
    task_id: str,
    project_id: str,
    text: str,
    ontology: dict,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    """Background worker for graph building."""
    task_mgr = TaskManager()
    try:
        task_mgr.update_task(task_id, status=TASK_PROCESSING, progress=5, message="Splitting text")

        chunks = split_text(text, chunk_size, chunk_overlap)
        task_mgr.update_task(task_id, progress=10, message=f"Split into {len(chunks)} chunks")

        builder = GraphBuilderService()
        graph_id = builder.create_graph(f"Graph for {project_id}")

        def on_progress(pct: int):
            task_mgr.update_task(task_id, progress=10 + int(pct * 0.8), message=f"Extracting: {pct}%")

        stats = builder.build_graph(graph_id, chunks, ontology, progress_callback=on_progress)

        # Update project with graph_id
        conn = get_db()
        try:
            conn.execute(
                "UPDATE projects SET graph_id = ?, status = 'graph_completed', updated_at = ? WHERE id = ?",
                (graph_id, datetime.utcnow().isoformat(), project_id),
            )
            conn.commit()
        finally:
            conn.close()

        task_mgr.complete_task(task_id, {"graph_id": graph_id, **stats})

    except Exception as exc:
        logger.error("Graph build worker failed: %s", exc)
        task_mgr.fail_task(task_id, str(exc))


# ============== Task Status ==============

@graph_bp.route('/task/<task_id>', methods=['GET'])
def get_task_status(task_id: str):
    """Return task status from TaskManager."""
    task = TaskManager().get_task(task_id)
    if not task:
        return jsonify({"success": False, "error": "Task not found"}), 404

    return jsonify({"success": True, "data": task})


@graph_bp.route('/tasks', methods=['GET'])
def list_tasks():
    """Return all tasks."""
    tasks = TaskManager().list_tasks()
    return jsonify({"success": True, "data": tasks, "count": len(tasks)})


# ============== Graph Data ==============

@graph_bp.route('/data/<graph_id>', methods=['GET'])
def get_graph_data(graph_id: str):
    """Return graph nodes + edges for D3 visualization."""
    try:
        builder = GraphBuilderService()
        data = builder.get_graph_data(graph_id)
        return jsonify({"success": True, "data": data})
    except Exception as exc:
        logger.error("Graph data fetch failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ============== Project CRUD ==============

@graph_bp.route('/project/<project_id>', methods=['GET'])
def get_project(project_id: str):
    """Return project details from DB."""
    project = _load_project(project_id)
    if not project:
        return jsonify({"success": False, "error": f"Project not found: {project_id}"}), 404

    # Parse JSON fields for response
    result = dict(project)
    result["ontology"] = json.loads(result.pop("ontology_json", "null") or "null")
    result["files"] = json.loads(result.pop("files_json", "[]") or "[]")

    return jsonify({"success": True, "data": result})


@graph_bp.route('/project/list', methods=['GET'])
def list_projects():
    """Return all projects."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, name, status, graph_id, created_at, updated_at "
            "FROM projects ORDER BY created_at DESC"
        ).fetchall()

        return jsonify({
            "success": True,
            "data": [dict(r) for r in rows],
            "count": len(rows),
        })
    finally:
        conn.close()


@graph_bp.route('/project/<project_id>', methods=['DELETE'])
def delete_project(project_id: str):
    """Delete project and its graph data."""
    project = _load_project(project_id)
    if not project:
        return jsonify({"success": False, "error": f"Project not found: {project_id}"}), 404

    # Delete graph data if exists
    graph_id = project.get("graph_id")
    if graph_id:
        try:
            builder = GraphBuilderService()
            builder.delete_graph(graph_id)
        except Exception as exc:
            logger.warning("Failed to delete graph %s: %s", graph_id, exc)

    conn = get_db()
    try:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
    finally:
        conn.close()

    return jsonify({"success": True, "message": f"Project {project_id} deleted"})


# ============== Internal Helpers ==============

def _load_project(project_id: str):
    """Load project row from DB."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _load_extracted_text(project_id: str) -> str:
    """Load extracted text file for a project."""
    text_path = os.path.join(Config.UPLOAD_DIR, 'projects', project_id, 'extracted_text.txt')
    if not os.path.exists(text_path):
        return ""
    with open(text_path, 'r', encoding='utf-8') as f:
        return f.read()
