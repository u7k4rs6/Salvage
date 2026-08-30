/**
 * What this build is for.
 *
 * The console has two audiences and they need different sets of pages. Working on it locally, all
 * of them: Overview, Incidents, Escalations, Ledger and Storefront all read a live FastAPI process
 * and are the reason the backend exists. Deployed as a public demo there is no backend, so those
 * five would render an error panel forever, and a first-time visitor reading five broken pages
 * concludes the project is broken rather than that it is not connected.
 *
 * So a production build ships the two pages that need nothing: the Scenario Runner, which replays
 * a recording committed to the repository, and Results, which reads a committed artifact.
 *
 * This is decided at build time and baked in. There is nothing to configure at deploy time and no
 * environment variable the deployed page reads, which is the point: a static host serves files.
 * `VITE_SALVAGE_FULL=1` at build time puts the other five back, for a build that will sit in front
 * of a real backend.
 */
export const FULL_CONSOLE: boolean =
  import.meta.env.DEV || import.meta.env.VITE_SALVAGE_FULL === "1";
