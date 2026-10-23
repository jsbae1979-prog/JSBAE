'use strict';
// View-only conveniences. No fetch, form submission, credential read or autosave.
(() => {
  const dialog = document.getElementById('access-dialog');
  if (!dialog) return;
  const search = dialog.querySelector('[data-access-search]');
  const entries = [...dialog.querySelectorAll('[data-access-destination]')];
  const aliases = {
    '/news#curation': 'Google News Trends SerpApi 구글 트렌드 뉴스 수집 화제성',
    '/character': '카피바라 느긋해 대리 캐릭터 코미디',
    '/image-posts': 'Instagram 인스타그램 피드 단일 사진 OpenAI 이미지',
    '/simple-settings#connections': 'Claude 클로드 OpenAI 오픈에이아이 Codex API Key 키 등록 변경 인증 모델',
    '/simple-settings#quality': 'ElevenLabs 일레븐랩스 Supertonic 슈퍼토닉 Windows 윈도우 Heami 해미 SAPI 로컬 음성',
    '/voices': 'ElevenLabs 일레븐랩스 내 음성 샘플 듣기',
    '/simple-settings#video-settings': 'Higgsfield 히그스필드 힉스필드 Kling 클링 Seedance PixVerse AI 영상',
    '/simple-settings#accounts': 'YouTube 유튜브 Instagram 인스타그램 Google Meta 구글 메타 계정 연결',
  };
  let returnFocus;
  const normalize = value => value.trim().toLocaleLowerCase().replace(/\s+/g, ' ');
  function filter() {
    const words = normalize(search.value).split(' ').filter(Boolean);
    let count = 0;
    entries.forEach(entry => {
      const label = normalize(`${entry.textContent} ${entry.dataset.accessSearchText || ''} ${aliases[entry.getAttribute('href')] || ''}`);
      entry.hidden = !words.every(word => label.includes(word));
      if (!entry.hidden) count++;
    });
    dialog.querySelectorAll('.access-group').forEach(group => {
      group.hidden = ![...group.querySelectorAll('a')].some(link => !link.hidden);
    });
    dialog.querySelector('[data-access-count]').textContent = `${count}개 이동 항목`;
    dialog.querySelector('[data-access-empty]').hidden = count !== 0;
  }
  function open() {
    if (dialog.open) return;
    returnFocus = document.activeElement;
    search.value = '';
    filter();
    dialog.showModal();
    document.querySelectorAll('[data-access-open]').forEach(button => button.setAttribute('aria-expanded','true'));
    search.focus();
  }
  document.querySelectorAll('[data-access-open]').forEach(button => button.addEventListener('click', open));
  dialog.querySelector('[data-access-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    document.querySelectorAll('[data-access-open]').forEach(button => button.setAttribute('aria-expanded','false'));
    returnFocus?.focus();
  });
  dialog.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); dialog.close(); }
  });
  // Native dialog traps focus; the explicit Escape handler also works inside a search input.
  dialog.addEventListener('click', event => { if (event.target === dialog) {
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  }});
  dialog.querySelectorAll('a').forEach(link => link.addEventListener('click', () => dialog.close()));
  search.addEventListener('input', filter);
  search.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      entries.find(entry => !entry.hidden)?.click();
    }
  });
  document.addEventListener('keydown', event => {
    if (event.altKey && !event.ctrlKey && !event.metaKey && (event.code === 'KeyK' || event.key.toLowerCase() === 'k')) {
      event.preventDefault(); open();
    }
  });

  // Index all sections, including closed details. Existing IDs and original settings tabs stay authoritative.
  const outline = document.querySelector('[data-access-outline]');
  const index = document.querySelector('[data-access-outline-links]');
  const seen = new Set();
  document.querySelectorAll('#main-content h2').forEach((heading, number) => {
    if (heading.closest('dialog,template,[data-access-outline],.dashboard-system,.workspace-video-card,[data-ai-provider][hidden]')) return;
    const label = heading.textContent.trim();
    if (!label || seen.has(label)) return;
    seen.add(label);
    if (!heading.id) {
      let id = `access-section-${number}`;
      while (document.getElementById(id)) id += '-section';
      heading.id = id;
    }
    const link = document.createElement('a');
    link.href = `#${heading.id}`;
    link.textContent = label;
    link.addEventListener('click', () => {
      const parents = [];
      for (let parent = heading.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parents.push(parent);
      parents.reverse().forEach(parent => { parent.open = true; });
      outline.open = false;
      // Let the existing hashchange handler reveal the right settings tab first.
      setTimeout(() => { heading.tabIndex = -1; heading.focus({preventScroll:true}); heading.scrollIntoView({block:'start'}); }, 0);
    });
    index.append(link);
  });
  outline.hidden = index.children.length < 2;

  // Decorative icons keep the existing accessible button text and event handlers intact.
  function iconFor(control) {
    const text = control.textContent.trim();
    if (/삭제|휴지/.test(text)) return 'trash';
    if (/다운로드|MP4 저장|영상 저장|이미지 저장|JPG 저장/.test(text)) return 'download';
    if (/미리듣|음성 선택|음성 목록/.test(text)) return 'voice';
    if (/캐릭터/.test(text)) return 'character';
    if (/키 등록|키 변경|연결 설정/.test(text)) return 'key';
    if (/이미지|피드/.test(text)) return 'image';
    if (/미리보기|재생|장면 영상/.test(text)) return 'play';
    if (/검토|확인|승인/.test(text)) return 'check';
    if (/편집|수정/.test(text)) return 'edit';
    if (/저장/.test(text)) return 'file';
    if (/설정/.test(text)) return 'settings';
    if (/예약/.test(text)) return 'clock';
    if (/게시|업로드/.test(text)) return 'send';
    if (/수집/.test(text)) return 'news';
    if (/대본|분석|생성/.test(text)) return 'sparkles';
    return null;
  }
  document.querySelectorAll('#main-content :is(a.button,button)').forEach(control => {
    if (control.closest('dialog,[data-access-outline]') || control.querySelector('svg,img') ||
        control.matches('[data-video-scene-select],[data-activity-day],[data-news-category],[role="tab"]') ||
        !control.textContent.trim() || control.textContent.trim().length > 55) return;
    const icon = iconFor(control);
    const template = document.querySelector(`template[data-access-icon="${icon}"]`);
    if (!template) return;
    control.prepend(template.content.cloneNode(true));
    control.classList.add('access-icon-action');
  });
  const sidebar = document.querySelector('[data-sidebar-menu]');
  const compact = window.matchMedia('(max-width:760px)');
  function sizeMenu() { if (sidebar) sidebar.open = !compact.matches; }
  sizeMenu();
  compact.addEventListener('change', sizeMenu);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && compact.matches && sidebar?.open && !dialog.open) {
      sidebar.open = false; sidebar.querySelector('summary').focus();
    }
  });
  document.addEventListener('click', event => {
    if (compact.matches && sidebar?.open && !sidebar.contains(event.target)) sidebar.open = false;
  });
  document.querySelectorAll('[data-studio-work-filter]').forEach(button => button.addEventListener('click', () => {
    const category = button.dataset.studioWorkFilter;
    let count = 0;
    document.querySelectorAll('.studio-all-work [data-studio-task]').forEach(row => {
      row.hidden = category !== 'all' && category !== row.dataset.studioCategory;
      if (!row.hidden) count++;
    });
    document.querySelectorAll('[data-studio-work-filter]').forEach(item => item.setAttribute('aria-pressed',String(item === button)));
    document.querySelector('[data-studio-work-result]').textContent = `${button.textContent} · ${count}개 기록`;
    document.querySelector('[data-studio-work-empty]').hidden = count !== 0;
  }));
  const initialWorkState = new URLSearchParams(location.search).get('work_state');
  if (['review', 'attention', 'running', 'saved'].includes(initialWorkState)) {
    document.querySelector(`[data-studio-work-filter="${initialWorkState}"]`)?.click();
  }

  // File selection preview is local to this page, never an automatic upload.
  let selection = 0;
  const input = document.querySelector('[data-character-reference]');
  input?.addEventListener('change', async () => {
    const current = ++selection;
    const preview = document.querySelector('[data-character-preview]');
    const status = document.querySelector('[data-character-file-status]');
    preview.hidden = true;
    preview.getContext('2d').clearRect(0,0,preview.width,preview.height);
    status.textContent = '';
    const file = input.files[0];
    if (!file) return;
    let bitmap;
    try {
      if (file.type !== 'image/png' || file.size > 10 * 1024 * 1024) throw new Error('format');
      const header = new DataView(await file.slice(0,24).arrayBuffer());
      if (header.byteLength < 24 || header.getUint32(0) !== 0x89504e47 || header.getUint32(4) !== 0x0d0a1a0a ||
          header.getUint32(16) < 128 || header.getUint32(16) > 4096 || header.getUint32(20) < 128 || header.getUint32(20) > 4096) throw new Error('dimensions');
      bitmap = await createImageBitmap(file);
      if (current !== selection) return;
      const ratio = Math.min(1,200/bitmap.width,260/bitmap.height);
      preview.width = Math.round(bitmap.width*ratio);
      preview.height = Math.round(bitmap.height*ratio);
      preview.getContext('2d').drawImage(bitmap,0,0,preview.width,preview.height);
      preview.hidden = false;
      status.textContent = '원본 선택됨 · 아직 저장하거나 전송하지 않았습니다.';
    } catch (_) {
      if (current === selection) status.textContent = 'PNG 원본을 확인하세요. 10MB 이내, 가로·세로 128~4096px를 지원합니다.';
    } finally {
      bitmap?.close();
    }
  });
})();
