"""Trace every domain operation; optionally export spans to a real OTLP collector."""
from contextlib import contextmanager
import os
import time
import uuid
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def build_tracer(service):
    provider = TracerProvider(resource=Resource.create({'service.name':'blackout.'+service}))
    endpoint = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT')
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip('/')+'/v1/traces')))
    return provider.get_tracer('blackout'), provider


@contextmanager
def operation(store, tracer, run, service, name, trace_key=None):
    correlation = trace_key or uuid.uuid4().hex
    start = time.perf_counter()
    with tracer.start_as_current_span(name, attributes={'lab.run':run,'lab.correlation':correlation}) as span:
        trace_id = f'{span.get_span_context().trace_id:032x}'
        try:
            yield correlation
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            store.log(run,service,'span',{'operation':name,'status':'error','error':str(exc),
                       'duration_ms':round((time.perf_counter()-start)*1000,3),'otel_trace_id':trace_id},correlation)
            raise
        else:
            store.log(run,service,'span',{'operation':name,'status':'ok',
                       'duration_ms':round((time.perf_counter()-start)*1000,3),'otel_trace_id':trace_id},correlation)
