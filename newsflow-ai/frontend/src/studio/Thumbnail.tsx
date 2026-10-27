import { useState } from "react";
import { Film } from "lucide-react";

/** Presentation only. Never substitutes artwork for a missing media file. */
export function Thumbnail({
  src,
  alt,
  kind = "",
  eager = false,
}: {
  src: string | null;
  alt: string;
  kind?: string;
  eager?: boolean;
}) {
  return (
    <ThumbnailImage
      key={src ?? "missing"}
      src={src}
      alt={alt}
      kind={kind}
      eager={eager}
    />
  );
}
function ThumbnailImage({
  src,
  alt,
  kind,
  eager,
}: {
  src: string | null;
  alt: string;
  kind: string;
  eager: boolean;
}) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <>
      {src && !failed && (
        <img
          className={`asset-thumb-img ${loaded ? "loaded" : ""}`}
          src={src}
          alt={alt}
          loading={eager ? "eager" : "lazy"}
          decoding="async"
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
        />
      )}
      {(!src || failed || !loaded) && (
        <div className={`project-placeholder ${kind}`} role="status">
          <Film size={26} />
          <span>
            {src && !failed ? "미리보기 불러오는 중" : "미리보기 없음"}
          </span>
        </div>
      )}
    </>
  );
}
