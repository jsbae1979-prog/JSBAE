import definitions from "../legacy-actions.json";
export type Item = Record<string, any>;
export type View = {
  schemaVersion: number;
  module: string;
  dataOrigin: string;
  csrfToken: string;
  commandsAvailable: boolean;
  collections: Record<string, Item[]>;
  catalog: Item;
  projects?: Item[];
  services?: Item[];
  settings?: Record<string, string>;
  policy?: Item;
};
export type Field = {
  name: string;
  type: string;
  required: boolean;
  default: unknown;
  path: boolean;
  ge?: number;
  le?: number;
  max_length?: number;
  min_length?: number;
  pattern?: string;
};
export type Action = {
  id: string;
  module: string;
  label: string;
  path: string;
  risk: string;
  fields: Field[];
  unsupported?: boolean;
  reason?: string;
  extraFields?: string;
};
export const actions = definitions as Action[];
export const titles: Record<string, string> = {
  news: "뉴스 스튜디오",
  shorts: "뉴스 쇼츠 제작실",
  characters: "캐릭터 쇼츠 제작실",
  images: "이미지 제작실",
  automation: "자동화 센터",
  library: "라이브러리",
  publishing: "게시 스튜디오",
  analytics: "성과 · 비용",
  settings: "설정 · 관리",
  onboarding: "시작 가이드",
};
export const status: Record<string, string> = {
  saved: "초안 저장",
  success: "생성 완료",
  completed: "생성 완료",
  failed: "실패 · 확인 필요",
  unknown: "결과 불명 · 재요청 금지",
  reserved: "예약 기록 · 확인 필요",
  pending: "대기",
  draft: "초안",
  ready: "준비",
  approved: "검토 기록 있음",
  review_required: "검토 필요",
  running: "진행 중",
  active: "사용 중",
  paused: "일시 정지",
  missing: "파일 확인 필요",
  needs_review: "검토 필요",
  needs_script: "대본 준비",
  quoted: "견적 확인",
  downloaded: "클립 저장",
  cancelled: "취소됨",
  blocked: "진행 차단",
};
export const labels: Record<string, string> = {
  prompt: "이미지 지시문",
  model: "AI 모델",
  provider: "제공사",
  size: "이미지 비율 · 크기",
  quality: "품질",
  reference: "참조 PNG · 로컬 보관",
  topic: "이야기 주제",
  episode_limit: "이번 작업 한도",
  day_limit: "하루 한도",
  script_model: "대본 모델",
  video_model: "영상 모델",
  reference_asset: "저장한 참조 소재",
  consent: "이 요청의 외부 전송·사용량에 동의합니다",
  reviewed: "내용과 출처를 검토했습니다",
  quote_hash: "확인한 공식 견적 식별값",
  article_ids: "선택 기사",
  article_id: "기사",
  analysis_id: "저장된 분석",
  draft_id: "대본",
  source_draft_id: "원본 대본",
  render_job_id: "완성 영상",
  identifier: "대상 항목",
  job_id: "제작 작업",
  plan_id: "AI 장면 계획",
  revision: "저장 버전",
  duration: "최종 길이(초)",
  voice: "이번 작업 음성",
  fontsize: "자막 크기",
  subtitle_y: "자막 위치",
  asset_permission: "이미지·영상 소재의 사용 권한을 확인했습니다",
  external_tts_consent: "이 작업의 외부 음성 전송에 동의합니다",
  title: "제목",
  description: "본문",
  caption: "이미지 문구",
  hashtags: "해시태그",
  name: "이름",
  url: "주소",
  content: "대본 · 장면 내용",
  sources: "출처",
  model_path: "등록된 영상 모델",
  confirmed: "표시한 견적과 생성 범위를 승인합니다",
  approved: "표시한 사용 범위를 승인합니다",
  shown_total: "화면에서 확인한 공식 견적",
  statement: "검토 메모",
  source_id: "뉴스 출처",
  schedule_id: "예약",
  run_id: "예약 실행 기록",
  local_time: "실행 시각",
  weekdays: "요일",
  once_date: "1회 실행일",
  kind: "예약 종류",
  source: "뉴스 자료",
  platform: "게시 대상",
  account_id: "연결 계정",
  target: "재사용 · 게시 대상",
  content_reviewed: "콘텐츠 내용을 검토했습니다",
  copyright_confirmed: "저작권·초상권을 확인했습니다",
  sources_confirmed: "출처를 확인했습니다",
  ai_disclosure: "AI 생성 표시",
  privacy: "공개 범위",
  approval_token: "게시 검토 식별값",
  cohort_id: "플랫폼별 검토 묶음",
  made_for_kids: "아동용 콘텐츠",
  input_per_1m: "확인한 입력 100만 토큰 단가",
  output_per_1m: "확인한 출력 100만 토큰 단가",
  currency: "통화",
  timeout: "요청 제한 시간(초)",
  max_tokens: "출력 토큰 제한",
  temperature: "응답 다양성",
  api_key: "API 키",
  key: "API 키",
  secret: "비밀값",
  client_secret: "앱 비밀값",
  client_id: "앱 식별값",
  mode: "영상 제작 방식",
  position: "장면 번호",
  resolution: "해상도",
  price_per_second: "공식 초당 단가",
  durations: "지원 길이",
  label: "표시 이름",
  rights_basis: "사용 권한 근거",
  permission: "이 소재를 사용할 권한이 있습니다",
  step: "설정 단계",
  action: "변경 동작",
  return_to: "저장 후 돌아갈 화면",
  script_style: "대본 스타일",
  tone: "전달 어조",
  audience: "대상 시청자",
  enabled: "사용",
  require_script_review: "영상 제작 전에 대본 확인하기",
  model_id: "등록 모델",
  confirmed_price: "공식 가격을 확인했습니다",
  review_notes: "검토 메모",
  script: "대본",
  heading: "이미지 제목",
  body: "본문",
  source_text: "출처 표기",
};
export function label(key: string) {
  return labels[key] ?? key.replaceAll("_", " ");
}
export function safeMedia(url: unknown) {
  return typeof url === "string" &&
    /^\/(?:video\/jobs\/\d+\/(?:file|thumbnail)|image-studio\/\d+\/file|image-posts\/\d+\/file|character\/[a-zA-Z0-9_-]+\/(?:file|clips\/\d+)|studio\/assets\/[a-zA-Z0-9._-]+)$/.test(
      url,
    )
    ? url
    : null;
}
export function itemTitle(item: Item) {
  return String(
    item.title ??
      item.topic ??
      item.name ??
      item.prompt ??
      item.label ??
      `기록 #${item.id ?? item.key ?? ""}`,
  );
}
