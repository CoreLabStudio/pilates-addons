# Runbook — turning a contact into a student

**For a walk-in, a phone booking, or anyone the studio enters by hand.**

A contact is not a student. "Student" means a user account carrying
`group_fitness_student`, and that is what the shop, the credits page and the
Students list are all gated on. A contact without one can still be booked and
sold to, but she will not appear in **Students** and cannot use the app.

## The six steps

1. **Contacts → New.** Type her name. Add her phone if she gave one.
   **Leave the email blank** if she has no real address — do not invent one.
2. **Save.** The button acts on a saved record; on an unsaved form it has
   nothing to work with.
3. **Click "Make This Person a Student"** in the form header.
4. **Check the dialog.** The login is filled in for you — her email address if
   she has one, otherwise a username built from her name (`Laura Lopez` →
   `laura.lopez`). Set a password and give it to her directly.
5. **Confirm.** You land on her student record. The header button now reads
   **"Student Account"**.
6. **Verify** — she appears under **Students**, and her name opens Bookings,
   Credits, Packages, Memberships and Details.

To try it safely first, do all six on a contact named `ZZ Test`, then delete
the contact **and** its user from Settings → Users.

## If the button is not there

In order of likelihood:

1. **You are not a studio manager.** The button is gated on
   `fitness_core.group_fitness_manager`, like every other CoreLab control.
   Someone without it sees the whole app with controls quietly missing.
2. **Your browser is holding an old page.** Odoo keeps view definitions in
   memory for the session, so a tab opened before a deploy keeps rendering
   the old form. **Ctrl+Shift+R**, then log out and back in.
3. **The deploy has not landed.** `fitness_portal` must be at least
   `19.0.1.25.0`.

`make_student_readiness.py` checks all three and prints which one it is.

## Do not use "Grant portal access" for this

Odoo's own wizard derives the login from the email:

```python
# portal/wizard/portal_wizard.py
'email': email_normalize(self.email),
'login': email_normalize(self.email),
```

A contact with no address produces no login, and login is required — so it
refuses, or makes an account that cannot be used. It also grants
`base.group_portal` only, never the student role, which is how a paying member
ended up with a login and a locked shop.

## She already has an account

Click the same button. It detects the existing account and **adds the student
role to it** rather than creating a second one. Her password does not change.

That is the common repair for anyone who was given portal access before this
existed.

## A student who will never open the app

Make her a student anyway, and simply do not hand out the password. It costs
nothing and it is what makes her bookings and purchases visible in **Students**
instead of stranded on a plain contact.

Everything the studio does for her works from the back office: book her into
classes from the class roster, sell her a pack or membership at the desk, and
read her history from her student record.

## No email is a supported state

See [RUNBOOK-students-without-email.md](RUNBOOK-students-without-email.md).
Briefly: the address stays blank, every email path skips her cleanly, and the
in-app notification is her channel. Never invent an address to get past a
form — `testN@gmail.com` is a real stranger's inbox, and one of them received
a student's invoice.
