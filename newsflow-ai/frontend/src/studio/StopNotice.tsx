import { useEffect, useState } from "react";
import { watchOwnDocumentStop } from "./ownDocumentStop";

export default function StopNotice() {
  const [message, setMessage] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void watchOwnDocumentStop({
      origin: window.location.origin,
      signal: controller.signal,
      fetchNotice: (path, options) => fetch(path, options),
      closeSelf: () => window.close(),
      isClosed: () => window.closed,
      schedule: (callback, delay) => window.setTimeout(callback, delay),
      notify: (value) => {
        if (!controller.signal.aborted) setMessage(value);
      },
    });
    return () => controller.abort();
  }, []);
  return message ? (
    <div className="work-notice" role="status">
      {message}
    </div>
  ) : null;
}
