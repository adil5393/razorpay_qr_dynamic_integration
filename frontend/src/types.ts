export type Role = "admin" | "cashier";

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface PaymentRecord {
  id: number;
  razorpay_payment_id: string;
  collection_id: number;
  amount_paise: number;
  currency: string;
  status: string;
  method: string | null;
  vpa: string | null;
  is_successful: boolean;
  error_description: string | null;
  rzp_created_at: string | null;
  first_seen_at: string;
}

export interface Collection {
  id: number;
  code: string;
  razorpay_qr_id: string;
  amount_paise: number;
  currency: string;
  reference: string | null;
  customer_name: string | null;
  description: string;
  image_url: string;
  qr_status: string;
  close_reason: string | null;
  close_by: string | null;
  closed_at: string | null;
  payment_status: "pending" | "paid" | "expired" | "closed";
  paid_at: string | null;
  amount_received_paise: number;
  created_by: { id: number; name: string };
  created_at: string;
  last_synced_at: string | null;
  payments?: PaymentRecord[];
}

export interface CollectionStatus {
  id: number;
  payment_status: Collection["payment_status"];
  qr_status: string;
  close_reason: string | null;
  close_by: string | null;
  paid_at: string | null;
  amount_received_paise: number;
  last_synced_at: string | null;
  sync_error: string | null;
  successful_payment: PaymentRecord | null;
}

export interface AppConfig {
  razorpay_configured: boolean;
  razorpay_mode: "test" | "live" | null;
  qr_expiry_minutes: number;
}
