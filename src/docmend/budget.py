"""Monotonic analysis deadline; synchronous CPU stages check at boundaries."""
import time
from .models import DocMendError

class Budget:
    def __init__(self, seconds: float):
        self.started=time.monotonic();self.deadline=self.started+seconds
    def remaining(self):
        left=self.deadline-time.monotonic()
        if left<=0:raise DocMendError('Analysis runtime budget exhausted; no complete result was produced')
        return left
    def elapsed_ms(self):return round((time.monotonic()-self.started)*1000,3)
