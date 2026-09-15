/**
 * The backend runs on the studio's clock.
 *
 * Odoo 19 formats every datetime in the web client through luxon:
 *
 *     DateTime.fromSQL(value, { zone: "utc" }).setZone(options?.tz || "default")
 *
 * "default" is luxon's default zone, and across the whole Odoo source the only
 * two assignments to Settings.defaultZone are in test files. So it stays
 * whatever the operating system says, and the Timezone field on the user has no
 * bearing on it: the same 07:00 class read 07:00 on a laptop in Spain and 10:30
 * on the same account from India.
 *
 * This sets it to the studio's own zone, for everybody.
 *
 * Deliberately a constant rather than the account's timezone. Reading the
 * account meant the right time depended on a field being correct in every
 * database, on the server's per-worker cache of context_get() being fresh, and
 * on session_info carrying it - three things that each failed at least once
 * while this was being built. CoreLab teaches in one room in Madrid; a class at
 * 07:00 is at 07:00, and there is no reader for whom another answer is useful.
 * If the studio ever opens somewhere else, this is the line to change.
 *
 * Server-side formatting was never part of the problem. Reports and anything
 * Python renders go through res.users.context_get(); the portal and the
 * notification emails are pinned to the same zone in Python. This closes the
 * JavaScript gap so all three agree.
 */
import { whenReady } from "@odoo/owl";

const STUDIO_TZ = "Europe/Madrid";

function applyStudioZone() {
    // luxon is a global provided by a library file in the bundle, not a module
    // import. Reading it at module scope is a race: if this file happens to
    // execute first, `luxon` is undefined, the module throws on load and
    // nothing is set - silently, as far as the page is concerned. Reading it
    // inside the function, and running twice, removes the ordering question.
    const lx = globalThis.luxon;
    if (!lx || !lx.Settings || !lx.IANAZone) {
        return false;
    }
    // An unknown zone does not throw: luxon stores an invalid zone and every
    // date in the backend renders "Invalid DateTime". Validate first, and on
    // failure leave the browser default - which is the behaviour that existed
    // before this file. Wrong-but-readable beats broken.
    if (!lx.IANAZone.isValidZone(STUDIO_TZ)) {
        return false;
    }
    lx.Settings.defaultZone = STUDIO_TZ;
    return true;
}

// As early as possible, for anything rendered during boot...
applyStudioZone();
// ...and again once the page is ready, in case this module loaded before the
// luxon library did. Setting the same zone twice costs nothing.
whenReady(applyStudioZone);
