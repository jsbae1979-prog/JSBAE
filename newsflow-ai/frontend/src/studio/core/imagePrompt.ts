export function imagePrompt(prompt: string, style: string, textMode: string, text: string): string {
  const design = textMode === "auto"
    ? "주제에 어울리는 짧은 한국어 문구 한 개를 직접 만들고 이미지와 함께 디자인하세요. 읽기 쉬운 한글 타이포그래피, 충분한 여백, 배경과 대비되는 강조색을 사용하고 주요 피사체를 가리지 마세요. 문구는 간결하게, 근거 없는 사실·수치·인용은 추가하지 마세요."
    : textMode === "manual" ? `이미지에 넣을 문구(원문 유지): ${text.trim()}\n문구를 이미지와 조화롭게 디자인하세요. 읽기 쉬운 한글, 여백과 강조색을 사용하고 글자를 자르지 마세요.`
    : "이미지에 글자나 문구를 넣지 마세요.";
  return [prompt.trim(), style && `시각 스타일: ${style}`, design].filter(Boolean).join("\n");
}
