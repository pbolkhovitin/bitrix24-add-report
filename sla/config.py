"""Configuration loading for SLA dashboard."""

import os
import json
from dataclasses import dataclass, field
from datetime import time, date
from typing import Optional, Dict, Any, List

import yaml

DEFAULT_CONFIG_PATH = "./config.yaml"
EXAMPLE_CONFIG_PATH = "./config.example.yaml"

DEFAULT_THRESHOLDS: Dict[str, Dict[str, int]] = {
    "default": {"first_response_minutes": 120, "resolution_minutes": 480},
    "1": {"first_response_minutes": 480, "resolution_minutes": 1440},
    "2": {"first_response_minutes": 240, "resolution_minutes": 960},
    "3": {"first_response_minutes": 60, "resolution_minutes": 480},
    "4": {"first_response_minutes": 15, "resolution_minutes": 240},
}


def _parse_time(s: str) -> time:
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]))


def _parse_holidays(raw: Any) -> set:
    holidays: set = set()
    if not raw:
        return holidays
    for h in raw:
        if isinstance(h, str):
            holidays.add(date.fromisoformat(h))
        elif isinstance(h, date):
            holidays.add(h)
    return holidays


@dataclass
class BitrixConfig:
    portal_url: str = ""
    webhook_user: str = ""
    webhook_token: str = ""
    tp_user_id: int = 0
    request_timeout: int = 30
    batch_size: int = 50


@dataclass
class SyncConfig:
    interval_minutes: int = 60


@dataclass
class WorkingHoursConfig:
    start: time = time(9, 0)
    end: time = time(18, 0)
    workdays: set = field(default_factory=lambda: {1, 2, 3, 4, 5})
    holidays: set = field(default_factory=set)


@dataclass
class SLAConfig:
    thresholds: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def get_threshold(self, priority: int) -> tuple:
        """Returns (first_response_minutes, resolution_minutes)."""
        key = str(priority)
        entry = self.thresholds.get(key) or self.thresholds.get("default", {})
        return (
            entry.get("first_response_minutes", 120),
            entry.get("resolution_minutes", 480),
        )


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class DeviationConfig:
    stuck_days_threshold: int = 2
    comment_window_minutes: int = 60
    min_result_comment_length: int = 20


@dataclass
class StageConfig:
    operator_minutes: int = 30
    dispatcher_minutes: int = 120
    head_minutes: int = 360


@dataclass
class MandatoryFieldsConfig:
    std_fields: List[str] = field(default_factory=lambda: ["DESCRIPTION"])
    uf_fields: List[str] = field(default_factory=list)


@dataclass
class ProcessConfig:
    deviations: DeviationConfig = field(default_factory=DeviationConfig)
    stages: StageConfig = field(default_factory=StageConfig)
    mandatory_fields: MandatoryFieldsConfig = field(default_factory=MandatoryFieldsConfig)
    status_mapping: Dict[str, str] = field(default_factory=dict)
    user_roles: Dict[str, str] = field(default_factory=dict)


