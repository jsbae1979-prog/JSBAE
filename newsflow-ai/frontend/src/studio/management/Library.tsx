import { useEffect, useRef, useState } from "react";
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
    [list, setList] = useState(false),
    [checked, setChecked] = useState<string[]>([]),
    [pendingDelete, setPendingDelete] = useState<Item[] | null>(null),
    [busy, setBusy] = useState(false),
    [mutationError, setMutationError] = useState(""),
    [deleteError, setDeleteError] = useState(""),
    [notice, setNotice] = useState(""),
    [localRemoved, setLocalRemoved] = useState<Item[]>([]),
    [localRestored, setLocalRestored] = useState<string[]>([]);
  const requestInFlight = useRef(false),
    deleteDialog = useRef<HTMLDialogElement>(null),
    cancelDelete = useRef<HTMLButtonElement>(null);
  const removalAvailable = c.view?.libraryRemovalAvailable === true && c.view.commandsAvailable && !!c.view.csrfToken;
  const canonicalId = (x: Item) => String(x.id ?? "");
  const removable = (x: Item) => /^(?:(?:news|image|post):[1-9][0-9]*|character:[a-f0-9]{32}|reference:[a-z0-9-]{1,48})$/.test(canonicalId(x));
  const locallyHidden = new Set(localRemoved.map(canonicalId));
  const references = c.view?.collections.ownedReferences ?? [];
  const own = (c.view?.projects ?? c.workspace?.projects ?? []).map(
    (x: Item) => ({ ...x, key: "own-" + x.id }),
  );
  const combined: Item[] = [
    ...own,
    ...references.map((x: Item) => ({ ...x, key: "reference-" + x.id })),
  ].filter((x) => !locallyHidden.has(canonicalId(x)));
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
  const eligible = rows.filter(removable);
  const selectedRows = eligible.filter((x) => checked.includes(x.key));
  const visibleKeys = eligible.map((x) => x.key).join("\n");
  useEffect(() => {
    const visible = new Set(visibleKeys.split("\n"));
    setChecked((previous) => {
      const next = previous.filter((key) => visible.has(key));
      return next.length === previous.length ? previous : next;
    });
  }, [visibleKeys]);
  useEffect(() => {
    const dialog = deleteDialog.current;
    if (pendingDelete && dialog && !dialog.open) {
      dialog.showModal();
      cancelDelete.current?.focus();
    } else if (!pendingDelete && dialog?.open) dialog.close();
  }, [pendingDelete]);
  useEffect(() => {
    if (!c.view) return;
    const serverTrash = new Set((c.view.collections.libraryRemoved ?? []).map((x: Item) => String(x.id)));
    // Keep confirmed mutations visible when refresh fails; discard the overlay
    // once a new server view acknowledges it, so a later external restore wins.
    setLocalRemoved((previous) => previous.filter((x) => !serverTrash.has(String(x.id))));
    setLocalRestored((previous) => previous.filter((id) => serverTrash.has(id)));
  }, [c.view]);
  const libraryTrash = Array.from(new Map([
    ...(c.view?.collections.libraryRemoved ?? []), ...localRemoved,
  ].map((x: Item) => [canonicalId(x), x])).values())
    .filter((x) => !localRestored.includes(canonicalId(x)));
  const closeDelete = () => {
    if (!requestInFlight.current) { setPendingDelete(null); setDeleteError(""); }
  };
  const askDelete = (items: Item[]) => {
    if (!removalAvailable || requestInFlight.current || !items.length || items.length > 100) return;
    setMutationError(""); setNotice(""); setDeleteError("");
    setPendingDelete(items.map((x) => ({ ...x })));
  };
  const mutateLibrary = async (action: "remove" | "restore", items: Item[]) => {
    if (!removalAvailable || requestInFlight.current || !items.length || items.length > 100) return;
    const ids = items.map(canonicalId);
    if (new Set(ids).size !== ids.length || !items.every(removable)) return;
    requestInFlight.current = true;
    setBusy(true); setMutationError(""); setDeleteError(""); setNotice("");
    try {
      const response = await fetch(`/api/studio/library/${action}`, {
        method: "POST", credentials: "same-origin",
        body: new URLSearchParams({ items: JSON.stringify(ids), confirm: "true", csrf_token: c.view?.csrfToken ?? "" }),
      });
      if (!response.ok) {
        throw Error(response.status === 409
          ? "진행 중이거나 상태가 변경된 항목이 있습니다. 목록을 새로고침해 확인하세요."
          : "요청을 완료하지 못했습니다. 목록을 새로고침해 저장 상태를 확인하세요.");
      }
      const result = await response.json();
      const accepted: unknown = result[action === "remove" ? "removed" : "restored"];
      if (!Array.isArray(accepted) || accepted.length !== ids.length ||
        new Set(accepted).size !== ids.length || !accepted.every((id) => typeof id === "string" && ids.includes(id)))
        throw Error("처리 결과를 확인하지 못했습니다. 다시 요청하기 전에 목록을 새로고침하세요.");
      if (action === "remove") {
        setLocalRemoved((previous) => [...previous.filter((x) => !ids.includes(canonicalId(x))), ...items.map((x) => ({ ...x, updatedAt: new Date().toISOString(), technicalStatus: "hidden" }))]);
        setLocalRestored((previous) => previous.filter((id) => !ids.includes(id)));
        setChecked((previous) => previous.filter((key) => !items.some((x) => x.key === key)));
        if (items.some((x) => x.key === chosen)) setChosen("");
        setPendingDelete(null);
        setNotice(`${ids.length}개를 라이브러리 휴지통으로 옮겼습니다.`);
      } else {
        setLocalRemoved((previous) => previous.filter((x) => !ids.includes(canonicalId(x))));
        setLocalRestored((previous) => [...new Set([...previous, ...ids])]);
        setNotice(`${ids.length}개를 라이브러리에 복원했습니다.`);
      }
      await c.load();
    } catch (error) {
      const message = error instanceof Error && /^(진행 중이거나|요청을 완료|처리 결과)/.test(error.message)
        ? error.message : "처리 결과를 확인하지 못했습니다. 다시 요청하기 전에 목록을 새로고침하세요.";
      if (action === "remove") setDeleteError(message);
      else setMutationError(message);
    } finally { requestInFlight.current = false; setBusy(false); }
  };
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
                  onClick={() => { setKind(v); setChecked([]); }}
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
                onChange={(e) => { setQuery(e.target.value); setChecked([]); }}
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
                  onClick={() => { setDays(v); setChecked([]); }}
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
          <div className="mg-library-selection" aria-label="콘텐츠 선택">
            <strong>선택 {selectedRows.length}개</strong>
            <button disabled={!removalAvailable || busy || !eligible.length} onClick={() => {
              if (eligible.length > 100) { setMutationError("한 번에 100개까지 선택할 수 있습니다. 검색이나 필터로 범위를 좁혀 주세요."); return; }
              setMutationError(""); setChecked(eligible.map((x) => x.key));
            }}>표시 항목 전체 선택</button>
            <button disabled={busy || !selectedRows.length} onClick={() => setChecked([])}>선택 해제</button>
            <button disabled={!removalAvailable || busy || !selectedRows.length} onClick={() => askDelete(selectedRows)}><Trash2 size={15} />선택 삭제</button>
          </div>
          {mutationError && <p className="mg-alert" role="alert">{mutationError}</p>}
          {notice && <p className="mg-muted" role="status">{notice}</p>}
          <div className={"mg-library-cards " + (list ? "list" : "")}>
            {rows.map((x) => (
              <div className="mg-library-card-wrap" key={x.key}>
              <input type="checkbox" className="mg-library-check" aria-label={`${x.title} 선택`}
                checked={checked.includes(x.key)} disabled={!removalAvailable || busy || !removable(x)}
                onChange={(event) => {
                  const isChecked = event.target.checked;
                  if (isChecked && selectedRows.length >= 100) { setMutationError("한 번에 100개까지 선택할 수 있습니다."); return; }
                  setChecked((previous) => isChecked ? [...previous, x.key] : previous.filter((key) => key !== x.key));
                }} />
              <button
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
              </div>
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
                    <details className="mg-advanced mg-library-file-cleanup">
                      <summary>영상 파일 보관 관리</summary>
                    <Action
                      c={c}
                      id="cleanup_remove_video"
                      context={{
                        identifier: String(selected.id).split(":")[1],
                      }}
                    >
                      <Trash2 size={16} />
                      영상 파일 휴지 보관
                    </Action>
                    </details>
                  )}
                </>
              )}
              <DownloadLink url={selected.mediaUrl} />
              <button disabled={!removalAvailable || busy || !removable(selected)} onClick={() => askDelete([selected])}>
                <Trash2 size={16} />이 콘텐츠 삭제
              </button>
            </>
          ) : (
            <Empty>콘텐츠를 선택하세요.</Empty>
          )}
        </Panel>
      </div>
      <details className="mg-advanced mg-library-trash">
        <summary>라이브러리 휴지통 · {libraryTrash.length}개</summary>
        <p className="mg-muted">원본 파일과 제작 작업·이력은 보존됩니다.</p>
        {libraryTrash.map((x) => <div className="mg-record" key={canonicalId(x)}>
          <strong>{x.title}</strong><small>{date(x.updatedAt)}</small>
          <button aria-label={`${x.title} 복원`} disabled={!removalAvailable || busy || !removable(x)} onClick={() => void mutateLibrary("restore", [x])}>복원</button>
        </div>)}
        {!libraryTrash.length && <Empty>휴지통이 비어 있습니다.</Empty>}
      </details>
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
      <dialog className="mg-library-delete-dialog" ref={deleteDialog} aria-labelledby="library-delete-title"
        onCancel={(event) => { event.preventDefault(); closeDelete(); }} onClose={() => { if (!requestInFlight.current) setPendingDelete(null); }}>
        <h2 id="library-delete-title">라이브러리에서 삭제</h2>
        <p>라이브러리 휴지통으로 옮깁니다. 원본 파일과 제작 작업·이력은 보존되며 복원할 수 있습니다.</p>
        <strong>선택한 콘텐츠 {pendingDelete?.length ?? 0}개</strong>
        <ul>{pendingDelete?.map((x) => <li key={canonicalId(x)}>{x.title}</li>)}</ul>
        {deleteError && <p className="mg-alert" role="alert">{deleteError}</p>}
        <div className="mg-library-dialog-actions">
          <button ref={cancelDelete} disabled={busy} onClick={closeDelete}>취소</button>
          <button className="mg-primary" disabled={busy || !removalAvailable || !pendingDelete?.length} onClick={() => pendingDelete && void mutateLibrary("remove", pendingDelete)}>{busy ? "처리 중…" : "휴지통으로 이동"}</button>
        </div>
      </dialog>
    </>
  );
}
