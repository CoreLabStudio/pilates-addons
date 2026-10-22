/**
 * A studio manager clicks the cancellation notice in her Odoo inbox and lands
 * on the class in CoreLab -> Schedule - not the Calendar app.
 */
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("fitness_class_notice_opens_schedule", {
    steps: () => [
        {
            content: "Open the messaging menu",
            trigger: ".o_menu_systray i[aria-label='Messages']",
            run: "click",
        },
        {
            content: "Click the cancellation notice",
            trigger: ".o-mail-NotificationItem:contains('TOUR Class')",
            run: "click",
        },
        {
            content: "The class's form is open, with its roster",
            trigger: ".o_form_view .o_breadcrumb:contains('TOUR Class')",
        },
        {
            content: "Inside CoreLab -> Schedule, not the Calendar app",
            trigger: ".o_main_navbar .o_menu_brand:contains('CoreLab')",
            run() {
                const crumbs = document.querySelector(".o_breadcrumb")?.innerText || "";
                if (!crumbs.includes("Schedule")) {
                    throw new Error("breadcrumb is '" + crumbs + "', not Schedule / the class");
                }
                if (window.location.pathname.includes("calendar")) {
                    throw new Error("opened at " + window.location.pathname + " - the Calendar app");
                }
            },
        },
    ],
});
