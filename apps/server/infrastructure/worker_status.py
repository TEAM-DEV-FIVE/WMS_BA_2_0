"""Small structured records; never capture exceptions, credentials or payloads."""

import json
import logging
from uuid import uuid4

from sqlalchemy import text

LOGGER = logging.getLogger("wms.workers")


class WorkerStatus:
    def __init__(self, engine, kind, registry_hash):
        self.engine, self.kind, self.id = engine, kind, uuid4()
        with engine.begin() as c:
            c.execute(
                text("""INSERT INTO wms.worker_status(id,kind,registry_hash,state)
                VALUES (:id,:kind,:hash,'STARTING')"""),
                dict(id=self.id, kind=kind, hash=registry_hash),
            )

    def update(self, state, result=None, *, completed=False):
        with self.engine.begin() as c:
            c.execute(
                text("""UPDATE wms.worker_status SET state=:state,result_code=:result,
                heartbeat_at=clock_timestamp(),completed_cycles=completed_cycles+:completed WHERE id=:id"""),
                dict(id=self.id, state=state, result=result, completed=int(completed)),
            )
        log = LOGGER.debug if state == "BUSY" else LOGGER.info
        log(
            json.dumps(
                dict(
                    event="worker_status", worker_id=str(self.id), kind=self.kind, state=state, result=result
                ),
                sort_keys=True,
            )
        )
