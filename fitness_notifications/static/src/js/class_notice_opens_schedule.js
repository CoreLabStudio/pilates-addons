/**
 * A notice about a class opens the class where the studio works.
 *
 * Clicking a message in the Odoo inbox opens the record it is about through
 * Thread.open(), which asks for the model's default form: for a class - a
 * calendar.event - that is the Calendar app's, outside CoreLab and with the
 * Calendar app behind it, which shows no classes at all (classes have no
 * invitees by design). The studio runs its week from CoreLab -> Schedule, so a
 * class opens there: the Schedule menu is selected - CoreLab in the top bar,
 * Schedule in the breadcrumb - and the class opened in its form.
 *
 * Only classes: an ordinary calendar event, if the studio ever has one, and
 * any user who cannot see the Schedule menu, get exactly what Odoo does.
 */
import { patch } from "@web/core/utils/patch";
import { Thread } from "@mail/core/common/thread_model";

const SCHEDULE_MENU = "fitness_core.menu_fitness_schedule";

patch(Thread.prototype, {
    open(options) {
        if (this.model === "calendar.event" && this.id) {
            this._fitnessOpenClass();
            return true;
        }
        return super.open(...arguments);
    },

    async _fitnessOpenClass() {
        const { orm, action, menu } = this.store.env.services;
        let isClass = false;
        try {
            const [event] = await orm.read("calendar.event", [this.id], ["is_fitness_class"]);
            isClass = Boolean(event?.is_fitness_class);
        } catch {
            isClass = false;
        }
        const schedule = isClass && menu.getAll().find((m) => m.xmlid === SCHEDULE_MENU);
        if (schedule) {
            await menu.selectMenu(schedule);
            return action.switchView("form", { resId: this.id });
        }
        return action.doAction(this.openRecordActionRequest);
    },
});
