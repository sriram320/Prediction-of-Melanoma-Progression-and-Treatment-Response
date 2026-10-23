import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext.jsx";
import { HOME_BY_ROLE, loginPathFor } from "./roles.js";
import PageLoading from "../components/PageLoading.jsx";

/** Gate for portal routes. The backend enforces the same rules; this only keeps the UI honest. */
export default function RequireAuth({ roles, allowPasswordChange = false, children }) {
  const { user, status } = useAuth();
  const location = useLocation();

  if (status === "loading") return <PageLoading />;
  if (!user) return <Navigate to={loginPathFor(roles)} replace state={{ from: location.pathname }} />;
  if (user.must_change_password && !allowPasswordChange) return <Navigate to="/change-password" replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to={HOME_BY_ROLE[user.role] || "/"} replace />;
  return children;
}
