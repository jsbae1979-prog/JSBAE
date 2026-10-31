import { useState } from "react";
import {
  Settings2,
  Rocket,
  KeyRound,
  RefreshCw,
  Folder,
  ShieldCheck,
  Rss,
  Bot,
} from "lucide-react";
import {
  Panel,
  Action,
  Accounts,
  Badge,
  Empty,
  type Controller,
} from "./shared";
const tabs = [
  ["overview", "개요"],
  ["accounts", "플랫폼 계정"],
  ["models", "AI 모델 · API 키"],
  ["defaults", "제작 기본값"],
  ["sources", "뉴스 수집"],
  ["windows", "자동화 & 실행"],
  ["system", "시스템 관리"],
];
export default function Settings({
  c,
  onNavigate,
}: {
  c: Controller;
  onNavigate: (p: string) => void;
}) {
  const [tab, setTab] = useState("overview"),
    [modelTab, setModelTab] = useState("text"),
    [startup, setStartup] = useState<any>(null),
    [loading, setLoading] = useState(false);
  const [probeBusy,setProbeBusy]=useState("");
  const [probeResult,setProbeResult]=useState<Record<string,any>>({});
  async function testProvider(provider:string,scope:string) {
    if(probeBusy)return;
    const key=provider+":"+scope;
    setProbeBusy(key);
    try {
      const response=await fetch(`/api/studio/providers/${provider}/check`,{
        method:"POST",credentials:"same-origin",
        body:new URLSearchParams({scope,consent:"true",csrf_token:c.view?.csrfToken??""})
      });
      const result=await response.json().catch(()=>({}));
      setProbeResult(previous=>({...previous,[key]:response.ok?result:{code:"unavailable",verified:false,message:"연결 테스트를 완료하지 못했습니다. 다시 누르기 전에 상태를 확인하세요."}}));
      await c.load();
    } catch {
      setProbeResult(previous=>({...previous,[key]:{code:"network",verified:false,message:"결과를 받지 못했습니다. 자동 재요청하지 않습니다."}}));
    } finally {setProbeBusy("");}
  }
  let setup: any = {};
  try {
    setup = JSON.parse(c.view?.settings?.easy_setup ?? "{}");
  } catch {}
  const show = (id: string) => tab === "overview" || tab === id;
  const providers = [
    {
      id: "openai",
      name: "OpenAI",
      action: "api_settings_save_key",
      provider: "openai_api",
      types: ["text", "image"],
    },
    {
      id: "claude",
      name: "Claude",
      action: "api_settings_save_key",
      provider: "claude_api",
      types: ["text"],
    },
    {
      id: "higgsfield",
      name: "Higgsfield",
      action: "video_ai_save_key",
      types: ["video"],
    },
    {
      id: "elevenlabs",
      name: "ElevenLabs",
      action: "video_save_tts_key",
      types: ["voice"],
    },
  ];
  async function inspect() {
    if (loading) return;
    setLoading(true);
    try {
      const r = await fetch("/api/studio/system-startup", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!r.ok) throw Error();
      setStartup(await r.json());
    } catch {
      c.setNotice(
        "실행 상태를 조회하지 못했습니다. 설정은 변경하지 않았습니다.",
      );
    } finally {
      setLoading(false);
    }
  }
  return (
    <>
      <nav className="mg-settings-tabs" role="tablist" aria-label="설정 항목">
        {tabs.map(([v, t]) => (
          <button
            role="tab"
            key={v}
            aria-selected={tab === v}
            onClick={() => setTab(v)}
          >
            {t}
          </button>
        ))}
      </nav>
      <section className="mg-guide">
        <Rocket size={50} />
        <div>
          <h2>시작 가이드 (7단계)</h2>
          <p>저장된 준비 상태를 확인하고, 필요한 항목부터 설정하세요.</p>
        </div>
        <ol>
          {[
            "시작",
            "뉴스 자료",
            "분석 AI",
            "영상 형식",
            "음성·자막",
            "저장 위치",
            "완료",
          ].map((t, i) => (
            <li
              key={t}
              aria-current={Number(setup.step) === i + 1 ? "step" : undefined}
            >
              <b>{i + 1}</b>
              <small>{t}</small>
              <span>
                {setup.completed || Number(setup.step) > i + 1
                  ? "저장 기록 있음"
                  : Number(setup.step) === i + 1
                    ? "진행 중"
                    : "대기"}
              </span>
            </li>
          ))}
        </ol>
        <button className="mg-primary" onClick={() => onNavigate("onboarding")}>
          가이드 시작하기
        </button>
      </section>
      <div
        className={"mg-settings-grid " + (tab !== "overview" ? "focused" : "")}
      >
        {show("accounts") && (
          <Panel title="플랫폼 계정" className="mg-settings-accounts">
            <Accounts c={c} compact />
            <p className="mg-muted">
              API 키 저장, 로컬 계정 등록, 실제 OAuth·권한 검증은 서로 다릅니다.
              실제로 연결되지 않은 계정을 연결 완료로 표시하지 않습니다.
            </p>
          </Panel>
        )}
        {show("windows") && (
          <Panel title="Windows 실행 설정" className="mg-settings-windows">
            <div className="mg-status-line">
              <Settings2 />
              <span>
                프로그램 자동 시작
                <small>
                  {startup?.status ?? "미조회 · 현재 상태 확인 필요"}
                </small>
              </span>
            </div>
            <div className="mg-status-line">
              <ShieldCheck />
              <span>
                자동 스케줄러
                <small>예약 저장과 활성화는 별도 · 무인 유료 실행 차단</small>
              </span>
            </div>
            <button
              className="mg-primary"
              onClick={() => void inspect()}
              disabled={loading}
            >
              <RefreshCw size={16} />
              현재 상태 확인
            </button>
            {startup && <p>{startup.message}</p>}
            {startup?.revision && (
              <Action
                c={c}
                id="operations_startup"
                context={{ revision: startup.revision }}
              >
                자동 시작 등록·해제 동의
              </Action>
            )}
            <Action
              c={c}
              id="operations_review"
              context={{ revision: c.view?.operationsReview?.revision ?? 0 }}
            >
              사람 검토 기록
            </Action>
          </Panel>
        )}
        {show("models") && (
          <Panel
            title="AI 모델 설정"
            className="mg-settings-models"
            tools={<Bot size={20} />}
          >
            <div className="mg-tabs">
              {[
                ["text", "텍스트"],
                ["image", "이미지"],
                ["video", "영상"],
                ["voice", "음성"],
              ].map(([v, t]) => (
                <button
                  key={v}
                  aria-selected={modelTab === v}
                  onClick={() => setModelTab(v)}
                >
                  {t}
                </button>
              ))}
            </div>
            <div className="mg-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>공급사</th>
                    <th>설정 상태</th>
                    <th>API 키</th>
                  </tr>
                </thead>
                <tbody>
                  {providers
                    .filter((p) => p.types.includes(modelTab))
                    .map((p) => {
                      const service = c.view?.services?.find((s) => s.id === p.id);
                      const meta=service?.checks?.[modelTab]??service;
                      const result=probeResult[p.id+":"+modelTab];
                      return (
                        <tr key={p.id}>
                          <td>
                            {p.name}
                            <small>
                              {meta?.model || "모델 설정에서 확인"}
                            </small>
                          </td>
                          <td>
                            {meta?.verified ? (
                              <span className="mg-badge good">인증 확인</span>
                            ) : (
                              <span className="mg-badge">{meta?.configured ? "연결 미확인" : "키 미설정"}</span>
                            )}
                            <small>
                              {meta?.message ?? (meta?.configured ? "키 저장 · 연결 미확인" : "키 미설정")}
                            </small>
                            {meta?.checkedAt&&<small>확인: {new Date(meta.checkedAt).toLocaleString("ko-KR")}</small>}
                          </td>
                          <td>
                            <button type="button" disabled={!!probeBusy || !meta?.configured}
                              title="저장된 키를 공식 공급사로 전송해 조회합니다. 콘텐츠는 생성하지 않습니다."
                              onClick={()=>void testProvider(p.id,modelTab)}>
                              <RefreshCw size={14}/>{probeBusy===p.id+":"+modelTab?"확인 중…":"API 키 테스트"}
                            </button>
                            {result&&!result.checkedAt&&<small role="status">{result.message}</small>}
                            <Action
                              c={c}
                              id={p.action}
                              context={
                                p.provider ? { provider: p.provider } : {}
                              }
                            >
                              <KeyRound size={14} />
                              {p.name} 키 설정
                            </Action>
                            <Action
                              c={c}
                              id={
                                p.id === "elevenlabs"
                                  ? "video_save_tts"
                                  : p.id === "higgsfield"
                                    ? "video_ai_save_settings"
                                    : "api_settings_save_configuration"
                              }
                              context={
                                p.id === "openai" || p.id === "claude"
                                  ? {
                                      ...c.view?.catalog.apiSettingsDefaults?.[
                                        p.id === "openai" ? "openai" : "claude_api"
                                      ],
                                      provider: p.id === "openai" ? "openai" : "claude_api",
                                    }
                                  : {}
                              }
                            >
                              1회 사용 한도
                            </Action>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
            <div className="mg-actions">
              <Action c={c} id="ai_settings_save_ai_settings">
                분석 AI 설정
              </Action>
              <Action c={c} id="video_save_tts">
                음성 모델 설정
              </Action>
              <Action c={c} id="video_ai_save_model_route">
                영상 모델 등록
              </Action>
            </div>
            <details>
              <summary>등록 영상 모델</summary>
              {c.list("models").map((x) => (
                <p key={x.id}>
                  {x.label} · {x.resolution} ·{" "}
                  {x.price_per_second == null
                    ? "단가 미확정"
                    : x.price_per_second + " /초"}
                  <small>{x.path}</small>
                </p>
              ))}
            </details>
          </Panel>
        )}
        {show("defaults") && (
          <Panel title="제작 기본값 설정" className="mg-settings-defaults">
            {[
              ["뉴스 쇼츠", "production_preferences", "shorts"],
              ["독립 AI 이미지", "creation_defaults", "images"],
              ["캐릭터 쇼츠", "character_character_defaults", "characters"],
            ].map(([t, id, page]) => (
              <div className="mg-setting-row" key={id}>
                <strong>{t}</strong>
                <small>다음 작업에 적용 · 기존 작업 유지</small>
                <div className="mg-actions">
                  <Action c={c} id={id}>
                    기본값 설정
                  </Action>
                  <button onClick={() => onNavigate(page)}>제작실 열기</button>
                </div>
              </div>
            ))}
          </Panel>
        )}
        {show("sources") && (
          <Panel
            title="뉴스 수집 설정"
            className="mg-settings-sources"
            tools={<Rss size={20} />}
          >
            <div className="mg-source-list">
              {c.list("sources").map((x) => (
                <article key={x.id}>
                  <strong>{x.name}</strong>
                  <span className="mg-badge">
                    {x.enabled ? "사용 설정" : "정지 설정"}
                  </span>
                  <small>{x.url}</small>
                  <Action
                    c={c}
                    id="sources_edit_source"
                    context={{ ...x, source_id: x.id }}
                  >
                    출처 설정
                  </Action>
                </article>
              ))}
            </div>
            {!c.list("sources").length && <Empty>등록된 수집 출처 없음</Empty>}
            <Action c={c} id="sources_add_source">
              수집 출처 추가
            </Action>
          </Panel>
        )}
        {show("system") && (
          <Panel title="시스템 관리" className="mg-settings-system">
            <label>
              <Folder size={16} />
              사용자 데이터 저장 위치
              <input
                aria-label="사용자 데이터 저장 경로"
                readOnly
                value={
                  c.view?.catalog.storage?.dataDirectory ??
                  "저장 경로 정보 미확인"
                }
              />
            </label>
            <dl>
              <dt>Python</dt>
              <dd>{c.view?.catalog.storage?.python ?? "미확인"}</dd>
              <dt>데이터 보존</dt>
              <dd>설치 자산과 사용자 DB·미디어 분리</dd>
              <dt>인증정보</dt>
              <dd>기존 DPAPI·사용자별 키 정책 유지</dd>
            </dl>
            <p className="mg-muted">
              이 화면에서 저장 폴더를 이동하거나 기존 데이터를 삭제하지
              않습니다.
            </p>
          </Panel>
        )}
        {show("system") && (
          <Panel title="도움말 및 지원" className="mg-settings-help">
            <div className="mg-help-grid">
              <button onClick={() => onNavigate("onboarding")}>
                <Rocket />
                7단계 시작 가이드
              </button>
              <button onClick={() => onNavigate("automation")}>
                <Settings2 />
                자동화 관리
              </button>
              <button onClick={() => onNavigate("library")}>
                <Folder />
                저장 콘텐츠 확인
              </button>
            </div>
            <p className="mg-muted">
              유료 실행·SNS 공개 게시 전에는 기존 별도 검토·승인 절차를
              따릅니다. 비밀값을 로그·캡처·브라우저 저장소에 표시하지 않습니다.
            </p>
          </Panel>
        )}
      </div>
    </>
  );
}
