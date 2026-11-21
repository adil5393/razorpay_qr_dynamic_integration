import React, { act } from "react";
import { createRoot } from "react-dom/client";
import AppLayout from "./AppLayout";

global.React = React;
let mockRole = "cashier";
let mockCutover = true;
jest.mock("@/context/AuthContext", () => ({ useAuth: () => ({ user: { id: 1, role: mockRole, name: "User", email: "user@example.test" }, logout: jest.fn() }) }));
jest.mock("@/hooks/queries", () => ({ useAppConfig: () => ({ data: { odoo_terminal_cutover: mockCutover } }) }));
jest.mock("@/context/ThemeContext", () => ({ useTheme: () => ({ theme: "light", toggle: jest.fn() }) }));
jest.mock("@/components/ui/sheet", () => ({ Sheet: ({ children }) => <div>{children}</div>, SheetContent: ({ children }) => <div>{children}</div>, SheetTitle: ({ children }) => <div>{children}</div> }));
jest.mock("react-router-dom", () => ({
  Outlet: () => <div />, useLocation: () => ({ pathname: "/", search: "" }),
  NavLink: ({ children, to, className, end, ...props }) => <a href={to} className={typeof className === "function" ? className({ isActive: false }) : className} {...props}>{children}</a>,
}));
let container, root;
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

test("cutover cashier sees terminal navigation without administrative links", async () => {
  mockRole = "cashier"; mockCutover = true; await act(async () => root.render(<AppLayout />));
  expect(container.querySelector('[data-testid="nav-new-qr-link"]')).toBeNull();
  expect(container.querySelector('[data-testid="nav-user-mgmt-link"]')).toBeNull();
  expect(container.querySelector('[data-testid="nav-settings-link"]')).toBeNull();
  expect(container.querySelector('[aria-label="Mobile navigation"]').textContent).toContain("Queue");
});
test("legacy cashier keeps manual collection while cutover is off", async () => {
  mockRole = "cashier"; mockCutover = false; await act(async () => root.render(<AppLayout />));
  expect(container.querySelector('[data-testid="nav-new-qr-link"]')).not.toBeNull();
  expect(container.querySelector('[aria-label="Mobile navigation"]').textContent).toContain("New QR");
});
test("administrator retains all administrative navigation", async () => {
  mockRole = "admin"; mockCutover = true; await act(async () => root.render(<AppLayout />));
  for (const id of ["nav-new-qr-link", "nav-user-mgmt-link", "nav-settings-link", "nav-odoo-requests", "nav-odoo-sync"]) expect(container.querySelector('[data-testid="' + id + '"]')).not.toBeNull();
});
