import axios from "axios";

// Separate client for the customer payment page: no cookies, no session refresh, no staff APIs.
export const publicApi = axios.create({
  baseURL: `${process.env.REACT_APP_BACKEND_URL}/api/public`,
  withCredentials: false,
  timeout: 15000,
});
