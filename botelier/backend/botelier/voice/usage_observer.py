from pipecat.frames.frames import MetricsFrame
from pipecat.metrics.metrics import LLMUsageMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed


class UsageObserver(BaseObserver):
    """Pipecat-native usage accumulator attached to PipelineTask as an observer.

    Intercepts every MetricsFrame pushed between processors without being
    injected into the pipeline chain — zero pipeline latency impact.

    Captures:
    - LLMUsageMetricsData  → prompt tokens, completion tokens, model name.
    - TTSUsageMetricsData  → character count sent to the TTS provider, model
                             name. This is the string passed to run_tts() after
                             sentence aggregation and text filtering — the value
                             the provider actually bills for. More accurate than
                             counting raw streaming TextFrames pre-aggregation.

    The model name fields record the last-seen model identifier per metric type,
    enabling per-model cost rate lookups when different accounts use different
    providers (e.g. gpt-4o vs gpt-4o-mini, sonic-2 vs sonic-english).

    All state is mutated from the Pipecat asyncio event loop; no locking needed.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._total_prompt_tokens: int = 0
        self._total_completion_tokens: int = 0
        self._total_tts_chars: int = 0
        self._llm_model: str = ""
        self._tts_model: str = ""

    @property
    def total_prompt_tokens(self) -> int:
        return self._total_prompt_tokens

    @property
    def total_completion_tokens(self) -> int:
        return self._total_completion_tokens

    @property
    def total_tts_chars(self) -> int:
        return self._total_tts_chars

    @property
    def llm_model(self) -> str:
        """Last LLM model name seen (e.g. 'gpt-4o', 'claude-3-opus')."""
        return self._llm_model

    @property
    def tts_model(self) -> str:
        """Last TTS model name seen (e.g. 'sonic-2', 'tts-1')."""
        return self._tts_model

    async def on_push_frame(self, data: FramePushed) -> None:
        if not isinstance(data.frame, MetricsFrame):
            return
        for metric in data.frame.data or []:
            if isinstance(metric, LLMUsageMetricsData):
                usage = metric.value
                self._total_prompt_tokens += usage.prompt_tokens
                self._total_completion_tokens += usage.completion_tokens
                if metric.model:
                    self._llm_model = metric.model
            elif isinstance(metric, TTSUsageMetricsData):
                self._total_tts_chars += metric.value
                if metric.model:
                    self._tts_model = metric.model
