import { type ReactNode } from "react";

/**
 * What this page is, how to use it, and what each thing on it means.
 *
 * The console was built for somebody who already knows the system, so every page opened straight
 * into dense telemetry with no statement of what it was. That is fine for the person who wrote it
 * and useless for everybody else, including a judge with five minutes and no context.
 *
 * One block at the top of every page, in the same shape each time, so the answer is always in the
 * same place: a sentence saying what the page is, a sentence saying what to do with it, and a list
 * naming each panel and what its numbers mean. Prose in full sentences, not labels, because the
 * labels are the thing being explained.
 */
export function PageIntro({
  title,
  what,
  use,
  shows,
  caveat,
}: {
  title: string;
  /** One sentence: what this page is. */
  what: ReactNode;
  /** One sentence: what a reader does with it. Omitted where a page is read-only. */
  use?: ReactNode;
  /** Each panel on the page, and what its figures mean. */
  shows?: [string, ReactNode][];
  /** Anything a reader would otherwise misread. */
  caveat?: ReactNode;
}) {
  return (
    <section className="intro" aria-label={`About the ${title} page`}>
      <h1 className="intro-title">{title}</h1>
      <p className="intro-what">{what}</p>
      {use && <p className="intro-use">{use}</p>}
      {shows && shows.length > 0 && (
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
    </section>
  );
}
