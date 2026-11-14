"""SQLite store for web logins, voice session bindings, post-call payloads, baskets and the audit trail.

One short-lived connection per operation: FastAPI runs sync code on worker threads, and SQLite
connections are thread-bound (tech-research §7). Read-modify-write goes through tx() (BEGIN IMMEDIATE).
"""

import hashlib
import json
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS web_session (
  token_hash TEXT PRIMARY KEY, buyer_id TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS voice_session (
  token_hash TEXT PRIMARY KEY,
  buyer_id TEXT NOT NULL, org_id TEXT NOT NULL, mandate_id TEXT NOT NULL,
  conversation_id TEXT UNIQUE,          -- NULL until bound (signed-URL sessions bind on the first tool call)
  mode TEXT NOT NULL,                   -- webrtc | websocket
  created_at REAL NOT NULL, expires_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS conversation (
  conversation_id TEXT PRIMARY KEY, agent_id TEXT, event_type TEXT NOT NULL,
  payload TEXT NOT NULL, received_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS basket (     -- docs/basket-plan.md B-02; the SQL lives in basket.py
  basket_id TEXT PRIMARY KEY, buyer_id TEXT NOT NULL,
  conversation_id TEXT,                 -- the voice call that started it: 'new' again in that call reuses it
  status TEXT NOT NULL,                 -- open | ordered (read-only)
  version INTEGER NOT NULL,             -- goes up on every change; a quote records the version it priced
  next_line_id INTEGER NOT NULL,        -- line ids are 1, 2, 3 ... per basket and never reused
  quote_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS basket_by_buyer ON basket (buyer_id, status);
CREATE TABLE IF NOT EXISTS basket_line (
  basket_id TEXT NOT NULL, line_id INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,    -- 0 after remove; restore sets it back (undo)
  draft TEXT NOT NULL,                  -- JSON: what the line asks for, so it can always be priced again
  priced TEXT NOT NULL,                 -- JSON: the last priced snapshot
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (basket_id, line_id)
);
CREATE TABLE IF NOT EXISTS basket_dish ( -- a dish plan_dish broke down into lines (M27); the SQL lives in dishes.py
  basket_id TEXT NOT NULL, seq INTEGER NOT NULL,
  dish TEXT NOT NULL,                   -- JSON: contract.BasketDish
  created_at TEXT NOT NULL,
  PRIMARY KEY (basket_id, seq)
);
CREATE TABLE IF NOT EXISTS dish_job (   -- the voice path of plan_dish: the open web page runs the job (M27.4)
  job_id TEXT PRIMARY KEY, buyer_id TEXT NOT NULL, basket_id TEXT NOT NULL,
  scope TEXT NOT NULL,                  -- the conversation, or web:<buyer>: an identical request there reuses the job
  request_key TEXT NOT NULL,            -- the normalised request
  request TEXT NOT NULL,                -- JSON: contract.PlanDishRequest with the resolved basket_id
  state TEXT NOT NULL,                  -- pending | running | done | failed
  claim TEXT NOT NULL DEFAULT '',       -- the run that holds a running job
  result TEXT,                          -- JSON: contract.DishResponse when done
  message TEXT,                         -- JSON: contract.Msg when failed
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS dish_job_by_request ON dish_job (buyer_id, scope, request_key);
CREATE INDEX IF NOT EXISTS dish_job_by_basket ON dish_job (basket_id, state);
CREATE TABLE IF NOT EXISTS audit_event ( -- append-only, hash-chained trail (PLAN M10.1); the SQL lives in audit.py
  seq INTEGER PRIMARY KEY,              -- 1, 2, 3 ... without gaps
  order_id TEXT, quote_id TEXT, basket_id TEXT, conversation_id TEXT, action TEXT,  -- copies of entry fields
  entry TEXT NOT NULL,                  -- RFC 8785 canonical JSON of the event, prev_hash included
  hash TEXT NOT NULL                    -- SHA-256 hex of entry
);
CREATE INDEX IF NOT EXISTS audit_by_order ON audit_event (order_id);
CREATE INDEX IF NOT EXISTS audit_by_quote ON audit_event (quote_id);
CREATE INDEX IF NOT EXISTS audit_by_basket ON audit_event (basket_id);
CREATE INDEX IF NOT EXISTS audit_by_conversation ON audit_event (conversation_id);
CREATE TRIGGER IF NOT EXISTS audit_event_no_update BEFORE UPDATE ON audit_event
BEGIN SELECT RAISE(ABORT, 'the audit trail is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_event_no_delete BEFORE DELETE ON audit_event
BEGIN SELECT RAISE(ABORT, 'the audit trail is append-only'); END;
"""


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@dataclass(frozen=True)
class VoiceSession:
    token_hash: str
    buyer_id: str
    org_id: str
    mandate_id: str
    conversation_id: str | None
    mode: str
    expires_at: float
    revoked: bool


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, timeout=5, isolation_level=None)  # autocommit; explicit BEGIN when needed
        try:
            c.execute("PRAGMA journal_mode=WAL")
            yield c
        finally:
            c.close()

    @contextmanager
    def tx(self, mode: str = "IMMEDIATE") -> Iterator[sqlite3.Connection]:
        """One transaction. IMMEDIATE (every read-modify-write) takes the write lock first, so versions and ids
        never race; DEFERRED gives a read a consistent snapshot."""
        if mode not in ("IMMEDIATE", "DEFERRED"):
            raise ValueError(mode)
        with self.conn() as c:
            c.execute(f"BEGIN {mode}")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            c.execute("COMMIT")

    # ---- web login (demo buyers) ----
    def create_web_session(self, buyer_id: str, ttl_s: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.conn() as c:
            c.execute("INSERT INTO web_session VALUES (?, ?, ?, ?)", (sha256(token), buyer_id, now, now + ttl_s))
        return token

    def web_session_buyer(self, token: str) -> str | None:
        with self.conn() as c:
            row = c.execute(
                "SELECT buyer_id FROM web_session WHERE token_hash = ? AND expires_at > ?", (sha256(token), time.time())
            ).fetchone()
        return row[0] if row else None

    def delete_web_session(self, token: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM web_session WHERE token_hash = ?", (sha256(token),))

    # ---- voice sessions ----
    def create_voice_session(
        self, *, buyer_id: str, org_id: str, mandate_id: str, conversation_id: str | None, mode: str, ttl_s: int
    ) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.conn() as c:
            c.execute(
                "INSERT INTO voice_session (token_hash, buyer_id, org_id, mandate_id, conversation_id, mode,"
                " created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sha256(token), buyer_id, org_id, mandate_id, conversation_id, mode, now, now + ttl_s),
            )
        return token

    def voice_session(self, token: str) -> VoiceSession | None:
        with self.conn() as c:
            row = c.execute(
                "SELECT token_hash, buyer_id, org_id, mandate_id, conversation_id, mode, expires_at, revoked"
                " FROM voice_session WHERE token_hash = ?",
                (sha256(token),),
            ).fetchone()
        return VoiceSession(*row[:7], bool(row[7])) if row else None

    def bind_conversation_once(self, token: str, conversation_id: str) -> VoiceSession | None:
        """Atomic bind-on-first-use for signed-URL sessions; a second, different id never overwrites."""
        with self.conn() as c:
            try:
                c.execute(
                    "UPDATE voice_session SET conversation_id = ? WHERE token_hash = ? AND conversation_id IS NULL",
                    (conversation_id, sha256(token)),
                )
            except sqlite3.IntegrityError:  # that conversation is already bound to another session
                pass
        return self.voice_session(token)

    def revoke_voice_session(self, token: str) -> None:
        with self.conn() as c:
            c.execute("UPDATE voice_session SET revoked = 1 WHERE token_hash = ?", (sha256(token),))

    # ---- post-call webhook ----
    def upsert_conversation(self, conversation_id: str, agent_id: str | None, event_type: str, payload: dict) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO conversation VALUES (?, ?, ?, ?, ?) ON CONFLICT(conversation_id) DO UPDATE SET"
                " agent_id = excluded.agent_id, event_type = excluded.event_type, payload = excluded.payload,"
                " received_at = excluded.received_at",
                (conversation_id, agent_id, event_type, json.dumps(payload, ensure_ascii=False), time.time()),
            )

    def conversation(self, conversation_id: str) -> dict | None:
        with self.conn() as c:
            row = c.execute("SELECT payload FROM conversation WHERE conversation_id = ?", (conversation_id,)).fetchone()
        return json.loads(row[0]) if row else None
