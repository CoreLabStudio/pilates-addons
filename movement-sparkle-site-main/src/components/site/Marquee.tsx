const phrases = [
  "Reformer Pilates",
  "Slow the pace",
  "Strengthen the core",
  "Breathe deeper",
  "Move better",
];

export function Marquee() {
  const row = [...phrases, ...phrases, ...phrases, ...phrases];
  return (
    <div className="border-y border-border bg-background overflow-hidden py-6">
      <div className="flex whitespace-nowrap marquee-track">
        {row.map((p, i) => (
          <span
            key={i}
            className="inline-flex items-center gap-8 pr-8 font-display text-4xl md:text-6xl tracking-tight"
          >
            <span className={i % 2 === 1 ? "italic text-accent font-light" : ""}>{p}</span>
            <span className="text-accent">✦</span>
          </span>
        ))}
      </div>
    </div>
  );
}
