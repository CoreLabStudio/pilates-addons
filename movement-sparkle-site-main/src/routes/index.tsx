import { createFileRoute } from "@tanstack/react-router";
import { BookingDialogProvider } from "@/components/site/BookingDialog";
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
      { title: "CoreLab — Reformer & Barre Pilates Studio" },
      {
        name: "description",
        content:
          "Boutique reformer and barre pilates studio. Small groups, considered teaching, real results.",
      },
      { property: "og:title", content: "CoreLab — Reformer & Barre Pilates Studio" },
      {
        property: "og:description",
        content:
          "Reformer and barre pilates. Classes, memberships, private sessions and workshops.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
});

function Index() {
  return (
    <BookingDialogProvider>
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
    </BookingDialogProvider>
  );
}
