# Runbook — students with no email address

**Read this before adding a contact who has no email.**

## The rule

**Leave the email field blank. Never invent a placeholder.**

Not `test1@gmail.com`, not `noemail@corelab.es`, not the studio's own address.
Blank.

## Why this rule exists

The studio used to put `test1@gmail.com` and similar into the email field so the
forms would accept a contact. Those are not fake addresses. `test1@gmail.com` is a
real Gmail account belonging to a real stranger.

On **24 September 2026** a real student's invoice — her name, her membership, the
amount she paid — was generated, posted and emailed to that stranger. It cannot be
recalled. Nine other contacts were carrying addresses of the same shape at the time.

A blank field sends nothing to nobody. A plausible-looking fake sends everything to
whoever owns it.

There is a second, quieter problem. Odoo's `res.users.login` is a **separate field**
from the partner's email. If a login is also `testN@gmail.com`, the person who owns
that inbox can use "forgot my password" on the studio portal and be let in **as that
student**. Blanking the email closes that door — `action_reset_password` refuses
outright when a user has no address — but the login should be corrected too, because
a login that looks like an address invites the attempt.

## The two cases

### Case 1 — no digital contact at all

She is on the books and off the network. No email, no portal login, no app.

| Field | Value |
|---|---|
| Email | **blank** |
| Phone | her real number, if she gave one |
| Portal access | **not granted** |

Everything works: she is bookable, sellable to, and invoiceable. Nothing will ever
try to email her, because there is nothing to email.

**Her invoice:** open it in the back office, **Print**, and hand or post her the
paper. There is no automated path and there should not be one.

### Case 2 — she uses the app but has no email

In-app notifications reach her; email silently skips her.

| Field | Value |
|---|---|
| Email | **blank** |
| Login | a **username**, not an address — e.g. `eli.lozano` |
| Portal access | granted |
| Password | set by an admin and given to her directly |

**The Grant Portal Access wizard will not work for her.** Odoo's
`portal.wizard._create_user()` uses the email as *both* the email and the login:

```python
'email': email_normalize(self.email),
'login': email_normalize(self.email),
```

With a blank email that produces a blank login, and login is required. So for Case 2,
**create the user directly** (Settings → Users → New, or from the contact's Action
menu), set a username login, set a password, and add the portal and student groups.
Do not route it through the wizard.

## What is skipped, and what still works

| | Case 1 | Case 2 |
|---|---|---|
| Booking, cancelling, moving classes | works | works |
| Credits, packs, memberships | works | works |
| Cash sale, invoice, settlement | works | works |
| **Invoice email** | skipped | skipped |
| **Class reminders / confirmations by email** | skipped | skipped |
| **In-app (bell) notifications** | n/a — no login | **works** |
| Password reset | n/a | refused, by design |
| Portal login | n/a | works, by username |

"Skipped" means skipped, not failed. Odoo's `account.move.send._send_mails()` filters
on `move.partner_id.email` before composing anything, so no `mail.mail` row is
created and nothing lands in the outgoing queue. This is asserted by
`fitness_portal/tests/test_blank_email.py`, including a test that a student who *does*
have an address still receives her invoice — so the handling cannot silently decay
into a blanket off switch.

## If she gives you an email later

Set it on the contact. For a Case 2 student, set the email **and** leave the username
login as it is — changing a working login logs her out of a session she may be relying
on, and the username is not the problem. Everything email-shaped starts working from
that moment with no further action.

## Do not

- Do not invent an address to get past a form.
- Do not reuse the studio's own address (`info@corelabstudio.es`) — replies and
  invoices will land in the studio inbox attributed to the student, and the Titan
  vacation responder will auto-reply to them.
- Do not use `@example.com`. It is reserved for documentation, but `odoobot@example.com`
  exists in every Odoo database and pattern-matching on that domain has already nearly
  deleted OdooBot once.
- Do not assume a blank email means the contact is incomplete. For Case 1 it is the
  finished, correct state.
