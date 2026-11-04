import { useEffect, useRef, useState } from "react";
import { Panel } from "./shared";
import { metaRequest, metaState } from "./MetaAccounts";

function StorageForm({
  id,
  busy,
  save,
}: {
  id: string;
  busy: boolean;
  save: (path: string, values: Record<string, string>) => Promise<void>;
}) {
  const [upload, setUpload] = useState(""),
    [download, setDownload] = useState(""),
    [expires, setExpires] = useState("");
  return (
    <details>
      <summary>고급 · 기존 파일별 주소 사용</summary>
      <div className="mg-form">
        <p>
          사용 중인 저장소에서 발급한 파일별 임시 주소를 입력하세요. 전송 승인
          전에는 업로드하지 않습니다.
        </p>
        <label>
          임시 업로드 주소(PUT)
          <input
            type="password"
            autoComplete="off"
            value={upload}
            onChange={(e) => setUpload(e.target.value)}
          />
        </label>
        <label>
          미디어 다운로드 주소(GET)
          <input
            type="password"
            autoComplete="off"
            value={download}
            onChange={(e) => setDownload(e.target.value)}
          />
        </label>
        <label>
          두 주소의 유효 기한(현재 PC 시간)
          <input
            type="datetime-local"
            value={expires}
            onChange={(e) => setExpires(e.target.value)}
          />
        </label>
        <p>
          JPEG 또는 MP4를 그대로 저장하는 HTTPS 저장소가 필요합니다. 유효 기한은
          15분 이후부터 7일 이내이며 Meta 처리가 끝날 때까지 유지해야 합니다.
        </p>
        <button
          disabled={busy || !upload || !download || !expires}
          onClick={() => {
            const date = new Date(expires);
            if (!Number.isFinite(date.getTime())) return;
            void save(`publications/${id}/storage`, {
              put_url: upload,
              get_url: download,
              expires: date.toISOString(),
            });
            setUpload("");
            setDownload("");
          }}
        >
          저장소 주소 저장
        </button>
      </div>
    </details>
  );
}

