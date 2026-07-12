from __future__ import annotations

from dataclasses import dataclass

from .models import PIDGains, TelemetrySample


@dataclass
class FirstOrderPlant:
    """Simple saturated first-order plant for repeatable tuner tests."""

    time_constant: float = 1.2
    gain: float = 1.0
    output_limit: float = 10.0
    value: float = 0.0
    integral: float = 0.0
    previous_error: float = 0.0

    def reset(self) -> None:
        self.value = 0.0
        self.integral = 0.0
        self.previous_error = 0.0

    def run_step(
        self, gains: PIDGains, setpoint: float = 1.0,
        duration: float = 8.0, dt: float = 0.02, pre_seconds: float = 1.0,
    ) -> list[TelemetrySample]:
        self.reset()
        samples: list[TelemetrySample] = []
        count = int((pre_seconds + duration) / dt)
        for index in range(count):
            now = index * dt
            target = 0.0 if now < pre_seconds else setpoint
            error = target - self.value
            self.integral += error * dt
            derivative = (error - self.previous_error) / dt
            output = (gains.kp * error + gains.ki * self.integral
                      + gains.kd * derivative)
            output = max(-self.output_limit, min(self.output_limit, output))
            self.value += dt * (-self.value + self.gain * output) / self.time_constant
            self.previous_error = error
            samples.append(TelemetrySample(now, target, self.value, output))
        return samples
