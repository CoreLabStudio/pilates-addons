/**
 * Render backend dates on the account's clock, not the machine's.
 *
 * Odoo 19 formats every datetime in the web client through luxon:
 *
 *     DateTime.fromSQL(value, { zone: "utc" }).setZone(options?.tz || "default")
 *
 * "default" is luxon's default zone, and nothing in Odoo ever sets it, so it
 * stays whatever the operating system says. The Timezone field on the user has
 * no bearing on it at all: the same class read 07:00 on a laptop in Spain and
 * 10:30 on the same account from India, because the browser was three and a
 * half hours ahead.
 *
 * Server-side formatting was never affected - reports and anything Python
 * renders already go through res.users.context_get(), which reads the account's
 * timezone. This closes the gap on the JavaScript side so both agree.
 *
 * The zone is validated before it is used. Assigning an unknown zone to luxon
 * does not throw; it produces an invalid zone, and every date in the backend
 * then renders as "Invalid DateTime". Falling back to the browser leaves the
 * behaviour exactly as it was before this file existed, which is the right
 * failure: wrong-but-readable beats broken.
 */
import { session } from "@web/session";

const { Settings, IANAZone } = luxon;

const accountTz = session.user_context && session.user_context.tz;

if (accountTz && IANAZone.isValidZone(accountTz)) {
    // Set, not read, at module load. dates.js resolves "default" at call time
    // rather than capturing it on import, so anything rendered after this
    // picks the new zone up.
    Settings.defaultZone = accountTz;
}
