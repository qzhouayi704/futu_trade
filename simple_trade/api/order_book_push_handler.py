"""SDK callback bridge; the sink must be bounded and perform no disk/network I/O."""

from datetime import datetime, timezone
import logging

from futu import OrderBookHandlerBase, RET_OK


class OrderBookPushHandler(OrderBookHandlerBase):
    def __init__(self, sink, connection_id: str) -> None:
        super().__init__()
        self._sink = sink
        self.connection_id = connection_id

    def on_recv_rsp(self, rsp_pb):
        received_at = datetime.now(timezone.utc)
        ret, data = self.parse_rsp_pb(rsp_pb)
        if ret == RET_OK:
            try:
                self._sink(data, received_at, self.connection_id)
            except Exception:
                logging.exception("Order book capture callback failed")
        return ret, data
