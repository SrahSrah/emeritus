"""Weather beat worker (FR-6).

Produces the next morning's run-window forecast and evaluates the freeze threshold
**from config**. The motivating job (PRD §1) is "weather that changes what she wears on a
6 am run", so the window is the 5–8 am slice the config names.

Scope, deliberately: this evaluates the threshold over the window the adapter actually
fetches. FR-10's prose implies a multi-day "freeze within N days" horizon; the NWS
adapter fetches the next morning only, FR-6's acceptance is scoped to that window, and
extending the forecast range is an open decision for Sarah rather than this beat's call.

No "what to wear" advice beyond what the numbers support.
"""

from __future__ import annotations

from typing import Any

from forecaster.beats.base import BeatContext, BeatItem, BeatResult, ObservationRef, register_beat
from forecaster.tools import mlb, weather


def _period_payload(period: weather.HourlyPeriod) -> dict[str, Any]:
    return {
        "startTime": period.start_time.isoformat(),
        "temperature": period.temperature,
        "temperatureUnit": period.temperature_unit,
        "windSpeed": period.wind_speed,
        "windDirection": period.wind_direction,
        "probabilityOfPrecipitation": period.precip_probability_pct,
        "shortForecast": period.short_forecast,
    }


@register_beat
class WeatherBeat:
    """`name = "weather"`."""

    name = "weather"
    completion_criterion = (
        "next morning's 5-8am run window reported with temperature, wind and precipitation "
        "probability, and the configured freeze threshold evaluated against it"
    )

    def should_run(self, context: BeatContext) -> bool:
        return bool(context.config.beats.get(self.name, False))

    def run(self, context: BeatContext) -> BeatResult:
        location = context.config.location
        run_config = context.config.run
        threshold = context.config.escalation.freeze_threshold_f

        arguments = {"lat": location.latitude, "lon": location.longitude}
        observation_id = context.trace.tool_call(
            beat=self.name, adapter=weather.ADAPTER_NAME, arguments=arguments
        )
        try:
            forecast = context.scratchpad.get_or_call(
                lambda: weather.fetch_hourly_forecast(
                    location.latitude, location.longitude, client=context.http_client
                ),
                beat=self.name,
                adapter=weather.ADAPTER_NAME,
                arguments=arguments,
            )
        except mlb.AdapterError as exc:
            context.trace.observation(observation_id, error=str(exc))
            raise

        morning = weather.next_morning(context.now)
        window = weather.run_window_periods(
            forecast.periods,
            day=morning,
            start=run_config.run_window_start,
            end=run_config.run_window_end,
        )

        context.trace.observation(
            observation_id,
            payload={
                "grid": forecast.grid.label,
                "morning": morning.isoformat(),
                "periods": [_period_payload(period) for period in window],
            },
        )
        ref = ObservationRef(observation_id, weather.ADAPTER_NAME)

        if not window:
            context.scratchpad.note_missing(
                self.name,
                f"the hourly forecast does not cover {morning} "
                f"{run_config.run_window_start}-{run_config.run_window_end}",
            )
            context.trace.decision(
                beat=self.name,
                decision="window_not_covered",
                reason=(
                    f"forecast returned {len(forecast.periods)} periods but none inside "
                    f"the {morning} run window"
                ),
            )
            return BeatResult.unavailable(
                self.name,
                f"the hourly forecast did not cover the {morning} run window",
                observations=[ref],
            )

        low = min(period.temperature for period in window)
        high = max(period.temperature for period in window)
        unit = window[0].temperature_unit
        precip = max(
            (period.precip_probability_pct or 0) for period in window
        )
        wind = window[0].wind_speed
        wind_direction = window[0].wind_direction

        freezing = low <= threshold
        context.trace.decision(
            beat=self.name,
            decision="freeze_threshold_evaluated",
            reason=(
                f"run-window low {low}{unit} vs configured threshold {threshold}"
                f"{unit}: {'at or below' if freezing else 'above'}"
            ),
            low=low,
            threshold=threshold,
        )

        summary = (
            f"Run window {run_config.run_window_start.strftime('%H:%M')}"
            f"-{run_config.run_window_end.strftime('%H:%M')}: "
            f"{low}-{high}{unit}, {wind} {wind_direction}, "
            f"{precip}% chance of precipitation."
        )

        return BeatResult(
            beat=self.name,
            items=[
                BeatItem(
                    beat=self.name,
                    text=summary,
                    fields={
                        "run_window_low_f": low,
                        "run_window_high_f": high,
                        "precip_probability_pct": precip,
                        "wind_speed": wind,
                        "grid": forecast.grid.label,
                        "morning": morning.isoformat(),
                    },
                    observations=[ref],
                )
            ],
            checkable_fields={
                "run_window_low_f": low,
                "run_window_high_f": high,
                "precip_probability_pct": precip,
                "wind_speed": wind,
            },
            available=True,
            escalation_candidate=freezing,
            escalation_reason=(
                f"run-window low {low}{unit} is at or below the configured freeze "
                f"threshold of {threshold}{unit}"
                if freezing
                else None
            ),
            observations=[ref],
        )


__all__ = ["WeatherBeat"]
