import { createFileRoute } from "@tanstack/react-router";
import { Nav } from "@/components/site/Nav";
import { Hero } from "@/components/site/Hero";
import { Marquee } from "@/components/site/Marquee";
import { Method } from "@/components/site/Method";
import { Story } from "@/components/site/Story";
import { Classes } from "@/components/site/Classes";
import { Studio } from "@/components/site/Studio";
import { Gallery } from "@/components/site/Gallery";
import { Teachers } from "@/components/site/Teachers";
import { Schedule } from "@/components/site/Schedule";
import { Workshops } from "@/components/site/Workshops";
import { Pricing } from "@/components/site/Pricing";
import { Testimonials } from "@/components/site/Testimonials";
import { Journal } from "@/components/site/Journal";
import { Newsletter } from "@/components/site/Newsletter";
import { Faq } from "@/components/site/Faq";
import { Contact } from "@/components/site/Contact";


export const Route = createFileRoute("/")({
  component: Index,
  head: () => ({
    meta: [
      { title: "mōva — Reformer Pilates Studio in Lisbon" },
      {
        name: "description",
        content:
          "Boutique reformer pilates in Príncipe Real, Lisbon. Six mats per class, slow deliberate teaching, memberships from €21 a class.",
      },
      { property: "og:title", content: "mōva — Reformer Pilates Studio in Lisbon" },
      {
        property: "og:description",
        content:
          "Small-group reformer and mat pilates in Príncipe Real. Classes, teachers, timetable and memberships.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
});

function Index() {
  return (
    <main className="grain min-h-screen bg-background text-foreground">
      <Nav />
      <Hero />
      <Marquee />
      <Method />
      <Story />
      <Classes />
      <Studio />
      <Gallery />
      <Teachers />
      <Schedule />
      <Workshops />
      <Pricing />
      <Testimonials />
      <Journal />
      <Newsletter />
      <Faq />
      <Contact />

    </main>
  );
}
