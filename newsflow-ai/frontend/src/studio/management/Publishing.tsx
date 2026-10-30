import { useEffect, useState } from "react";
import { Search, Send, CalendarDays } from "lucide-react";
import { safeMedia, type Item } from "../contracts";
import {
  Panel,
  Empty,
  Badge,
  Media,
  Thumb,
  Action,
  Accounts,
  PlatformIcon,
  platforms,
  date,
  type Controller,
} from "./shared";
export default function Publishing({ c }: { c: Controller }) {
  const [id, setId] = useState(""),
    [query, setQuery] = useState(""),
    [type, setType] = useState("all"),
    [form, setForm] = useState<Item>({}),
    [targets, setTargets] = useState<string[]>([]),
    [time, setTime] = useState(""),
    [cohortId, setCohortId] = useState("");
  // The module supplies publishable candidates; historical drafts/results stay
  // in their own collections and never reintroduce hidden or unfinished media.
  const projects = (c.view?.module === "publishing" ? c.view.projects ?? [] : []).filter((x) =>
    !!safeMedia(x.mediaUrl) && (x.kind === "character" ? x.technicalStatus === "completed" : x.technicalStatus === "success"));
  const drafts = c.list("drafts").filter((draft) =>
    projects.some((project: Item) => project.id === "news:" + draft.render_job_id));
  const [projectId, setProjectId] = useState("");
  const selectionMissing =
    (!!projectId && !projects.some((x: Item) => x.id === projectId)) ||
    (!!id && id !== "new" && !drafts.some((x) => String(x.id) === id));
  const selected = selectionMissing || id === "new"
    ? undefined : (drafts.find((x) => String(x.id) === id) ?? drafts[0]);
  const project = selectionMissing ? undefined : (
    projects.find((x: Item) => x.id === (projectId || "news:" + selected?.render_job_id)) ?? projects[0]);
  useEffect(() => {
    if (!selectionMissing) return;
    setId("new"); setProjectId(""); setForm({});
    setTargets([]); setTime(""); setCohortId("");
  }, [selectionMissing]);
  useEffect(() => {
    const next = selected
      ? {
          draft_id: selected.id,
          revision: selected.revision,
          title: selected.title,
          description: selected.description,
          hashtags: Array.isArray(selected.hashtags)
            ? selected.hashtags.join(" ")
            : selected.hashtags,
          platform: selected.platform,
          account_id: selected.account_id,
        }
      : {};
    setForm((old) =>
      old.draft_id !== next.draft_id ||
      (old.title === next.title &&
        old.description === next.description &&
        old.hashtags === next.hashtags)
        ? next
        : old,
    );
    if (selected) setProjectId("news:" + selected.render_job_id);
  }, [selected?.id, selected?.revision]);
  const cohorts = c
    .list("cohorts")
    .filter(
      (x) =>
        project?.kind === "news" &&
        x.targets?.some((t: Item) =>
          drafts.some(
            (d) =>
              d.id === t.draft_id && "news:" + d.render_job_id === project.id,
          ),
        ),
    );
  const cohort = cohorts.find((x) => String(x.id) === cohortId) ?? cohorts[0];
  function selectProject(x: Item) {
    const matching = drafts.find((d) => "news:" + d.render_job_id === x.id);
    setId(matching ? String(matching.id) : "new");
    setProjectId(x.id);
    if (!matching) setForm({ title: x.title, description: "", hashtags: "" });
    setCohortId("");
  }
  const context = {
    ...form,
    render_job_id:
      project?.kind === "news" ? String(project.id).split(":")[1] : undefined,
    target: targets,
    content_reviewed: false,
    copyright_confirmed: false,
    sources_confirmed: false,
  };
  function update(k: string, v: string) {
    setForm((x) => ({ ...x, [k]: v }));
  }
  return (
    <>
      <ol className="mg-publish-steps">
        {[
          "콘텐츠 선택",
          "게시 설정",
          "미리보기 및 검토",
          "예약 또는 최종 승인",
          "결과 확인",
        ].map((t, i) => (
          <li key={t}>
            <b>{i + 1}</b>
            <span>
              {t}
              <small>
                {
                  [
                    "저장된 콘텐츠에서 선택",
                    "플랫폼 및 옵션 설정",
                    "내용·권한·출처 확인",
                    "별도 사용자 승인 필요",
                    "결과 불명 재전송 금지",
                  ][i]
                }
              </small>
            </span>
          </li>
        ))}
      </ol>
      <div className="mg-publishing-grid">
        <Panel title="콘텐츠 선택" className="mg-publish-content">
          <label className="mg-search">
            <Search size={16} />
            <input
              aria-label="게시 콘텐츠 검색"
              placeholder="제목으로 검색"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="mg-tabs">
            {[
              ["all", "전체"],
              ["news", "뉴스 쇼츠"],
              ["character", "캐릭터"],
              ["image", "이미지"],
            ].map(([v, t]) => (
              <button
                key={v}
                aria-selected={type === v}
                onClick={() => setType(v)}
              >
                {t}
              </button>
            ))}
          </div>
          <div className="mg-publish-list">
            {projects
              .filter(
                (x: Item) =>
                  (type === "all" || x.kind === type) &&
                  String(x.title).includes(query),
              )
              .map((x: Item) => (
                <button
                  key={x.id}
                  aria-pressed={project?.id === x.id}
                  onClick={() => selectProject(x)}
                >
                  <Thumb item={x} />
                  <span>
                    <strong>{x.title}</strong>
                    <small>{date(x.updatedAt)}</small>
                    <Badge value={x.technicalStatus} />
                  </span>
                </button>
              ))}
          </div>
          {!projects.length && <Empty>게시할 수 있는 완성 콘텐츠가 없습니다.</Empty>}
          <h3>로컬 게시 초안</h3>
          <div className="mg-draft-list">
            {drafts.map((x) => (
              <button
                key={x.id}
                aria-pressed={selected?.id === x.id}
                onClick={() => {
                  setId(String(x.id));
                  setProjectId("news:" + x.render_job_id);
                  setCohortId("");
                }}
              >
                {x.title}
                <Badge value={x.state} />
              </button>
            ))}
          </div>
          <Action
            c={c}
            id="unified_publishing_local_draft"
            context={context}
            disabled={!project || project.kind !== "news"}
            primary
          >
            새 로컬 초안 저장
          </Action>
        </Panel>
        <Panel title="콘텐츠 미리보기 및 편집" className="mg-publish-editor">
          <div className="mg-publish-edit-grid">
            <Media url={project?.mediaUrl} image={project?.kind === "image"} />
            <div>
              <label>
                제목
                <input
                  aria-label="게시 제목"
                  value={form.title ?? project?.title ?? ""}
                  onChange={(e) => update("title", e.target.value)}
                  maxLength={100}
                />
              </label>
              <label>
                설명
                <textarea
                  aria-label="게시 설명"
                  value={form.description ?? ""}
                  onChange={(e) => update("description", e.target.value)}
                />
              </label>
              <label>
                해시태그
                <textarea
                  aria-label="게시 해시태그"
                  value={form.hashtags ?? ""}
                  onChange={(e) => update("hashtags", e.target.value)}
                />
              </label>
              <div className="mg-actions">
                <Action
                  c={c}
                  id="publishing_edit"
                  context={context}
                  disabled={!selected}
                >
                  초안 수정 · 저장
                </Action>
                <Action
                  c={c}
                  id="publishing_validate"
                  context={{ draft_id: selected?.id }}
                  disabled={!selected}
                >
                  형식 검증
                </Action>
              </div>
              <p className="mg-muted">
                저장과 검토·최종 게시 승인은 별도입니다. 수정한 내용은 기존 저장
                창에서 확인합니다.
              </p>
              <div className="mg-review-checks">
                {[
                  ["content_reviewed", "콘텐츠 검토"],
                  ["copyright_confirmed", "저작권·사용권"],
                  ["sources_confirmed", "원문 출처"],
                ].map(([k, t]) => (
                  <p key={k}>
                    <Badge
                      value={selected?.[k] ? "approved" : "review_required"}
                    />
                    {t}
                  </p>
                ))}
              </div>
            </div>
          </div>
        </Panel>
        <aside className="mg-publish-right">
          <Panel title="게시 플랫폼 설정">
            <div className="mg-publish-platforms">
              {platforms.map((p) => (
                <article key={p.id}>
                  <header>
                    <PlatformIcon id={p.id} />
                    <strong>{p.label}</strong>
                    <input
                      type="checkbox"
                      aria-label={p.label + " 검토 대상"}
                      checked={targets.includes(p.id)}
                      onChange={(e) =>
                        setTargets((x) =>
                          e.target.checked
                            ? [...x, p.id]
                            : x.filter((t) => t !== p.id),
                        )
                      }
                    />
                  </header>
                  <small>
                    {["tiktok", "facebook"].includes(p.id)
                      ? "실전송 차단 · 로컬 검토만 지원"
                      : "게시 전 실제 계정 권한·승인 필요"}
                  </small>
                  {c
                    .list("accounts")
                    .filter((x: Item) => x.platform === p.id)
                    .map((a: Item) => (
                      <label className="mg-inline" key={a.id}>
                        계정 {a.label}
                        <Badge value="review_required" />
                      </label>
                    ))}
                  {!c.list("accounts").some((x) => x.platform === p.id) && (
                    <p className="mg-muted">등록 계정 없음</p>
                  )}
                  <Action
                    c={c}
                    id="publishing_account"
                    context={{ platform: p.id }}
                  >
                    계정 설정
                  </Action>
                </article>
              ))}
            </div>
            <Action
              c={c}
              id="unified_publishing_review"
              context={context}
              disabled={!context.render_job_id || !targets.length}
              primary
            >
              선택 플랫폼 게시 검토
            </Action>
          </Panel>
          <Panel title="게시 일정 · 승인">
            <label>
              검토 기록
              <select
                aria-label="게시 검토 기록"
                value={cohort?.id ?? ""}
                onChange={(e) => setCohortId(e.target.value)}
              >
                <option value="">검토 기록 선택</option>
                {cohorts.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              예약 일시
              <input
                aria-label="게시 예약 일시"
                type="datetime-local"
                value={time}
                onChange={(e) => setTime(e.target.value)}
              />
            </label>
            <Action
              c={c}
              id="social_schedule"
              context={{
                cohort_id: cohort?.id,
                due: time
                  ? (time.length === 16 ? time + ":00" : time) + "+09:00"
                  : "",
              }}
              disabled={!cohort || !time}
            >
              <CalendarDays size={16} />
              예약 저장 · 검토
            </Action>
            <Action
              c={c}
              id="unified_publishing_execute"
              context={{
                cohort_id: cohort?.id,
                approval_token: cohort?.approval_token,
              }}
              disabled={!cohort?.can_execute}
              primary
            >
              <Send size={16} />
              최종 게시 승인
            </Action>
            <p className="mg-warning">
              권한·검토·플랫폼별 승인이 없으면 실행할 수 없습니다. 성공·결과
              불명 요청은 재전송하지 않습니다.
            </p>
          </Panel>
        </aside>
      </div>
      <Panel title="게시 대기 목록 · 결과 기록">
        <div className="mg-table-scroll">
          <table>
            <thead>
              <tr>
                <th>콘텐츠 / 기록</th>
                <th>플랫폼</th>
                <th>예약 일정</th>
                <th>상태</th>
                <th>결과·오류</th>
              </tr>
            </thead>
            <tbody>
              {c.list("jobs").map((x) => (
                <tr key={x.id}>
                  <td>
                    게시 #{x.id} · 초안 #{x.draft_id}
                  </td>
                  <td>{x.platform}</td>
                  <td>기록 시각 · {date(x.created_at)}</td>
                  <td>
                    <Badge value={x.status} />
                  </td>
                  <td>{x.message}</td>
                </tr>
              ))}
              {c.list("calendar").map((x) => (
                <tr key={"schedule-" + x.id}>
                  <td>게시 예약 #{x.id}</td>
                  <td>검토 대상별 분리</td>
                  <td>{date(x.due_at)}</td>
                  <td>
                    <Badge value={x.status} />
                  </td>
                  <td>
                    <Action
                      c={c}
                      id="social_cancel"
                      context={{ identifier: x.id, revision: x.revision }}
                    >
                      예약 취소 검토
                    </Action>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!c.list("jobs").length && !c.list("calendar").length && (
          <Empty>저장된 게시·예약 기록 없음</Empty>
        )}
        <details>
          <summary>
            단일 피드 이미지 전달 기록 · {c.list("deliveries").length}개
          </summary>
          {c.list("deliveries").map((x) => (
            <p key={x.id}>
              이미지 #{x.post_id} · 계정 #{x.account_id}{" "}
              <Badge value={x.status} />
            </p>
          ))}
        </details>
      </Panel>
    </>
  );
}
