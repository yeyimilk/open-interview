import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import { App } from "./App";
import { AuthProvider, RequireAuth } from "./auth/AuthContext";
import { AuthLayout } from "./components/layout/AuthLayout";
import { ThemeProvider } from "./components/theme/ThemeProvider";
import { Toaster } from "./components/ui/sonner";
import { LoginPage } from "./features/auth/LoginPage";
import { RegisterPage } from "./features/auth/RegisterPage";
import { ChatListPage } from "./features/chat/ChatListPage";
import { ChatSessionPage } from "./features/chat/ChatSessionPage";
import { EvaluationPage } from "./features/interviewer/EvaluationPage";
import { InterviewerListPage } from "./features/interviewer/InterviewerListPage";
import { InterviewerSessionPage } from "./features/interviewer/InterviewerSessionPage";
import { InterviewerStartPage } from "./features/interviewer/InterviewerStartPage";
import { MentorListPage } from "./features/mentor/MentorListPage";
import { MentorSessionPage } from "./features/mentor/MentorSessionPage";
import { ProjectDetailPage } from "./features/projects/ProjectDetailPage";
import { ProjectsPage } from "./features/projects/ProjectsPage";
import { QASetPage } from "./features/qa/QASetPage";
import { ResumeDetailPage } from "./features/resumes/ResumeDetailPage";
import { ResumesPage } from "./features/resumes/ResumesPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { AdminKBPage } from "./features/admin/AdminKBPage";
import { AdminKBDocumentsPage } from "./features/admin/AdminKBDocumentsPage";
import { AdminKBItemsPage } from "./features/admin/AdminKBItemsPage";
import { AdminUsersPage } from "./features/admin/AdminUsersPage";
import { HomePage } from "./pages/HomePage";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider defaultTheme="system" storageKey="oi-theme">
      <AuthProvider>
        <Toaster richColors closeButton position="top-right" />
        <BrowserRouter>
          <Routes>
            {/* Public auth pages, separate layout */}
            <Route element={<AuthLayout />}>
              <Route path="login" element={<LoginPage />} />
              <Route path="register" element={<RegisterPage />} />
            </Route>

            {/* Main app with sidebar */}
            <Route path="/" element={<App />}>
              <Route
                index
                element={
                  <RequireAuth>
                    <HomePage />
                  </RequireAuth>
                }
              />
              <Route
                path="settings"
                element={
                  <RequireAuth>
                    <SettingsPage />
                  </RequireAuth>
                }
              />
              <Route
                path="admin/users"
                element={
                  <RequireAuth>
                    <AdminUsersPage />
                  </RequireAuth>
                }
              />
              <Route
                path="admin/kb"
                element={
                  <RequireAuth>
                    <AdminKBPage />
                  </RequireAuth>
                }
              />
              <Route
                path="admin/kb/documents"
                element={
                  <RequireAuth>
                    <AdminKBDocumentsPage />
                  </RequireAuth>
                }
              />
              <Route
                path="admin/kb/items"
                element={
                  <RequireAuth>
                    <AdminKBItemsPage />
                  </RequireAuth>
                }
              />
              <Route
                path="projects"
                element={
                  <RequireAuth>
                    <ProjectsPage />
                  </RequireAuth>
                }
              />
              <Route
                path="projects/:id"
                element={
                  <RequireAuth>
                    <ProjectDetailPage />
                  </RequireAuth>
                }
              />
              <Route
                path="resumes"
                element={
                  <RequireAuth>
                    <ResumesPage />
                  </RequireAuth>
                }
              />
              <Route
                path="resumes/:id"
                element={
                  <RequireAuth>
                    <ResumeDetailPage />
                  </RequireAuth>
                }
              />
              <Route
                path="qa-sets/:id"
                element={
                  <RequireAuth>
                    <QASetPage />
                  </RequireAuth>
                }
              />
              <Route
                path="chat"
                element={
                  <RequireAuth>
                    <ChatListPage />
                  </RequireAuth>
                }
              />
              <Route
                path="chat/:id"
                element={
                  <RequireAuth>
                    <ChatSessionPage />
                  </RequireAuth>
                }
              />
              <Route
                path="mentor"
                element={
                  <RequireAuth>
                    <MentorListPage />
                  </RequireAuth>
                }
              />
              <Route
                path="mentor/:id"
                element={
                  <RequireAuth>
                    <MentorSessionPage />
                  </RequireAuth>
                }
              />
              <Route
                path="interviewer"
                element={
                  <RequireAuth>
                    <InterviewerListPage />
                  </RequireAuth>
                }
              />
              <Route
                path="interviewer/start"
                element={
                  <RequireAuth>
                    <InterviewerStartPage />
                  </RequireAuth>
                }
              />
              <Route
                path="interviewer/:id"
                element={
                  <RequireAuth>
                    <InterviewerSessionPage />
                  </RequireAuth>
                }
              />
              <Route
                path="interviewer/:id/evaluation"
                element={
                  <RequireAuth>
                    <EvaluationPage />
                  </RequireAuth>
                }
              />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  </React.StrictMode>
);
