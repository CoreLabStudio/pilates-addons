export const CLASS_CAPACITY = 6;

export const BOOKING_WINDOW_DAYS = 21;

const DAY_INDEX: Record<string, number> = {
  Sun: 0,
  Mon: 1,
  Tue: 2,
  Wed: 3,
  Thu: 4,
  Fri: 5,
  Sat: 6,
};

export const WEEKLY_SCHEDULE: { day: string; items: [string, string][] }[] = [
  {
    day: "Mon",
    items: [
      ["07:00", "Reformer Flow"],
      ["12:15", "Mat & Props"],
      ["19:00", "Reformer Flow"],
    ],
  },
  {
    day: "Tue",
    items: [
      ["07:00", "Mat & Props"],
      ["18:00", "Reformer Flow"],
      ["19:15", "Slow Reformer"],
    ],
  },
  {
    day: "Wed",
    items: [
      ["07:00", "Reformer Flow"],
      ["12:15", "Mat & Props"],
      ["19:00", "Reformer Flow"],
    ],
  },
  {
    day: "Thu",
    items: [
      ["07:00", "Mat & Props"],
      ["18:00", "Reformer Flow"],
      ["19:15", "Slow Reformer"],
    ],
  },
  {
    day: "Fri",
    items: [
      ["07:00", "Reformer Flow"],
      ["12:15", "Mat & Props"],
      ["18:00", "Reformer Flow"],
    ],
  },
  {
    day: "Sat",
    items: [
      ["09:00", "Reformer Flow"],
      ["10:15", "Mat & Props"],
      ["11:30", "Reformer Flow"],
    ],
  },
];

export type WeeklySlot = {
  dayOfWeek: number;
  time: string;
  className: string;
};

export const WEEKLY_SLOTS: WeeklySlot[] = WEEKLY_SCHEDULE.flatMap(({ day, items }) =>
  items.map(([time, className]) => ({ dayOfWeek: DAY_INDEX[day], time, className })),
);

export const CLASS_NAMES = Array.from(new Set(WEEKLY_SLOTS.map((s) => s.className)));

function slugify(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

export function makeSessionId(date: string, time: string, className: string) {
  return `${date}T${time}__${slugify(className)}`;
}

export type ClassSession = {
  sessionId: string;
  className: string;
  date: string;
  time: string;
  dayLabel: string;
  capacity: number;
};

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function toDateString(date: Date) {
  return date.toISOString().slice(0, 10);
}

/**
 * Expands the weekly template into concrete dated sessions for a rolling
 * window starting today (UTC), so dev/prod agree regardless of host timezone.
 */
export function generateSessions(days: number = BOOKING_WINDOW_DAYS): ClassSession[] {
  const sessions: ClassSession[] = [];
  const today = new Date();
  const start = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));

  for (let i = 0; i < days; i++) {
    const d = new Date(start);
    d.setUTCDate(d.getUTCDate() + i);
    const dow = d.getUTCDay();
    const date = toDateString(d);

    for (const slot of WEEKLY_SLOTS) {
      if (slot.dayOfWeek !== dow) continue;
      sessions.push({
        sessionId: makeSessionId(date, slot.time, slot.className),
        className: slot.className,
        date,
        time: slot.time,
        dayLabel: DAY_LABELS[dow],
        capacity: CLASS_CAPACITY,
      });
    }
  }

  return sessions.sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time));
}
