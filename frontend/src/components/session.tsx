"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode, FormEvent } from "react";
import {
  ArrowRight,
  Fingerprint,
  Ghost,
  LockKeyhole,
  ShieldCheck,
  Terminal,
} from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import type { Session } from "@/lib/api/types";
import { Button, ErrorPanel, LoadingSkeleton } from "./ui";
import type { CommandStore } from "@/lib/owner-commands";

type Auth = {
  session: Session;
  logout: () => Promise<void>;
  commands: CommandStore;
  inspectSession: () => Promise<Session>;
};
const Context = createContext<Auth | null>(null);
export function useSession() {
  const auth = useContext(Context);
  if (!auth) throw new Error("Session boundary required");
  return auth;
}

export function SessionBoundary({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [expired, setExpired] = useState(false);
  const generation = useRef(0);
  const expiryInProgress = useRef(false);
  const [commands] = useState<CommandStore>(() => new Map());
  const invalidate = useCallback(() => {
    generation.current += 1;
  }, []);
  const bootstrap = useCallback(() => {
    const current = ++generation.current;
    return api
      .get("/api/app/v1/session")
      .then((view) => {
        if (current === generation.current) setSession(view);
      })
      .catch((e: unknown) => {
        if (current === generation.current) {
          setSession(null);
          setError(e);
        }
      })
      .finally(() => {
        if (current === generation.current) setLoading(false);
      });
  }, []);
  const inspectSession = useCallback(() => {
    const current = ++generation.current;
    return api.get("/api/app/v1/session").then((view) => {
      if (current !== generation.current)
        throw new ApiError(401, "SESSION_REQUIRED");
      if (!view.authenticated) {
        commands.clear();
        setExpired(true);
      }
      setSession(view);
      return view;
    });
  }, [commands]);
  useEffect(() => {
    void bootstrap();
    const expire = () => {
      if (expiryInProgress.current) return;
      expiryInProgress.current = true;
      invalidate();
      commands.clear();
      setSession(null);
      setExpired(true);
      setLoading(true);
      setError(null);
      void bootstrap().finally(() => {
        expiryInProgress.current = false;
      });
    };
    window.addEventListener("ghost:session-expired", expire);
    return () => {
      invalidate();
      window.removeEventListener("ghost:session-expired", expire);
    };
  }, [bootstrap, invalidate, commands]);
  useEffect(() => {
    if (!session?.authenticated) return;
    const deadline = Math.min(
      Date.parse(session.idle_expires_at),
      Date.parse(session.absolute_expires_at),
    );
    const timer = setTimeout(
      () => window.dispatchEvent(new Event("ghost:session-expired")),
      Math.max(0, deadline - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [session]);
  async function logout() {
    if (!session) return;
    commands.clear();
    try {
      await api.post(
        "/api/app/v1/session/logout",
        {},
        { csrf: session.csrf_token },
      );
    } catch (e) {
      setError(e);
      ++generation.current;
      setSession(null);
      return;
    }
    ++generation.current;
    setSession(null);
    setExpired(false);
    await bootstrap();
  }
  if (session?.authenticated)
    return (
      <Context.Provider value={{ session, logout, commands, inspectSession }}>
        {children}
      </Context.Provider>
    );
  return (
    <Pairing
      session={session}
      loading={loading}
      error={error}
      expired={expired}
      reload={() => {
        setLoading(true);
        setError(null);
        return bootstrap();
      }}
      paired={(view) => {
        commands.clear();
        setExpired(false);
        setError(null);
        setSession(view);
      }}
    />
  );
}

function Pairing({
  session,
  loading,
  error,
  expired,
  reload,
  paired,
}: {
  session: Session | null;
  loading: boolean;
  error: unknown;
  expired: boolean;
  reload: () => Promise<void>;
  paired: (session: Session) => void;
}) {
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const blocked = pending || loading || !session || Boolean(error);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (blocked || !session) return;
    const pairingCode = code;
    setCode("");
    setPending(true);
    setFailure(null);
    try {
      paired(
        await api.post(
          "/api/app/v1/session/login",
          { pairing_code: pairingCode },
          { csrf: session.csrf_token },
        ),
      );
    } catch (e) {
      setFailure(e);
    } finally {
      setPending(false);
    }
  }
  return (
    <main className="access-page">
      <div className="access-brand">
        <Ghost size={28} />
        <span>
          GHOST<span className="brand-sub">PROTOCOL</span>
        </span>
        <span className="version">CONTROL ROOM / 01</span>
      </div>
      <div className="access-grid">
        <section className="access-story">
          <p className="eyebrow">PERSONAL AI. HUMAN AUTHORITY.</p>
          <h1>
            Your AI can propose.
            <br />
            <span>You decide.</span>
          </h1>
          <p className="lead">
            A clear line between what your agent plans and what you authorize.
            One local workspace. Every decision in view.
          </p>
          <div className="access-principles">
            <div>
              <ShieldCheck />
              <span>Explicit human control</span>
            </div>
            <div>
              <Fingerprint />
              <span>Owner-scoped records</span>
            </div>
            <div>
              <LockKeyhole />
              <span>Local session. HttpOnly cookie.</span>
            </div>
          </div>
          <p className="local-note">
            LOCAL OFFLINE DEMO <span>·</span> Simulated planning
            <br />
            Native OpenShell enforcement is not verified.
          </p>
        </section>
        <section className="access-card" aria-labelledby="pair-title">
          <div className="access-icon">
            <Fingerprint size={30} />
          </div>
          <p className="eyebrow">PRIVATE WORKSPACE</p>
          <h2 id="pair-title">Pair with your control room</h2>
          <p>
            Enter the one-use code from your private operator terminal. It
            expires after 120 seconds.
          </p>
          {expired ? (
            <p className="notice" role="status">
              Your session ended. Drafts were cleared. Pair again to review
              current records.
            </p>
          ) : null}
          {loading ? <LoadingSkeleton /> : null}
          {error ? (
            <ErrorPanel error={error} onRetry={() => void reload()} />
          ) : null}
          {failure ? <ErrorPanel error={failure} /> : null}
          <form onSubmit={submit}>
            <label htmlFor="pair-code">Local pairing code</label>
            <input
              id="pair-code"
              type="password"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              minLength={43}
              maxLength={43}
              pattern={"[A-Za-z0-9_\\-]{43}"}
              autoComplete="off"
              spellCheck={false}
              required
              disabled={blocked}
              aria-describedby="pair-help"
              placeholder="One-use operator code"
            />
            <p id="pair-help" className="field-help">
              The code stays in memory and clears on submission.
            </p>
            <Button type="submit" disabled={blocked}>
              {pending ? "Checking local access…" : "Enter control room"}
              <ArrowRight size={17} />
            </Button>
          </form>
          <div className="operator-help">
            <Terminal size={17} />
            <span>
              Pairing is enabled only by the local operator. No account or
              backend API key is needed.
            </span>
          </div>
          {failure instanceof ApiError && failure.uncertain ? (
            <Button variant="secondary" onClick={() => void reload()}>
              Inspect session state
            </Button>
          ) : null}
        </section>
      </div>
      <footer className="access-footer">
        GHOST PROTOCOL{" "}
        <span>Model proposes. Gateway decides. Human stays in control.</span>
      </footer>
    </main>
  );
}
