# Runbook — outgoing email

**Read this before changing any mail setting, and before believing `mail.default.from`.**

## The trap

`mail.default.from` and `mail.catchall.domain` are **legacy**. Odoo 17 and later
read neither. On CoreLab production both were set correctly, and every email from
an author outside `corelabstudio.es` was still refused by the SMTP host:

```
SMTPDataError: (550, 'SMTP mailfrom domain "gmail.com" must match
 authenticated account domain "corelabstudio.es")
```

**619 of 1165 mail rows were failures.** Invoices, booking notices and instructor
assignments were all being lost as they were written, with nothing on screen to
say so. A student simply never heard back.

## What actually decides the sender

The company's **alias domain** — a `mail.alias.domain` record pointed at by
`res.company.alias_domain_id`.

```python
# odoo/addons/mail/models/ir_mail_server.py
def _get_default_from_address(self):
    if default_from := self.env.company.default_from_email:   # alias_domain_id.default_from_email
        return default_from
    return super()._get_default_from_address()                # tools.config['email_from']
```

With no alias domain this returns `False`. In `_find_mail_server`, step 2 — *"try
to find a mail server for `<notifications@domain>`"* — is guarded by
`if notifications_email:` and is therefore **skipped entirely**. Execution falls
through to step 4:

```python
# 4. Return the first mail server even if it was configured for another domain
_logger.warning("No mail server matches the from_filter, using %s as fallback", email_from)
```

Odoo then hands the host the author's own address — `yoleyva@gmail.com`,
`odoobot@example.com` — as the SMTP envelope sender, and a host that authenticates
as `info@corelabstudio.es` refuses it.

`from_filter` being set correctly does not save you. It was set, on both the server
and `mail.default.from_filter`, six days before the failures being investigated.

## The fix

```python
d = env['mail.alias.domain'].sudo().create({
    'name': 'corelabstudio.es',
    'default_from': 'info',
    'bounce_alias': 'bounce',
    'catchall_alias': 'catchall',
})
env.company.sudo().write({'alias_domain_id': d.id})
env.cr.commit()
```

`env.company.default_from_email` must then read `info@corelabstudio.es`. If it is
empty, the fix has not taken and nothing else is worth trying yet.

`bounce_alias` and `catchall_alias` are **required** fields — they cannot be left
blank. So ask the mail host to create `bounce@` and `catchall@` as aliases
forwarding to the main mailbox, or bounce notifications and any reply a student
sends will vanish. Outgoing mail works either way; this is about what comes back.

## How to diagnose it, and how not to

**Probe. Do not reason.** One email, sent deliberately *as* a foreign address:

```python
m = env['mail.mail'].sudo().create({
    'subject': 'SMTP probe',
    'body_html': '<p>Sent as a foreign address on purpose.</p>',
    'email_to': 'you@yourdomain',
    'email_from': '"Probe" <probe.sender@gmail.com>',
})
m.send()
```

The server log names the exact branch taken — the `No mail server matches the
from_filter` warning is what identified this in the end. Two confident fixes were
proposed before that probe was run, from reasoning about Odoo's behaviour rather
than reading it, and both were wrong: first "set `from_filter`" when it was already
set, then the two legacy parameters that nothing reads. The source was on the
machine the whole time.

## A successful send deletes the row

`mail.mail` records are **unlinked** once they send:

```
odoo.models.unlink: User #1 deleted mail.mail records with IDs: [1825]
```

So this is the **success** case, not a failure:

```
MissingError: Record does not exist or has been deleted.
```

Read `state` *before* sending, or check that the row is gone afterwards. A row
still sitting in `exception` is the failure. This also means `mail.mail` is close
to a list of everything that has ever failed, which makes it a useful audit table
and a misleading one — the count is failures, not traffic.

## Re-sending something that failed

```python
rows = env['mail.mail'].sudo().browse([<ids>])
rows.write({'state': 'outgoing'})
rows.send()
```

**Look at who each one goes to first.** The backlog contains test contacts and
week-old notifications; releasing it wholesale sends a burst of stale mail to real
people. On 24 Sep 2026 exactly one row was released — a customer invoice — and 224
instructor assignment notices were deliberately left dead.

## Checking the health of this

```python
env['mail.mail'].sudo().search_count([('state', '=', 'exception')])
```

Group by `failure_reason` to separate real problems from historical noise: a
connection outage leaves hundreds of identical rows, and Windows error `10061`
rows come from a dev machine and arrive in production through a database restore.
Filter recipients by domain — `example.com`, `example.invalid`, `*.test` — before
reporting a number to anyone, or a handful of real failures looks like a crisis.
