"""Versioned SQL migrations for the job store (data/jobs.db).

Files are named ``NNNN_<name>.sql`` (four digits, contiguous from 0001) and are applied in
order by ``jobbot.db.migrate``, which tracks the applied version in ``PRAGMA user_version``.

Rules for adding a migration:
- Never edit a migration that has been released; add a new ``NNNN_<name>.sql`` instead.
- The runner wraps each file and its version bump in one transaction, so a migration must not
  contain BEGIN/COMMIT/ROLLBACK, VACUUM, or ``PRAGMA foreign_keys`` (they cannot run inside a
  transaction or would break atomicity).
- Destructive changes (DROP, type narrowing, data rewrites) need explicit human approval.
"""
