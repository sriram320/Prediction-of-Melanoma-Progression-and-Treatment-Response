import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { onSessionEnd, post, refreshSession, setAccessToken } from "../api/client.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready

  const endSession = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    onSessionEnd(endSession);
    let cancelled = false;
    refreshSession()
      .then((data) => !cancelled && setUser(data.user))
      .catch(() => !cancelled && setUser(null))
      .finally(() => !cancelled && setStatus("ready"));
    return () => {
      cancelled = true;
    };
  }, [endSession]);

  const acceptLogin = useCallback((data) => {
    setAccessToken(data.access_token);
    queryClient.clear();
    setUser(data.user);
    return data.user;
  }, [queryClient]);

  const value = useMemo(() => ({
    user,
    status,
    setUser,
    loginHospital: async (hospital_code, email, password) =>
      acceptLogin(await post("/auth/hospital/login", { hospital_code, email, password })),
    loginPatient: async (identifier, password) =>
      acceptLogin(await post("/auth/patient/login", { identifier, password })),
    loginAdmin: async (email, password) => acceptLogin(await post("/auth/admin/login", { email, password })),
    activatePatient: async (payload) => acceptLogin(await post("/auth/patient/activate", payload)),
    logout: async () => {
      try {
        await post("/auth/logout");
      } finally {
        endSession();
      }
    },
  }), [user, status, acceptLogin, endSession]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
