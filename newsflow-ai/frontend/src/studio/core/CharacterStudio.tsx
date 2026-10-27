import { useEffect, useState } from "react";
import SampleGallery from "../SampleGallery";
import { Sparkles, ImagePlus, Film, Settings2 } from "lucide-react";
import { Thumbnail } from "../Thumbnail";
import { safeMedia, type Item } from "../contracts";
import {
  Panel,
  Empty,
  Media,
  Select,
  State,
  ActionButton,
  type Controller,
} from "./shared";
const allowed: Record<string, string[]> = {
  write: ["needs_script", "script_failed"],
  prepare: ["script_review"],
  submit: ["quoted"],
  check: ["generating"],
  render: ["clips_review"],
  "retry-scene": ["retry_quoted"],
};
export default function CharacterStudio({ c }: { c: Controller }) {
  const [id, setId] = useState(""),
    [topic, setTopic] = useState(""),
    [model, setModel] = useState(""),
    [scene, setScene] = useState(-1),
    [sampleRef, setSampleRef] = useState<string | null>(null),
    [sampleBusy, setSampleBusy] = useState(false);
  const jobs = c.list("jobs"),
    job = jobs.find((x) => String(x.id) === id) ?? jobs[0],
    defaults = c.view?.catalog.characterDefaults ?? {};
  useEffect(() => {
    if (!model && defaults.script_model) setModel(defaults.script_model);
  }, [defaults.script_model, model]);
  const selection = job?.selection ?? {},
    story = job?.story,
    scenes = story?.scenes ?? [],
    clips = job?.scenes ?? [],
    clip = clips[scene];
  const ref =
    job && job.referenceUrl === `/api/studio/characters/${job.id}/reference`
      ? job.referenceUrl
      : null;
  const refAssets = c.view?.catalog.referenceAssets ?? [],
    [asset, setAsset] = useState("");
  const button = (kind: string, caption: string) => (
    <ActionButton
      c={c}
      id={`character_act_${kind}`}
      context={{
        state: job?.state,
        retry_hash: job?.retry_hash,
        retryQuote: job?.retryQuote,
        job_id: job?.id,
        quote_hash: kind === "retry-scene" ? job?.retry_hash : job?.quote_hash,
      }}
      disabled={
        sampleBusy ||
        !job ||
        (allowed[kind] && !allowed[kind].includes(job.state)) ||
        (kind === "retry-scene" && (!job.retry_hash || !job.retryQuote))
      }
    >
      {caption}
    </ActionButton>
  );
  return (
    <>
      <SampleGallery
        onBusyChange={setSampleBusy}
        initialExpanded={jobs.length === 0}
        types={["character", "character-short"]}
        csrf={c.view?.csrfToken ?? ""}
        onUse={({ asset: sample, copy }) => {
          setAsset(copy.referenceAsset ?? "");
          setSampleRef(`/api/samples/${sample.referenceId || sample.id}/file`);
          void c.load();
          c.setNotice(
            "샘플 참조 PNG를 새 작업 입력에 연결했습니다. 주제를 입력해 새 작업을 저장하세요. 기존 작업은 보존됩니다.",
          );
        }}
      />
      <div className="core-character" aria-busy={sampleBusy}>
        <div className="core-character-steps">
          <div>
            <b>1</b>
            <span>
              <strong>캐릭터 선택</strong>
              <small>참조 PNG로 캐릭터를 설정합니다.</small>
            </span>
          </div>
          <div>
            <b>2</b>
            <span>
              <strong>스토리 생성</strong>
              <small>주제를 입력하고 장면을 검토합니다.</small>
            </span>
          </div>
          <div>
            <b>3</b>
            <span>
              <strong>영상 제작</strong>
              <small>견적·승인 후 장면을 합성합니다.</small>
            </span>
          </div>
        </div>
        <div className="core-character-grid">
          <Panel title="캐릭터 선택" className="core-reference-panel">
            <div className="core-reference-layout">
              <div className="core-reference">
                {sampleRef || ref ? (
                  <Thumbnail
                    src={sampleRef || ref}
                    alt="저장한 캐릭터 참조 PNG"
                  />
                ) : (
                  <Empty>참조 PNG 없음 · 파일을 등록하세요.</Empty>
                )}
              </div>
              <div className="core-options">
                <button
                  disabled={sampleBusy}
                  onClick={() => {
                    setSampleRef(null);
                    setAsset("");
                    c.open("character_create", {
                      topic,
                      script_model: model,
                      video_model: defaults.video_model,
                      reference_asset: "",
                    });
                  }}
                >
                  <ImagePlus size={19} />
                  참조 PNG 등록 · 새 작업
                </button>
                <Select
                  label="저장한 참조 소재"
                  disabled={sampleBusy}
                  value={asset}
                  onChange={(value) => {
                    setAsset(value);
                    setSampleRef(null);
                  }}
                  options={Object.fromEntries(
                    refAssets.map((x: Item) => [
                      x.id ?? x.key,
                      x.label ?? x.title ?? x.id,
                    ]),
                  )}
                />
                <small>
                  참조 이미지는 로컬에 보관됩니다. 외부 전송은 생성 승인 시 별도
                  확인합니다.
                </small>
              </div>
            </div>
            {sampleRef && (
              <p className="core-muted">
                샘플 참조 · 새 작업 입력용. 기존 캐릭터 작업은 변경되지
                않았습니다.
              </p>
            )}
            <h3>내 캐릭터 작업</h3>
            <div className="core-job-list">
              {jobs.map((x) => (
                <button
                  key={x.id}
                  disabled={sampleBusy}
                  aria-pressed={job?.id === x.id}
                  onClick={() => {
                    setSampleRef(null);
                    setId(String(x.id));
                    setScene(-1);
                  }}
                >
                  <strong>{x.topic}</strong>
                  <State value={x.state} />
                </button>
              ))}
            </div>
          </Panel>
          <Panel title="스토리 생성" className="core-story-panel">
            <label>
              스토리 주제
              <textarea
                aria-label="스토리 주제"
                placeholder="캐릭터가 어떤 이야기를 펼칠까요?"
                maxLength={2000}
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
              />
            </label>
            <Select
              label="Claude 대본 모델 · 새 작업"
              value={model}
              onChange={setModel}
              options={c.view?.catalog.apiModels?.claude_api ?? []}
            />
            <ActionButton
              c={c}
              id="character_create"
              context={{
                topic,
                script_model: model,
                video_model: defaults.video_model,
                reference_asset: asset,
              }}
              disabled={sampleBusy || !topic.trim()}
              primary
            >
              이 주제로 작업 저장
            </ActionButton>
            <p className="core-muted">
              저장 후 선택한 작업에 Claude 생성을 요청합니다. 기존 작업의 모델은
              바뀌지 않습니다.
            </p>
            {job && (
              <>
                <p className="core-bound-model">
                  작업 고정 모델 · {selection.script_model ?? "확인 필요"}
                </p>
                {button("write", "Claude 스토리 생성 · 승인")}
                {story ? (
                  <div className="core-story-text">
                    <h3>{story.title}</h3>
                    {scenes.map((s: Item, i: number) => (
                      <p key={i}>
                        <strong>
                          장면 {i + 1} · {s.seconds}초
                        </strong>
                        <br />
                        {s.caption}
                        <br />
                        {s.action}
                      </p>
                    ))}
                  </div>
                ) : (
                  <Empty>생성된 스토리가 없습니다.</Empty>
                )}
              </>
            )}
          </Panel>
          <Panel title="영상 제작" className="core-character-video">
            <div className="core-settings-preview">
              <Media url={scene >= 0 ? clip?.mediaUrl : job?.mediaUrl} />
              <div className="core-options">
                <h3>영상 설정</h3>
                <dl>
                  <dt>영상 모델</dt>
                  <dd>
                    {selection.video_model ??
                      defaults.video_model ??
                      "확인 필요"}
                  </dd>
                  <dt>화면 비율</dt>
                  <dd>{selection.aspect_ratio ?? "9:16"}</dd>
                  <dt>생성 해상도</dt>
                  <dd>{selection.resolution ?? "견적 확인 필요"}</dd>
                  <dt>최종 출력</dt>
                  <dd>FFmpeg · 1080×1920</dd>
                </dl>
                <div className="core-quote">
                  <strong>공식 견적</strong>
                  <p>
                    {job?.quote
                      ? JSON.stringify(job.quote)
                      : "미확정 · 유료 실행 차단"}
                  </p>
                </div>
                {button("prepare", "공식 견적 · 검토")}
                {button("submit", "장면 생성 · 비용 승인")}
                {button("check", "요청한 장면 상태 확인")}
                {button("render", "검토 장면 FFmpeg 합성")}
              </div>
            </div>
            <details className="core-advanced">
              <summary>
                <Settings2 size={14} />
                고급 설정 · 실패 장면
              </summary>
              <p>새 작업 기본값은 기존 작업을 변경하지 않습니다.</p>
              <ActionButton c={c} id="character_character_defaults">
                다음 작업 모델 기본값
              </ActionButton>
              {job?.state === "scene_review" &&
                button("retry-quote", "실패 장면 새 견적 확인")}
              {button("retry-scene", "추가 견적 승인 · 재생성")}
              {job?.state === "submission_unknown" && (
                <p className="core-warning">
                  결과 불명 · 자동 재요청 금지. 기존 공급사 결과를 먼저
                  확인하세요.
                </p>
              )}
            </details>
          </Panel>
        </div>
        <Panel
          title={`스토리보드 · ${scenes.length}장면`}
          tools={
            <button
              onClick={() => setScene(-1)}
              disabled={!safeMedia(job?.mediaUrl)}
            >
              최종 영상 보기
            </button>
          }
        >
          <div className="core-timeline">
            {scenes.map((s: Item, i: number) => (
              <button
                key={i}
                aria-pressed={scene === i}
                onClick={() => setScene(i)}
              >
                <span className="core-scene-number">{i + 1}</span>
                <Film size={22} />
                <strong>{s.caption || `장면 ${i + 1}`}</strong>
                <p>{s.action}</p>
                <small>
                  {s.seconds}초 · <State value={clips[i]?.state ?? "pending"} />
                </small>
              </button>
            ))}
            {!scenes.length && (
              <Empty>스토리가 생성되면 장면별 상태가 표시됩니다.</Empty>
            )}
          </div>
        </Panel>
      </div>
    </>
  );
}
