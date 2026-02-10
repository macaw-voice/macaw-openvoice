"""POST /v1/audio/transcriptions — transcricao de arquivo + cancel."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, UploadFile

from Macaw.postprocessing.pipeline import PostProcessingPipeline  # noqa: TC001
from Macaw.preprocessing.pipeline import AudioPreprocessingPipeline  # noqa: TC001
from Macaw.scheduler.scheduler import Scheduler  # noqa: TC001
from Macaw.server.dependencies import (
    get_postprocessing_pipeline,
    get_preprocessing_pipeline,
    get_scheduler,
)
from Macaw.server.routes._common import handle_audio_request

router = APIRouter()


@router.post("/v1/audio/transcriptions/{request_id}/cancel")
async def cancel_transcription(
    request_id: str,
    scheduler: Scheduler = Depends(get_scheduler),  # noqa: B008
) -> dict[str, Any]:
    """Cancela uma request de transcricao na fila ou em execucao.

    Idempotente: cancel de request inexistente ou ja completada retorna
    ``cancelled: false`` sem erro.

    Returns:
        JSON com ``request_id`` e ``cancelled`` (bool).
    """
    cancelled = scheduler.cancel(request_id)
    return {"request_id": request_id, "cancelled": cancelled}


@router.post("/v1/audio/transcriptions")
async def create_transcription(
    file: UploadFile,
    model: str = Form(),
    language: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    response_format: str = Form(default="json"),
    temperature: float = Form(default=0.0),
    itn: bool = Form(default=True),
    scheduler: Scheduler = Depends(get_scheduler),  # noqa: B008
    preprocessing_pipeline: AudioPreprocessingPipeline | None = Depends(  # noqa: B008
        get_preprocessing_pipeline
    ),
    postprocessing_pipeline: PostProcessingPipeline | None = Depends(get_postprocessing_pipeline),  # noqa: B008
) -> Any:
    """Transcreve arquivo de audio.

    Compativel com OpenAI Audio API POST /v1/audio/transcriptions.
    """
    return await handle_audio_request(
        file=file,
        model=model,
        language=language,
        prompt=prompt,
        response_format=response_format,
        temperature=temperature,
        task="transcribe",
        scheduler=scheduler,
        preprocessing_pipeline=preprocessing_pipeline,
        postprocessing_pipeline=postprocessing_pipeline,
        itn=itn,
    )
