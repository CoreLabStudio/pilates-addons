# Test infrastructure

Two scripts, and the reasons they exist. Both encode fixes for problems that
cost a full day to diagnose and that look like nothing at all from the outside,
so please read this before simplifying either of them.

- `run-tests.bat` — runs the module test suite
- `clean-sessions.py` — cleans an Odoo filesystem session store

## Running the tests

```
tools\run-tests.bat -u fitness_portal --test-tags /fitness_portal

tools\run-tests.bat -u fitness_core,fitness_packages,fitness_portal ^
                    --test-tags /fitness_core,/fitness_packages,/fitness_portal
```

Paths default to this machine's layout and can be overridden from the shell:
`ODOO_PYTHON`, `ODOO_BIN`, `ODOO_CONF`, `TEST_DATA_DIR`, `TESTDB`, `TESTPORT`,
`TEST_LOG`.

Use the venv interpreter, not the system Python — the system one does not have
`passlib` and Odoo will not start on it.

## The three flags that matter

### `--data-dir` — the important one

**Symptom.** The suite was nondeterministic. Six runs gave 6, 7, 7, 12, 8 and 8
failures, never the same set twice, each with a scatter of
`odoo.http: Session expired` in the log. A test would authenticate successfully
and then have every subsequent request answered as if it were logged out,
redirected to `/web/login`, and fail asserting against a login page.

**Cause.** Odoo keeps sessions as files under `<data_dir>/sessions`. The conf
points `data_dir` at the dev server's filestore, so a test run and the running
dev server shared one session directory. Saving a session is not atomic-safe
there, and the failure is silent — `odoo/tools/_vendor/sessions.py`:

```python
try:
    rename(tmp, fn)
    os.chmod(fn, self.mode)
except (IOError, OSError):
    pass          # the save is abandoned: no exception, no log line
```

When that rename fails the session is never written, the orphaned temp file is
left behind, and the next request arrives with a cookie for a session that does
not exist. `ir_http._auth_method_user()` then raises
`SessionExpiredException("Session expired")`.

**Evidence.** The orphaned temp files are the fingerprint, and they are
countable:

| Session store | Orphaned `tmp*.__wz_sess` | Result |
|---|---|---|
| Shared with the dev server | 243 (135 in one afternoon) | 2 of 3 runs failed |
| Its own directory | 0 | 3 of 3 runs clean |

Login churn was identical in both (17 logins per run), so this is not about how
the tests authenticate — only about where the sessions are written. Rewriting
the tests to log in once per test instead of once per helper call was tried and
did **not** help; the store is the variable.

After the fix, three consecutive full runs: 133 tests, 0 session expiries,
0 failures, three times identically.

> Do not point the tests at the dev server's `data_dir`, and do not "simplify"
> this by dropping the flag because the conf already sets one. That is the bug.

### `--db-filter`

The conf pins `dbfilter = ^yoleyva_fitness_v2$` and `db_name` to the dev
database. Without overriding it, the test database is rejected by the filter and
**every** `HttpCase` session is dropped — this produced 72 failures out of 128
before it was found.

### `--max-cron-threads=0`

The conf runs two cron threads. They have no business firing underneath a test
run.

## The session leak

`run-tests.bat` deletes `<TEST_DATA_DIR>\sessions` before each run. That is
working around a real bug in Odoo's own test harness, not tidiness.

`odoo/tests/common.py` declares `session` as a **class** attribute:

```python
class HttpCase(TransactionCase):
    session: odoo.http.Session = None
```

while `authenticate()` assigns an **instance** attribute:

```python
def authenticate(self, user, password, *, ...):
    if getattr(self, 'session', None):
        odoo.http.root.session_store.delete(self.session)
    self.session = session = odoo.http.root.session_store.new()
```

Each test runs on a fresh instance, so `getattr(self, 'session', None)` finds
the class-level `None`, the delete never fires, and the previous test's session
file is orphaned. The guard only ever works *within* a test, on a second
`authenticate()` call.

Measured at exactly one file per test: a 13-test class left 13, then 26, then 39
files across three runs. Over a full suite the directory reached 270 files and
kept climbing — heading straight back to the crowded-store condition that
`--data-dir` exists to avoid.

With the wipe in place the store sits flat at 77 files run after run instead of
accumulating.

## Cleaning a session store

```
python tools/clean-sessions.py <sessions-dir> [--keep-db DB] [--max-age-days N] [--dry-run]
```

Removes orphaned temp files, sessions belonging to other databases, and anything
past the age limit. Recent sessions belonging to `--keep-db` are kept, so this
is safe to run against a live server's store without logging anyone out:

```
python tools/clean-sessions.py C:\odoo-dev\filestore\pilates\sessions --keep-db yoleyva_fitness_v2
```

Start with `--dry-run` if you want to see the damage first.
