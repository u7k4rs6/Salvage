import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { SessionProvider } from "./lib/session";
import { TopBar } from "./components/TopBar";
import { ErrorBoundary } from "./components/ErrorBoundary";
import Overview from "./pages/Overview";
import Incidents from "./pages/Incidents";
import IncidentDetail from "./pages/IncidentDetail";
import Escalations from "./pages/Escalations";
import Ledger from "./pages/Ledger";
import Results from "./pages/Results";
import Storefront from "./pages/Storefront";
import ScenarioRunner from "./pages/ScenarioRunner";
// Not in NAV. The specimen sheet is a design surface, not a page of the console, and it is
// reached by typing the path.
import Specimens from "./pages/Specimens";

// Seven entries in the order docs/04_FRONTEND_SPEC.md section 2 fixes.
const NAV = [
  { to: "/overview", label: "Overview" },
  { to: "/incidents", label: "Incidents" },
  { to: "/escalations", label: "Escalations" },
  { to: "/ledger", label: "Ledger" },
  { to: "/results", label: "Results" },
  { to: "/storefront", label: "Storefront" },
  { to: "/runner", label: "Scenario Runner" },
];

export default function App() {
  return (
    <SessionProvider>
      <div className="chrome-ui min-h-screen">
        <TopBar />
        <div className="flex">
          <nav className="min-h-[calc(100vh-42px)] w-48 shrink-0 border-r border-neutral-200 bg-white py-3">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  // A 2px marker and weight, nothing else. No pill, no card.
                  `block border-l-2 px-4 py-[7px] text-[12.5px] tracking-[0.01em] ${
                    isActive
                      ? "border-neutral-900 font-semibold text-neutral-900"
                      : "border-transparent text-neutral-500 hover:border-neutral-300 hover:text-neutral-900"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <main className="min-w-0 flex-1 p-4">
            <ErrorBoundary name="This page">
              <Routes>
                <Route path="/" element={<Navigate to="/overview" replace />} />
                <Route path="/overview" element={<Overview />} />
                <Route path="/incidents" element={<Incidents />} />
                <Route
                  path="/incidents/:incidentId"
                  element={<IncidentDetail />}
                />
                <Route path="/escalations" element={<Escalations />} />
                <Route path="/ledger" element={<Ledger />} />
                <Route path="/results" element={<Results />} />
                <Route path="/storefront" element={<Storefront />} />
                <Route path="/runner" element={<ScenarioRunner />} />
                <Route path="/specimens" element={<Specimens />} />
                <Route path="*" element={<Navigate to="/overview" replace />} />
              </Routes>
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </SessionProvider>
  );
}
