import { motion } from "motion/react";
import heroImg from "@/assets/studio-hero.jpg";
import { useBookingDialog } from "@/components/site/BookingDialog";

const words = ["Move", "with", "intention."];

export function Hero() {
  const { openDialog } = useBookingDialog();
  return (
    <section id="top" className="relative pt-32 md:pt-40 pb-20 md:pb-28 px-6 md:px-10 overflow-hidden">
      <div className="mx-auto max-w-[1400px]">
        {/* eyebrow */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className="flex items-center gap-3 text-xs uppercase tracking-[0.32em] text-muted-foreground"
        >
          <span className="h-px w-8 bg-accent" />
          Lisbon · Príncipe Real
        </motion.div>

        <div className="mt-8 grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-16 items-end">
          <div className="lg:col-span-7">
            <h1 className="font-display text-[14vw] leading-[0.92] sm:text-8xl md:text-9xl lg:text-[10.5rem] tracking-[-0.04em]">
              {words.map((w, i) => (
                <span key={i} className="inline-block overflow-hidden align-bottom mr-[0.15em]">
                  <motion.span
                    initial={{ y: "110%" }}
                    animate={{ y: "0%" }}
                    transition={{ duration: 1.1, delay: 0.3 + i * 0.12, ease: [0.22, 1, 0.36, 1] }}
                    className="inline-block"
                  >
                    {i === 2 ? (
                      <span className="italic text-accent font-light">{w}</span>
                    ) : (
                      w
                    )}
                  </motion.span>
                </span>
              ))}
            </h1>

            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, delay: 0.9 }}
              className="mt-8 max-w-xl text-lg md:text-xl text-foreground/70 text-pretty"
            >
              A boutique reformer pilates studio built around slow, deliberate practice.
              Small groups. Considered teaching. A space that feels like a deep breath.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, delay: 1.05 }}
              className="mt-10 flex flex-wrap items-center gap-4"
            >
              <button
                onClick={openDialog}
                className="inline-flex items-center gap-3 rounded-full bg-accent text-accent-foreground px-7 py-4 text-sm tracking-wide hover:opacity-90 transition-opacity"
              >
                Reserve your mat
                <span aria-hidden>→</span>
              </button>
              <a
                href="#method"
                className="inline-flex items-center gap-2 px-2 py-4 text-sm story-link"
              >
                Discover the method
              </a>
            </motion.div>
          </div>

          <motion.div
            initial={{ opacity: 0, scale: 0.94, y: 40 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ duration: 1.4, delay: 0.4, ease: [0.22, 1, 0.36, 1] }}
            className="lg:col-span-5 img-cover-zoom overflow-hidden rounded-[2rem] aspect-[4/5] relative"
          >
            <img
              src={heroImg}
              alt="Reformer pilates studio interior with natural light"
              width={1600}
              height={1200}
              className="w-full h-full object-cover"
            />
            <div className="absolute bottom-5 left-5 right-5 flex items-center justify-between rounded-full bg-background/85 backdrop-blur px-5 py-3 text-xs uppercase tracking-[0.24em]">
              <span>Est. 2019</span>
              <span className="text-accent">●</span>
              <span>8 Reformers</span>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
