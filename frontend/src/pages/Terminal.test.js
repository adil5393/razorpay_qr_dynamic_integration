import React, { act } from "react";
import { createRoot } from "react-dom/client";
import Terminal from "./Terminal";

global.React = React;
let mockRows = [];
let mockLive = {};
let mockUserId = 100;
const mockSetParams = jest.fn();
jest.mock("react-router-dom", () => ({ useSearchParams: () => [new URLSearchParams(), mockSetParams] }));
jest.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: mockRows, isLoading: false, error: null, refetch: jest.fn() }) }));
jest.mock("@/hooks/queries", () => ({ useCollectionStatus: (id) => ({ data: mockLive[id] }) }));
jest.mock("@/context/AuthContext", () => ({ useAuth: () => ({ user: { id: mockUserId, role: "cashier" } }) }));
jest.mock("@/components/QRDisplay", () => ({ QRDisplay: ({ collection }) => <div>QR {collection.id}</div> }));
jest.mock("sonner", () => ({ toast: { info: jest.fn(), success: jest.fn(), error: jest.fn() } }));

const request = (id, name) => ({ id, invoice_number: "INV-" + id, customer_name: name, amount_paise: 10000, state: "ready", error: null, collection: { id, payment_status: "pending", qr_status: "active", image_url: "https://example.test/qr.png", close_by: null } });
let container, root;
const render = async () => { await act(async () => { root.render(<Terminal />); }); };
const click = async (text) => { const button = [...container.querySelectorAll("button")].find((el) => el.textContent.includes(text)); expect(button).toBeTruthy(); await act(async () => { button.dispatchEvent(new MouseEvent("click", { bubbles: true })); }); };
beforeEach(() => { global.IS_REACT_ACT_ENVIRONMENT = true; mockRows = []; mockLive = {}; mockUserId++; container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

test("opens incoming requests when idle and preserves an active request", async () => {
  await render(); expect(container.textContent).toContain("Ready for the next payment");
  mockRows = [request(11, "First"), request(12, "Second")]; await render();
  expect(container.textContent).toContain("QR 11");
  mockRows = [request(13, "Third"), ...mockRows]; await render();
  expect(container.textContent).toContain("QR 11");
  await click("Second"); expect(container.textContent).toContain("QR 12");
});

test("prepares the QR and waits for acknowledgement before selecting another", async () => {
  mockRows = [{ ...request(21, "First"), state: "creating", collection: null }, request(22, "Second")]; await render();
  expect(container.textContent).toContain("Preparing your QR");
  mockRows = [request(21, "First"), request(22, "Second")]; await render(); expect(container.textContent).toContain("QR 21");
  mockLive[21] = { payment_status: "paid", qr_status: "closed", successful_payment: { razorpay_payment_id: "pay_test" } }; await render();
  expect(container.textContent).toContain("Payment received"); await click("Second"); expect(container.textContent).toContain("Payment received");
  await click("Done, next payment"); expect(container.textContent).toContain("QR 22");
});


test("shows a full-screen QR and responsive queue layout", async () => {
  mockRows = [request(31, "Customer")]; await render();
  expect(container.querySelector('[aria-label="Payment queue"]').className).toContain("lg:block");
  await click("Full screen");
  expect(container.querySelector('[role="dialog"][aria-label="Full screen payment QR"]')).not.toBeNull();
  const close = container.querySelector('[aria-label="Close full screen"]');
  await act(async () => close.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  expect(container.querySelector('[role="dialog"]')).toBeNull();
});
