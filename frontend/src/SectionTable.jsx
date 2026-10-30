// One row per section from GET /rules/{docket}/sections, in reading order. Parent rows come
// before their children, so indenting by depth is enough to show the tree.

// The API sends null for counts it has no data for yet (citing passages and letters, until
// comment passages are linked to sections). Null is unknown, not zero, so it is not shown as 0.
function count(value) {
  return value === null ? <span className="muted">—</span> : value.toLocaleString("en-US");
}

export function sectionKey(s) {
  return `${s.document_number}/${s.section_ref}`;
}

// Clicking anywhere on a row selects it. The title is a button so the keyboard can reach it too;
// Enter on the button fires a click that bubbles up to the row.
export default function SectionTable({ sections, selected, onSelect }) {
  const unknown = sections.some((s) => s.citing_passages === null);
  return (
    <div>
      <table className="sections">
        <thead>
          <tr>
            <th>Section</th>
            <th className="n">FR page</th>
            <th className="n">Rule passages</th>
            <th className="n">Citing passages</th>
            <th className="n">Citing letters</th>
          </tr>
        </thead>
        <tbody>
          {sections.map((s) => {
            const key = sectionKey(s);
            const isSelected = key === selected;
            return (
              <tr
                key={key}
                className={`depth-${s.depth}${isSelected ? " sel" : ""}`}
                onClick={() => onSelect(key)}
              >
                <td>
                  <button
                    type="button"
                    className="title"
                    aria-pressed={isSelected}
                    style={{ marginLeft: `${(s.depth - 1) * 1.25}rem` }}
                  >
                    {s.title}
                  </button>
                </td>
                <td className="n">{s.page ?? count(null)}</td>
                <td className="n">{count(s.rule_passages)}</td>
                <td className="n">{count(s.citing_passages)}</td>
                <td className="n">{count(s.citing_letters)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {unknown && (
        <p className="foot">
          — means not counted yet. Citing counts appear once comment passages are linked to the
          sections they cite.
        </p>
      )}
    </div>
  );
}
