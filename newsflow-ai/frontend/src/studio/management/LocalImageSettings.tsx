import { useEffect, useState } from "react";
import "./local-image-settings.css";

type DeliveryState = {
  available: boolean;
  enabled: boolean;
  active: boolean;
  port: number;
};

export default function LocalImageSettings({ data, busy, save }: {
  data: DeliveryState;
  busy: boolean;
  save: (path: string, values: Record<string, string>) => Promise<void>;
}) {
  const [port, setPort] = useState(String(data.port));
  useEffect(() => setPort(String(data.port)), [data.port]);
  const value = Number(port);
  const valid = Number.isInteger(value) && value >= 1024 && value <= 65535
    && ![8765, 18768].includes(value);
  const locked = busy || data.active;
  const status = data.active ? "전달 중" : !data.available ? "준비 필요"
    : data.enabled ? "사용 설정됨" : "꺼짐";
  const update = (enabled: boolean, selectedPort: number) =>
    void save("local-images", { enabled: String(enabled), port: String(selectedPort) });

  return (
    <section className="meta-local-delivery" aria-label="PC 이미지 전달">
      <header>
        <div><h3>PC 이미지 전달</h3><span className="meta-local-delivery__badge">시험 기능</span></div>
        <span className="meta-local-delivery__status" role="status" aria-live="polite">{status}</span>
      </header>
      <p>별도 저장소 계정 없이 이미지를 전달합니다.</p>
      <div className="meta-local-delivery__action">
        <span>{!data.available ? "전달 도구를 먼저 준비해 주세요."
          : data.active ? "완료될 때까지 앱을 켜 두세요."
          : "게시 화면에서 전송을 승인하면 연결됩니다."}</span>
        <button disabled={locked || (!data.available && !data.enabled)}
          aria-label={data.enabled ? "PC 이미지 전달 끄기" : "PC 이미지 전달 사용하기"}
          onClick={() => update(!data.enabled, data.port)}>
          {data.enabled ? "끄기" : "사용하기"}
        </button>
      </div>
      <details>
        <summary>연결 설정 · 안내</summary>
        <div className="meta-local-delivery__port">
          <label>이미지 전달 포트
            <input type="number" min={1024} max={65535} step={1} value={port}
              disabled={locked} onChange={(event) => setPort(event.target.value)} />
          </label>
          <button disabled={locked || !valid || value === data.port || (!data.available && data.enabled)}
            onClick={() => update(data.enabled, value)}>포트 저장</button>
        </div>
        {!valid && <p role="alert">1024~65535 중 8765·18768을 제외한 포트를 입력하세요.</p>}
        <ul>
          <li>Cloudflare 임시 연결을 사용합니다. 실제 Instagram 전송은 아직 미확인입니다.</li>
          <li>설정만으로 파일을 공개하지 않습니다. 전송 완료까지 PC와 앱을 켜 두세요.</li>
          <li>시험용 연결로 중단될 수 있습니다. 포트 충돌 시 자동 변경하지 않습니다.</li>
        </ul>
      </details>
    </section>
  );
}
