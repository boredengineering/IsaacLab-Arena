# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

"""Create-only nonsecret profiles on the application's existing Journal."""

import json

from isaaclab_arena.agentic_environment_generation.inference_profiles import checked_inference_profile


class ModelProfileConflict(ValueError):
    """An immutable identity already has another body, or the catalogue is full."""


class ModelProfileStore:
    """Share the Journal transaction and lifecycle; never own another connection."""

    def __init__(self, journal):
        self.journal = journal
        with journal._transaction() as db:
            journal._check_schema()
            db.execute("CREATE TABLE IF NOT EXISTS model_profiles (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            for action in ("UPDATE", "DELETE"):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS model_profiles_no_{action.lower()} "
                           f"BEFORE {action} ON model_profiles BEGIN "
                           "SELECT RAISE(ABORT, 'Immutable model profile'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS model_profiles_no_replace BEFORE INSERT ON model_profiles "
                       "WHEN EXISTS(SELECT 1 FROM model_profiles WHERE id=NEW.id) BEGIN "
                       "SELECT RAISE(ABORT, 'Immutable model profile'); END")

    def catalogue(self):
        with self.journal._transaction() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM model_profiles ORDER BY id")]

    def create(self, profile, protect_public):
        """Screen before insertion and compare exact detached replay within the transaction."""
        profile = checked_inference_profile(profile)
        if profile["origin"] != "user_defined":
            raise ValueError("Only user-defined profiles belong in the workspace catalogue")
        encoded = json.dumps(profile, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.journal._transaction() as db:
            protect_public(profile)
            row = db.execute("SELECT body FROM model_profiles WHERE id=?", (profile["id"],)).fetchone()
            if row is not None:
                if row[0] != encoded:
                    raise ModelProfileConflict("Model profile identity already exists")
            else:
                if db.execute("SELECT COUNT(*) FROM model_profiles").fetchone()[0] >= 64:
                    raise ModelProfileConflict("Model profile capacity reached")
                db.execute("INSERT INTO model_profiles VALUES (?,?)", (profile["id"], encoded))
        return json.loads(encoded)
