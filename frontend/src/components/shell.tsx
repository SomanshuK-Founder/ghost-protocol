"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowUpRight,
  ChevronRight,
  Ghost,
  LayoutDashboard,
  ListTodo,
  LogOut,
  Menu,
  Settings2,
  ShieldCheck,
  ShieldQuestion,
  X,
  Activity,
  Files,
  ListChecks,
} from "lucide-react";
import { useSession } from "./session";
import { Button } from "./ui";
import { trapDialogFocus } from "./review-primitives";

const items = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/tasks/", label: "Tasks", icon: ListTodo },
  { href: "/approvals/", label: "Approvals", icon: ShieldQuestion },
  { href: "/operations/", label: "Operations", icon: ListChecks },
  { href: "/audit/", label: "Audit explorer", icon: Activity },
  { href: "/documents/", label: "Documents", icon: Files },
  { href: "/settings/", label: "Settings & status", icon: Settings2 },
];
function Navigation({ close }: { close?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main navigation">
      {items.map(({ href, label, icon: Icon }) => {
        const active =
          href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={`nav-item ${active ? "active" : ""}`}
            aria-current={active ? "page" : undefined}
            title={label}
            onClick={close}
          >
            <Icon size={19} />
            <span>{label}</span>
            {active ? <span className="nav-marker" /> : null}
          </Link>
        );
      })}
    </nav>
  );
}
export function Shell({ children }: { children: ReactNode }) {
  const { session, logout } = useSession();
  const pathname = usePathname();
  const dialog = useRef<HTMLDialogElement>(null);
  const logoutDialog = useRef<HTMLDialogElement>(null);
  const navigationTrigger = useRef<HTMLElement | null>(null);
  const logoutTrigger = useRef<HTMLElement | null>(null);
  const [leaving, setLeaving] = useState(false);
  const main = useRef<HTMLElement>(null);
  const currentRoute = items.find(({ href }) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href),
  );
  useEffect(() => {
    main.current?.focus();
  }, [pathname]);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace">
        Skip to workspace
      </a>
      <aside className="sidebar">
        <Link href="/" className="brand" aria-label="Ghost Protocol overview">
          <Ghost size={30} />
          <span>
            GHOST<span className="brand-sub">PROTOCOL</span>
          </span>
        </Link>
        <p className="nav-label">WORKSPACE</p>
        <Navigation />
        <div className="sidebar-bottom">
          <div className="boundary-note">
            <ShieldCheck size={20} />
            <strong>
              Human authority.
              <br />
              By design.
            </strong>
            <p>
              Your agent proposes.
              <br />
              The gateway decides.
            </p>
            <Link href="/settings/">
              View boundaries <ArrowUpRight size={13} />
            </Link>
          </div>
          <div className="owner">
            <span className="avatar">LO</span>
            <span>
              Local demo owner<small>Private workspace</small>
            </span>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <Button
            variant="ghost"
            className="mobile-menu"
            onClick={(event) => {
              navigationTrigger.current = event.currentTarget;
              dialog.current?.showModal();
            }}
            aria-label="Open navigation"
          >
            <Menu size={22} />
          </Button>
          <div className="breadcrumb">
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>{currentRoute?.label ?? "Local help"}</strong>
          </div>
          <div className="topbar-right">
            <span className="local-status">
              <span />
              Local offline
            </span>
            <span className="session-label">Session active</span>
            <Button
              variant="ghost"
              aria-label="Log out"
              title="Log out"
              onClick={(event) => {
                logoutTrigger.current = event.currentTarget;
                logoutDialog.current?.showModal();
              }}
            >
              <LogOut size={17} />
            </Button>
          </div>
        </header>
        <main id="workspace" ref={main} tabIndex={-1} className="main-content">
          {children}
        </main>
        <footer className="workspace-footer">
          <span>
            <ShieldCheck size={13} /> Model proposes. Gateway decides.
          </span>
          <span>Local SQLite · Simulated planning</span>
        </footer>
      </div>
      <dialog
        ref={dialog}
        className="mobile-drawer"
        aria-labelledby="nav-title"
        onKeyDown={trapDialogFocus}
        onClose={() =>
          navigationTrigger.current?.focus({ preventScroll: true })
        }
      >
        <div className="dialog-heading">
          <h2 id="nav-title">Ghost Protocol</h2>
          <Button
            variant="ghost"
            aria-label="Close navigation"
            onClick={() => dialog.current?.close()}
          >
            <X />
          </Button>
        </div>
        <Navigation
          close={() => {
            navigationTrigger.current = null;
            dialog.current?.close();
          }}
        />
      </dialog>
      <dialog
        ref={logoutDialog}
        className="confirm-dialog"
        aria-labelledby="logout-title"
        aria-describedby="logout-description"
        onKeyDown={trapDialogFocus}
        onCancel={(event) => {
          if (leaving) event.preventDefault();
        }}
        onClose={() => logoutTrigger.current?.focus({ preventScroll: true })}
      >
        <LogOut className="iris-text" size={26} />
        <h2 id="logout-title">End this local session?</h2>
        <p id="logout-description">
          Local drafts will be cleared. Stored tasks and consent remain on the
          server. Logging out does not revoke approvals or cancel admitted work.
        </p>
        <div className="dialog-actions">
          <Button
            variant="secondary"
            autoFocus
            onClick={() => logoutDialog.current?.close()}
            disabled={leaving}
          >
            Keep working
          </Button>
          <Button
            variant="danger"
            disabled={leaving}
            onClick={() => {
              setLeaving(true);
              void logout();
            }}
          >
            {leaving ? "Ending session…" : "Log out"}
          </Button>
        </div>
      </dialog>
      <span className="sr-only">
        Session expires {session.absolute_expires_at}
      </span>
    </div>
  );
}
