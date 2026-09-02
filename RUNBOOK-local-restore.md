# Runbook — restoring a production database locally

**Read this before restoring a production Odoo Enterprise backup onto a dev machine.**

## The trap

A restored production database keeps production's `database.uuid`. Odoo's
`Publisher: Update Notification` cron (`ir.cron` id 4, weekly, **active by default**)
phones home to odoo.com on startup and sends that UUID.

odoo.com recognises the UUID, matches it to the real subscription, and registers your
dev box as a second — **On-Premise** — installation on it. Your dev machine then reports
its own user count against the client's paid seats.

**This happens fast.** On 2026-08-30 the local CoreLab instance first started at
14:11:28 and the cron fired at **14:12:32** — 64 seconds later. It wrote back
`database.enterprise_code`, `database.expiration_date` and `publisher_warranty.cloc`
from odoo.com's response, proving the round trip completed.

**It is silent.** The publisher-warranty cron logs nothing on success. Grepping
`odoo.log` for `odoo.com` or `publisher_warranty` finds nothing. The only evidence is
the `write_date` on those `ir_config_parameter` rows matching the cron's `lastcall`.

Symptom on the client's side: an unexpected "extra user" or "On-Premise" alert on a
subscription whose production database lives on odoo.sh.

## The fix — regenerate the UUID

Do this **before first startup** (best) or **immediately after** (fine, if you catch it
within the week before the next ping). Restoring, then starting, then leaving it is what
causes the problem.

```sql
BEGIN;
UPDATE ir_config_parameter
   SET value = gen_random_uuid()::text, write_date = now()
 WHERE key = 'database.uuid';
DELETE FROM ir_config_parameter
 WHERE key IN ('database.enterprise_code',
               'database.expiration_date',
               'database.expiration_reason',
               'publisher_warranty.cloc');
COMMIT;
```

Then **restart the instance** — `database.uuid` is read through `get_param`, which is
ormcached, so a running process keeps serving the old value until it restarts.

```powershell
Restart-Service odoo-corelab     # elevated PowerShell
```

Verify:

```sql
SELECT key, value FROM ir_config_parameter
 WHERE key IN ('database.uuid','database.enterprise_code');
-- expect: a new uuid, and no enterprise_code row at all

SELECT count(*) FROM ir_config_parameter WHERE value LIKE '%<old-production-uuid>%';
-- expect: 0
```

Back up the old values first — one line, and it makes the change reversible:

```sql
SELECT key, value, create_date, write_date FROM ir_config_parameter
 WHERE key IN ('database.uuid','database.enterprise_code','database.expiration_date',
               'database.expiration_reason','publisher_warranty.cloc');
```

### Why not just disable the cron?

Deactivating `ir.cron` id 4 stops the ping, but leaves production's UUID in the
database. The next person to clone that database, or anyone who re-enables the cron or
runs `-u base`, re-arms the whole problem. Regenerating the UUID removes the cause.

After regeneration the cron can stay active: with a fresh UUID and no
`database.enterprise_code`, the instance registers as a brand-new unknown database on
its own trial, with no link to the client's subscription.

## Related gotcha — `share = NULL` inflates the user count

> In the 2026-08-31 incident this turned out to be **local-only** — production had
> 0 NULL-`share` rows and a clean count of 1. Check before assuming it affects
> production; the queries below work on either side.


`res_users.share` is a **stored computed** boolean
(`store=True`, `@api.depends('all_group_ids')`). If the compute never persisted for a
row, the column is `NULL`.

Odoo's ORM domain `('share','=',False)` compiles to `(share IS NULL OR share = false)`,
so a NULL-`share` **portal** user is billed as an **internal** user.

Check for it:

```sql
-- what Odoo bills
SELECT count(*) FROM res_users WHERE active = true AND (share IS NULL OR share = false);
-- strict
SELECT count(*) FROM res_users WHERE active = true AND share = false;
-- a difference between these two = phantom billable users
SELECT id, login, COALESCE(share::text,'NULL') FROM res_users
 WHERE active = true AND share IS NULL;
```

Fix through the ORM, never with a hand-written `UPDATE` — a manual update drifts back
on the next recompute and hides the cause:

```python
# odoo-bin shell
Users = env['res.users']
targets = Users.browse([<ids>])
env.add_to_compute(Users._fields['share'], targets)
env.flush_all()
env.cr.commit()
```

Confirm the user genuinely lacks `base.group_user` before doing this — if they hold it,
they really are internal and really are billable.

## Checklist for the next local restore

1. Restore the dump.
2. **Regenerate `database.uuid` and drop the inherited subscription params** (SQL above)
   — before first start.
3. Start the instance.
4. Confirm: new UUID present, no `database.enterprise_code`, old UUID matches 0 rows.
5. Never regenerate the UUID **on production** — that detaches the real database from
   the real subscription.

---

*Written 2026-08-31 after this bit us on the CoreLab/Yoleyva subscription
(SO2026/7991965). Production-side verification steps live in
`C:\odoo-dev\PRODUCTION-CHECKS.md` on the dev machine.*
