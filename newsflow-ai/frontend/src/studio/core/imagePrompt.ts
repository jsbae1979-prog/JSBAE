export function imagePrompt(prompt: string, style: string, textMode: string, text: string): string {
  const design = textMode === "auto"
    ? "주제에 어울리는 짧은 한국어 문구 한 개를 직접 만들고 이미지와 함께 디자인하세요. 읽기 쉬운 한글 타이포그래피, 충분한 여백, 배경과 대비되는 강조색을 사용하고 주요 피사체를 가리지 마세요. 문구는 간결하게, 근거 없는 사실·수치·인용은 추가하지 마세요."
    : textMode === "manual" ? `이미지에 넣을 문구(원문 유지): ${text.trim()}\n문구를 이미지와 조화롭게 디자인하세요. 읽기 쉬운 한글, 여백과 강조색을 사용하고 글자를 자르지 마세요.`
    : "이미지에 글자나 문구를 넣지 마세요.";
  return [prompt.trim(), style && `시각 스타일: ${style}`, design].filter(Boolean).join("\n");
}


// Read-only presentation: remove only the exact suffix produced by this app.
// Saved prompts and generated files remain unchanged; no model call is made.
export function imageDescription(value: string) {
  let request = value.trim();
  const auto = imagePrompt("", "", "auto", "");
  const none = imagePrompt("", "", "none", "");
  const manualEnding = "문구를 이미지와 조화롭게 디자인하세요. 읽기 쉬운 한글, 여백과 강조색을 사용하고 글자를 자르지 마세요.";
  let generatedSuffix = false;
  for (const suffix of [auto, none]) {
    if (request.endsWith("\n" + suffix)) {
      request = request.slice(0, -suffix.length).trimEnd(); generatedSuffix = true; break;
    }
  }
  if (!generatedSuffix && request.endsWith("\n" + manualEnding)) {
    const marker = request.lastIndexOf("\n이미지에 넣을 문구(원문 유지): ");
    if (marker >= 0) { request = request.slice(0, marker); generatedSuffix = true; }
  }
  let style = "";
  if (generatedSuffix) {
    const match = request.match(/\n시각 스타일: (3D 애니메이션|애니메이션|실사풍|일러스트|만화풍|스케치)$/u);
    if (match) { style = match[1]; request = request.slice(0, match.index).trimEnd(); }
  }
  const plain = request.replace(/\s+/gu, " ").trim();
  const brief = plain.match(/^(.+?)\s*[(（]([^()（）]+)[)）]$/u);
  const subject = brief ? brief[1].trim() : plain;
  const intent = brief ? brief[2].trim() : plain;
  const shorten = (text: string, limit: number) => {
    const chars = Array.from(text);
    return chars.length > limit ? chars.slice(0, limit).join("").trimEnd() + "…" : text;
  };
  return {
    title: shorten(subject, 64) || "AI 생성 이미지",
    description: intent ? `${shorten(intent, 130)}${style ? ` · ${style}` : ""}` : "",
    request,
  };
}
