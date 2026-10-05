"""Explicit subscriptions: unknown versions remain pending for investigation."""

import hashlib
import json

from apps.server.application import export_jobs, import_jobs, print_jobs
from apps.server.application.outbox import ConsumerRegistry


def consumer_factory():
    factories = (import_jobs.consumer_factory, export_jobs.consumer_factory, print_jobs.consumer_factory)
    consumers = []
    for factory in factories:
        registry = factory()
        for event_type in registry.event_types:
            consumers.extend(registry.consumers_for(event_type))
    return ConsumerRegistry(consumers)


def fingerprint(registry):
    subscriptions = [(t, c.name) for t in registry.event_types for c in registry.consumers_for(t)]
    return hashlib.sha256(json.dumps(subscriptions, separators=(",", ":")).encode()).hexdigest()
