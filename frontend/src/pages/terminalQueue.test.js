import { nextAutomaticRequest } from "./terminalQueue";

const preparing = { id: 1, state: "creating", collection: null };
const pending = { id: 2, state: "ready", collection: { payment_status: "pending" } };
const paid = { id: 3, state: "ready", collection: { payment_status: "paid" } };
const ambiguous = { id: 4, state: "ambiguous", collection: null };

test("opens the first pending or preparing request when idle", () => {
  expect(nextAutomaticRequest([paid, preparing, pending], null)).toBe(1);
});
test("keeps a current or manually selected request when new requests arrive", () => {
  expect(nextAutomaticRequest([preparing, pending], 2)).toBe(2);
});
test("does not reopen paid or unresolved requests after acknowledgement", () => {
  expect(nextAutomaticRequest([paid, ambiguous], null)).toBeNull();
  expect(nextAutomaticRequest([paid, ambiguous, pending], null)).toBe(2);
});

test("does not reopen an acknowledged request while the list is stale", () => {
  expect(nextAutomaticRequest([pending, preparing], null, new Set([2]))).toBe(1);
});
