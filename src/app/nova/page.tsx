import { ModuleShell } from "@/components/ModuleShell";

// NEWS (formerly "Nova"). Empty shell; build the news/catalyst model.
export default function NewsPage() {
  return (
    <ModuleShell
      name="News"
      latin="catalysts + headlines"
      title="What's new, and what it means for us."
      intro="Market news and catalysts that can move the book."
    />
  );
}
