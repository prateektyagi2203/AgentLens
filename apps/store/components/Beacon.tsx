"use client";

import { useEffect } from "react";

/** Fires once per page load; JS-running clients produce a beacon event, plain fetchers do not. */
export default function Beacon() {
  useEffect(() => {
    if (navigator.sendBeacon) navigator.sendBeacon("/api/beacon");
    else void fetch("/api/beacon", { method: "POST", keepalive: true });
  }, []);
  return null;
}
