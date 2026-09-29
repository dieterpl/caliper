import { lazy, Suspense } from "react";
import { HashRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { Toaster } from "sonner";
import Hub from "./pages/Hub";
import { Logo } from "./components/Logo";

// The gallery can load without downloading the CAD viewer or physics engine.
const Workspace = lazy(() => import("./pages/Workspace"));
const ProjectProposal = lazy(() => import("./pages/ProjectProposal"));

// Preserve panes within one design; reset files and drafts when the design changes.
function WorkspaceRoute() {
  const { slug } = useParams();
  return <Workspace key={slug} />;
}

export default function App() {
  return (
    <HashRouter>
      <Suspense fallback={<div className="flex h-full flex-col items-center justify-center gap-3" role="status"><Logo size={40} mono className="animate-pulse opacity-30" /><p className="text-muted-foreground">Opening your workbench…</p></div>}>
        <Routes>
          <Route path="/" element={<Hub />} />
          <Route path="/ws/:slug/*" element={<WorkspaceRoute />} />
          <Route path="/proposal" element={<ProjectProposal />} />
          <Route path="/prototype" element={<ProjectProposal />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
      <Toaster theme="dark" position="bottom-center" richColors closeButton />
    </HashRouter>
  );
}
