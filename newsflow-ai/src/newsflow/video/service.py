"""One render per data directory, immutable projects, safe publication and recovery."""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from uuid import uuid4

from filelock import FileLock, Timeout
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import AudioTrack, ContentDraft, RenderJob, Scene, SubtitleTrack, VideoProject, utcnow
from newsflow.intelligence.schema import Script

from .engine import FFmpegAdapter, RenderEngine, RenderError, RenderPlan, ScenePlan, load_image
from .tts import OfflineTTS, SpeechSettings, TTSError, TTSProvider, WindowsTTS


class VideoError(Exception):
    pass


class RenderBusy(VideoError):
    pass


class VideoCoordinator:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        data_dir: Path,
        engine: RenderEngine | None = None,
        tts: TTSProvider | None = None,
    ) -> None:
        self.sessions, self.root = sessions, data_dir.resolve()
        self.outputs = self.root / "outputs/videos"
        self.temporary = self.root / "render-tmp"
        self.assets = self.root / "assets"
        for directory in (self.outputs, self.temporary, self.assets):
            directory.mkdir(parents=True, exist_ok=True)
        self.engine, self.tts = engine or FFmpegAdapter(), tts
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="newsflow-render")
        self.cancel = Event()
        self.lock = FileLock(str(self.root / "render.lock"), thread_local=False)
        self.guard = Lock()
        self.future: Future | None = None
        self.control = Lock()
        self.active_job_id: int | None = None
        self.job_cancel: Event | None = None

    def assets_list(self) -> list[str]:
        return sorted(
            p.name
            for p in self.assets.iterdir()
            if p.is_file()
            and not p.is_symlink()
            and p.suffix.lower() in {".png", ".jpg", ".jpeg"}
            and len(p.name) <= 255
        )[:100]

    def asset(self, name: str) -> Path:
        if not name or len(name) > 255 or Path(name).name != name or any(c in name for c in "\\/:\x00"):
            raise VideoError("소재는 assets 폴더의 PNG/JPEG 파일명으로 선택하세요.")
        path = self.assets / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.assets.resolve()):
            raise VideoError("소재 경로가 허용된 폴더 밖에 있습니다.")
        try:
            load_image(path).close()
        except RenderError:
            raise VideoError("소재 형식·크기·파일 접근을 확인하세요.") from None
        return path

    @staticmethod
    def timings(content: dict, duration: int) -> list[tuple[int, int]]:
        script = Script.model_validate(content)
        total = sum(s.seconds for s in script.scenes)
        result, start = [], 0
        for index, scene in enumerate(script.scenes):
            end = (
                duration * 1000
                if index == len(script.scenes) - 1
                else round((sum(s.seconds for s in script.scenes[: index + 1]) / total) * duration * 1000)
            )
            if end - start < 100:
                raise VideoError("장면 시간이 너무 짧습니다.")
            result.append((start, end))
            start = end
        return result

    def start(
        self,
        draft_id: int,
        duration: int,
        voice: str = "offline-silence",
        font_size: int = 48,
        subtitle_y: int = 1420,
        images: list[str] | None = None,
        reviewed: bool = False,
        asset_permission: bool = False,
    ) -> int:
        if duration not in (30, 45, 60) or not reviewed:
            raise VideoError("영상 길이를 선택하고 렌더링 전 대본·출처 검토를 확인하세요.")
        return self._start(draft_id, duration, voice, font_size, subtitle_y, images, asset_permission, False)

    def start_preview(
        self,
        draft_id: int,
        duration: int,
        on_job: Callable[[int], None] | None = None,
        *,
        voice: str | None = None,
        speech: SpeechSettings | None = None,
    ) -> int:
        """Create a clearly marked local review copy without granting human approval.

        A real Windows voice renders with audio-fit timing so subtitles follow the
        narration; the silent offline voice keeps the script's planned scene seconds.
        """
        if duration not in (30, 45, 60):
            raise VideoError("영상 길이는 30초, 45초, 60초 중 선택하세요.")
        from newsflow.easy_setup import preview_preferences, speech_preferences

        default_voice, size, position = preview_preferences(self.sessions)
        voice = voice or default_voice
        if speech is None:
            try:
                speech = speech_preferences(self.sessions)
            except TTSError:
                raise VideoError("음성 속도·쉼 설정을 다시 저장하세요.") from None
        return self._start(
            draft_id, duration, voice, size, position, None, False, True, on_job,
            speech=speech, fit_audio=voice != "offline-silence",
        )

    def voice_available(self, voice: str) -> bool:
        """True when the configured local provider lists the voice; never substitutes another."""
        if voice == "offline-silence":
            return True
        try:
            provider = self.tts or WindowsTTS()
            return voice in provider.voices()
        except TTSError:
            return False

    def _start(
        self,
        draft_id: int,
        duration: int,
        voice: str,
        font_size: int,
        subtitle_y: int,
        images: list[str] | None,
        asset_permission: bool,
        preview_only: bool,
        on_job: Callable[[int], None] | None = None,
        *,
        speech: SpeechSettings | None = None,
        fit_audio: bool = False,
    ) -> int:
        speech = speech or SpeechSettings()
        if self.cancel.is_set():
            raise VideoError("프로그램 종료 중에는 새 영상을 제작할 수 없습니다.")
        images = images or []
        if any(images) and not asset_permission:
            raise VideoError("로컬 소재 이용 권한을 확인하세요.")
        if not self.guard.acquire(blocking=False):
            raise RenderBusy("이미 영상 제작이 실행 중입니다.")
        if self.future and not self.future.done():
            self.guard.release()
            raise RenderBusy("이미 영상 제작이 실행 중입니다.")
        try:
            self.lock.acquire(timeout=0)
        except Timeout:
            self.guard.release()
            raise RenderBusy("이미 영상 제작이 실행 중입니다.") from None
        except OSError:
            self.guard.release()
            raise VideoError("영상 잠금 파일의 접근 권한을 확인하세요.") from None
        job_id = None
        try:
            if shutil.disk_usage(self.root).free < (256 + duration * 4) * 1024 * 1024:
                raise VideoError("영상 제작을 위한 디스크 공간이 부족합니다. 최소 약 500MB를 확보하세요.")
            with self.sessions.begin() as session:
                draft = session.get(ContentDraft, draft_id)
                if not draft:
                    raise VideoError("저장된 대본을 찾지 못했습니다.")
                key = os.environ.get("NEWSFLOW_AI_API_KEY", "")
                if key and key in json.dumps(
                    {"content": draft.content, "sources": draft.sources}, ensure_ascii=False
                ):
                    raise VideoError("비밀정보가 포함된 초안은 영상으로 제작할 수 없습니다.")
                times = self.timings(draft.content, duration)
                if images and len(images) != len(times):
                    raise VideoError("장면별 소재 개수를 확인하세요.")
                images = images or [""] * len(times)
                for name in images:
                    if name:
                        self.asset(name)
                if self.tts:
                    tts = self.tts
                elif voice == "offline-silence":
                    tts = OfflineTTS()
                else:
                    tts = WindowsTTS()
                if voice not in tts.voices():
                    raise VideoError("설치된 음성 목록에서 음성을 선택하세요.")
                plan = RenderPlan(
                    draft.content["title"],
                    [
                        ScenePlan((end - start) / 1000, s["narration"], s["caption"])
                        for (start, end), s in zip(times, draft.content["scenes"])
                    ],
                    [],
                    voice,
                    font_size,
                    subtitle_y,
                    speech,
                    fit_audio,
                )
                plan.validate()
                project = VideoProject(
                    draft_id=draft.id,
                    title=draft.content["title"],
                    duration=duration,
                    snapshot={
                        **draft.content, "draft_revision": draft.revision,
                        "speech": {"rate": speech.rate, "pause_ms": speech.pause_ms, "fit_audio": fit_audio},
                    },
                    sources=draft.sources,
                    preview_only=preview_only,
                )
                session.add(project)
                session.flush()
                for index, ((start, end), scene, name) in enumerate(
                    zip(times, draft.content["scenes"], images)
                ):
                    session.add(
                        Scene(
                            project_id=project.id,
                            position=index,
                            start_ms=start,
                            end_ms=end,
                            narration=scene["narration"],
                            caption=scene["caption"],
                            material=name,
                        )
                    )
                session.add(
                    AudioTrack(
                        project_id=project.id,
                        provider="offline" if voice == "offline-silence" else "windows",
                        voice=voice,
                    )
                )
                session.add(
                    SubtitleTrack(
                        project_id=project.id,
                        font_size=font_size,
                        position_y=subtitle_y,
                        cues=[
                            {"start_ms": start, "end_ms": end, "text": s["caption"]}
                            for (start, end), s in zip(times, draft.content["scenes"])
                        ],
                    )
                )
                job = RenderJob(project_id=project.id, output_name=f"video-{uuid4().hex}.mp4")
                session.add(job)
                session.flush()
                job_id = job.id
            if on_job:
                on_job(job_id)
            job_cancel = Event()
            with self.control:
                self.active_job_id, self.job_cancel = job_id, job_cancel
                if self.cancel.is_set():
                    job_cancel.set()
            self.future = self.executor.submit(self._run, job_id, tts, job_cancel)
            return job_id
        except Exception:
            try:
                if job_id is not None:
                    with self.sessions.begin() as session:
                        job = session.get(RenderJob, job_id)
                        job.status, job.message, job.finished_at = (
                            "failed",
                            "영상 제작 준비 기록에 실패했습니다. 다시 시도하세요.",
                            utcnow(),
                        )
                        session.scalar(
                            select(AudioTrack).where(AudioTrack.project_id == job.project_id)
                        ).status = "failed"
            finally:
                with self.control:
                    if self.active_job_id == job_id:
                        self.active_job_id, self.job_cancel = None, None
                self.lock.release()
                self.guard.release()
            raise

    def _progress(self, identifier: int, value: int) -> None:
        with self.sessions.begin() as session:
            job = session.get(RenderJob, identifier)
            job.progress = min(max(value, 0), 99)
            job.message = (
                "장면·음성 준비 중"
                if value < 10
                else ("영상 인코딩 중" if value < 95 else "완성 MP4 검증 중")
            )

    def _run(self, identifier: int, tts: TTSProvider, cancel: Event) -> None:
        published: Path | None = None
        try:
            with self.sessions() as session:
                job = session.get(RenderJob, identifier)
                project = session.get(VideoProject, job.project_id)
                scenes = list(
                    session.scalars(
                        select(Scene).where(Scene.project_id == project.id).order_by(Scene.position)
                    )
                )
                audio = session.scalar(select(AudioTrack).where(AudioTrack.project_id == project.id))
                subtitles = session.scalar(
                    select(SubtitleTrack).where(SubtitleTrack.project_id == project.id)
                )
                source_links = [
                    source for article in project.sources.get("articles", []) for source in article["sources"]
                ]
                output = self.output_path(job.output_name)
                title, voice, font_size, position_y = (
                    ("검토용 초안 · " if project.preview_only else "") + project.title,
                    audio.voice,
                    subtitles.font_size,
                    subtitles.position_y,
                )
                saved = project.snapshot.get("speech") or {}
                try:
                    speech = SpeechSettings(int(saved.get("rate", 0)), int(saved.get("pause_ms", 250)))
                except (TTSError, TypeError, ValueError):
                    speech = SpeechSettings()
                fit_audio = bool(saved.get("fit_audio")) and voice != "offline-silence"
            with TemporaryDirectory(prefix=f"job-{identifier}-", dir=self.temporary) as directory:
                work = Path(directory)
                plans = []
                for index, scene in enumerate(scenes):
                    image = None
                    if scene.material:
                        image = work / f"asset-{index}.png"
                        with load_image(self.asset(scene.material)) as asset:
                            asset.save(image, format="PNG")
                    plans.append(
                        ScenePlan(
                            (scene.end_ms - scene.start_ms) / 1000, scene.narration, scene.caption, image
                        )
                    )
                plan = RenderPlan(title, plans, source_links, voice, font_size, position_y, speech, fit_audio)
                result, metadata = self.engine.render(
                    plan, work, tts, lambda value: self._progress(identifier, value), cancel
                )
                if cancel.is_set():
                    raise RenderError("영상 제작이 종료되었습니다.")
                if (
                    not result.resolve().is_relative_to(work.resolve())
                    or result.is_symlink()
                    or not result.is_file()
                ):
                    raise RenderError("렌더링 결과 경로가 잘못되었습니다.")
                # Exclusive creation never overwrites an existing user video.
                with output.open("xb") as target, result.open("rb") as source:
                    published = output
                    shutil.copyfileobj(source, target)
                    target.flush()
                    os.fsync(target.fileno())
            if cancel.is_set():
                raise RenderError("영상 제작이 종료되었습니다.")
            with self.sessions.begin() as session:
                job = session.get(RenderJob, identifier)
                job.status = "success" if metadata.get("playable") else "simulated"
                job.progress, job.metadata_json, job.finished_at = 100, metadata, utcnow()
                self._apply_timings(session, job.project_id, metadata)
                job.message = (
                    "MP4 제작 완료 · 사람의 내용/품질 검토 필요"
                    if job.status == "success"
                    else "Fake 렌더 시뮬레이션 완료 · 실제 MP4 아님"
                )
                session.scalar(select(AudioTrack).where(AudioTrack.project_id == job.project_id)).status = (
                    "success" if job.status == "success" else "simulated"
                )
        except Exception as exc:  # noqa: BLE001 - sanitized adapter failure boundary
            cleanup_pending = False
            if published:
                try:
                    published.unlink(missing_ok=True)
                except OSError:
                    cleanup_pending = True
            hints = {
                "font": "한국어 글꼴 설정",
                "subtitle": "자막 길이·안전 영역",
                "dependency": "FFmpeg/ffprobe 설치·버전",
                "validation": "완성 MP4 코덱·해상도·길이·오디오",
                "audio": "음성 길이",
            }
            kind = (
                "음성 생성"
                if isinstance(exc, TTSError)
                else hints.get(getattr(exc, "kind", None), "FFmpeg·장면·파일 처리")
            )
            if isinstance(exc, FileExistsError):
                kind = "출력 파일명 충돌 (기존 파일 보존)"
            elif isinstance(exc, OSError) and exc.errno == 28:
                kind = "디스크 공간 부족"
            with self.sessions.begin() as session:
                job = session.get(RenderJob, identifier)
                job.status = "interrupted" if cancel.is_set() else "failed"
                job.message = (
                    f"{kind} 실패. 설치·음성 길이·자막 안전 영역·코덱·디스크 공간을 확인하세요."
                    if job.status == "failed"
                    else "사용자 취소 또는 프로그램 종료로 영상 제작이 중단되었습니다."
                )
                if cleanup_pending:
                    job.message += " · 생성 파일 정리 실패; 출력 폴더를 수동 확인하세요."
                code = getattr(exc, "exit_code", None)
                if isinstance(code, int):
                    job.message += f" · 종료 코드 {code}"
                job.finished_at = utcnow()
                session.scalar(
                    select(AudioTrack).where(AudioTrack.project_id == job.project_id)
                ).status = job.status
        finally:
            with self.control:
                if self.active_job_id == identifier:
                    self.active_job_id, self.job_cancel = None, None
            self.lock.release()
            self.guard.release()

    @staticmethod
    def _apply_timings(session: Session, project_id: int, metadata: dict) -> None:
        """Persist audio-fit scene boundaries so subtitles and the stored plan match the MP4."""
        timings = metadata.get("scene_timings")
        if not isinstance(timings, list) or not timings:
            return
        scenes = list(
            session.scalars(select(Scene).where(Scene.project_id == project_id).order_by(Scene.position))
        )
        subtitles = session.scalar(select(SubtitleTrack).where(SubtitleTrack.project_id == project_id))
        if len(scenes) != len(timings) or subtitles is None:
            return
        start = 0
        cues = []
        for index, (scene, timing) in enumerate(zip(scenes, timings)):
            seconds = float(timing.get("seconds", 0))
            end = scenes[-1].end_ms if index == len(scenes) - 1 else start + round(seconds * 1000)
            scene.start_ms, scene.end_ms = start, end
            cues.append({"start_ms": start, "end_ms": end, "text": scene.caption})
            start = end
        subtitles.cues = cues

    def request_cancel(self, job_id: int) -> bool:
        """Cancel only the matching running job; a later render gets a fresh Event."""
        with self.control:
            if self.active_job_id != job_id or self.job_cancel is None:
                return False
            self.job_cancel.set()
            return True

    def output_path(self, name: str) -> Path:
        if not re.fullmatch(r"video-[0-9a-f]{32}\.mp4", name):
            raise VideoError("결과 파일명이 안전하지 않습니다.")
        path = self.outputs / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.outputs.resolve()):
            raise VideoError("결과 파일 경로를 확인하세요.")
        return path

    def recover(self) -> None:
        if self.guard.locked():
            return
        try:
            with self.lock.acquire(timeout=0):
                with self.sessions.begin() as session:
                    for job in session.scalars(select(RenderJob).where(RenderJob.status == "running")):
                        job.status, job.message, job.finished_at = (
                            "interrupted",
                            "이전 영상 제작이 중단되었습니다. 자동 재실행하지 않습니다.",
                            utcnow(),
                        )
                        session.scalar(
                            select(AudioTrack).where(AudioTrack.project_id == job.project_id)
                        ).status = "interrupted"
                for directory in self.temporary.iterdir():
                    if (
                        directory.is_dir()
                        and not directory.is_symlink()
                        and re.fullmatch(r"job-[0-9]+-[a-zA-Z0-9_-]+", directory.name)
                    ):
                        shutil.rmtree(directory)
        except Timeout:
            pass  # Another process still owns an active render.

    def close(self) -> None:
        self.cancel.set()
        with self.control:
            if self.job_cancel is not None:
                self.job_cancel.set()
        self.executor.shutdown(wait=True, cancel_futures=False)
