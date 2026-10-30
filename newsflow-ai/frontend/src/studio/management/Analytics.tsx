import { useState } from "react";
import {
  Search,
  Coins,
  CircleDollarSign,
  Wallet,
  ArrowRight,
} from "lucide-react";
import type { Item } from "../contracts";
import {
  Panel,
  Empty,
  Badge,
  Media,
  Thumb,
  platforms,
  PlatformIcon,
  Action,
  date,
  withinPeriod,
  type Controller,
} from "./shared";
function finite(v: unknown) {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : null;
}
export default function Analytics({ c }: { c: Controller }) {
  const [platform, setPlatform] = useState("all"),
    [account, setAccount] = useState("all"),
    [query, setQuery] = useState(""),
    [period, setPeriod] = useState("all"),
    [id, setId] = useState("");
  const accounts = c.publishing?.collections?.accounts ?? [],
    projects = c.view?.publishedProjects ?? [],
    selected = projects.find((x: Item) => x.id === id) ?? projects[0];
  const inPeriod = (x: Item) =>
    withinPeriod(x.period_end ?? x.created_at ?? x.fetched_at, period);
  const metrics = (c.view?.publishedProjects ? c.list("metrics") : [])
    .filter(
      (x) =>
        (platform === "all" || x.platform === platform) &&
        (account === "all" || String(x.account_id) === account) &&
        inPeriod(x),
    );
  const usage = c.list("usage").filter(inPeriod),
    requests = c.list("requests").filter(inPeriod),
    estimates = requests
      .map((x) => finite(x.estimated_usd))
      .filter((v): v is number => v !== null),
    reserved = requests.filter((x) =>
      ["reserved", "unknown"].includes(x.status),
    );
  const knownTokens = usage
    .map((x) => finite(x.total_tokens))
    .filter((v): v is number => v !== null);
  const totalTokens = knownTokens.reduce((a, b) => a + b, 0);
  const series = Object.entries(
    usage.reduce((a: Record<string, number>, x: Item) => {
      const n = finite(x.total_tokens);
      if (n !== null) {
        const day = String(x.created_at).slice(0, 10);
        a[day] = (a[day] ?? 0) + n;
      }
      return a;
    }, {}),
  ).sort(([a], [b]) => a.localeCompare(b));
  const max = Math.max(1, ...series.map(([, n]) => Number(n))),
    points = series
      .map(([, n], i) =>
        [
          series.length === 1 ? 50 : 10 + (i * 280) / (series.length - 1),
          100 - (Number(n) * 80) / max,
        ].join(","),
      )
      .join(" ");
  function linkedProject(m: Item) {
    const job = c.publishing?.collections?.jobs?.find(
        (j: Item) => j.id === m.job_id,
      ),
      draft = c.publishing?.collections?.drafts?.find(
        (d: Item) => d.id === job?.draft_id,
      );
    return projects.find((p: Item) => p.id === "news:" + draft?.render_job_id);
  }
  return (
    <>
      <div className="mg-cost-header">
        <article>
          <Coins />
          <span>
            기록된 AI 사용량
            <strong>
              {knownTokens.length
                ? totalTokens.toLocaleString("ko-KR") + " tokens"
                : "기록 없음"}
            </strong>
            <small>사용량 · 청구액과 별개</small>
          </span>
        </article>
        <article>
          <CircleDollarSign />
          <span>
            확인된 예상 비용
            <strong>
              {estimates.length
                ? "USD " +
                  estimates
                    .reduce((a, b) => a + b, 0)
                    .toLocaleString("en-US", { maximumFractionDigits: 8 })
                : "견적 미확정"}
            </strong>
            <small>금액이 있는 {estimates.length}건만 · 전체 비용 아님</small>
          </span>
        </article>
        <article>
          <Wallet />
          <span>
            실제 청구 비용<strong>미확인</strong>
            <small>공급사 청구자료 확인 전</small>
          </span>
        </article>
        <Panel title="기간 선택">
          <div className="mg-tabs">
            {[
              ["1", "오늘"],
              ["7", "최근 7일"],
              ["30", "최근 30일"],
              ["all", "전체 기간"],
            ].map(([v, t]) => (
              <button
                key={v}
                aria-selected={period === v}
                onClick={() => setPeriod(v)}
              >
                {t}
              </button>
            ))}
          </div>
        </Panel>
      </div>
      <div className="mg-analytics-layout">
        <div className="mg-analytics-main">
          <Panel title="콘텐츠 · 플랫폼 성과">
            <div className="mg-toolbar">
              <select
                aria-label="성과 계정 필터"
                value={account}
                onChange={(e) => setAccount(e.target.value)}
              >
                <option value="all">전체 등록 계정</option>
                {accounts
                  .filter(
                    (a: Item) => platform === "all" || a.platform === platform,
                  )
                  .map((a: Item) => (
                    <option key={a.id} value={String(a.id)}>
                      {a.platform} · {a.label}
                    </option>
                  ))}
              </select>
              <label className="mg-search">
                <Search size={16} />
                <input
                  aria-label="성과 콘텐츠 검색"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="콘텐츠 검색"
                />
              </label>
            </div>
            <div className="mg-tabs mg-platform-tabs">
              <button
                aria-selected={platform === "all"}
                onClick={() => {
                  setPlatform("all");
                  setAccount("all");
                }}
              >
                전체
              </button>
              {platforms.map((p) => (
                <button
                  key={p.id}
                  aria-selected={platform === p.id}
                  onClick={() => {
                    setPlatform(p.id);
                    setAccount("all");
                  }}
                >
                  <PlatformIcon id={p.id} />
                  {p.label}
                  <small>
                    ({accounts.filter((a: Item) => a.platform === p.id).length})
                  </small>
                </button>
              ))}
            </div>
            <p className="mg-muted">
              등록 계정 수와 연결·권한 확인은 별개입니다. 계정 식별자가 없는
              지표를 특정 계정에 귀속하지 않습니다.
            </p>
          </Panel>
          <div className="mg-analytics-center">
            <Panel title="콘텐츠별 성과" className="mg-performance-content">
              <div className="mg-performance-cards">
                {projects
                  .filter((x: Item) => String(x.title).includes(query))
                  .map((x: Item) => (
                    <button
                      key={x.id}
                      aria-pressed={selected?.id === x.id}
                      onClick={() => setId(x.id)}
                    >
                      <Thumb item={x} />
                      <strong>{x.title}</strong>
                      <Badge value={x.technicalStatus} />
                      <small>성과는 연결된 게시 기록에서 확인</small>
                    </button>
                  ))}
              </div>
              {!projects.length && <Empty>아직 게시 완료된 콘텐츠가 없습니다.</Empty>}
              <div className="mg-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>플랫폼 · 계정</th>
                      <th>지표</th>
                      <th>값</th>
                      <th>자료 구분</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.map((m) => (
                      <tr key={m.id}>
                        <td>
                          {m.platform}
                          <small>
                            {accounts.find((a: Item) => a.id === m.account_id)
                              ?.label ?? "계정 미확인"}
                          </small>
                        </td>
                        <td>
                          {m.metric}
                          <small>
                            {linkedProject(m)?.title ?? "콘텐츠 연결 미확인"}
                          </small>
                        </td>
                        <td>
                          {m.value == null ? "미수집" : m.value} {m.unit}
                        </td>
                        <td>{m.synthetic ? "합성 검증 자료" : "수집 지표"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!metrics.length && (
                <Empty>
                  선택 조건의 수집 지표 없음 · 0으로 대체하지 않습니다.
                </Empty>
              )}
            </Panel>
            <div>
              <Panel title="AI 사용량 추이">
                {series.length >= 2 ? (
                  <>
                    <svg
                      className="mg-chart"
                      viewBox="0 0 310 120"
                      role="img"
                      aria-label="기록된 날짜별 토큰 사용량"
                    >
                      <path
                        d="M10 20H300M10 60H300M10 100H300"
                        stroke="#245174"
                        fill="none"
                      />
                      <polyline
                        points={points}
                        fill="none"
                        stroke="#42e7ec"
                        strokeWidth="3"
                      />
                    </svg>
                    <small>
                      {series[0][0]} ~ {series.at(-1)?.[0]} · 실제 기록 토큰
                    </small>
                  </>
                ) : (
                  <div className="mg-chart-empty">
                    추이 기록 부족 · 임의 그래프 없음
                  </div>
                )}
                <div className="mg-mini-stats">
                  <div>
                    <small>사용량 기록</small>
                    <strong>{usage.length}</strong>
                  </div>
                  <div>
                    <small>결과 불명·예약</small>
                    <strong>{reserved.length}</strong>
                  </div>
                </div>
              </Panel>
              <Panel title="최근 요청 기록">
                {requests.slice(0, 4).map((x) => (
                  <div className="mg-record" key={x.id}>
                    <strong>
                      {x.provider} · {x.kind}
                    </strong>
                    <Badge value={x.status} />
                    <small>{date(x.created_at)}</small>
                  </div>
                ))}
                {!requests.length && <Empty>요청 기록 없음</Empty>}
              </Panel>
            </div>
          </div>
          <Panel title="AI 사용량 · 비용 근거">
            <div className="mg-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>공급사 · 모델</th>
                    <th>작업</th>
                    <th>상태</th>
                    <th>입력 / 출력 토큰</th>
                  </tr>
                </thead>
                <tbody>
                  {usage.map((x) => (
                    <tr key={x.id}>
                      <td>
                        {x.provider}
                        <small>{x.model}</small>
                      </td>
                      <td>{x.kind}</td>
                      <td>
                        <Badge value={x.status} />
                      </td>
                      <td>
                        {x.prompt_tokens ?? "미확인"} /{" "}
                        {x.completion_tokens ?? "미확인"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Action c={c} id="social_collect">
              성과 조회 범위 · 승인 확인
            </Action>
          </Panel>
        </div>
        <aside className="mg-analytics-side">
          <Panel title="선택한 콘텐츠 미리보기">
            <Media
              url={selected?.mediaUrl}
              image={selected?.kind === "image"}
            />
            {selected ? (
              <>
                <h3>{selected.title}</h3>
                <small>{date(selected.updatedAt)}</small>
                <Badge value={selected.technicalStatus} />
                <a
                  className="mg-button"
                  href={
                    "/studio/" +
                    (selected.kind === "news"
                      ? "shorts"
                      : selected.kind === "image"
                        ? "images"
                        : "characters")
                  }
                >
                  제작실로 이동
                  <ArrowRight size={16} />
                </a>
              </>
            ) : (
              <Empty>콘텐츠 선택 대기</Empty>
            )}
          </Panel>
          <Panel title="예상 비용 분석">
            <div className="mg-cost-ring">
              <span>
                {estimates.length ? "추정 USD" : "금액 미확정"}
                <strong>
                  {estimates.length
                    ? estimates
                        .reduce((a, b) => a + b, 0)
                        .toLocaleString("en-US", { maximumFractionDigits: 8 })
                    : "청구 자료 없음"}
                </strong>
              </span>
            </div>
            <p>
              예상 비용·예약 금액·실제 청구액은 별도입니다. 결과 불명 예약을
              자동 해제하거나 재전송하지 않습니다.
            </p>
            <details>
              <summary>계정별 비교</summary>
              {accounts.map((a: Item) => (
                <div className="mg-record" key={a.id}>
                  {a.platform} · {a.label}
                  <small>
                    식별된 지표{" "}
                    {metrics.filter((m) => m.account_id === a.id).length}건
                  </small>
                </div>
              ))}
            </details>
          </Panel>
        </aside>
      </div>
    </>
  );
}
