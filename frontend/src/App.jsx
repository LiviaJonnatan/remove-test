import { useEffect, useState } from "react";

import { getJson } from "./api.js";
import SectionDetail from "./SectionDetail.jsx";
import SectionTable, { sectionKey } from "./SectionTable.jsx";

// ?docket=EPA-HQ-OW-2022-0801 picks the rule; without it the page shows the first docket the
// API has indexed, which is the only one until more rules are collected.
function docketFromUrl() {
  return new URLSearchParams(window.location.search).get("docket");
}

export default function App() {
  const [docket, setDocket] = useState(docketFromUrl);
  const [sections, setSections] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    if (docket) return;
    getJson("/health").then((health) => {
      if (health.dockets.length) setDocket(health.dockets[0]);
      else setError(new Error("The API has no rule text indexed yet."));
    }, setError);
  }, [docket]);

  useEffect(() => {
    if (!docket) return;
    getJson(`/rules/${encodeURIComponent(docket)}/sections`).then(
      (body) => setSections(body.sections),
      setError,
    );
  }, [docket]);

  const citations = sections && [...new Set(sections.map((s) => s.citation))].join(", ");
  const detail = sections?.find((s) => sectionKey(s) === selected);

  return (
    <>
      <header className="bar">
        <span className="brand">UNDERSIGNED</span>
        <span className="crumb">Rules / {docket ?? "…"}</span>
      </header>
      <main className="card">
        <h1>Sections of the rule</h1>
        {error && <p className="error">{error.message}</p>}
        {!error && !sections && <p className="muted">Loading sections…</p>}
        {sections && sections.length === 0 && (
          <p className="muted">No sections found for {docket}.</p>
        )}
        {sections && sections.length > 0 && (
          <>
            <p className="muted">
              {sections.length} sections from {citations}. Select one to see its details.
            </p>
            <div className={detail ? "layout open" : "layout"}>
              <SectionTable sections={sections} selected={selected} onSelect={setSelected} />
              {detail && <SectionDetail docket={docket} section={detail} onClose={() => setSelected(null)} />}
            </div>
          </>
        )}
      </main>
    </>
  );
}
