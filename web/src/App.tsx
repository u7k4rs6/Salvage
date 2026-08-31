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
      {/* A column that fills the viewport, with the row under the bar taking what is left. The nav
          used to carry min-h-[calc(100vh-36px)], which hardcoded the bar's height; raising the type
          made the bar taller and every page grew a spurious scrollbar. Nothing measures the bar
          now. */}
      <div className="app-shell">
        <TopBar />
        <div className="app-body">
          <nav className="side" aria-label="Sections">
            {NAV.map((section) => (
              <div key={section.group} className="side-group">
                <div className="side-label">{section.group}</div>
                {section.items.map((item) => (
                  <NavLink key={item.to} to={item.to} className="side-link focus-ring">
                    {item.label}
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
          <main className="app-main min-w-0">
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
                    <Suspense fallback={<div className="p-4 text-[color:var(--text-muted)]">Loading</div>}>
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
