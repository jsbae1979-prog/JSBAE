import { useEffect, useRef, useState } from "react";
import {
  FileText,
  Sparkles,
  Save,
  Film,
  ChevronRight,
  SlidersHorizontal,
} from "lucide-react";
import { actions, type Item } from "../contracts";
import { submitOriginal } from "../CommandDialog";
import {
  ActionButton,
  Empty,
  Media,
  NewsImage,
  Panel,
  Select,
  State,
  type Controller,
} from "./shared";
export default function NewsShortsStudio({
  c,
  onNavigate,
}: {
  c: Controller;
  onNavigate: (page: string) => void;
}) {
  const [archiveId, setArchiveId] = useState<number | null>(
    () => Number(new URLSearchParams(location.search).get("draft_id")) || null,
  );
  const [rank, setRank] = useState(
      () => Number(new URLSearchParams(location.search).get("rank")) || 1,
    ),
    [duration, setDuration] = useState("30"),
    [voice, setVoice] = useState("offline-silence"),
    [subtitle, setSubtitle] = useState("48:1420"),
    [visual, setVisual] = useState("card");
  const [editor, setEditor] = useState<Item | null>(null),
    [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [scene, setScene] = useState(0),
    [imagePaths, setImagePaths] = useState<Record<number, string>>({});
  const rows = c.context?.top3 ?? [],
    chosen = rows.find((x: Item) => x.rank === rank),
    draft = c
      .list("drafts")
      .find((x) => x.id === (archiveId ?? chosen?.draftId)),
    editorVersion = useRef("");
  const key = draft ? `studio-script-${draft.id}-${draft.revision}` : "";
  useEffect(() => {
    if (editorVersion.current === key) return;
    editorVersion.current = key;
    let value = draft?.content ? structuredClone(draft.content) : null,
      recovered = false;
    try {
      const saved = key && sessionStorage.getItem(key);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed && Array.isArray(parsed.scenes)) {
          value = parsed;
          recovered = true;
        }
      }
    } catch {
      c.setNotice("임시 대본 복원 자료를 확인하세요.");
    }
    setEditor(value);
    setDirty(recovered);
    setScene(0);
    setImagePaths(
      Object.fromEntries(
        (draft?.imageLinks ?? []).map((x: Item, i: number) => [
          i,
          x.mode === "manual" ? (x.name ?? "") : "",
        ]),
      ),
    );
  }, [key]);
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  function update(next: Item) {
    setEditor(next);
    setDirty(true);
    try {
      if (key) sessionStorage.setItem(key, JSON.stringify(next));
    } catch {
      c.setNotice("임시 복원 공간이 부족합니다. 대본을 저장하세요.");
    }
  }
  function choose(n: number) {
    if (
      dirty &&
      !window.confirm(
        "저장하지 않은 대본은 임시 복원본으로 남습니다. 다른 뉴스로 이동할까요?",
      )
    )
      return;
    setArchiveId(null);
    setRank(n);
  }
  async function save() {
    if (!draft || !editor || !c.view || busy) return;
    setBusy(true);
    try {
      const a = actions.find((a) => a.id === "intelligence_edit")!;
      await submitOriginal(
        a,
        {
          draft_id: draft.id,
          revision: draft.revision,
          content: JSON.stringify(editor),
        },
        c.view,
        {},
      );
      sessionStorage.removeItem(key);
      setDirty(false);
      c.setNotice("대본을 저장했습니다.");
      await c.load();
    } catch (e) {
      c.setNotice(
        e instanceof Error ? e.message : "저장 실패 · 편집 내용은 보존됩니다.",
      );
    } finally {
      setBusy(false);
    }
  }
  const scenes = Array.isArray(editor?.scenes) ? editor.scenes : [],
    project = (c.view?.projects ?? []).find((x) => x.draftId === draft?.id);
  const voices: Record<string, string> = {
    "offline-silence": "무음 · 로컬 검증",
  };
  for (const x of c.view?.catalog.voices ?? [])
    if (x.id) voices[x.id] = x.label ?? x.id;
  if (c.view?.catalog.ttsVoice) voices[c.view.catalog.ttsVoice] = "저장한 음성";
  const extraImages = scenes.map((_: Item, i: number) =>
    visual === "card" ? "__card__" : (imagePaths[i] ?? ""),
  );
  return (
    <div className="core-shorts">
      <Panel
        title="분석된 뉴스 TOP 3"
        tools={
          <button onClick={() => onNavigate("news")}>
            뉴스 스튜디오 <ChevronRight size={14} />
          </button>
        }
      >
        <p className="core-muted">
          저장된 분석 #{c.context?.selection?.id ?? "—"} ·{" "}
          {c.context?.selection?.provider ?? "분석 대기"} · 순위와 출처를 그대로
          연결합니다.
        </p>
        {c.context?.blockedReason && (
          <p className="core-warning">{c.context.blockedReason}</p>
        )}
        <div className="core-news-top3">
          {rows.map((x: Item) => (
            <button
              key={x.rank}
              className={`core-news-card ${rank === x.rank ? "selected" : ""}`}
              onClick={() => choose(x.rank)}
              aria-pressed={rank === x.rank}
            >
              <div className="core-news-picture">
                <NewsImage item={x} />
                <b>TOP {x.rank}</b>
              </div>
              <div>
                <small>{x.category || "분석 뉴스"}</small>
                <strong>{x.title}</strong>
                <p>{x.summary}</p>
              </div>
            </button>
          ))}
          {!rows.length && (
            <Empty>완료된 TOP 3 분석을 뉴스 스튜디오에서 선택하세요.</Empty>
          )}
        </div>
      </Panel>
      <div className="core-short-work">
        <Panel
          title="AI 대본 생성 · 편집"
          className="core-script"
          tools={
            <span className="core-tag">
              {draft
                ? `저장 버전 ${draft.revision}${dirty ? " · 편집 중" : ""}`
                : "뉴스 선택 후 생성"}
            </span>
          }
        >
          <div className="core-actions">
            <Select
              label="영상 길이"
              value={duration}
              onChange={setDuration}
              options={{ 30: "30초", 45: "45초", 60: "60초" }}
            />
            <ActionButton
              c={c}
              id="curation_generate"
              context={{
                analysis_id: c.context?.selection?.id,
                rank,
                duration: Number(duration),
              }}
              disabled={!chosen || !!c.context?.selection?.stale}
              primary
            >
              <Sparkles size={16} />
              AI 대본 생성
            </ActionButton>
          </div>
          {draft && editor ? (
            <>
              <label>
                대본 제목
                <input
                  aria-label="대본 제목"
                  value={editor.title ?? ""}
                  onChange={(e) => update({ ...editor, title: e.target.value })}
                />
              </label>
              <div className="core-script-scroll">
                {scenes.map((s: Item, i: number) => (
                  <label key={i} className={scene === i ? "active-script" : ""}>
                    <span>
                      장면 {i + 1} · {s.seconds}초
                    </span>
                    <textarea
                      aria-label={`장면 ${i + 1} 대본`}
                      value={s.narration ?? ""}
                      onFocus={() => setScene(i)}
                      onChange={(e) =>
                        update({
                          ...editor,
                          scenes: scenes.map((x: Item, j: number) =>
                            i === j ? { ...x, narration: e.target.value } : x,
                          ),
                        })
                      }
                    />
                  </label>
                ))}
              </div>
              <div className="core-actions">
                <button
                  disabled={!dirty || busy || !c.view?.commandsAvailable}
                  onClick={() => void save()}
                >
                  <Save size={15} />
                  대본 저장
                </button>
                <State value={draft.review_status} />
              </div>
            </>
          ) : (
            <Empty>
              {chosen
                ? "선택 기사와 기존 분석을 사용해 대본을 생성하세요."
                : "먼저 TOP 3 뉴스를 선택하세요."}
            </Empty>
          )}
        </Panel>
        <Panel title="간편 영상 설정 · 미리보기" className="core-simple-video">
          <div className="core-settings-preview">
            <div className="core-options">
              <Select
                label="음성"
                value={voice}
                onChange={setVoice}
                options={voices}
              />
              <Select
                label="영상 방식"
                value={visual}
                onChange={setVisual}
                options={{
                  card: "FFmpeg 기본 카드",
                  news: "연결 뉴스 이미지",
                  ai: "AI 장면 · 별도 견적",
                }}
              />
              <Select
                label="자막"
                value={subtitle}
                onChange={setSubtitle}
                options={{
                  "48:1420": "기본 · 하단",
                  "56:1320": "크게 · 중앙 하단",
                  "40:1460": "작게 · 하단",
                }}
              />
              <p className="core-muted">
                1080×1920 · 9:16
                <br />
                음성·소재 권한과 비용은 제작 전 다시 확인합니다.
              </p>
              <a href="/studio/settings">음성·Provider 설정</a>
              {visual === "ai" && (
                <ActionButton
                  c={c}
                  id="video_ai_create_plan"
                  context={{ draft_id: draft?.id, duration: Number(duration) }}
                  disabled={!draft || dirty}
                >
                  AI 장면 계획 · 견적
                </ActionButton>
              )}
            </div>
            <Media url={project?.mediaUrl} />
          </div>
        </Panel>
      </div>
      <div className="core-render-bar">
        <div>
          <Film size={23} />
          <span>
            <strong>영상 제작 및 저장</strong>
            <small>대본 저장 → 검토·권한 확인 → 합성 → 결과 검토</small>
          </span>
        </div>
        <ActionButton
          c={c}
          id="video_render"
          primary
          disabled={!draft || dirty || visual === "ai"}
          context={{
            draft_id: draft?.id,
            duration: Number(duration),
            voice,
            font_size: Number(subtitle.split(":")[0]),
            subtitle_y: Number(subtitle.split(":")[1]),
            __extra: { images: extraImages },
          }}
        >
          <Film size={17} />
          영상 제작 · 승인 확인
        </ActionButton>
      </div>
      <details className="core-advanced">
        <summary>
          <SlidersHorizontal size={15} />
          고급 장면 편집 · 기존 작업
        </summary>
        {scenes.length > 0 && (
          <>
            <div className="core-timeline">
              {scenes.map((s: Item, i: number) => (
                <button
                  key={i}
                  onClick={() => setScene(i)}
                  aria-pressed={scene === i}
                >
                  <FileText size={17} />
                  <strong>장면 {i + 1}</strong>
                  <span>{s.caption || s.narration}</span>
                  <small>{s.seconds}초</small>
                </button>
              ))}
            </div>
            <label>
              선택 장면 자막
              <input
                value={scenes[scene]?.caption ?? ""}
                onChange={(e) =>
                  update({
                    ...editor,
                    scenes: scenes.map((s: Item, i: number) =>
                      i === scene ? { ...s, caption: e.target.value } : s,
                    ),
                  })
                }
              />
            </label>
            {visual === "news" && (
              <>
                <label>
                  선택 장면 이미지
                  <select
                    aria-label="선택 장면 이미지"
                    value={imagePaths[scene] ?? ""}
                    onChange={(e) =>
                      setImagePaths({ ...imagePaths, [scene]: e.target.value })
                    }
                  >
                    <option value="">뉴스 연결 이미지 자동 선택</option>
                    <option value="__card__">기본 이미지 카드</option>
                    {(c.view?.catalog.assets ?? []).map((name: string) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                <p>
                  허용 저장소 안의 경로만 서버에서 검증합니다. 빈 경로는 기본
                  카드입니다.
                </p>
              </>
            )}
          </>
        )}
        <div className="core-history">
          {c.list("drafts").map((d) => (
            <a key={d.id} href={`/studio/shorts?draft_id=${d.id}`}>
              대본 #{d.id} · {d.content?.title}
            </a>
          ))}
        </div>
        {c.list("plans").map((plan) => (
          <div key={plan.id} className="core-actions">
            <strong>AI 계획 #{plan.id}</strong>
            <State value={plan.status} />
            {[
              "video_ai_save_scenes",
              "video_ai_confirm",
              "video_ai_review",
              "video_ai_approve",
            ].map((id) => (
              <ActionButton
                key={id}
                c={c}
                id={id}
                context={{ plan_id: plan.id, revision: plan.revision }}
              >
                {" "}
                {actions.find((a) => a.id === id)?.label}
              </ActionButton>
            ))}
          </div>
        ))}
      </details>
    </div>
  );
}