@dataclass
class Settings:
    bitrix: BitrixConfig = field(default_factory=BitrixConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    working_hours: WorkingHoursConfig = field(default_factory=WorkingHoursConfig)
    sla: SLAConfig = field(default_factory=SLAConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    process: ProcessConfig = field(default_factory=ProcessConfig)
    demo: bool = False
    config_loaded: bool = False


def load_settings(path: Optional[str] = None) -> Settings:
    """Load settings from config YAML, with fallbacks and overrides."""
    if path is None:
        path = os.environ.get("SLA_CONFIG", DEFAULT_CONFIG_PATH)

    raw_config: dict = {}
    config_loaded = False

    for candidate in [path, EXAMPLE_CONFIG_PATH]:
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                raw_config = yaml.safe_load(f) or {}
                config_loaded = True
            break

    # Bitrix
    br = raw_config.get("bitrix", {}) or {}
    bitrix = BitrixConfig(
        portal_url=br.get("portal_url", ""),
        webhook_user=str(br.get("webhook_user", "")),
        webhook_token=br.get("webhook_token", ""),
        tp_user_id=int(br.get("tp_user_id", 0) or 0),
        request_timeout=int(br.get("request_timeout", 30)),
        batch_size=int(br.get("batch_size", 50)),
    )

    # Sync
    sr = raw_config.get("sync", {}) or {}
    sync = SyncConfig(interval_minutes=int(sr.get("interval_minutes", 60)))

    # Working hours
    whr = raw_config.get("working_hours", {}) or {}
    working_hours = WorkingHoursConfig(
        start=_parse_time(whr.get("start", "09:00")),
        end=_parse_time(whr.get("end", "18:00")),
        workdays={int(d) for d in whr.get("workdays", [1, 2, 3, 4, 5])},
        holidays=_parse_holidays(whr.get("holidays", [])),
    )

    # SLA
    slar = raw_config.get("sla", {}) or {}
    thresholds = dict(DEFAULT_THRESHOLDS)
    thresholds_raw = slar.get("thresholds", {}) or {}
    if thresholds_raw:
        for k, v in thresholds_raw.items():
            thresholds[str(k)] = v
    sla = SLAConfig(thresholds=thresholds)

    # Server
    serverr = raw_config.get("server", {}) or {}
    server = ServerConfig(
        host=serverr.get("host", "0.0.0.0"),
        port=int(serverr.get("port", 8080)),
    )

    # Process config
    procr = raw_config.get("process", {}) or {}
    devr = procr.get("deviations", {}) or {}
    stgr = procr.get("stages", {}) or {}
    mfr = procr.get("mandatory_fields", {}) or {}
    process = ProcessConfig(
        deviations=DeviationConfig(
            stuck_days_threshold=int(devr.get("stuck_days_threshold", 2)),
            comment_window_minutes=int(devr.get("comment_window_minutes", 60)),
            min_result_comment_length=int(devr.get("min_result_comment_length", 20)),
        ),
        stages=StageConfig(
            operator_minutes=int(stgr.get("operator_minutes", 30)),
            dispatcher_minutes=int(stgr.get("dispatcher_minutes", 120)),
            head_minutes=int(stgr.get("head_minutes", 360)),
        ),
        mandatory_fields=MandatoryFieldsConfig(
            std_fields=mfr.get("std_fields", ["DESCRIPTION"]),
            uf_fields=mfr.get("uf_fields", []),
        ),
        status_mapping=procr.get("status_mapping", {}),
        user_roles=procr.get("user_roles", {}),
    )

    # Demo detection
    demo = os.environ.get("SLA_DEMO", "") == "1"
    if not demo and (bitrix.webhook_token == "" or bitrix.webhook_token == "demo"):
        demo = True

    settings = Settings(
        bitrix=bitrix,
        sync=sync,
        working_hours=working_hours,
        sla=sla,
        server=server,
        process=process,
        demo=demo,
        config_loaded=config_loaded,
    )

    # Apply runtime overrides if present
    override_path = "sla_config_override.json"
    if os.path.exists(override_path):
        try:
            with open(override_path, "r") as f:
                overrides = json.load(f)
            _apply_overrides(settings, overrides)
        except Exception as e:
            print(f"Warning: failed to load config overrides: {e}")

    return settings


def _apply_overrides(settings: Settings, overrides: dict) -> None:
    """Apply runtime config overrides to settings."""
    if "thresholds" in overrides:
        for k, v in overrides["thresholds"].items():
            settings.sla.thresholds[str(k)] = v
    if "working_hours" in overrides:
        wh = overrides["working_hours"]
        if "start" in wh:
            settings.working_hours.start = _parse_time(wh["start"])
        if "end" in wh:
            settings.working_hours.end = _parse_time(wh["end"])
        if "workdays" in wh:
            settings.working_hours.workdays = {int(d) for d in wh["workdays"]}
        if "holidays" in wh:
            settings.working_hours.holidays = {date.fromisoformat(d) for d in wh["holidays"]}
    if "status_mapping" in overrides:
        settings.process.status_mapping.update(overrides["status_mapping"])
    if "stage_thresholds" in overrides:
        st = overrides["stage_thresholds"]
        if "operator_minutes" in st:
            settings.process.stages.operator_minutes = int(st["operator_minutes"])
        if "dispatcher_minutes" in st:
            settings.process.stages.dispatcher_minutes = int(st["dispatcher_minutes"])
        if "head_minutes" in st:
            settings.process.stages.head_minutes = int(st["head_minutes"])
