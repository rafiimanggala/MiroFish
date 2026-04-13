"""
SQLite database manager using stdlib sqlite3.
Manages all persistent storage for projects, graphs, simulations, and reports.
"""

import os
import sqlite3
import logging
from typing import Optional

logger = logging.getLogger('mirofish.db')

_DB_PATH: Optional[str] = None


def _get_db_path() -> str:
    """Resolve database file path."""
    global _DB_PATH
    if _DB_PATH is None:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _DB_PATH = os.path.join(base, 'mirofish.db')
    return _DB_PATH


def get_db() -> sqlite3.Connection:
    """Get a new database connection with row_factory."""
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    conn = get_db()
    try:
        _create_projects_table(conn)
        _create_graph_tables(conn)
        _create_simulation_tables(conn)
        _create_report_table(conn)
        conn.commit()
        logger.info("Database initialized: %s", _get_db_path())
    finally:
        conn.close()


def _create_projects_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'created',
            simulation_requirement TEXT,
            ontology_json TEXT,
            graph_id TEXT,
            files_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error TEXT
        )
    """)


def _create_graph_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_nodes (
            id TEXT PRIMARY KEY,
            graph_id TEXT NOT NULL,
            name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            attributes_json TEXT,
            summary TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_edges (
            id TEXT PRIMARY KEY,
            graph_id TEXT NOT NULL,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            fact TEXT,
            attributes_json TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_nodes_graph ON graph_nodes(graph_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_edges_graph ON graph_edges(graph_id)"
    )


def _create_simulation_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS simulations (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            config_json TEXT,
            profiles_json TEXT,
            current_round INTEGER DEFAULT 0,
            total_rounds INTEGER DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_actions (
            id TEXT PRIMARY KEY,
            simulation_id TEXT NOT NULL,
            round_num INTEGER NOT NULL,
            agent_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            platform TEXT,
            action_type TEXT NOT NULL,
            content TEXT,
            target_id TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_actions_sim ON agent_actions(simulation_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_actions_round ON agent_actions(simulation_id, round_num)"
    )


def _create_report_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            simulation_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            sections_json TEXT,
            outline TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reports_sim ON reports(simulation_id)"
    )
