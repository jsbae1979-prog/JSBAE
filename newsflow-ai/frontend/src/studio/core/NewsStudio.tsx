import { useState } from "react";
import {NewsCollectionControls} from "./NewsCollectionControls";
import {NewsAnalysisControls} from "./NewsAnalysisControls";
import { Search, Sparkles, ArrowRight, ExternalLink, Newspaper } from "lucide-react";
import type { Item } from "../contracts";
import {
  Panel,
  Empty,
  ActionButton,
  Select,
  type Controller,
} from "./shared";
function ArticleImage({ item }: { item: Item }) {
  const src = typeof item.thumbnailUrl === "string" &&
    /^\/news\/[1-9]\d*\/thumbnail$/.test(item.thumbnailUrl)
    ? item.thumbnailUrl : null;
  return <ArticleImagePreview key={`${item.id}:${src ?? "missing"}`}
    src={src} publisher={String(item.publisher || "뉴스 출처")} />;
}
function ArticleImagePreview({ src, publisher }: { src: string | null; publisher: string }) {
  const [loaded, setLoaded] = useState(false), [failed, setFailed] = useState(false);
  return <div className="core-news-article-image">
    {src && !failed && <img src={src} alt={`${publisher} 제공 기사 이미지`}
      loading="lazy" decoding="async" className={loaded ? "loaded" : ""}
      onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />}
    {(!src || failed || !loaded) && <div className="core-news-source-fallback" role="status">
      <Newspaper size={30} aria-hidden="true" />
      <span>{publisher}</span>
      <small>{!src ? "출처 이미지 없음" : failed ? "이미지를 불러오지 못했습니다" : "기사 이미지 불러오는 중"}</small>
    </div>}
  </div>;
}
function publicLink(url: unknown) {
  try {
    const u = new URL(String(url));
    return ["https:", "http:"].includes(u.protocol) &&
      !u.username &&
      !u.password
      ? u.href
      : null;
  } catch {
    return null;
  }
}
export default function NewsStudio({
  c,
  onNavigate,
}: {
  c: Controller;
  onNavigate: (page: string) => void;
}) {
  const [query, setQuery] = useState(""),
    [category, setCategory] = useState(""),
    [id, setId] = useState<number | null>(null),
    [recent, setRecent] = useState<number[]>([]),
    [collectionMethod,setCollectionMethod]=useState("rss");
  const all = c.list("articles"),
    currentTop3 = (c.context?.top3 ?? []).filter((item: Item) =>
      item.articleIds.some((articleId: number) => all.some(article => article.id === articleId))),
    rows = all.filter(
      (x) =>
        (!category || x.category === category) &&
        `${x.title} ${x.publisher} ${x.summary ?? ""}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    ),
    selected = all.find((x) => x.id === id) ?? rows[0],
    ranked = currentTop3.find((x: Item) =>
      x.articleIds.includes(selected?.id),
    ),
    url = publicLink(selected?.url);
  function choose(x: Item) {
    setId(x.id);
    setRecent((xs) => [x.id, ...xs.filter((i) => i !== x.id)].slice(0, 8));
  }
  return (
    <>
      <div className="core-news-grid">
        <Panel title="보관 뉴스 · 검색" className="core-news-search">
          <label className="core-search">
            <Search size={16} />
            <input
              aria-label="보관 뉴스 검색"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="제목 · 출처 · 요약 검색"
            />
          </label>
          <Select
            label="기사 분야"
            value={category}
            onChange={setCategory}
            options={{
              "": "전체",
              ...Object.fromEntries(
                [...new Set(all.map((x) => x.category).filter(Boolean))].map(
                  (x) => [x, x],
                ),
              ),
            }}
          />
          <div className="core-news-list">
            {rows.map((x) => (
              <button
                key={x.id}
                aria-pressed={selected?.id === x.id}
                onClick={() => choose(x)}
              >
                <div className="core-news-list-picture">
                  <ArticleImage item={x} />
                  {currentTop3.some((r: Item) =>
                    r.articleIds.includes(x.id),
                  ) && (
                    <b>
                      TOP{" "}
                      {
                        currentTop3.find((r: Item) =>
                          r.articleIds.includes(x.id),
                        )?.rank
                      }
                    </b>
                  )}
                </div>
                <div>
                  <strong>{x.title}</strong>
                  <small>
                    {x.category} · {x.publisher}
                  </small>
                  {x.used === true && <span className="core-tag">영상 사용됨</span>}
                  <p>{x.summary}</p>
                </div>
              </button>
            ))}
            {!rows.length && (
              <Empty>검색 조건에 맞는 보관 기사가 없습니다.</Empty>
            )}
          </div>
          <NewsCollectionControls c={c} method={collectionMethod} onMethodChange={setCollectionMethod}/>
        </Panel>
        <div className="core-news-center">
          <Panel
            title="선택한 뉴스"
            tools={
              url && (
                <a href={url} target="_blank" rel="noreferrer">
                  <ExternalLink size={14} />
                  원문 보기
                </a>
              )
            }
          >
            {selected ? (
              <>
                <div className="core-article-head">
                  <ArticleImage item={selected} />
                  <div>
                    <h3>{selected.title}</h3>
                    <small>
                      {selected.publisher} · {selected.category}
                    </small>
                    <p>{selected.summary || "저장된 기사 요약이 없습니다."}</p>
                  </div>
                </div>
              </>
            ) : (
              <Empty>왼쪽에서 기사를 선택하세요.</Empty>
            )}
          </Panel>
          <Panel
            title="AI 뉴스 분석"
            tools={
              ranked && <span className="core-tag">TOP {ranked.rank}</span>
            }
          >
            <NewsAnalysisControls c={c} selected={selected} collectionMethod={collectionMethod}/>
            {ranked ? (
              <>
                <h3>핵심 요약</h3>
                <p className="core-analysis-summary">
                  {ranked.summary || "저장된 요약 필드 없음"}
                </p>
                <h3>핵심 키워드</h3>
                <p className="core-muted core-missing-keywords">
                  저장된 분석에 별도 키워드 필드가 없습니다.
                </p>
                <h3>선정 근거</h3>
                <p>{ranked.reason || "저장된 근거 필드 없음"}</p>
                <small>
                  분석 #{c.context?.selection?.id} ·{" "}
                  {c.context?.selection?.provider} ·{" "}
                  {c.context?.selection?.model}
                </small>
              </>
            ) : (
              <Empty>
                선택 기사에 연결된 완료 TOP 3 분석이 없습니다. 분석 결과를
                임의로 만들지 않습니다.
              </Empty>
            )}

          </Panel>
        </div>
        <div className="core-news-right">
          <Panel title="다음 제작으로 이동">
            <a
              className="core-destination primary"
              href={
                ranked ? `/studio/shorts?rank=${ranked.rank}` : "/studio/shorts"
              }
            >
              뉴스 쇼츠 제작실
              <ArrowRight size={18} />
            </a>
            <a className="core-destination" href="/studio/images?mode=top3">
              뉴스 TOP 3 이미지 제작
              <ArrowRight size={18} />
            </a>
            <button
              className="core-destination"
              onClick={() => onNavigate("characters")}
            >
              캐릭터 쇼츠 제작실
              <ArrowRight size={18} />
            </button>
            <p className="core-muted">
              제작실 이동은 저장된 분석을 재사용하며 자동 유료 생성하지
              않습니다.
            </p>
          </Panel>
          <Panel title="TOP 3 분석 결과">
            {c.context?.blockedReason && (
              <p className="core-warning">{c.context.blockedReason}</p>
            )}
            {currentTop3.map((x: Item) => (
              <button
                className="core-ranked-row"
                key={x.rank}
                onClick={() => {
                  const a = all.find((a) => a.id === x.articleId);
                  if (a) choose(a);
                }}
              >
                <b>{x.rank}</b>
                <span>{x.title}</span>
              </button>
            ))}
          </Panel>
          <Panel title="출처 · 검토">
            <p>{selected?.publisher ?? "기사 미선택"}</p>
            {url && (
              <a href={url} target="_blank" rel="noreferrer">
                원문 출처 확인
              </a>
            )}
            <p className="core-muted">
              추천·즐겨찾기·미지원 분석 탭은 추가하지 않습니다. 출처와 사용권
              검토는 제작 시 유지됩니다.
            </p>
          </Panel>
        </div>
      </div>
      <Panel title="최근 확인한 뉴스 · 이번 화면">
        <div className="core-recent">
          {recent
            .map((i) => all.find((a) => a.id === i))
            .filter(Boolean)
            .map((x) => (
              <button key={x!.id} onClick={() => choose(x!)}>
                <ArticleImage item={x!} />
                <strong>{x!.title}</strong>
              </button>
            ))}
          {!recent.length && (
            <Empty>기사를 선택하면 이번 화면의 확인 기록이 표시됩니다.</Empty>
          )}
        </div>
      </Panel>
    </>
  );
}
