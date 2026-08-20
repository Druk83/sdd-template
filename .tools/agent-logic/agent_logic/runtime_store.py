# @todo #IMPL-029:1d Защитить локальное SQLite runtime-хранилище
# refs: .tasks/IMPL-029.md
# scope: src/agent_logic/runtime_store.py, src/agent_logic/cli.py, tests/test_agent_logic.py
# type: debt
# prio: P1
# accept: runtime ограничен 100 MiB, конкурентная запись и повреждённая БД дают контролируемую диагностику
'''Local, versioned SQLite storage for explicitly persisted ASIR results.'''
from __future__ import annotations
import hashlib
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from .errors import InputError

def _canonical(value: object) -> str:
    # Канонический JSON нужен для дедупликации.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def _checksum(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()

class RuntimeStore:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace)
        self.runtime_dir = self.workspace / '.tools' / 'agent-logic' / '.runtime'
        self.store_dir = self.runtime_dir / 'store'
        self.current_dir = self.runtime_dir / 'current'
        self.exports_dir = self.runtime_dir / 'exports'
        self.db_path = self.store_dir / 'agent-logic.db'

    def _connect(self, *, write: bool) -> sqlite3.Connection | None:
        if not write and not self.db_path.exists():
            return None
        if write:
            self.store_dir.mkdir(parents=True, exist_ok=True)
            self.current_dir.mkdir(parents=True, exist_ok=True)
            self.exports_dir.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.db_path)
            self._initialize(connection)
        else:
            connection = sqlite3.connect(f'file:{self.db_path.as_posix()}?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        return connection

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS objects (
                checksum TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS model_versions (
                model_version TEXT PRIMARY KEY,
                compilation_id TEXT NOT NULL,
                source_checksum TEXT NOT NULL,
                asir_checksum TEXT NOT NULL,
                rules_checksum TEXT NOT NULL,
                checks_checksum TEXT NOT NULL,
                report_checksum TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS version_objects (
                model_version TEXT NOT NULL REFERENCES model_versions(model_version) ON DELETE CASCADE,
                checksum TEXT NOT NULL REFERENCES objects(checksum),
                role TEXT NOT NULL,
                PRIMARY KEY (model_version, checksum, role)
            );
            CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                model_version TEXT NOT NULL REFERENCES model_versions(model_version),
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS actions (
                action_id TEXT PRIMARY KEY,
                model_version TEXT NOT NULL REFERENCES model_versions(model_version),
                initiator TEXT NOT NULL,
                basis TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        ''')

    @staticmethod
    def _put_object(connection: sqlite3.Connection, kind: str, payload: object) -> str:
        checksum = _checksum(payload)
        connection.execute('INSERT OR IGNORE INTO objects(checksum, kind, payload) VALUES (?, ?, ?)', (checksum, kind, _canonical(payload)))
        return checksum

    def record_report(self, model: Mapping, report: Mapping) -> dict:
        if not isinstance(model, Mapping) or not isinstance(report, Mapping):
            raise InputError('model and report must be JSON objects')
        compilation_id = model.get('compilationId')
        if not isinstance(compilation_id, str) or not compilation_id:
            raise InputError('model has no compilationId')
        model_version = model.get('model_version')
        if not isinstance(model_version, str) or not model_version:
            model_version = _checksum(model)[:16]
        connection = self._connect(write=True)
        assert connection is not None
        try:
            with connection:
                source_checksum = self._put_object(connection, 'sources', model.get('sources', []))
                asir_checksum = self._put_object(connection, 'asir', dict(model))
                rules_checksum = self._put_object(connection, 'rules', (report.get('agent_context') or {}).get('applicable_rules', []))
                checks_checksum = self._put_object(connection, 'checks', model.get('checks', []))
                report_checksum = self._put_object(connection, 'report', dict(report))
                connection.execute('''
                    INSERT OR IGNORE INTO model_versions(model_version, compilation_id, source_checksum, asir_checksum, rules_checksum, checks_checksum, report_checksum)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (model_version, compilation_id, source_checksum, asir_checksum, rules_checksum, checks_checksum, report_checksum))
                for checksum, role in ((source_checksum, 'sources'), (asir_checksum, 'asir'), (rules_checksum, 'rules'), (checks_checksum, 'checks'), (report_checksum, 'report')):
                    connection.execute('INSERT OR IGNORE INTO version_objects(model_version, checksum, role) VALUES (?, ?, ?)', (model_version, checksum, role))
                for record in model.get('decision_records', []):
                    if isinstance(record, dict):
                        decision_id = _checksum(record)
                        connection.execute('INSERT OR IGNORE INTO decisions(decision_id, model_version, payload) VALUES (?, ?, ?)', (decision_id, model_version, _canonical(record)))
            return {'model_version': model_version, 'database': str(self.db_path), 'created': True}
        finally:
            connection.close()

    def record_action(self, model_version: str, *, initiator: str, basis: str, result: str) -> dict:
        if not all(isinstance(value, str) and value.strip() for value in (model_version, initiator, basis, result)):
            raise InputError('model_version, initiator, basis and result must be non-empty strings')
        connection = self._connect(write=True)
        assert connection is not None
        try:
            with connection:
                version = connection.execute('SELECT 1 FROM model_versions WHERE model_version = ?', (model_version,)).fetchone()
                if version is None:
                    raise InputError('unknown model_version in runtime store')
                payload = {'model_version': model_version, 'initiator': initiator, 'basis': basis, 'result': result}
                action_id = _checksum(payload)
                connection.execute('INSERT OR IGNORE INTO actions(action_id, model_version, initiator, basis, result) VALUES (?, ?, ?, ?, ?)', (action_id, model_version, initiator, basis, result))
            return {'action_id': action_id, 'model_version': model_version}
        finally:
            connection.close()

    def list_versions(self) -> list[dict]:
        connection = self._connect(write=False)
        if connection is None:
            return []
        try:
            rows = connection.execute('''
                SELECT version.model_version, version.compilation_id, version.created_at,
                       COUNT(DISTINCT decision.decision_id) AS decisions,
                       COUNT(DISTINCT action.action_id) AS actions
                FROM model_versions AS version
                LEFT JOIN decisions AS decision ON decision.model_version = version.model_version
                LEFT JOIN actions AS action ON action.model_version = version.model_version
                GROUP BY version.model_version
                ORDER BY version.created_at, version.model_version
            ''').fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def summary(self) -> dict:
        connection = self._connect(write=False)
        if connection is None:
            return {'database': str(self.db_path), 'exists': False, 'versions': 0, 'objects': 0, 'decisions': 0, 'actions': 0}
        try:
            counts = {name: connection.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in ('model_versions', 'objects', 'decisions', 'actions')}
            return {'database': str(self.db_path), 'exists': True, 'versions': counts['model_versions'], 'objects': counts['objects'], 'decisions': counts['decisions'], 'actions': counts['actions']}
        finally:
            connection.close()

    def cleanup(self, *, apply: bool = False) -> dict:
        connection = self._connect(write=apply)
        if connection is None:
            return {'removed_versions': 0, 'removed_objects': 0, 'applied': apply}
        try:
            protected = '''SELECT model_version FROM decisions UNION SELECT model_version FROM actions'''
            candidates = connection.execute(f'SELECT model_version FROM model_versions WHERE model_version NOT IN ({protected})').fetchall()
            if not apply:
                return {'removed_versions': len(candidates), 'removed_objects': 0, 'applied': False}
            with connection:
                connection.executemany('DELETE FROM model_versions WHERE model_version = ?', [(row['model_version'],) for row in candidates])
                before = connection.execute('SELECT COUNT(*) FROM objects').fetchone()[0]
                connection.execute('DELETE FROM objects WHERE checksum NOT IN (SELECT checksum FROM version_objects)')
                after = connection.execute('SELECT COUNT(*) FROM objects').fetchone()[0]
            return {'removed_versions': len(candidates), 'removed_objects': before - after, 'applied': True}
        finally:
            connection.close()
