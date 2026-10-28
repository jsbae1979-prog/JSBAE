import { useState } from "react";
import { CalendarPlus, Play, BookOpen, Search, Clock3 } from "lucide-react";
import { type Item, itemTitle, label } from "../contracts";
import { Panel, Empty, Badge, Action, date, type Controller } from "./shared";
export default function Automation({
  c,
  onNavigate,
}: {
  c: Controller;
  onNavigate: (p: string) => void;
}) {
  const [id, setId] = useState(""),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all");
  const rows = c.list("schedules"),
    selected = rows.find((x) => String(x.id) === id) ?? rows[0],
    runs = c.list("runs"),
    jobs = c.list("jobs");
  const counts = [
    ["저장된 예약", rows.length],
    ["활성 예약", rows.filter((x) => x.status === "active").length],
    ["확인 필요", runs.filter((x) => /unknown|fail/.test(x.status)).length],
  ];
  return (
    <>
      <div className="mg-shortcuts">
        <Action c={c} id="autopilot_quick_start" primary>
          <Play />
          자동 제작 빠른 시작<span>범위를 확인한 뒤 별도 승인</span>
        </Action>
        <Action c={c} id="scheduler_save">
          <CalendarPlus />새 예약 만들기<span>저장과 활성화는 별도</span>
        </Action>
        <button onClick={() => onNavigate("settings")}>
          <Clock3 />
          자동화 설정<span>기존 실행 정책 확인</span>
        </button>
        <button onClick={() => onNavigate("onboarding")}>
          <BookOpen />
          운영 가이드<span>시작 가이드 열기</span>
        </button>
      </div>
      <div className="mg-automation-grid">
        <aside>
          <Panel title="제작 유형">
            <div className="mg-type-menu">
              <button
                aria-pressed={filter === "all"}
                onClick={() => setFilter("all")}
              >
                전체 예약
              </button>
              <button
                aria-pressed={filter === "news"}
                onClick={() => setFilter("news")}
              >
                뉴스 쇼츠 · 기존 예약
              </button>
            </div>
            <p className="mg-muted">
              현재 예약 서비스가 지원하는 제작만 표시합니다. 캐릭터·이미지·TOP 3
              무인 유료 예약은 추가하지 않았습니다.
            </p>
          </Panel>
          <Panel title="자동화 현황">
            <div className="mg-mini-stats">
              {counts.map(([t, n]) => (
                <div key={t}>
                  <small>{t}</small>
                  <strong>{n}</strong>
                </div>
              ))}
            </div>
          </Panel>
        </aside>
        <Panel
          title="제작 예약 목록"
          className="mg-schedules"
          tools={<span className="mg-badge">{rows.length}개</span>}
        >
          <label className="mg-search">
            <Search size={16} />
            <input
              aria-label="예약 검색"
              placeholder="제목 또는 주제를 검색하세요"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="mg-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>상태</th>
                  <th>제목 / 주제</th>
                  <th>제작 유형</th>
                  <th>주기 · 시간</th>
                  <th>다음 실행</th>
                </tr>
              </thead>
              <tbody>
                {rows
                  .filter((x) =>
                    x.name.toLowerCase().includes(query.toLowerCase()),
                  )
                  .map((x) => (
                    <tr
                      key={x.id}
                      className={selected?.id === x.id ? "selected" : ""}
                    >
                      <td>
                        <Badge value={x.status} />
                      </td>
                      <td>
                        <button
                          className="mg-table-select"
                          aria-pressed={selected?.id === x.id}
                          onClick={() => setId(String(x.id))}
                        >
                          {x.name}
                        </button>
                      </td>
                      <td>뉴스 쇼츠</td>
                      <td>
                        {label(x.kind)}
                        <small>{x.local_time}</small>
                      </td>
                      <td>{date(x.next_run_at)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {!rows.length && <Empty>저장된 제작 예약이 없습니다.</Empty>}
          <p className="mg-muted">
            예약을 선택하여 저장된 Revision과 실행 상태를 확인하세요.
          </p>
        </Panel>
        <Panel
          title="예약 상세 설정"
          className="mg-schedule-detail"
          tools={
            <Action
              c={c}
              id="scheduler_save"
              context={
                selected ? { ...selected, schedule_id: selected.id } : {}
              }
              disabled={!selected}
              primary
            >
              편집 · 저장
            </Action>
          }
        >
          {selected ? (
            <>
              <label>
                제목
                <input value={selected.name} readOnly />
              </label>
              <dl>
                <dt>주기</dt>
                <dd>{label(selected.kind)}</dd>
                <dt>실행 시간</dt>
                <dd>{selected.local_time}</dd>
                <dt>요일</dt>
                <dd>{selected.weekdays?.join(", ") || "설정 없음"}</dd>
                <dt>상태</dt>
                <dd>
                  <Badge value={selected.status} />
                </dd>
                <dt>Revision</dt>
                <dd>{selected.revision}</dd>
              </dl>
              <div className="mg-next">
                <Clock3 />
                <span>
                  {selected.status === "active"
                    ? "다음 실행 예정"
                    : "저장된 실행 시각 · 일시 정지"}
                  <strong>{date(selected.next_run_at)}</strong>
                </span>
              </div>
              <Action
                c={c}
                id="scheduler_state"
                context={{
                  schedule_id: selected.id,
                  revision: selected.revision,
                }}
              >
                활성화 · 정지 검토
              </Action>
              <p className="mg-muted">
                편집 창에서 저장합니다. 저장만으로 예약을 활성화하지 않습니다.
              </p>
            </>
          ) : (
            <Empty>예약 선택 대기</Empty>
          )}
          <p className="mg-warning">
            결과 불명 작업은 자동 재요청하지 않습니다.
          </p>
        </Panel>
      </div>
      <Panel title="예약 실행 기록" className="mg-run-history">
        <div className="mg-table-scroll">
          <table>
            <thead>
              <tr>
                <th>실행 시간</th>
                <th>예약</th>
                <th>상태</th>
                <th>결과 요약</th>
                <th>검토</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((x) => (
                <tr key={x.id}>
                  <td>{date(x.created_at)}</td>
                  <td>
                    {rows.find((s) => s.id === x.schedule_id)?.name ??
                      x.schedule_id}
                  </td>
                  <td>
                    <Badge value={x.status} />
                  </td>
                  <td>{x.message || "기록 없음"}</td>
                  <td>
                    <Action
                      c={c}
                      id="scheduler_command_cancel"
                      context={{ run_id: x.id, revision: x.revision }}
                    >
                      취소 검토
                    </Action>
                    <Action
                      c={c}
                      id="scheduler_command_retry"
                      disabled={/unknown|running/.test(x.status)}
                      context={{ run_id: x.id, revision: x.revision }}
                    >
                      재시도 검토
                    </Action>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!runs.length && (
          <Empty>예약 실행 기록 없음 · 자동 실행하지 않습니다.</Empty>
        )}
      </Panel>
      <details className="mg-advanced">
        <summary>자동 제작 작업 기록 · {jobs.length}개</summary>
        {jobs.map((x: Item) => (
          <div className="mg-record" key={x.id}>
            <strong>{itemTitle(x)}</strong>
            <Badge value={x.status} />
            <p>{x.message}</p>
            <Action
              c={c}
              id="autopilot_cancel"
              context={{ job_id: x.id, revision: x.revision }}
            >
              취소 검토
            </Action>
            <Action
              c={c}
              id="autopilot_resume"
              context={{ job_id: x.id, revision: x.revision }}
              disabled={/unknown/.test(x.status)}
            >
              재개 검토
            </Action>
          </div>
        ))}
      </details>
    </>
  );
}
