import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import App from "./App.jsx";

// fetch is faked, so the tests need no API. ROUTES maps each /api path to [status, body];
// a path that is not listed rejects the way fetch does when the server is down.
let ROUTES;

beforeEach(() => {
  ROUTES = {
    "/api/health": [200, { status: "ok", passages: 538, dockets: ["EPA-HQ-OW-2018-0149"] }],
    "/api/rules/EPA-HQ-OW-2018-0149/sections": [200, { docket_id: "EPA-HQ-OW-2018-0149", sections: SECTIONS }],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) => {
      if (!(url in ROUTES)) throw new TypeError("Failed to fetch");
      const [status, body] = ROUTES[url];
      return { ok: status < 400, status, statusText: "", json: async () => body };
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

// Same fields as GET /rules/{docket}/sections, taken from the real response for the 2019 rule.
// path is the section's heading from the top of the rule down, so its last entry is the title.
function section(section_ref, path, page, rule_passages) {
  return {
    document_number: "2019-00791",
    citation: "84 FR 4154",
    section_ref,
    parent_ref: section_ref.split("/").slice(0, -1).join("/") || null,
    heading: path.join(" > "),
    title: path.at(-1),
    depth: path.length,
    page,
    rule_passages,
    citing_passages: null,
    citing_letters: null,
  };
}

const II = "II. Background";
const III = "III. Proposed Definition of “Waters of the United States”";
const PROPOSING = "1. What are the agencies proposing?";

// The two "1. What are the agencies proposing?" rows share a title, as many sections in III do.
const SECTIONS = [
  section("II", [II], 4155, 120),
  section("II/A", [II, "A. Executive Summary"], 4155, 6),
  section("II/B", [II, "B. The Clean Water Act"], 4156, 51),
  section("II/B/1", [II, "B. The Clean Water Act", "1. Regulatory History"], 4156, 14),
  section("III/B", [III, "B. Interstate Waters"], 4171, 14),
  section("III/B/1", [III, "B. Interstate Waters", PROPOSING], 4171, 14),
  section("III/D", [III, "D. Tributaries"], 4173, 46),
  section("III/D/1", [III, "D. Tributaries", PROPOSING], 4173, 40),
];

// Each body row as its cell texts: title, page, rule passages, citing passages, citing letters.
async function tableRows() {
  const table = await screen.findByRole("table");
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell").map((cell) => cell.textContent));
}

test("lists the sections of the first indexed docket in reading order", async () => {
  render(<App />);
  const rows = await tableRows();
  expect(rows.map((r) => r[0])).toEqual(SECTIONS.map((s) => s.title));
  expect(rows[0].slice(1, 3)).toEqual(["4155", "120"]);
  expect(screen.getByText("Rules / EPA-HQ-OW-2018-0149")).toBeTruthy();
  expect(screen.getByText(/^8 sections from 84 FR 4154\./)).toBeTruthy();
  expect(screen.queryByRole("complementary", { name: "Section details" })).toBeNull();
});

test("says it is loading until the sections arrive", async () => {
  render(<App />);
  expect(screen.getByText("Loading sections…")).toBeTruthy();
  await screen.findByRole("table");
  expect(screen.queryByText("Loading sections…")).toBeNull();
});

test("indents each section by its depth", async () => {
  render(<App />);
  await screen.findByRole("table");
  const indent = (title) => screen.getByText(title).style.marginLeft;
  expect(indent(II)).toBe("0rem");
  expect(indent("A. Executive Summary")).toBe("1.25rem");
  expect(indent("1. Regulatory History")).toBe("2.5rem");
});

test("shows unknown citing counts as a dash, not zero, and explains it", async () => {
  render(<App />);
  const rows = await tableRows();
  expect(rows[0].slice(3)).toEqual(["—", "—"]);
  expect(screen.getByText(/— means not counted yet/)).toBeTruthy();
});

test("shows citing counts once the API has them", async () => {
  const counted = SECTIONS.map((s) => ({ ...s, citing_passages: 1234, citing_letters: 0 }));
  ROUTES["/api/rules/EPA-HQ-OW-2018-0149/sections"][1].sections = counted;
  render(<App />);
  const rows = await tableRows();
  expect(rows[0].slice(3)).toEqual(["1,234", "0"]);
  expect(screen.queryByText(/— means not counted yet/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: II }));
  expect(within(panel()).getByText("1,234")).toBeTruthy();
  expect(within(panel()).queryByText("not counted yet")).toBeNull();
});

test("?docket= picks the rule without asking /health", async () => {
  window.history.replaceState(null, "", "/?docket=EPA-HQ-OW-2022-0801");
  ROUTES["/api/rules/EPA-HQ-OW-2022-0801/sections"] = [
    200,
    { docket_id: "EPA-HQ-OW-2022-0801", sections: [section("I", ["I. General Information"], 10, 3)] },
  ];
  render(<App />);
  expect((await tableRows()).map((r) => r[0])).toEqual(["I. General Information"]);
  expect(fetch.mock.calls.map(([url]) => url)).not.toContain("/api/health");
});

test("says so when none of the linked passages are in the passage file", async () => {
  withCounts(5);
  ROUTES[PASSAGES] = [200, { docket_id: "EPA-HQ-OW-2018-0149", section_ref: "III/D", total: 0, passages: [] }];
  const details = await openTributaries();
  expect(await details.findByText("The linked passages are not in this docket's passage file.")).toBeTruthy();
});

test("opening another section never shows the previous section's passages", async () => {
  withCounts(3);
  ROUTES[PASSAGES] = [200, {
    docket_id: "EPA-HQ-OW-2018-0149", section_ref: "III/D", total: 1,
    passages: [passage("L1:p000", "EPA-HQ-OW-2018-0149-1001", ["Section III.D"], "Ephemeral streams are not tributaries.")],
  }];
  const details = await openTributaries();
  expect(await details.findByText("Ephemeral streams are not tributaries.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: II }));
  expect(within(panel()).queryByText("Ephemeral streams are not tributaries.")).toBeNull();
});

test("shows the API's reason for an unknown docket", async () => {
  window.history.replaceState(null, "", "/?docket=NOPE");
  const detail = "No rule text indexed for docket 'NOPE'. Indexed: EPA-HQ-OW-2018-0149";
  ROUTES["/api/rules/NOPE/sections"] = [404, { detail }];
  render(<App />);
  expect(await screen.findByText(detail)).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
});

test("says so when the API cannot be reached", async () => {
  delete ROUTES["/api/health"];
  render(<App />);
  expect(await screen.findByText("The API cannot be reached.")).toBeTruthy();
});

test("says so when the API has no rule indexed", async () => {
  ROUTES["/api/health"][1].dockets = [];
  render(<App />);
  expect(await screen.findByText("The API has no rule text indexed yet.")).toBeTruthy();
});

const panel = () => screen.queryByRole("complementary", { name: "Section details" });

test("clicking a section shows its heading path, rule citation, counts, and that citations are not counted", async () => {
  render(<App />);
  await screen.findByRole("table");
  const tributaries = screen.getAllByRole("button", { name: PROPOSING })[1];
  fireEvent.click(tributaries);

  const details = within(panel());
  expect(details.getAllByRole("listitem").map((li) => li.textContent)).toEqual([III, "D. Tributaries", PROPOSING]);
  const link = details.getByRole("link", { name: "84 FR 4154" });
  expect(link.getAttribute("href")).toBe("https://www.federalregister.gov/d/2019-00791");
  expect(link.parentElement.textContent).toBe("84 FR 4154, page 4173");
  expect(details.getByText("40")).toBeTruthy();
  expect(details.getAllByText("not counted yet")).toHaveLength(2);
  expect(details.getByText(/^Not counted yet: the passage stage has not run/)).toBeTruthy();
  expect(fetch.mock.calls.some(([url]) => url.includes("/passages"))).toBe(false);
  expect(tributaries.getAttribute("aria-pressed")).toBe("true");
});

test("a repeated title opens the section that was clicked, not the first with that title", async () => {
  render(<App />);
  await screen.findByRole("table");
  const [interstate, tributaries] = screen.getAllByRole("button", { name: PROPOSING });

  fireEvent.click(interstate);
  expect(within(panel()).getByText("B. Interstate Waters")).toBeTruthy();
  fireEvent.click(tributaries);
  expect(within(panel()).getByText("D. Tributaries")).toBeTruthy();
  expect(within(panel()).queryByText("B. Interstate Waters")).toBeNull();
  expect(interstate.getAttribute("aria-pressed")).toBe("false");
});

test("clicking anywhere on a row selects it", async () => {
  render(<App />);
  const table = await screen.findByRole("table");
  const executiveSummary = within(table).getAllByRole("row")[2];
  fireEvent.click(within(executiveSummary).getByText("6"));
  expect(within(panel()).getAllByRole("listitem").at(-1).textContent).toBe("A. Executive Summary");
});

test("the close button hides the panel", async () => {
  render(<App />);
  await screen.findByRole("table");
  fireEvent.click(screen.getByRole("button", { name: II }));
  fireEvent.click(within(panel()).getByRole("button", { name: "Close details" }));
  expect(panel()).toBeNull();
  expect(screen.getByRole("button", { name: II }).getAttribute("aria-pressed")).toBe("false");
});

test("says so when a docket has no sections", async () => {
  ROUTES["/api/rules/EPA-HQ-OW-2018-0149/sections"][1].sections = [];
  render(<App />);
  expect(await screen.findByText("No sections found for EPA-HQ-OW-2018-0149.")).toBeTruthy();
});

const PASSAGES = "/api/rules/EPA-HQ-OW-2018-0149/passages?section_ref=III%2FD&limit=20";

// Every section cited by n passages from 2 letters, or by none when n is 0.
function withCounts(n) {
  const counted = SECTIONS.map((s) => ({ ...s, citing_passages: n, citing_letters: n && 2 }));
  ROUTES["/api/rules/EPA-HQ-OW-2018-0149/sections"][1].sections = counted;
}

// Same fields as GET /rules/{docket}/passages. A passage citing one section twice repeats its
// citation_raw under two section_refs, so the page must not print it twice.
function passage(passage_id, letter_id, raws, text) {
  const citations = raws.map((citation_raw, i) => ({ section_ref: `III/D/${i + 1}`, citation_raw }));
  return { passage_id, letter_id, index: 0, text, n_words: text.split(" ").length, citations };
}

async function openTributaries() {
  render(<App />);
  await screen.findByRole("table");
  fireEvent.click(screen.getByRole("button", { name: "D. Tributaries" }));
  return within(panel());
}

test("lists the comment passages that cite a section, with links to their letters", async () => {
  withCounts(3);
  ROUTES[PASSAGES] = [200, {
    docket_id: "EPA-HQ-OW-2018-0149", section_ref: "III/D", total: 3,
    passages: [
      passage("L1:p000", "EPA-HQ-OW-2018-0149-1001", ["Section III.D"], "Ephemeral streams are not tributaries."),
      passage("L2:p004", "EPA-HQ-OW-2018-0149-2002", ["§ 120.2(c)", "§ 120.2(d)", "§ 120.2(c)"], "Keep intermittent streams."),
    ],
  }];
  const details = await openTributaries();
  expect(await details.findByText("Ephemeral streams are not tributaries.")).toBeTruthy();
  const letter = details.getByRole("link", { name: "EPA-HQ-OW-2018-0149-2002" });
  expect(letter.getAttribute("href")).toBe("https://www.regulations.gov/comment/EPA-HQ-OW-2018-0149-2002");
  expect(details.getByText("cites § 120.2(c), § 120.2(d)")).toBeTruthy();
  expect(details.getByText("Showing 2 of 3.")).toBeTruthy();
});

test("says nobody cites a section when its count is zero, without asking the API", async () => {
  withCounts(0);
  const details = await openTributaries();
  expect(details.getByText("No comment passage cites this section by number.")).toBeTruthy();
  expect(fetch.mock.calls.some(([url]) => url.includes("/passages"))).toBe(false);
});

test("says so when none of the linked passages are in the passage file", async () => {
  withCounts(5);
  ROUTES[PASSAGES] = [200, { docket_id: "EPA-HQ-OW-2018-0149", section_ref: "III/D", total: 0, passages: [] }];
  const details = await openTributaries();
  expect(await details.findByText("The linked passages are not in this docket's passage file.")).toBeTruthy();
});

test("opening another section never shows the previous section's passages", async () => {
  withCounts(3);
  ROUTES[PASSAGES] = [200, {
    docket_id: "EPA-HQ-OW-2018-0149", section_ref: "III/D", total: 1,
    passages: [passage("L1:p000", "EPA-HQ-OW-2018-0149-1001", ["Section III.D"], "Ephemeral streams are not tributaries.")],
  }];
  const details = await openTributaries();
  expect(await details.findByText("Ephemeral streams are not tributaries.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: II }));
  expect(within(panel()).queryByText("Ephemeral streams are not tributaries.")).toBeNull();
});

test("shows the API's reason when the citing passages cannot be loaded", async () => {
  withCounts(3);
  ROUTES[PASSAGES] = [404, { detail: "No section 'III/D' in 'EPA-HQ-OW-2018-0149'." }];
  const details = await openTributaries();
  expect(await details.findByText("No section 'III/D' in 'EPA-HQ-OW-2018-0149'.")).toBeTruthy();
});
