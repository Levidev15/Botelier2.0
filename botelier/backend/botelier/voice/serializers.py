"""Custom Twilio WebSocket serializer for Botelier.

Pipecat's stock TwilioFrameSerializer.deserialize handles only `media` and
`dtmf` events and silently drops everything else (returns None).  In particular
it drops Twilio's `mark` acknowledgment events, which means
TwilioMarkWatcher.send_mark_and_wait() can never receive an ack and always
runs to its full timeout — producing dead air after the goodbye message.

BoteliTwilioFrameSerializer fixes this by intercepting `mark` events in
deserialize() and returning an InputTransportMessageFrame whose `.message` is
the raw parsed JSON dict.  Pipecat's FastAPIWebsocketInputTransport already
broadcasts InputTransportMessageFrame both upstream and downstream, so the
frame reaches TwilioMarkWatcher.process_frame which matches on
message["event"] == "mark" and resolves the pending asyncio.Event.

All other events are delegated to the parent class unchanged.
"""

import json

from pipecat.frames.frames import Frame, InputTransportMessageFrame
from pipecat.serializers.twilio import TwilioFrameSerializer


class BoteliTwilioFrameSerializer(TwilioFrameSerializer):
    """TwilioFrameSerializer extended to deliver mark acknowledgments.

    The only behavioral difference from the parent: when Twilio sends a
    ``mark`` event over the WebSocket, ``deserialize`` returns an
    ``InputTransportMessageFrame`` carrying the raw message dict instead of
    returning ``None``.  This allows ``TwilioMarkWatcher`` to receive and
    acknowledge playback marks so that post-speech hangup and transfer paths
    fire promptly instead of waiting out the full mark-timeout.
    """

    async def deserialize(self, data: str | bytes) -> Frame | None:
        message = json.loads(data)
        if message.get("event") == "mark":
            return InputTransportMessageFrame(message=message)
        return await super().deserialize(data)
