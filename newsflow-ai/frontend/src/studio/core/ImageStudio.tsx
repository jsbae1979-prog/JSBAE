import { useEffect, useState } from "react";
import SampleGallery from "../SampleGallery";
import { Sparkles, Save, Download } from "lucide-react";
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
export default function ImageStudio({ c }: { c: Controller }) {
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
    blocked = !!selected?.reference || selected?.outputId != null;
  function choose(x: Item) {
    setId(x.id);
  }
  return (
    <>
      <SampleGallery
        types={["standalone"]}
        csrf={c.view?.csrfToken ?? ""}
        onUse={({ copy }) => {
          setPrompt(copy.promptExample);
          setId(null);
          c.setNotice(
            "샘플 프롬프트 예제를 입력했습니다. 초안 저장 후 별도 승인해야 생성됩니다.",
          );
        }}
      />
      <div className="core-image-grid">
        <div className="core-image-input">
          <Panel title="이미지 주제 입력">
            <label>
              프롬프트
              <textarea
                aria-label="이미지 프롬프트"
                maxLength={8000}
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
              {styles.map((s) => (
                <button
                  key={s}
                  aria-pressed={style === s}
                  onClick={() => setStyle(style === s ? "" : s)}
                >
                  <Sparkles size={21} />
                  {s}
                </button>
              ))}
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
              참조 PNG는 초안 창에서 첨부·보관할 수 있습니다. 참조 기반 유료
              이미지 편집 생성은 미구현입니다.
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
                  견적 · 생성 승인
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
            {selected?.reference
              ? "참조 기반 유료 편집 생성은 미구현 · 로컬 보관만 지원"
              : selected?.outputId != null
                ? "기존 생성 결과·실패·결과 불명 기록은 보존됩니다. 자동 재요청하지 않습니다."
                : "공식 견적을 확인한 후 승인합니다. 미확정 비용은 0원으로 표시하지 않습니다."}
          </p>
        </Panel>
        <Panel title="생성 이력" className="core-image-history">
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
      <Panel title="최근 생성 이미지">
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
