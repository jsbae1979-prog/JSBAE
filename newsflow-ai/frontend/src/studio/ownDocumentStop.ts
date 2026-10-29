/** Closes only this document after an authenticated explicit Stop response.
 * A disconnect, expired session, invalid response or rejected request never closes it.
 */
export const stopNoticePath = "/api/studio/session-stop";
export const stopCloseFallback =
  "종료 요청이 확인되었습니다. 브라우저가 자동 닫기를 허용하지 않아 이 탭은 직접 닫아주세요.";
type ResponseLike = {
  status: number;
  ok: boolean;
  url: string;
  redirected: boolean;
  json(): Promise<unknown>;
};
type OwnDocument = {
  origin: string;
  signal: AbortSignal;
  fetchNotice: (path: string, options: RequestInit) => Promise<ResponseLike>;
  closeSelf: () => void;
  isClosed: () => boolean;
  schedule: (callback: () => void, milliseconds: number) => unknown;
  notify: (message: string) => void;
};
export async function watchOwnDocumentStop(
  host: OwnDocument,
): Promise<"requested" | "disconnected" | "cancelled"> {
  const expected = new URL(stopNoticePath, host.origin).href;
  while (!host.signal.aborted) {
    try {
      const response = await host.fetchNotice(stopNoticePath, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal: host.signal,
      });
      if (host.signal.aborted) return "cancelled";
      if (
        !response.ok ||
        response.status !== 200 ||
        response.redirected ||
        response.url !== expected
      )
        return "disconnected";
      const data = (await response.json()) as {
        schemaVersion?: unknown;
        stopAccepted?: unknown;
      };
      if (host.signal.aborted) return "cancelled";
      if (
        !data ||
        data.schemaVersion !== 1 ||
        typeof data.stopAccepted !== "boolean"
      )
        return "disconnected";
      if (!data.stopAccepted) continue;
      try {
        host.closeSelf();
      } catch {
        /* A browser may refuse; never target another tab/window. */
      }
      host.schedule(() => {
        if (!host.isClosed()) host.notify(stopCloseFallback);
      }, 350);
      return "requested";
    } catch {
      return host.signal.aborted ? "cancelled" : "disconnected";
    }
  }
  return "cancelled";
}
