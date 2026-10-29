import { useState } from "react";
import { Search, Grid2X2, List, Trash2, ArrowRight } from "lucide-react";
import { type Item, safeMedia } from "../contracts";
import {
  Panel,
  Empty,
  Badge,
  Thumb,
  Media,
  Action,
  DownloadLink,
  date,
  withinPeriod,
  type Controller,
} from "./shared";

export default function Library({ c }: { c: Controller }) {
  const [kind, setKind] = useState("all"),
    [query, setQuery] = useState(""),
    [days, setDays] = useState("all"),
    [chosen, setChosen] = useState(""),
    [sort, setSort] = useState("new"),
    [list, setList] = useState(false);
  const references = c.view?.collections.ownedReferences ?? [];
  const own = (c.view?.projects ?? c.workspace?.projects ?? []).map(
    (x: Item) => ({ ...x, key: "own-" + x.id }),
  );
  const combined: Item[] = [
    ...own,
    ...references.map((x: Item) => ({ ...x, key: "reference-" + x.id })),
  ];
  const rows = combined
    .filter(
      (x) =>
        (kind === "all" || x.kind === kind) &&
        String(x.title).toLowerCase().includes(query.toLowerCase()) &&
        (days === "all" || withinPeriod(x.updatedAt, days)),
    )
    .sort((a, b) =>
      sort === "title"
        ? a.title.localeCompare(b.title)
        : String(b.updatedAt ?? "").localeCompare(a.updatedAt ?? ""),
    );
  const selected = rows.find((x) => x.key === chosen) ?? rows[0];
  const destination =
    selected?.kind === "news"
      ? "shorts"
      : selected?.kind === "character"
        ? "characters"
        : "images";
  return (
    <>
      <div className="mg-library-grid">
        <aside>
          <Panel title="콘텐츠 유형">
            <div className="mg-type-menu">
              {[
                ["all", "전체"],
                ["news", "뉴스 쇼츠"],
                ["character", "캐릭터 쇼츠"],
                ["image", "이미지"],
                ...(references.some((x: Item) => x.kind === "reference")
                  ? [["reference", "참조 영상"]]
                  : []),
              ].map(([v, t]) => (
                <button
                  key={v}
                  aria-pressed={kind === v}
                  onClick={() => setKind(v)}
                >
                  {t}
                  <span>
                    {combined.filter((x) => v === "all" || x.kind === v).length}
                  </span>
                </button>
              ))}
            </div>
          </Panel>
          <Panel title="검색">
            <label className="mg-search">
              <input
                aria-label="라이브러리 검색"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="제목, 키워드를 검색하세요"
              />
              <Search size={17} />
            </label>
          </Panel>
          <Panel title="기간 필터">
            <div className="mg-type-menu">
              {[
                ["all", "전체 기간"],
                ["1", "오늘"],
                ["7", "최근 7일"],
                ["30", "최근 30일"],
              ].map(([v, t]) => (
                <button
                  key={v}
                  aria-pressed={days === v}
                  onClick={() => setDays(v)}
                >
                  {t}
                </button>
              ))}
            </div>
          </Panel>
        </aside>
        <Panel
          title="콘텐츠 목록"
          className="mg-library-content"
          tools={<span className="mg-badge">{rows.length}개</span>}
        >
          <div className="mg-toolbar">
            <span className="mg-badge">내 콘텐츠</span>
            <select
              aria-label="콘텐츠 정렬"
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              <option value="new">저장일 최신순</option>
              <option value="title">제목순</option>
            </select>
            <button
              aria-label="카드 보기"
              aria-pressed={!list}
              onClick={() => setList(false)}
            >
              <Grid2X2 size={16} />
            </button>
            <button
              aria-label="목록 보기"
              aria-pressed={list}
              onClick={() => setList(true)}
            >
              <List size={16} />
            </button>
          </div>
          <div className={"mg-library-cards " + (list ? "list" : "")}>
            {rows.map((x) => (
              <button
                key={x.key}
                className="mg-content-card"
                aria-pressed={selected?.key === x.key}
                onClick={() => setChosen(x.key)}
                data-content-id={x.key}
              >
                <Thumb item={x} />
                <div>
                  <span className="mg-badge">
                    {x.referenceOnly
                      ? "참조 파일"
                      : x.kind === "image"
                        ? "이미지"
                        : x.kind === "news"
                          ? "뉴스 쇼츠"
                          : "캐릭터 쇼츠"}
                  </span>
                  <strong>{x.title}</strong>
                  <small>{date(x.updatedAt)}</small>
                  <Badge value={x.technicalStatus} />
                </div>
              </button>
            ))}
          </div>
          {!rows.length && <Empty>조건에 맞는 콘텐츠가 없습니다.</Empty>}
        </Panel>
        <Panel title="콘텐츠 미리보기" className="mg-library-detail">
          {selected ? (
            <>
              <Media
                url={selected.mediaUrl}
                image={selected.kind === "image"}
              />
              <h3>{selected.title}</h3>
              <dl>
                <dt>구분</dt>
                <dd>{selected.sourceLabel}</dd>
                <dt>상태</dt>
                <dd>
                  <Badge value={selected.technicalStatus} />
                </dd>
              </dl>
              {selected.referenceOnly ? (
                <p className="mg-muted">
                  사용자가 보관한 참조 파일입니다. 편집 가능한 원본 제작
                  프로젝트나 생성 완료 이력으로 취급하지 않습니다.
                </p>
              ) : (
                <>
                  <a
                    className="mg-button mg-primary"
                    href={
                      String(selected.id).startsWith("post:")
                        ? "/image-posts?post_id=" +
                          String(selected.id).split(":")[1]
                        : "/studio/" +
                          destination +
                          (selected.kind === "news" && selected.draftId
                            ? "?draft_id=" + selected.draftId
                            : selected.kind === "image"
                              ? "?draft_id=" + String(selected.id).split(":")[1]
                              : selected.kind === "character"
                                ? "?job_id=" + String(selected.id).split(":")[1]
                                : "")
                    }
                  >
                    제작실로 이동
                    <ArrowRight size={16} />
                  </a>
                  {String(selected.id).startsWith("image:") &&
                    safeMedia(selected.mediaUrl) && (
                      <Action
                        c={c}
                        id="creation_reuse"
                        context={{
                          identifier: String(selected.id).split(":")[1],
                        }}
                      >
                        검토 후 재사용
                      </Action>
                    )}
                  {selected.kind !== "news" &&
                    !String(selected.id).startsWith("post:") && (
                      <a
                        className="mg-button"
                        href={
                          selected.kind === "character"
                            ? "/character?job_id=" +
                              encodeURIComponent(
                                String(selected.id).split(":")[1],
                              )
                            : "/image-studio?draft_id=" +
                              Number(String(selected.id).split(":")[1])
                        }
                      >
                        선택한 원본 작업 상세
                      </a>
                    )}
                  {selected.kind === "news" && (
                    <Action
                      c={c}
                      id="cleanup_remove_video"
                      context={{
                        identifier: String(selected.id).split(":")[1],
                      }}
                    >
                      <Trash2 size={16} />
                      휴지 보관
                    </Action>
                  )}
                </>
              )}
              <DownloadLink url={selected.mediaUrl} />
            </>
          ) : (
            <Empty>콘텐츠를 선택하세요.</Empty>
          )}
        </Panel>
      </div>
      <details className="mg-advanced">
        <summary>휴지 보관 · {c.list("removed").length}개</summary>
        {c.list("removed").map((x) => (
          <div className="mg-record" key={x.key}>
            <strong>{x.key}</strong>
            <small>{date(x.created_at)}</small>
            <Action c={c} id="cleanup_restore" context={{ item: x.key }}>
              복원 검토
            </Action>
          </div>
        ))}
      </details>
    </>
  );
}
