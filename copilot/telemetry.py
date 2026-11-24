"""Bounded turn traces with optional OpenTelemetry console export."""
from contextlib import contextmanager, nullcontext
import sys
from time import perf_counter

MAX_STEPS = 10


class StepLimit(RuntimeError):
    pass


class Trace:
    def __init__(self, tracer=None):
        self.tracer = tracer
        self.steps = []

    @contextmanager
    def step(self, stage, name):
        if len(self.steps) >= MAX_STEPS:
            raise StepLimit("The request reached its step limit.")
        row = {"stage": stage, "operation": name, "status": "ok"}
        self.steps.append(row)
        start = perf_counter()
        span_context = (
            self.tracer.start_as_current_span(f"copilot.{stage}.{name}", record_exception=False,
                                              set_status_on_exception=False)
            if self.tracer else nullcontext()
        )
        with span_context as span:
            try:
                yield row
            except Exception as exc:
                row["status"] = "error"
                row["error_type"] = type(exc).__name__
                raise
            finally:
                row["duration_ms"] = round((perf_counter() - start) * 1000, 2)
                if span:
                    for key, value in row.items():
                        span.set_attribute(f"copilot.{key}", value)
                    if row["status"] == "error":
                        from opentelemetry.trace import Status, StatusCode
                        span.set_status(Status(StatusCode.ERROR))

    def turn(self):
        if self.tracer:
            return self.tracer.start_as_current_span("copilot.turn", record_exception=False,
                                                     set_status_on_exception=False)
        return nullcontext()



def console_tracer():
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "employee-ops-copilot"}))
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
    return provider.get_tracer("copilot")
