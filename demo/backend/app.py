"""Aplicacao FastAPI para o demo end-to-end."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette import status

from Macaw._types import ModelType, ResponseFormat
from Macaw.config.postprocessing import PostProcessingConfig
from Macaw.config.preprocessing import PreprocessingConfig
from Macaw.logging import get_logger
from Macaw.postprocessing.itn import ITNStage
from Macaw.postprocessing.pipeline import PostProcessingPipeline
from Macaw.preprocessing.dc_remove import DCRemoveStage
from Macaw.preprocessing.gain_normalize import GainNormalizeStage
from Macaw.preprocessing.pipeline import AudioPreprocessingPipeline
from Macaw.preprocessing.resample import ResampleStage
from Macaw.registry.registry import ModelRegistry
from Macaw.scheduler.queue import RequestPriority
from Macaw.scheduler.scheduler import Scheduler
from Macaw.scheduler.streaming import StreamingGRPCClient
from Macaw.server.error_handlers import register_error_handlers
from Macaw.server.models.requests import TranscribeRequest
from Macaw.server.routes import health, realtime, speech, transcriptions, translations
from Macaw.workers.manager import WorkerManager

from .config import DemoConfig
from .jobs import DemoJob, DemoJobStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from Macaw.postprocessing.stages import TextStage
    from Macaw.preprocessing.stages import AudioStage

logger = get_logger("demo.backend")


def create_demo_app(config: DemoConfig | None = None) -> FastAPI:
    """Cria aplicacao FastAPI com lifecycle completo do Macaw."""

    settings = config or DemoConfig()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "demo_starting",
            models_dir=str(settings.models_dir),
            worker_base_port=settings.worker_base_port,
        )

        registry = ModelRegistry(settings.models_dir)
        await registry.scan()
        models = registry.list_models()
        stt_manifests = [m for m in models if m.model_type == ModelType.STT]
        tts_manifests = [m for m in models if m.model_type == ModelType.TTS]
        if not stt_manifests and not tts_manifests:
            msg = (
                "Nenhum modelo encontrado. Execute 'Macaw pull <modelo>' antes de iniciar o demo."
            )
            logger.error("demo_no_models", models_dir=str(settings.models_dir))
            raise RuntimeError(msg)

        worker_manager = WorkerManager()
        port_counter = settings.worker_base_port

        for manifest in stt_manifests:
            model_path = str(registry.get_model_path(manifest.name))
            await worker_manager.spawn_worker(
                model_name=manifest.name,
                port=port_counter,
                engine=manifest.engine,
                model_path=model_path,
                engine_config=manifest.engine_config.model_dump(),
                worker_type="stt",
            )
            logger.info(
                "demo_worker_spawned",
                model=manifest.name,
                engine=manifest.engine,
                port=port_counter,
                worker_type="stt",
            )
            port_counter += 1

        for manifest in tts_manifests:
            model_path = str(registry.get_model_path(manifest.name))
            tts_engine_config = manifest.engine_config.model_dump()
            tts_engine_config["model_name"] = manifest.name
            await worker_manager.spawn_worker(
                model_name=manifest.name,
                port=port_counter,
                engine=manifest.engine,
                model_path=model_path,
                engine_config=tts_engine_config,
                worker_type="tts",
            )
            logger.info(
                "demo_worker_spawned",
                model=manifest.name,
                engine=manifest.engine,
                port=port_counter,
                worker_type="tts",
            )
            port_counter += 1

        preprocessing_pipeline = _build_preprocessing_pipeline()
        postprocessing_pipeline = _build_postprocessing_pipeline()

        scheduler = Scheduler(
            worker_manager,
            registry,
            aging_threshold_s=settings.aging_threshold_s,
            batch_accumulate_ms=settings.batch_accumulate_ms,
            batch_max_size=settings.batch_max_size,
        )
        await scheduler.start()
        logger.info(
            "demo_scheduler_started",
            aging_threshold_s=settings.aging_threshold_s,
            batch_accumulate_ms=settings.batch_accumulate_ms,
            batch_max_size=settings.batch_max_size,
        )

        streaming_grpc_client: StreamingGRPCClient | None = None
        if stt_manifests:
            first_stt_port = settings.worker_base_port
            streaming_grpc_client = StreamingGRPCClient(f"localhost:{first_stt_port}")
            await streaming_grpc_client.connect()
            logger.info("demo_streaming_grpc_connected", port=first_stt_port)

        job_store = DemoJobStore()
        app.state.registry = registry
        app.state.scheduler = scheduler
        app.state.worker_manager = worker_manager
        app.state.preprocessing_pipeline = preprocessing_pipeline
        app.state.postprocessing_pipeline = postprocessing_pipeline
        app.state.streaming_grpc_client = streaming_grpc_client
        app.state.demo_jobs = job_store
        app.state.demo_tasks: set[asyncio.Task[Any]] = set()

        try:
            yield
        finally:
            tasks = list(app.state.demo_tasks)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            if streaming_grpc_client is not None:
                await streaming_grpc_client.close()

            await scheduler.stop()
            await worker_manager.stop_all()
            logger.info("demo_stopped")

    app = FastAPI(
        title="Macaw OpenVoice Demo",
        version="1.0",
        description="Demo interativa do Scheduler e API Macaw",
        lifespan=lifespan,
    )

    app.state.config = settings
    app.state.registry = None
    app.state.scheduler = None
    app.state.worker_manager = None
    app.state.preprocessing_pipeline = None
    app.state.postprocessing_pipeline = None
    app.state.demo_jobs = DemoJobStore()
    app.state.demo_tasks = set()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(health.router, prefix="/api")
    app.include_router(transcriptions.router, prefix="/api")
    app.include_router(translations.router, prefix="/api")
    app.include_router(speech.router, prefix="/api")
    app.include_router(realtime.router, prefix="/api")

    _register_demo_routes(app)

    return app


def _build_preprocessing_pipeline() -> AudioPreprocessingPipeline:
    config = PreprocessingConfig()
    stages: list[AudioStage] = []
    if config.resample:
        stages.append(ResampleStage(config.target_sample_rate))
    if config.dc_remove:
        stages.append(DCRemoveStage(config.dc_remove_cutoff_hz))
    if config.gain_normalize:
        stages.append(GainNormalizeStage(config.target_dbfs))
    return AudioPreprocessingPipeline(config, stages)


def _build_postprocessing_pipeline() -> PostProcessingPipeline:
    config = PostProcessingConfig()
    stages: list[TextStage] = []
    if config.itn.enabled:
        stages.append(ITNStage(config.itn.language))
    return PostProcessingPipeline(config, stages)


def _register_demo_routes(app: FastAPI) -> None:
    @app.get("/demo/models")
    async def list_models(request: Request) -> dict[str, Any]:
        registry: ModelRegistry = request.app.state.registry
        manifests = registry.list_models()
        return {
            "items": [
                {
                    "name": manifest.name,
                    "engine": manifest.engine,
                    "version": manifest.version,
                    "description": manifest.description,
                    "type": manifest.model_type.value,
                    "capabilities": manifest.capabilities.model_dump(),
                    "resources": manifest.resources.model_dump(),
                }
                for manifest in manifests
            ],
        }

    @app.get("/demo/queue")
    async def queue_metrics(request: Request) -> dict[str, Any]:
        scheduler: Scheduler = request.app.state.scheduler
        depth = scheduler.queue.depth
        depth_by_priority = scheduler.queue.depth_by_priority
        return {
            "depth": depth,
            "depth_by_priority": depth_by_priority,
        }

    @app.get("/demo/jobs")
    async def list_jobs(request: Request) -> dict[str, Any]:
        store: DemoJobStore = request.app.state.demo_jobs
        jobs = await store.list()
        jobs.sort(key=lambda job: job.created_at, reverse=True)
        return {"items": [job.as_dict() for job in jobs]}

    @app.get("/demo/jobs/{request_id}")
    async def get_job(request_id: str, request: Request) -> dict[str, Any]:
        store: DemoJobStore = request.app.state.demo_jobs
        job = await store.get(request_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job nao encontrado")
        return job.as_dict()

    @app.post("/demo/jobs")
    async def submit_job(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
        model: str = Form(...),
        priority: str = Form("BATCH"),
        language: str | None = Form(None),
    ) -> dict[str, Any]:
        scheduler: Scheduler = request.app.state.scheduler
        registry: ModelRegistry = request.app.state.registry
        store: DemoJobStore = request.app.state.demo_jobs

        if not registry.has_model(model):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Modelo '{model}' nao encontrado",
            )

        try:
            request_priority = RequestPriority[priority.upper()]
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Prioridade invalida. Use REALTIME ou BATCH.",
            ) from exc

        payload = await file.read()
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Arquivo de audio vazio.",
            )

        request_id = uuid.uuid4().hex
        transcribe_request = TranscribeRequest(
            request_id=request_id,
            model_name=model,
            audio_data=payload,
            language=language,
            response_format=ResponseFormat.JSON,
        )

        job = DemoJob(
            request_id=request_id,
            model_name=model,
            priority=request_priority,
            language=language,
        )
        await store.add(job)

        future = await scheduler.submit(transcribe_request, priority=request_priority)

        task = asyncio.create_task(_finalize_job(request.app, job.request_id, future))
        request.app.state.demo_tasks.add(task)
        task.add_done_callback(request.app.state.demo_tasks.discard)

        logger.info(
            "demo_job_enqueued",
            request_id=request_id,
            model=model,
            priority=request_priority.name,
            language=language,
        )

        return {"request_id": request_id, "status": job.status}

    @app.post("/demo/jobs/{request_id}/cancel")
    async def cancel_job(request_id: str, request: Request) -> dict[str, Any]:
        scheduler: Scheduler = request.app.state.scheduler
        store: DemoJobStore = request.app.state.demo_jobs

        cancelled = scheduler.cancel(request_id)
        if cancelled:
            job = await store.update(request_id, status="cancelled")
        else:
            job = await store.get(request_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job nao encontrado",
            )
        logger.info("demo_job_cancel", request_id=request_id, cancelled=cancelled)
        return {
            "request_id": request_id,
            "cancelled": cancelled,
            "status": job.status,
        }


async def _finalize_job(app: FastAPI, request_id: str, future: asyncio.Future[Any]) -> None:
    store: DemoJobStore = app.state.demo_jobs
    try:
        result = await future
    except asyncio.CancelledError:
        await store.update(request_id, status="cancelled")
        raise
    except Exception as exc:
        logger.error("demo_job_failed", request_id=request_id, error=str(exc))
        await store.update(request_id, status="failed", error=str(exc))
    else:
        await store.update(request_id, status="completed", result=result)
        logger.info("demo_job_completed", request_id=request_id)


app = create_demo_app()
