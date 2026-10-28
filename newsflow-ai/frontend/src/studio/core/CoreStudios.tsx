import { useState } from "react";
import { useStudio, StudioFrame, ImageTabs } from "./shared";
import NewsShortsStudio from "./NewsShortsStudio";
import CharacterStudio from "./CharacterStudio";
import ImageStudio from "./ImageStudio";
import TopThreeImageStudio from "./TopThreeImageStudio";
import NewsStudio from "./NewsStudio";
import "./core-studios.css";

export default function CoreStudios({
  module,
  onNavigate,
}: {
  module: string;
  onNavigate: (page: string) => void;
}) {
  const c = useStudio(module),
    [imageMode, setImageMode] = useState(() =>
      new URLSearchParams(location.search).get("mode") === "top3"
        ? "top3"
        : "standalone",
    );
  const titles: Record<string, string> = {
    shorts: "뉴스 쇼츠 제작실",
    characters: "캐릭터 쇼츠 제작실",
    images: "이미지 제작실",
    news: "뉴스 스튜디오",
  };
  return (
    <StudioFrame
      c={c}
      module={module}
      imageMode={imageMode}
      onNavigate={onNavigate}
      title={titles[module]}
      subtitle={
        module === "shorts"
          ? "분석된 뉴스로 만드는 나만의 쇼츠"
          : module === "characters"
            ? "캐릭터와 스토리로 완성하는 짧은 이야기"
            : module === "images"
              ? "아이디어와 뉴스를 이미지로 만드세요"
              : "뉴스를 모으고, 분석하고, 제작으로 이어갑니다"
      }
    >
      {module === "shorts" ? (
        <NewsShortsStudio c={c} onNavigate={onNavigate} />
      ) : module === "characters" ? (
        <CharacterStudio c={c} />
      ) : module === "news" ? (
        <NewsStudio c={c} onNavigate={onNavigate} />
      ) : (
        <>
          {imageMode === "top3" ? (
            <TopThreeImageStudio
              c={c}
              tabs={<ImageTabs mode={imageMode} onChange={setImageMode} />}
            />
          ) : (
            <ImageStudio
              c={c}
              tabs={<ImageTabs mode={imageMode} onChange={setImageMode} />}
            />
          )}
        </>
      )}
    </StudioFrame>
  );
}
