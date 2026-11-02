import { useEffect, useRef, useState } from "react";
import { Panel } from "./shared";

export async function metaRequest(
  path: string,
  csrf: string,
  values?: Record<string, string>,
) {
  const response = await fetch("/api/meta/" + path, {
    credentials: "same-origin",
    ...(values
      ? {
          method: "POST",
          body: new URLSearchParams({ ...values, csrf_token: csrf }),
        }
      : {}),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      data.detail?.message ??
        "연결 상태를 확인하세요. 자동 재요청하지 않습니다.",
    );
  return data;
}
const names: Record<string, string> = {
  connected: "연결됨",
  disconnected: "연결 해제",
  expired: "만료 · 다시 연결",
  permission: "권한 확인 필요",
  identity: "서비스 설정 변경 · 다시 연결",
  draft: "게시 준비",
  sending: "전송 중",
  processing: "미디어 처리 중",
  ready: "최종 게시 대기",
  publishing: "게시 중",
  published_unverified: "결과 확인 필요",
  published: "게시 완료",
  failed: "실패",
  unknown: "결과 불명 · 재전송 금지",
};
export const metaState = (value: string) => names[value] ?? value;
const date = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "만료일 미지정 · 철회 시 무효";

export default function MetaAccounts({ csrf }: { csrf: string }) {
  const [data, setData] = useState<any>(null),
    [config, setConfig] = useState<any>(null),
    [error, setError] = useState("");
  const [busy, setBusy] = useState(false),
    [origin, setOrigin] = useState(""),
    [credential, setCredential] = useState("");
  const lock = useRef(false);
  async function load() {
    try {
      const value = await metaRequest("status", csrf);
      setData(value);
      setConfig((old: any) => old ?? value.config);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    if (!data?.pending) return;
    const timer = setInterval(() => void load(), 2000);
    return () => clearInterval(timer);
  }, [data?.pending]);
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
  return (
    <Panel title="Facebook · Instagram 연결">
      <p>
        본인의 Meta 계정으로 로그인해 관리하는 페이지를 선택하세요. Instagram은
        Facebook 페이지에 연결된 비즈니스·크리에이터 계정이어야 합니다.
      </p>
      <p>
        이 Windows 사용자에게만 저장됩니다. 다른 사용자와 토큰을 공유하지
        않습니다.
      </p>
      {error && <p role="alert">{error}</p>}
      {data?.cleanupPending && <p role="status">사용하지 않는 암호화 자료의 정리가 필요합니다. 연결 상태와 게시 기록은 유지됩니다.</p>}
      {data?.executionReady === false && <p role="status">Meta 실행 연결이 아직 적용되지 않았습니다. 서비스 설정을 준비한 후 운영 반영이 필요합니다.</p>}
      {data?.error && (
        <p role="status">
          로그인 결과: {metaState(data.error)}. 자동 재요청하지 않습니다.
        </p>
      )}
      {config && (
        <details>
          <summary>서비스 연결 설정</summary>
          <div className="mg-form">
            {[
              ["appId", "Meta 앱 ID"],
              ["configId", "로그인 구성 ID"],
              ["graphVersion", "API 버전"],
              ["relayOrigin", "인증 서버 HTTPS 주소"],
            ].map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  value={config[key]}
                  onChange={(e) =>
                    setConfig({ ...config, [key]: e.target.value })
                  }
                />
              </label>
            ))}
            <button
              disabled={busy || data?.pending}
              onClick={() =>
                act("config", {
                  app_id: config.appId,
                  config_id: config.configId,
                  graph_version: config.graphVersion,
                  relay_origin: config.relayOrigin,
                })
              }
            >
              서비스 설정 저장
            </button>
            <p>
              앱 시크릿은 인증 서버에만 보관합니다. 이 PC에 입력하지 마세요.
            </p>
            <label>
              미디어 서버 HTTPS 주소
              <input
                value={origin}
                onChange={(e) => setOrigin(e.target.value)}
              />
            </label>
            <label>
              본인 전용 업로드 키
              <input
                type="password"
                autoComplete="off"
                value={credential}
                onChange={(e) => setCredential(e.target.value)}
              />
            </label>
            <button
              disabled={busy || !origin || !credential}
              onClick={() => {
                void act("media-config", { origin, credential });
                setCredential("");
              }}
            >
              미디어 연결 저장
            </button>
            <p>
              미디어 전달:{" "}
              {data?.mediaReady ? "설정됨 · 실제 전달 미검증" : "미설정"}
            </p>
          </div>
        </details>
      )}
      <button
        disabled={busy || !data?.configured || data?.pending || data?.executionReady === false}
        onClick={() => act("connect", { consent: "true" })}
      >
        Meta 로그인 · 계정 추가
      </button>
      {data?.pending && (
        <>
          <p role="status">Meta 로그인 · 페이지 선택 진행 중</p>
          <button disabled={busy} onClick={() => act("cancel", {})}>
            로그인 취소
          </button>
        </>
      )}
      {data?.pages?.map((page: any) => (
        <button
          key={page.id}
          disabled={busy}
          onClick={() => act("select-page", { page_id: page.id })}
        >
          {page.name} ·{" "}
          {page.instagram_id ? "Instagram 연결 포함" : "Facebook만"} 선택
        </button>
      ))}
      {data?.accounts?.map((account: any) => (
        <article key={account.id} className="mg-panel">
          <strong>{account.label}</strong> · {metaState(account.state)}
          <p>
            Facebook {account.pageId}{" "}
            {account.instagramId && (
              <>
                · Instagram @{account.instagramName} ({account.instagramId})
              </>
            )}
          </p>
          <details>
            <summary>권한 · 만료일</summary>
            <p>{account.scopes.join(", ")}</p>
            <p>사용자 토큰: {date(account.userExpiresAt)}</p>
            <p>페이지 토큰: {date(account.pageExpiresAt)}</p>
            <p>데이터 접근: {date(account.dataExpiresAt)}</p>
          </details>
          <button
            disabled={busy}
            onClick={() => {
              const label = window.prompt("연결 이름", account.label);
              if (label) void act(`accounts/${account.id}/rename`, { label });
            }}
          >
            이름 변경
          </button>
          <button
            disabled={busy || data?.pending}
            onClick={() =>
              act("connect", { consent: "true", reconnect: account.id })
            }
          >
            다시 연결
          </button>
          <button
            disabled={busy || data?.pending || (account.state === "disconnected" && !account.cleanupRequired)}
            onClick={() => {
              if (
                window.confirm(
                  `${account.label} 연결을 해제하고 이 PC의 토큰을 삭제할까요? 기존 게시 기록은 보존합니다. Meta 전체 앱 권한 철회는 Meta 설정에서 할 수 있습니다.`,
                )
              )
                void act(`accounts/${account.id}/disconnect`, {
                  consent: "true",
                });
            }}
          >
            연결 해제
          </button>
        </article>
      ))}
    </Panel>
  );
}
