import os
import httpx
from opentelemetry.propagate import inject
from .db import Store
from .services import Service, DomainError


class LocalTransport:
    """Same service boundaries in one process; useful for offline development/tests."""
    def __init__(self, directory):
        self.services = {r:Service(r,Store(directory / f'{r}.sqlite'),self) for r in ('orders','payments','inventory')}

    def call(self, role, action, run, payload=None, correlation=None):
        return self.services[role].call(action,run,payload,correlation)

    def close(self):
        for service in self.services.values(): service.provider.shutdown()


class HTTPTransport:
    """No automatic mutation retries: callers deliberately replay idempotent operations."""
    def __init__(self, urls=None):
        self.urls = urls or {r:os.environ[f'{r.upper()}_URL'].rstrip('/') for r in ('orders','payments','inventory')}
        self.client = httpx.Client(timeout=10,trust_env=False)

    def call(self, role, action, run, payload=None, correlation=None):
        headers = {'X-Lab-Correlation':correlation or ''}
        if os.getenv('BLACKOUT_INTERNAL_TOKEN'):
            headers['X-Lab-Token'] = os.environ['BLACKOUT_INTERNAL_TOKEN']
        inject(headers)
        try:
            response = self.client.post(f'{self.urls[role]}/internal/{run}/{action}',json=payload or {},headers=headers)
        except httpx.HTTPError as exc:
            raise DomainError(f'{role} transport unavailable',503) from exc
        if response.is_error:
            try: detail = response.json().get('detail','Service operation failed')
            except ValueError: detail = 'Service operation failed'
            raise DomainError(str(detail),response.status_code)
        return response.json()

    def close(self): self.client.close()
