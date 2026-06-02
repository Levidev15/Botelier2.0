import unittest
from unittest.mock import AsyncMock, MagicMock

from pipecat.frames.frames import TTSAudioRawFrame, TTSStoppedFrame, EndFrame
from pipecat.transports.base_output import BaseOutputTransport, MediaSender


class TestTTSBufferFlush(unittest.IsolatedAsyncioTestCase):
    """Test that partial audio buffers are flushed when TTS stops."""

    async def test_partial_audio_buffer_flush_on_tts_stopped(self):
        """Test that TTSStoppedFrame triggers flush of partial audio buffer."""
        # Create mock transport and sender
        transport = MagicMock(spec=BaseOutputTransport)
        sender = MediaSender(transport)

        # Mock the transport's send_audio method
        transport.send_audio = AsyncMock()

        # Send a partial audio frame (less than buffer size)
        audio_data = b"partial_audio_data"  # Less than typical buffer size
        audio_frame = TTSAudioRawFrame(audio=audio_data, sample_rate=16000)
        await sender.handle_audio_frame(audio_frame)

        # At this point, audio should be buffered but not sent
        transport.send_audio.assert_not_called()

        # Send TTSStoppedFrame - this should trigger buffer flush
        stopped_frame = TTSStoppedFrame()
        await sender._handle_frame(stopped_frame)

        # Now the buffered audio should be sent
        transport.send_audio.assert_called_once()

        # Verify the call was made with the buffered audio
        call_args = transport.send_audio.call_args
        self.assertEqual(call_args[0][0], audio_data)  # audio data
        self.assertEqual(call_args[0][1], 16000)  # sample rate

    async def test_partial_audio_buffer_flush_on_end_frame(self):
        """Test that EndFrame also triggers flush of partial audio buffer."""
        # Create mock transport and sender
        transport = MagicMock(spec=BaseOutputTransport)
        sender = MediaSender(transport)

        # Mock the transport's send_audio method
        transport.send_audio = AsyncMock()

        # Send a partial audio frame
        audio_data = b"partial_audio_data"
        audio_frame = TTSAudioRawFrame(audio=audio_data, sample_rate=16000)
        await sender.handle_audio_frame(audio_frame)

        # Send EndFrame - this should also trigger buffer flush
        end_frame = EndFrame()
        await sender._handle_frame(end_frame)

        # Buffered audio should be sent
        transport.send_audio.assert_called_once()


if __name__ == "__main__":
    unittest.main()