"""fleet.db writer for the router (HERMES-ROUTER-001).

Single writer: the router records delegations/comparisons AS it acts.
delegations.id is a TEXT UUID primary key (matches the existing schema).
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
import uuid

FLEET_DB = os.environ.get("FLEET_DB", "/home/mai/.hermes/fleet.db")


def _conn():
    return sqlite3.connect(FLEET_DB, timeout=10)


def record_delegation(task_type, chosen_service, chosen_model, reason, route_inputs,
                      outcome=None, escalated_from=None, local_attempt_id=None,
                      result_quality=None, budget_remaining_at_time=0.0):
    did = str(uuid.uuid4())
    reason_s = reason if isinstance(reason, str) else json.dumps(reason)
    c = _conn()
    c.execute(
        """INSERT INTO delegations
           (id, task_type, chosen_service, chosen_model, reason, route_inputs, outcome,
            escalated_from, local_attempt_id, result_quality,
            budget_remaining_at_time, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (did, task_type, chosen_service, chosen_model, reason_s, json.dumps(route_inputs),
         outcome, escalated_from, local_attempt_id, result_quality,
         budget_remaining_at_time, time.time()))
    c.commit()
    c.close()
    return did


def record_comparison(delegation_id, service, model, output_summary, quality_score, won):
    c = _conn()
    c.execute(
        """INSERT INTO result_comparisons
           (delegation_id, service, model, output_summary, quality_score, won, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (delegation_id, service, model, output_summary, quality_score,
         int(bool(won)), time.time()))
    c.commit()
    c.close()
