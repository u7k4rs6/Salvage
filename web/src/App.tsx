import { Suspense, lazy } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { FULL_CONSOLE } from "./lib/build";
import { SessionProvider } from "./lib/session";
import { TopBar } from "./components/TopBar";
import { ErrorBoundary } from "./components/ErrorBoundary";
import Overview from "./pages/Overview";
import Incidents from "./pages/Incidents";
import IncidentDetail from "./pages/IncidentDetail";
import Escalations from "./pages/Escalations";
import Ledger from "./pages/Ledger";
import Storefront from "./pages/Storefront";
import ScenarioRunner from "./pages/ScenarioRunner";
// Results is the only page that draws a chart, and Recharts is five times the size of the rest of
// the console put together. Loaded on demand so that a visitor who lands on the replay and never
// opens Results never downloads it.
const Results = lazy(() => import("./pages/Results"));
// Not in NAV. The specimen sheet is a design surface, not a page of the console, and it is
// reached by typing the path.
import Specimens from "./pages/Specimens";

// The seven entries docs/04_FRONTEND_SPEC.md section 2 fixes, in the order it fixes them.
//
// The group headings are presentation, not architecture: no route is added, removed or reordered.
// They separate the surfaces that are live during an incident from the durable record and from
// the simulation controls, which is a distinction the system already makes and the flat list hid.
const FULL_NAV: { group: string; items: { to: string; label: string }[] }[] = [
  {
    group: "Operations",
    items: [
      { to: "/overview", label: "Overview" },
      { to: "/incidents", label: "Incidents" },
      { to: "/escalations", label: "Escalations" },
    ],
  },
  {
    group: "Record",
    items: [
      { to: "/ledger", label: "Ledger" },
      { to: "/results", label: "Results" },
    ],
  },
  {
    group: "Simulation",
    items: [
      { to: "/storefront", label: "Storefront" },
      { to: "/runner", label: "Scenario Runner" },
    ],
  },
];

/**
 * The public demo's two pages, in the order a visitor should meet them: the run first, then the
 * measurements. The five that are missing all read a live backend and there is not one.
 */
const DEMO_NAV: { group: string; items: { to: string; label: string }[] }[] = [
  {
    group: "Demo",
    items: [
      { to: "/runner", label: "Scenario Runner" },
      { to: "/results", label: "Results" },
    ],
  },
];

const NAV = FULL_CONSOLE ? FULL_NAV : DEMO_NAV;

export default function App() {
  return (
    <SessionProvider>
      <div className="chrome-ui min-h-screen">
        <TopBar />
        <div className="flex">
          <nav className="min-h-[calc(100vh-36px)] w-44 shrink-0 border-r border-[color:var(--line)] bg-[color:var(--bg)] py-2">
            {NAV.map((section) => (
              <div key={section.group} className="mb-1 last:mb-0">
                <div className="nav-group px-4 pb-1 pt-2 text-[9.5px] font-medium uppercase tracking-[0.1em] text-[color:var(--fg-3)]">
                  {section.group}
                </div>
                {section.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      // A 2px marker and weight, nothing else. No pill, no card.
                      `block border-l-2 px-4 py-[5px] text-[12.5px] tracking-[0.01em] ${
                        isActive
                          ? "border-[color:var(--info)] font-semibold text-[color:var(--fg)]"
                          : "border-transparent text-[color:var(--fg-3)] hover:border-[color:var(--line-2)] hover:text-[color:var(--fg)]"
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
          <main className="min-w-0 flex-1 p-4">
            <ErrorBoundary name="This page">
              <Routes>
                <Route
                  path="/"
                  element={<Navigate to={FULL_CONSOLE ? "/overview" : "/runner"} replace />}
                />
                <Route path="/runner" element={<ScenarioRunner />} />
                <Route
                  path="/results"
                  element={
                    <Suspense fallback={<div className="p-4 text-[color:var(--fg-3)]">Loading</div>}>
                      <Results />
                    </Suspense>
                  }
                />
                {FULL_CONSOLE && (
                  <>
                    <Route path="/overview" element={<Overview />} />
                    <Route path="/incidents" element={<Incidents />} />
                    <Route path="/incidents/:incidentId" element={<IncidentDetail />} />
                    <Route path="/escalations" element={<Escalations />} />
                    <Route path="/ledger" element={<Ledger />} />
                    <Route path="/storefront" element={<Storefront />} />
                    <Route path="/specimens" element={<Specimens />} />
                  </>
                )}
                <Route
                  path="*"
                  element={<Navigate to={FULL_CONSOLE ? "/overview" : "/runner"} replace />}
                />
              </Routes>
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </SessionProvider>
  );
}
