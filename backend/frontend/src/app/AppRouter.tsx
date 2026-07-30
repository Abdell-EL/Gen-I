import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ActivationPage } from "../pages/ActivationPage";
import { AdminPage } from "../pages/AdminPage";
import { AgentPage } from "../pages/AgentPage";
import { LandingPage } from "../pages/LandingPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { SignInPage } from "../pages/SignInPage";
import { ProtectedRoute } from "./ProtectedRoute";

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/signin" element={<SignInPage />} />
        <Route path="/activate" element={<ActivationPage />} />
        <Route
          path="/agent"
          element={
            <ProtectedRoute roles={["agent", "admin"]}>
              <AgentPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute roles={["admin"]}>
              <AdminPage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  );
}
