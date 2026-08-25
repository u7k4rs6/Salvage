import { createContext, useContext, useState, type ReactNode } from "react";

/**
 * The dashboard token, held in React state only.
 *
 * docs/03_SECURITY_AND_ACCESS.md section 9 puts it in memory rather than localStorage on purpose:
 * a token in localStorage survives the tab, is readable by anything else served from this origin,
 * and outlives the demo. Reloading the page and typing it again is the correct cost.
 */
interface Session {
  token: string | null;
  setToken: (token: string | null) => void;
}

const SessionContext = createContext<Session>({ token: null, setToken: () => {} });

export function SessionProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  return (
    <SessionContext.Provider value={{ token, setToken }}>{children}</SessionContext.Provider>
  );
}

export function useSession(): Session {
  return useContext(SessionContext);
}
