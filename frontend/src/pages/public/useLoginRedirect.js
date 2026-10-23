import { useLocation, useNavigate } from "react-router-dom";
import { HOME_BY_ROLE } from "../../auth/roles.js";

/** After a successful login: forced password change first, then the page the user wanted, then home. */
export function useLoginRedirect() {
  const navigate = useNavigate();
  const location = useLocation();
  return (user) => {
    if (user.must_change_password) return navigate("/change-password", { replace: true });
    const home = HOME_BY_ROLE[user.role] || "/";
    const from = location.state?.from;
    navigate(from && from.startsWith(home) ? from : home, { replace: true });
  };
}
