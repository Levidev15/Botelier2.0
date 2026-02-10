import re
from loguru import logger

from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, TextFrame, TTSSpeakFrame, LLMFullResponseEndFrame, InterruptionFrame, EndFrame, CancelFrame


def normalize_currency(text: str) -> str:
    def replace_with_cents(match):
        whole = match.group(1)
        cents = match.group(2)

        whole_int = int(whole)
        cents_int = int(cents)

        if whole_int == 0 and cents_int > 0:
            return f"{cents_int} cents"

        dollar_word = "dollar" if whole_int == 1 else "dollars"
        if cents_int > 0:
            cent_word = "cent" if cents_int == 1 else "cents"
            return f"{whole_int} {dollar_word} and {cents_int} {cent_word}"
        return f"{whole_int} {dollar_word}"

    def replace_whole(match):
        whole_int = int(match.group(1))
        dollar_word = "dollar" if whole_int == 1 else "dollars"
        return f"{whole_int} {dollar_word}"

    text = re.sub(r'\$(\d+)\.(\d{2})\s*cents?\b', replace_with_cents, text)
    text = re.sub(r'\$(\d+)\.(\d{2})\b', replace_with_cents, text)
    text = re.sub(r'\$(\d+)\s*dollars?\b', replace_whole, text)
    text = re.sub(r'\$(\d+)(?![\.\d])', replace_whole, text)

    return text


def normalize_percentage(text: str) -> str:
    text = re.sub(r'(\d+(?:\.\d+)?)%', r'\1 percent', text)
    return text


def normalize_common_symbols(text: str) -> str:
    text = re.sub(r'\b(\d+)\s*&\s*(\d+)\b', r'\1 and \2', text)
    text = re.sub(r'#(\d+)', r'number \1', text)
    text = re.sub(r'\b(\d+)\s*x\s*(\d+)\b', r'\1 by \2', text, flags=re.IGNORECASE)
    return text


def normalize_time(text: str) -> str:
    def replace_time(match):
        hour = int(match.group(1))
        minute = match.group(2)
        period = match.group(3).upper() if match.group(3) else ""

        if minute and int(minute) > 0:
            time_str = f"{hour} {minute}"
        else:
            time_str = f"{hour}"

        if period:
            spoken_period = "A M" if period == "AM" else "P M"
            time_str = f"{time_str} {spoken_period}"

        return time_str

    text = re.sub(r'\b(\d{1,2}):(\d{2})\s*(am|pm|AM|PM|a\.m\.|p\.m\.)\b', replace_time, text)
    text = re.sub(r'\b(\d{1,2}):(\d{2})\b(?!\s*(?:am|pm|AM|PM))', replace_time, text)
    return text


def normalize_text_for_tts(text: str) -> str:
    if not text or not text.strip():
        return text

    original = text
    text = normalize_currency(text)
    text = normalize_percentage(text)
    text = normalize_common_symbols(text)
    text = normalize_time(text)

    if text != original:
        logger.debug(f"TTS normalized: '{original[:80]}' → '{text[:80]}'")

    return text


CURRENCY_START = re.compile(r'\$\d')


class TTSTextNormalizer(FrameProcessor):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._buffer = ""
        self._buffering = False

    async def _flush_buffer(self, direction: FrameDirection):
        if self._buffer:
            normalized = normalize_text_for_tts(self._buffer)
            frame = TextFrame(text=normalized)
            await self.push_frame(frame, direction)
            self._buffer = ""
            self._buffering = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, TextFrame) and hasattr(frame, 'text') and frame.text:
            text = frame.text

            if self._buffering:
                self._buffer += text
                if re.search(r'\d[^$.\d]', self._buffer) or len(self._buffer) > 20:
                    await self._flush_buffer(direction)
                return

            if CURRENCY_START.search(text) or text == '$':
                self._buffering = True
                self._buffer = text
                return

            if re.search(r'[\$%#]|\d+[:.]\d', text):
                frame.text = normalize_text_for_tts(text)

            await self.push_frame(frame, direction)
            return

        if isinstance(frame, (LLMFullResponseEndFrame, InterruptionFrame, EndFrame, CancelFrame)):
            await self._flush_buffer(direction)
            await self.push_frame(frame, direction)
            return

        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, TTSSpeakFrame) and hasattr(frame, 'text') and frame.text:
            frame.text = normalize_text_for_tts(frame.text)

        await self.push_frame(frame, direction)
