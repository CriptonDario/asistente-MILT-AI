import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Navigate, createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { AppShell } from "../components/layout/AppShell";
import { Logo } from "../components/ui/Logo";
import { useAuthBootstrap } from "../hooks/useAuthBootstrap";
import { useApplyTheme } from "../hooks/useTheme";
import { ChatPage } from "../pages/ChatPage";
import { LoginPage } from "../pages/LoginPage";
import { useSession } from "../stores/session";
import { queryClient } from "./queryClient";

function Splash() {
  return (
    <div className="flex h-full items-center justify-center" role="status" aria-label="Cargando MILT">
      <Logo size={48} active />
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const status = useSession((s) => s.status);
  if (status === "loading") return <Splash />;
  if (status === "anonymous") return <Navigate to="/login" replace />;
  return children;
}

function PublicOnly({ children }: { children: ReactNode }) {
  const status = useSession((s) => s.status);
  if (status === "loading") return <Splash />;
  return children;
}

const router = createBrowserRouter([
  {
    path: "/login",
    element: (
      <PublicOnly>
        <LoginPage />
      </PublicOnly>
    ),
  },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <ChatPage /> },
      { path: "c/:conversationId", element: <ChatPage /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);

export function App() {
  useAuthBootstrap();
  useApplyTheme();
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
