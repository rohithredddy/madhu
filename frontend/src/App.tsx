import { NavLink, Route, Routes } from "react-router-dom";
import { StatusChips } from "./components/StatusChips";
import { HomePage } from "./pages/HomePage";
import { CasesPage } from "./pages/CasesPage";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { ReplayPage } from "./pages/ReplayPage";
import { LabPage } from "./pages/LabPage";
import { BenchmarkPage } from "./pages/BenchmarkPage";
import { UploadPage } from "./pages/UploadPage";
import { MethodPage } from "./pages/MethodPage";

const LINKS: [string, string][] = [
  ["/cases", "Failures"],
  ["/replay", "Replay"],
  ["/lab", "Synthetic lab"],
  ["/benchmark", "Benchmark"],
  ["/upload", "Upload data"],
  ["/method", "How it works"],
];

/** The shell: navigation on the left, the page on the right. */
export function App() {
  return (
    <div className="shell">
      <nav className="nav" aria-label="Main">
        <NavLink to="/" className="nav-title" end>
          <img src="/favicon.svg" alt="" width={22} height={22} />
          Cause or symptom
        </NavLink>
        {LINKS.map(([to, label]) => (
          <NavLink key={to} to={to} className="nav-link">
            {label}
          </NavLink>
        ))}
        <div className="nav-foot">
          <StatusChips />
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/cases" element={<CasesPage />} />
          <Route path="/cases/:caseId" element={<CaseDetailPage />} />
          <Route path="/replay" element={<ReplayPage />} />
          <Route path="/lab" element={<LabPage />} />
          <Route path="/benchmark" element={<BenchmarkPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/method" element={<MethodPage />} />
          <Route path="*" element={<p>This page does not exist. Pick one on the left.</p>} />
        </Routes>
      </main>
    </div>
  );
}
