import { type ReactNode } from "react";

/**
 * The page header: where you are, what this page is, and what to do with it.
 *
 * It is a header, not a card. It used to be a bordered panel with a two column definition list,
 * which put a large decorated block between the reader and the data on every route and repeated
 * the page title twice on pages that also had a panel heading.
 *
 * The per-section glossary is still here, because a console that cannot explain itself is only
 * useful to the person who wrote it, but it sits behind a disclosure. Someone who needs it opens
 * it once; someone who does not never has it in the way.
 */
export function PageIntro({
  title,
  what,
  use,
  shows,
  caveat,
  right,
}: {
  title: string;
  /** One sentence: what this page is. */
  what: ReactNode;
  /** One sentence: what a reader does with it. */
  use?: ReactNode;
  /** Each section on the page, and what its figures mean. */
  shows?: [string, ReactNode][];
  /** Anything a reader would otherwise misread. */
  caveat?: ReactNode;
  /** Page-level controls, such as a run selector. */
  right?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="page-title">{title}</h1>
          {/* What the page is and what to do with it are two separate sentences, so they sit as
              two columns rather than as two stacked blocks each ending two thirds of the way
              across the header. */}
          <div className="prose-cols mt-2">
            <p className="page-sub">{what}</p>
            {use && (
              <p className="page-sub text-[color:var(--text-muted)]">{use}</p>
            )}
          </div>
        </div>
        {right && <div className="shrink-0">{right}</div>}
      </div>

      {(shows || caveat) && (
        <details className="intro-details">
          <summary className="intro-summary focus-ring">
            What each section shows
          </summary>
          <div className="intro-detail-body">
            {shows && (
              <dl className="intro-shows">
                {shows.map(([term, meaning]) => (
                  <div key={term} className="intro-row">
                    <dt className="intro-term">{term}</dt>
                    <dd className="intro-def">{meaning}</dd>
                  </div>
                ))}
              </dl>
            )}
            {caveat && <p className="intro-caveat">{caveat}</p>}
          </div>
        </details>
      )}
    </header>
  );
}
