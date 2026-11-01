import { useEffect, useState, type ReactNode } from "react";
import {
  Sparkles,
  Save,
  Download,
  Box,
  Palette,
  Camera,
  Paintbrush,
  Brush,
  Pencil,
} from "lucide-react";
import { safeMedia, type Item } from "../contracts";
import {
  Panel,
  Media,
  Empty,
  State,
  Select,
  ActionButton,
  type Controller,
} from "./shared";
export default function ImageStudio({
  c,
  tabs,
}: {
  c: Controller;
  tabs: ReactNode;
}) {
  const [prompt, setPrompt] = useState(""),
    [style, setStyle] = useState(""),
    [options, setOptions] = useState<Item>({}),
    [id, setId] = useState<number | null>(null);
  const drafts = c.list("drafts"),
    selected = drafts.find((x) => x.id === id) ?? drafts[0],
    success = drafts.filter(
      (x) => x.status === "success" && safeMedia(x.mediaUrl),
    );
  useEffect(() => {
    setOptions(c.view?.catalog.imageDefaults ?? {});
  }, [c.view?.catalog.imageDefaults]);
  const styles = [
      "3D 애니메이션",
      "애니메이션",
      "실사풍",
      "일러스트",
      "만화풍",
      "스케치",
    ],
    context = {
      prompt: style ? `${prompt}\n시각 스타일: ${style}` : prompt,
      ...options,
    },
    blocked = selected?.outputId != null;
  function choose(x: Item) {
    setId(x.id);
  }
  return (
    <>
      <div className="core-image-grid">
        <div className="core-image-input">
          {tabs}
          <Panel title="이미지 주제 입력">
            <label>
              프롬프트
              <textarea
                aria-label="이미지 프롬프트"
                maxLength={4000}
                placeholder="만들고 싶은 이미지를 설명해 주세요."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </label>
            <div className="core-tags">
              {["여행", "일상", "판타지", "도시", "자연"].map((x) => (
                <button
                  key={x}
                  onClick={() => setPrompt((p) => `${p}${p ? ", " : ""}${x}`)}
                >
                  {x}
                </button>
              ))}
            </div>
          </Panel>
          <Panel title="스타일 선택">
            <div className="core-style-options">
              {styles.map((s, index) => {
                const Icon = [Box, Palette, Camera, Paintbrush, Brush, Pencil][
                  index
                ];
                return (
                  <button
                    key={s}
                    aria-pressed={style === s}
                    onClick={() => setStyle(style === s ? "" : s)}
                  >
                    <Icon size={26} />
                    {s}
                  </button>
                );
              })}
            </div>
          </Panel>
          <Panel title="모델 · 생성 설정">
            <Select
              label="이미지 모델"
              value={options.model}
              onChange={(v) => setOptions({ ...options, model: v })}
              options={c.view?.catalog.imageModels ?? []}
            />
            <div className="core-two-fields">
              <Select
                label="화면 비율 · 크기"
                value={options.size}
                onChange={(v) => setOptions({ ...options, size: v })}
                options={c.view?.catalog.sizes ?? {}}
              />
              <Select
                label="이미지 품질"
                value={options.quality}
                onChange={(v) => setOptions({ ...options, quality: v })}
                options={c.view?.catalog.qualities ?? {}}
              />
            </div>
            <div className="core-actions">
              <ActionButton
                c={c}
                id="creation_draft"
                context={context}
                disabled={!prompt.trim()}
                primary
              >
                <Save size={16} />
                초안 저장 · 참조 첨부
              </ActionButton>
              <ActionButton c={c} id="creation_defaults" context={options}>
                다음 작업 기본값 저장
              </ActionButton>
            </div>
            <p className="core-muted">
              참조 이미지를 첨부하면 이미지 편집 방식으로 요청합니다. 생성 전 키·실행 승인·비용 조건을 확인합니다.
            </p>
          </Panel>
        </div>
        <Panel
          title="생성 결과"
          className="core-image-result"
          tools={selected && <State value={selected.status} />}
        >
          <Media
            url={selected?.status === "success" ? selected.mediaUrl : null}
            kind="image"
            label="실제 생성 결과"
          />
          <div className="core-actions">
            {selected && (
              <>
                <ActionButton
                  c={c}
                  id="creation_generate"
                  context={{ identifier: selected.id }}
                  disabled={blocked}
                  primary
                >
                  <Sparkles size={16} />
                  생성 조건 확인
                </ActionButton>
                <ActionButton
                  c={c}
                  id="creation_reuse"
                  context={{ identifier: selected.id }}
                  disabled={
                    selected.status !== "success" ||
                    !safeMedia(selected.mediaUrl)
                  }
                >
                  검토 후 재사용
                </ActionButton>
              </>
            )}
            {safeMedia(selected?.mediaUrl) && (
              <a
                href={`${safeMedia(selected?.mediaUrl)}?download=true`}
                download
              >
                <Download size={15} />
                다운로드
              </a>
            )}
          </div>
          {selected && (
            <div className="core-saved-selection">
              <strong>{selected.title}</strong>
              <p>{selected.prompt}</p>
              <small>
                {selected.selection?.model} · {selected.selection?.size} ·{" "}
                {selected.selection?.quality}
              </small>
            </div>
          )}
          <p className="core-warning">
            {selected?.outputId != null
                ? "기존 생성 결과·실패·결과 불명 기록은 보존됩니다. 자동 재요청하지 않습니다."
                : "이미지 요금은 모델·크기·품질·사용량에 따라 달라집니다. 비용 확인 전에는 생성하지 않습니다."}
          </p>
        </Panel>
        <Panel title="생성 이력" className="core-image-history">
          {!drafts.length && <Empty>아직 저장한 생성 이력이 없습니다.</Empty>}
          <div className="core-history-grid">
            {drafts.map((x) => (
              <button
                key={x.id}
                aria-pressed={selected?.id === x.id}
                onClick={() => choose(x)}
              >
                {x.status === "success" && safeMedia(x.mediaUrl) ? (
                  <Media url={x.mediaUrl} kind="image" />
                ) : (
                  <Empty>저장 초안 · 결과 없음</Empty>
                )}
                <strong>{x.title}</strong>
                <State value={x.status} />
              </button>
            ))}
          </div>
        </Panel>
      </div>
      <Panel title="최근 생성 이미지" className="core-recent-panel">
        <div className="core-recent">
          {success.map((x) => (
            <button key={x.id} onClick={() => choose(x)}>
              <Media url={x.mediaUrl} kind="image" />
              <strong>{x.title}</strong>
            </button>
          ))}
          {!success.length && (
            <Empty>검증된 생성 성공 파일만 표시합니다.</Empty>
          )}
        </div>
      </Panel>
    </>
  );
}