export default function MetaPublishPanel({
  csrf,
  contentId,
  caption,
}: {
  csrf: string;
  contentId: string;
  caption: string;
}) {
  const [data, setData] = useState<any>(null),
    [targets, setTargets] = useState<string[]>([]),
    [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const lock = useRef(false);
  async function load() {
    try {
      setData(await metaRequest("status", csrf));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    setTargets([]);
    setReviewed(false);
  }, [contentId]);
  useEffect(() => {
    setReviewed(false);
  }, [caption]);
  async function act(path: string, values: Record<string, string>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await metaRequest(path, csrf, values);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  const rows = (data?.publications ?? []).filter(
    (row: any) => row.contentId === contentId,
  );
  return (
    <Panel title="Facebook · Instagram 다중 계정 게시">
      <p>
        현재 선택한 콘텐츠를 게시할 계정을 고르세요. 대상별로 전송·최종 게시
        결과를 확인합니다.
      </p>
      {error && <p role="alert">{error}</p>}
      {data?.executionReady === false && (
        <p>Meta 실행 연결이 준비되기 전에는 게시 준비만 저장할 수 있습니다.</p>
      )}
      {!data?.accounts?.length && (
        <a href="/studio/settings?tab=accounts">설정에서 Meta 계정 연결</a>
      )}
      {data?.accounts?.map((a: any) => (
        <div key={a.id}>
          <strong>{a.label}</strong>
          {["facebook", "instagram"].map((platform) => {
            const key = a.id + ":" + platform;
            const enabled =
              platform === "facebook" ? a.facebookReady : a.instagramReady;
            return (
              <label
                key={key}
                style={{
                  display: "inline-flex",
                  flexDirection: "row",
                  alignItems: "center",
                  width: "auto",
                  gap: 8,
                  margin: 8,
                }}
              >
                <input
                  type="checkbox"
                  style={{ width: 16, height: 16 }}
                  checked={targets.includes(key)}
                  disabled={busy || !enabled}
                  onChange={(e) => {
                    setTargets((old) =>
                      e.target.checked
                        ? [...old, key]
                        : old.filter((v) => v !== key),
                    );
                    setReviewed(false);
                  }}
                />
                {platform === "facebook"
                  ? "Facebook 페이지"
                  : `Instagram @${a.instagramName ?? "미연결"}`}
              </label>
            );
          })}
        </div>
      ))}
      <label
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
        }}
      >
        <input
          type="checkbox"
          style={{ width: 16, height: 16 }}
          checked={reviewed}
          onChange={(e) => setReviewed(e.target.checked)}
        />
        선택 계정·콘텐츠·문구와 권리·출처·AI 표시를 확인했습니다.
      </label>
      <button
        disabled={
          busy || !contentId || !targets.length || !reviewed || !caption.trim()
        }
        onClick={() =>
          act("publications/prepare", {
            content_id: contentId,
            caption,
            targets: JSON.stringify(
              targets.map((t) => {
                const [connectionId, platform] = t.split(":");
                return { connectionId, platform };
              }),
            ),
            reviewed: "true",
          })
        }
      >
        대상별 게시 준비 저장
      </button>
      <p>
        전송 승인 후 파일을 자동 업로드합니다. 직접 전송 가능한 콘텐츠에는 외부
        저장소가 필요 없습니다.
      </p>
      {busy && (
        <p role="status" aria-live="polite">
          전송·처리 중… 완료될 때까지 다시 누르지 마세요.
        </p>
      )}
      {rows.map((row: any) => (
        <article key={row.id} className="mg-panel">
          <strong>
            {row.platform} ·{" "}
            {data?.accounts.find((a: any) => a.id === row.connectionId)
              ?.label ?? row.targetId}
          </strong>
          <p>
            {metaState(row.state)}{" "}
            {row.errorCode && `· ${metaState(row.errorCode)}`}
          </p>
          <details>
            <summary>게시 문구 · 결과</summary>
            <p style={{ whiteSpace: "pre-wrap" }}>{row.caption}</p>
            <p>대상 ID: {row.targetId}</p>
            {row.remoteId && <p>결과 ID: {row.remoteId}</p>}
            {row.publishedAt && (
              <time>{new Date(row.publishedAt).toLocaleString()}</time>
            )}
          </details>
          {row.state === "draft" && (
            <>
              <p>
                {data?.transferModes?.[row.id] === "direct"
                  ? "프로그램에서 Meta로 직접 업로드"
                  : data?.transferModes?.[row.id] === "local"
                    ? "이 PC에서 임시 주소로 전달 · 처리 완료까지 앱을 켜 두세요."
                  : data?.storageReady?.[row.id]
                    ? "전송 승인 시 자동 업로드"
                    : "Instagram 이미지 전달 방식을 설정에서 준비하세요."}
              </p>
              {data?.transferModes?.[row.id] !== "direct" &&
                !data?.storageReady?.[row.id] && (
                  <>
                    <a href="/studio/settings?tab=accounts">
                      자동 업로드 연결 설정
                    </a>
                    <StorageForm id={row.id} busy={busy} save={act} />
                  </>
                )}
            </>
          )}
          {row.state === "draft" && (
            <button
              disabled={
                busy ||
                !(data?.storageReady?.[row.id] ?? data?.mediaReady) ||
                data?.executionReady === false
              }
              onClick={() => {
                if (
                  window.confirm(
                    `${row.platform} 대상 ${row.targetId}에 이 문구와 콘텐츠를 전송할까요? Facebook은 즉시 게시됩니다.`,
                  )
                )
                  void act(`publications/${row.id}/send`, { consent: "true" });
              }}
            >
              전송 승인{row.platform === "facebook" ? " · 게시" : ""}
            </button>
          )}
          {(["processing", "ready", "published_unverified"].includes(
            row.state,
          ) ||
            row.canCheck) && (
            <button
              disabled={busy || data?.executionReady === false}
              onClick={() => act(`publications/${row.id}/check`, {})}
            >
              처리 · 게시 결과 확인
            </button>
          )}
          {row.state === "ready" && (
            <button
              disabled={busy || data?.executionReady === false}
              onClick={() => {
                if (
                  window.confirm(
                    `Instagram 대상 ${row.targetId}에 최종 게시할까요?`,
                  )
                )
                  void act(`publications/${row.id}/publish`, {
                    consent: "true",
                  });
              }}
            >
              Instagram 최종 게시 승인
            </button>
          )}
        </article>
      ))}
      <p>
        예약 게시와 자동 재시도는 하지 않습니다. PC가 꺼지면 상태 확인도
        멈춥니다.
      </p>
    </Panel>
  );
}
