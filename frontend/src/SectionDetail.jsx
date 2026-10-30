import { useEffect, useState } from "react";

import { getJson } from "./api.js";

// How many citing passages the panel lists; the count above it says how many there are in all.
const LETTER_URL = "https://www.regulations.gov/comment/";
const SHOWN = 20;

// The panel for the section picked in the table. Titles repeat across the rule (every part of
// III has a "1. What are the agencies proposing?"), so it leads with the full heading path.

function count(value) {
  return value === null ? <span className="muted">not counted yet</span> : value.toLocaleString("en-US");
}

export default function SectionDetail({ docket, section, onClose }) {
  const path = section.heading.split(" > ");
  return (
    <aside className="detail" aria-label="Section details">
      <button type="button" className="close" onClick={onClose} aria-label="Close details">
        ×
      </button>
      <ol className="path">
        {path.map((part, i) => (
          <li key={i} className={i === path.length - 1 ? "here" : undefined}>
            {part}
          </li>
        ))}
      </ol>
      <dl className="facts">
        <dt>Rule</dt>
        <dd>
          <a href={`https://www.federalregister.gov/d/${section.document_number}`} target="_blank" rel="noreferrer">
            {section.citation}
          </a>
          {section.page !== null && `, page ${section.page}`}
        </dd>
        <dt>Rule passages</dt>
        <dd>{count(section.rule_passages)}</dd>
        <dt>Citing passages</dt>
        <dd>{count(section.citing_passages)}</dd>
        <dt>Citing letters</dt>
        <dd>{count(section.citing_letters)}</dd>
      </dl>
      <h2>Comment passages that cite this section</h2>
      <CitingPassages key={section.section_ref} docket={docket} section={section} />
    </aside>
  );
}

// Fetched only when the count says there is something to list: null means passage-stage has not
// run on this docket, and 0 means it ran and nobody cited the section by number.
function CitingPassages({ docket, section }) {
  const [state, setState] = useState(null);
  const ref = section.section_ref;
  const cited = section.citing_passages;

  useEffect(() => {
    if (!cited) return;
    let current = true;
    const query = new URLSearchParams({ section_ref: ref, limit: SHOWN });
    getJson(`/rules/${encodeURIComponent(docket)}/passages?${query}`).then(
      (body) => current && setState({ body }),
      (error) => current && setState({ error }),
    );
    // A slow answer for a section the reader has already left must not replace the new one.
    return () => {
      current = false;
    };
  }, [docket, ref, cited]);

  if (cited === null) {
    return <p className="muted">Not counted yet: the passage stage has not run on this docket's letters.</p>;
  }
  if (cited === 0) return <p className="muted">No comment passage cites this section by number.</p>;
  if (!state) return <p className="muted">Loading passages…</p>;
  if (state.error) return <p className="error">{state.error.message}</p>;

  const { passages, total } = state.body;
  // Counts come from links.parquet and the list from passages.parquet; the API sends null when
  // only the first exists.
  if (passages === null) return <p className="muted">The passage text for this docket is not available.</p>;
  if (passages.length === 0) return <p className="muted">The linked passages are not in this docket's passage file.</p>;
  return (
    <>
      <ul className="citing">
        {passages.map((p) => (
          <li key={p.passage_id}>
            <a href={LETTER_URL + p.letter_id} target="_blank" rel="noreferrer">
              {p.letter_id}
            </a>
            <span className="muted"> cites {[...new Set(p.citations.map((c) => c.citation_raw))].join(", ")}</span>
            <p className="quote">{p.text}</p>
          </li>
        ))}
      </ul>
      {total > passages.length && (
        <p className="muted">
          Showing {passages.length} of {total.toLocaleString("en-US")}.
        </p>
      )}
    </>
  );
}
