"""
Raw Audio Frame Serializer - For direct browser PCM audio streaming.

Handles raw Int16 PCM audio from browser WebSocket without Protobuf encoding.
Simpler than Protobuf for test calls where we control both endpoints.
"""

from pipecat.serializers.base_serializer import FrameSerializer, FrameSerializerType
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
)
from loguru import logger


class RawAudioFrameSerializer(FrameSerializer):
    """
    Serializer for raw PCM audio from browser WebSocket.
    
    Browser sends: Int16Array as ArrayBuffer (raw PCM audio)
    Pipeline expects: InputAudioRawFrame
    
    Pipeline sends: OutputAudioRawFrame
    Browser expects: ArrayBuffer (raw PCM audio)
    """
    
    def __init__(self, sample_rate: int = 16000):
        """
        Initialize raw audio serializer.
        
        Args:
            sample_rate: Audio sample rate (default 16000 Hz for browser)
        """
        self._sample_rate = sample_rate
    
    @property
    def type(self) -> FrameSerializerType:
        """Binary serializer type."""
        return FrameSerializerType.BINARY
    
    async def serialize(self, frame: Frame) -> bytes | None:
        """
        Serialize OutputAudioRawFrame to raw PCM bytes.
        
        Args:
            frame: Pipecat frame to serialize
            
        Returns:
            Raw PCM audio bytes or None if not audio frame
        """
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        
        return None
    
    async def deserialize(self, data: bytes) -> Frame | None:
        """
        Deserialize raw PCM bytes to InputAudioRawFrame.
        
        Args:
            data: Raw PCM audio bytes from browser
            
        Returns:
            InputAudioRawFrame for Pipecat pipeline
        """
        if isinstance(data, bytes) and len(data) > 0:
            return InputAudioRawFrame(
                audio=data,
                sample_rate=self._sample_rate,
                num_channels=1,
            )
        
        logger.warning(f"Received invalid audio data: {type(data)}, len={len(data) if isinstance(data, bytes) else 'N/A'}")
        return None
