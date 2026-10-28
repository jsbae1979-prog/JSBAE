import { useEffect, useState } from "react";
import type { Item } from "../contracts";
import type { SampleUse } from "../SampleGallery";
import { Thumbnail } from "../Thumbnail";
// Compact reference picker; copy/visibility storage and the full sample gallery remain unchanged.
export default function CharacterReferenceSamples({
  csrf,
  busy,
  onBusy,
  onUse,
}: {
  csrf: string;
  busy: boolean;
  onBusy: (value: boolean) => void;
  onUse: (value: SampleUse) => Promise<void>;
}) {
  const [rows, setRows] = useState<Item[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    fetch("/api/samples", { credentials: "same-origin", cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw Error();
        const x = await r.json();
        if (x.schemaVersion !== 1 || !Array.isArray(x.assets)) throw Error();
        if (active)
          setRows(
            x.assets.filter(
              (a: Item) =>
                a.type === "character" &&
                !a.hidden &&
                /^[a-z0-9-]+$/.test(a.id) &&
                a.mediaUrl === `/api/samples/${a.id}/file`,
            ),
          );
      })
      .catch(() => {
        if (active)
          setError(
            "샘플 참조를 읽지 못했습니다. PNG 업로드는 계속 사용할 수 있습니다.",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  async function select(asset: Item) {
    if (busy) return;
    onBusy(true);
    setError("");
    try {
      const r = await fetch(`/api/samples/${asset.id}/copy`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ csrf_token: csrf, use: "true" }),
      });
      if (!r.ok) throw Error();
      const copy = await r.json();
      await onUse({ asset, copy });
    } catch {
      setError("참조 복사 실패 · 자동 재요청하지 않습니다.");
    } finally {
      onBusy(false);
    }
  }
  return (
    <div className="core-character-samples" aria-label="기본 캐릭터 샘플">
      <h3>
        샘플 캐릭터 <small>새 작업 참조용</small>
      </h3>
      <div>
        {rows.map((a) => (
          <article key={a.id} data-sample-id={a.id}>
            <Thumbnail src={a.mediaUrl} alt={`${a.title} 샘플`} />
            <strong>{a.title}</strong>
            <button
              aria-label="참조 PNG로 선택"
              disabled={busy || !csrf}
              onClick={() => void select(a)}
            >
              선택
            </button>
          </article>
        ))}
      </div>
      {!rows.length && !error && (
        <p className="core-muted">
          표시할 샘플이 없습니다. 아래 샘플 관리에서 숨김 상태를 확인하세요.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      <small>
        샘플 선택은 유료 생성을 실행하지 않습니다. 복사·숨김·사용권 안내는 아래
        샘플 갤러리에서 확인하세요.
      </small>
    </div>
  );
}
