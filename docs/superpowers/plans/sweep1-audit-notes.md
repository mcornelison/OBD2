# Sweep 1 Audit Notes (scratch — deleted before merge)

Baseline: branch `sprint/reorg-sweep1-facades` @ df40ca2. Symbols captured
via `python -c "import ...; print(sorted(dir(m)))"` after adding `src/` to
`sys.path`. Imports routed through `src/obd/__init__.py` which already
loads the flat facades, so "flat" symbols reflect the facade's own
re-exports.

Convention: "canonical" in this doc refers to the actual module/package
that holds the real implementation. Where the 20-file spec said a single
file like `src/obd/config/loader.py`, the real landing spot is often the
package `__init__.py` (which re-exports from multiple submodules). Those
cases are noted explicitly.

## Audit summary
- PURE facades (safe to delete after `src/obd/__init__.py` rewrite): **17**
  (files 1-17)
- LOGIC (need migration before delete): **3** (obd_config_loader,
  shutdown_manager, shutdown_command)
- SUPERSEDED/DUPLICATE: **0**
- AMBIGUOUS (blockers): **1** (obd_config_loader — see BLOCKER below)
- ORPHANS (not imported anywhere outside the facade file itself): **8**
  (battery_monitor, power_monitor, calibration_manager,
  calibration_comparator, recommendation_ranker, ai_analyzer,
  ai_prompt_template, profile_switcher)

## BLOCKER — file 18 obd_config_loader.py is AMBIGUOUS

See `offices/pm/tech_debt/TD-reorg-sweep1-config-loader-divergence.md`.

Short version: the flat file `src/obd/obd_config_loader.py` is NOT a
re-export facade — it's 871 lines of real implementation with 24
function/class definitions. The specified canonical (`src/obd/config/loader.py`)
is ~584 lines and covers only `loadObdConfig`, `validateObdConfig`, and
constants. Fourteen getter functions in the flat file
(`getActiveProfile`, `getConfigSection`, `getLoggedParameters`,
`getPollingInterval`, `getRealtimeParameters`, `getStaticParameters`,
`shouldQueryStaticOnFirstConnection`, `getSimulatorConfig`,
`isSimulatorEnabled`, `getSimulatorProfilePath`, `getSimulatorScenarioPath`,
`getSimulatorConnectionDelay`, `getSimulatorUpdateInterval`,
`getSimulatorFailures`) are NOT in `config/loader.py`.

The same 14 getter functions DO exist in `src/obd/config/helpers.py` and
`src/obd/config/simulator.py`, and the package `src/obd/config/__init__.py`
re-exports all of them. So the `obd.config` PACKAGE is a strict superset
of `obd.obd_config_loader` in terms of public symbols. The flat file is a
duplicate implementation of logic that has already been decomposed into
helpers + simulator + loader in the config subpackage.

Per the decision tree in the sweep plan (file 18 has symbols not in the
nominated canonical module), this is AMBIGUOUS and the sweep is BLOCKED
pending CIO resolution.

Suggested resolution (CIO to confirm): treat canonical as the
`obd.config` PACKAGE (not the specific `loader.py` submodule), reclassify
as SUPERSEDED, and in Task 3 wire `src/obd/__init__.py` to re-export
from `obd.config` rather than `obd.obd_config_loader`. No symbol loss if
that path is taken.

## src/obd/data_logger.py
- Classification: PURE
- Canonical: `src/obd/data/logger.py` + `src/obd/data/realtime.py` + `src/obd/data/helpers.py` (flat file imports from `.data` package)
- Orphan: No (imported by `src/obd/__init__.py` and `src/obd/orchestrator.py`)
- Lines: 91, def/class count: 0
- Symbols (flat): `DataLoggerError`, `LoggedReading`, `LoggingState`, `LoggingStats`, `ObdDataLogger`, `ParameterNotSupportedError`, `ParameterReadError`, `RealtimeDataLogger`, `createDataLoggerFromConfig`, `createRealtimeLoggerFromConfig`, `logReading`, `queryParameter`, `verifyDataPersistence`
- Symbols in `obd.data.logger`: `DataLoggerError, LoggedReading, ObdDataLogger, ParameterNotSupportedError, ParameterReadError, OBD_AVAILABLE`
- Symbols in `obd.data.realtime`: `DataLoggerError, LoggedReading, LoggingState, LoggingStats, ObdDataLogger, ParameterNotSupportedError, ParameterReadError, RealtimeDataLogger`
- Symbols in `obd.data.helpers`: `DataLoggerError, LoggedReading, ObdDataLogger, RealtimeDataLogger, createDataLoggerFromConfig, createRealtimeLoggerFromConfig, logReading, queryParameter, verifyDataPersistence`
- Symbols in `obd.data` package: superset of all above
- Notes: all facade symbols are present in the `obd.data` package. Facade imports from `.data` (the package `__init__.py`), which itself re-exports from `logger`, `realtime`, and `helpers`. Safe PURE facade.

## src/obd/drive_detector.py
- Classification: PURE
- Canonical: `src/obd/drive` package (not just `detector.py`)
- Orphan: No (imported by `src/obd/__init__.py` and `src/obd/orchestrator.py`)
- Lines: 107, def/class count: 0
- Symbols (flat): `DEFAULT_DRIVE_END_DURATION_SECONDS`, `DEFAULT_DRIVE_END_RPM_THRESHOLD`, `DEFAULT_DRIVE_START_DURATION_SECONDS`, `DEFAULT_DRIVE_START_RPM_THRESHOLD`, `DRIVE_DETECTION_PARAMETERS`, `DetectorConfig`, `DetectorState`, `DetectorStats`, `DriveDetector`, `DriveDetectorConfigError`, `DriveDetectorError`, `DriveDetectorStateError`, `DriveSession`, `DriveState`, `MIN_INTER_DRIVE_SECONDS`, `createDriveDetectorFromConfig`, `getDefaultDriveDetectionConfig`, `getDriveDetectionConfig`, `isDriveDetectionEnabled`
- Symbols in `obd.drive.detector`: `DEFAULT_DRIVE_END_DURATION_SECONDS`, `DEFAULT_DRIVE_END_RPM_THRESHOLD`, `DEFAULT_DRIVE_START_DURATION_SECONDS`, `DEFAULT_DRIVE_START_RPM_THRESHOLD`, `DRIVE_DETECTION_PARAMETERS`, `DetectorConfig`, `DetectorState`, `DetectorStats`, `DriveDetector`, `DriveSession`, `DriveState`
- Notes: extra facade symbols (`DriveDetectorError`, `DriveDetectorConfigError`, `DriveDetectorStateError`, `MIN_INTER_DRIVE_SECONDS`, and the helper functions) live in sibling modules `drive/exceptions.py`, `drive/types.py`, `drive/helpers.py`. Flat file does `from obd.drive import (...)` — so canonical is the `obd.drive` package. Safe PURE facade.

## src/obd/vin_decoder.py
- Classification: PURE
- Canonical: `src/obd/vehicle` package (not just `vin_decoder.py`)
- Orphan: No (imported by `src/obd/__init__.py`, `src/obd/orchestrator.py`, `src/obd/vehicle/helpers.py`, `src/obd/vehicle/__init__.py`)
- Lines: 100, def/class count: 0
- Symbols (flat): `ApiCallResult`, `DEFAULT_API_TIMEOUT`, `NHTSA_API_BASE_URL`, `NHTSA_EXTRA_FIELDS`, `NHTSA_FIELD_MAPPING`, `VinApiError`, `VinApiTimeoutError`, `VinDecodeResult`, `VinDecoder`, `VinDecoderError`, `VinStorageError`, `VinValidationError`, `createVinDecoderFromConfig`, `decodeVinOnFirstConnection`, `getVehicleInfo`, `isVinDecoderEnabled`, `validateVinFormat`
- Symbols in `obd.vehicle.vin_decoder`: `ApiCallResult`, `DEFAULT_API_TIMEOUT`, `NHTSA_API_BASE_URL`, `NHTSA_EXTRA_FIELDS`, `NHTSA_FIELD_MAPPING`, `VinApiTimeoutError`, `VinDecodeResult`, `VinDecoder`, `VinStorageError`
- Notes: extra facade symbols (`VinDecoderError`, `VinValidationError`, `VinApiError`, plus helper functions) are in `obd.vehicle.exceptions` / `obd.vehicle.helpers`. All present in `obd.vehicle` package. Safe PURE facade.

## src/obd/static_data_collector.py
- Classification: PURE
- Canonical: `src/obd/vehicle` package
- Orphan: No (imported by `src/obd/__init__.py`)
- Lines: 78, def/class count: 0
- Symbols (flat): `CollectionResult`, `StaticDataCollector`, `StaticDataError`, `StaticDataStorageError`, `StaticReading`, `VinNotAvailableError`, `collectStaticDataOnFirstConnection`, `createStaticDataCollectorFromConfig`, `getStaticDataCount`, `verifyStaticDataExists`
- Symbols in `obd.vehicle.static_collector`: `CollectionResult`, `OBD_AVAILABLE`, `StaticDataCollector`, `StaticDataStorageError`, `StaticReading`, `VinNotAvailableError`
- Notes: extra facade symbols (`StaticDataError` and the helper functions) live in `obd.vehicle.exceptions` / `obd.vehicle.helpers` and are re-exported from the `obd.vehicle` package. Safe PURE facade.

## src/obd/profile_statistics.py
- Classification: PURE
- Canonical: `src/analysis/profile_statistics.py` (different top-level package) + `src/obd/statistics_engine.py` for `StatisticsEngine` / `ParameterStatistics` / `AnalysisResult`
- Orphan: No (imported by `src/obd/__init__.py` and `src/analysis/__init__.py`)
- Lines: 99, def/class count: 0
- Symbols (flat): `AnalysisResult`, `ParameterComparison`, `ParameterStatistics`, `ProfileComparison`, `ProfileComparisonResult`, `ProfileStatisticsError`, `ProfileStatisticsManager`, `ProfileStatisticsReport`, `SIGNIFICANCE_THRESHOLD`, `StatisticsEngine`, `compareProfiles`, `createProfileStatisticsManager`, `generateProfileReport`, `getAllProfilesStatistics`, `getProfileStatisticsSummary`, `getStatisticsSummary`
- Symbols in `analysis.profile_statistics`: `ParameterComparison`, `ProfileComparison`, `ProfileComparisonResult`, `ProfileStatisticsError`, `ProfileStatisticsManager`, `ProfileStatisticsReport`, `SIGNIFICANCE_THRESHOLD`, `StatisticsEngine`, `compareProfiles`, `createProfileStatisticsManager`, `generateProfileReport`, `getAllProfilesStatistics`, `getProfileStatisticsSummary`, `getStatisticsSummary`
- Notes: flat file also re-exports `AnalysisResult`, `ParameterStatistics` — those come from `statistics_engine.py` (imported in the flat file alongside the analysis package). Safe PURE facade. Task 3 wiring needs to route `AnalysisResult` / `ParameterStatistics` from `obd.statistics_engine` while the rest go from `analysis.profile_statistics`.

## src/obd/profile_manager.py
- Classification: PURE
- Canonical: `src/profile/manager.py` (+ `src/profile` package for helpers)
- Orphan: **No** — imported by `src/obd/orchestrator.py` (lines 1623, 1998) as `from .profile_manager import createProfileManagerFromConfig` and `createProfileSwitcherFromConfig`. NOT imported by `src/obd/__init__.py`.
- Lines: 110, def/class count: 0
- Symbols (flat): `DEFAULT_ALERT_THRESHOLDS`, `DEFAULT_POLLING_INTERVAL_MS`, `DEFAULT_PROFILE_DESCRIPTION`, `DEFAULT_PROFILE_ID`, `DEFAULT_PROFILE_NAME`, `Profile`, `ProfileDatabaseError`, `ProfileError`, `ProfileManager`, `ProfileNotFoundError`, `ProfileValidationError`, `createProfileManagerFromConfig`, `createProfileSwitcherFromConfig`, `getActiveProfileFromConfig`, `getDefaultProfile`, `getProfileByIdFromConfig`, `syncConfigProfilesToDatabase`
- Symbols in `profile.manager`: `DEFAULT_ALERT_THRESHOLDS`, `DEFAULT_POLLING_INTERVAL_MS`, `DEFAULT_PROFILE_DESCRIPTION`, `DEFAULT_PROFILE_ID`, `DEFAULT_PROFILE_NAME`, `Profile`, `ProfileDatabaseError`, `ProfileError`, `ProfileManager`, `ProfileNotFoundError`, `ProfileValidationError`, `getDefaultProfile`
- Notes: remaining symbols (`createProfileManagerFromConfig`, `createProfileSwitcherFromConfig`, `getActiveProfileFromConfig`, `getProfileByIdFromConfig`, `syncConfigProfilesToDatabase`) live elsewhere in the `profile` package (likely `profile/helpers.py`). Facade also re-exports `createProfileSwitcherFromConfig` which orchestrator uses. Safe PURE facade once those are confirmed re-exported from `profile` package — Task 3 will wire through `profile.*`. **Orchestrator will need its import updated.**

## src/obd/profile_switcher.py
- Classification: PURE
- Canonical: `src/profile/switcher.py` (+ `src/profile` package)
- Orphan: **YES** — no references found in `src/` or `tests/` outside the facade file itself (docstring reference only).
- Lines: 108, def/class count: 0
- Symbols (flat): `PROFILE_CHANGE_EVENT`, `PROFILE_SWITCH_ACTIVATED`, `PROFILE_SWITCH_REQUESTED`, `ProfileChangeEvent`, `ProfileNotFoundError`, `ProfileSwitchError`, `ProfileSwitchNotFoundError`, `ProfileSwitchPendingError`, `ProfileSwitcher`, `SwitcherState`, `createProfileSwitcherFromConfig`, `getActiveProfileIdFromConfig`, `getAvailableProfilesFromConfig`, `isProfileInConfig`
- Symbols in `profile.switcher`: `PROFILE_SWITCH_ACTIVATED`, `PROFILE_SWITCH_REQUESTED`, `ProfileChangeEvent`, `ProfileSwitchError`, `ProfileSwitchNotFoundError`, `ProfileSwitcher`, `SwitcherState`
- Notes: extra symbols (`PROFILE_CHANGE_EVENT`, `ProfileNotFoundError`, `ProfileSwitchPendingError`, `createProfileSwitcherFromConfig`, `getActiveProfileIdFromConfig`, `getAvailableProfilesFromConfig`, `isProfileInConfig`) live in `profile.exceptions` / `profile.helpers`. Safe PURE facade. Orphan — can be deleted outright in Task 7. Note: `createProfileSwitcherFromConfig` is ALSO exposed by `obd.profile_manager` flat facade (which IS referenced by orchestrator) — the duplication is confusing but not breaking.

## src/obd/alert_manager.py
- Classification: PURE
- Canonical: `src/alert` package (not just `alert/manager.py`)
- Orphan: No (imported by `src/obd/__init__.py` and `src/obd/orchestrator.py`)
- Lines: 106, def/class count: 0
- Symbols (flat): `ALERT_PRIORITIES`, `ALERT_TYPE_BOOST_PRESSURE_MAX`, `ALERT_TYPE_COOLANT_TEMP_CRITICAL`, `ALERT_TYPE_OIL_PRESSURE_LOW`, `ALERT_TYPE_RPM_REDLINE`, `AlertConfigurationError`, `AlertDatabaseError`, `AlertDirection`, `AlertError`, `AlertEvent`, `AlertManager`, `AlertState`, `AlertStats`, `AlertThreshold`, `DEFAULT_COOLDOWN_SECONDS`, `MIN_COOLDOWN_SECONDS`, `PARAMETER_ALERT_TYPES`, `THRESHOLD_KEY_TO_PARAMETER`, `checkThresholdValue`, `createAlertManagerFromConfig`, `getAlertThresholdsForProfile`, `getDefaultThresholds`, `isAlertingEnabled`
- Symbols in `alert.manager`: `AlertEvent`, `AlertManager`, `AlertState`, `AlertStats`, `AlertThreshold`, `DEFAULT_COOLDOWN_SECONDS`, `MIN_COOLDOWN_SECONDS`, `convertThresholds`
- Notes: extra symbols (constants `ALERT_TYPE_*`, `ALERT_PRIORITIES`, `PARAMETER_ALERT_TYPES`, `THRESHOLD_KEY_TO_PARAMETER`, `AlertDirection`, exceptions, helper functions) come from `alert.types` / `alert.exceptions` / `alert.helpers`. All present in `alert` package. Safe PURE facade.

## src/obd/battery_monitor.py
- Classification: PURE
- Canonical: `src/power/battery.py` (+ `src/power` package)
- Orphan: **YES** — no import statements in `src/` or `tests/` outside the facade file itself.
- Lines: 98, def/class count: 0
- Symbols (flat): `BATTERY_LOG_EVENT_CRITICAL`, `BATTERY_LOG_EVENT_SHUTDOWN`, `BATTERY_LOG_EVENT_VOLTAGE`, `BATTERY_LOG_EVENT_WARNING`, `BatteryConfigurationError`, `BatteryError`, `BatteryMonitor`, `BatteryState`, `BatteryStats`, `DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS`, `DEFAULT_CRITICAL_VOLTAGE`, `DEFAULT_POLLING_INTERVAL_SECONDS`, `DEFAULT_WARNING_VOLTAGE`, `MIN_POLLING_INTERVAL_SECONDS`, `VoltageReading`, `createAdcVoltageReader`, `createBatteryMonitorFromConfig`, `createMockVoltageReader`, `getBatteryMonitoringConfig`, `isBatteryMonitoringEnabled`
- Symbols in `power.battery`: `BATTERY_LOG_EVENT_CRITICAL`, `BATTERY_LOG_EVENT_SHUTDOWN`, `BATTERY_LOG_EVENT_VOLTAGE`, `BATTERY_LOG_EVENT_WARNING`, `BatteryMonitor`, `BatteryState`, `BatteryStats`, `DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS`, `DEFAULT_CRITICAL_VOLTAGE`, `DEFAULT_WARNING_VOLTAGE`, `MIN_POLLING_INTERVAL_SECONDS`, `VoltageReading`
- Notes: extra symbols (`BatteryError`, `BatteryConfigurationError`, `DEFAULT_POLLING_INTERVAL_SECONDS`, `createAdcVoltageReader`, `createBatteryMonitorFromConfig`, `createMockVoltageReader`, `getBatteryMonitoringConfig`, `isBatteryMonitoringEnabled`) live in sibling `power` modules. Safe PURE facade. Orphan — can be deleted outright in Task 7.

## src/obd/power_monitor.py
- Classification: PURE
- Canonical: `src/power/power.py` (+ `src/power` package)
- Orphan: **YES** — no import statements in `src/` or `tests/` outside the facade file itself.
- Lines: 103, def/class count: 0
- Symbols (flat): `DEFAULT_DISPLAY_DIM_PERCENTAGE`, `DEFAULT_POLLING_INTERVAL_SECONDS`, `DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS`, `MIN_POLLING_INTERVAL_SECONDS`, `POWER_LOG_EVENT_AC_POWER`, `POWER_LOG_EVENT_BATTERY_POWER`, `POWER_LOG_EVENT_POWER_SAVING_DISABLED`, `POWER_LOG_EVENT_POWER_SAVING_ENABLED`, `POWER_LOG_EVENT_TRANSITION_TO_AC`, `POWER_LOG_EVENT_TRANSITION_TO_BATTERY`, `PowerConfigurationError`, `PowerError`, `PowerMonitor`, `PowerMonitorState`, `PowerReading`, `PowerSource`, `PowerStats`, `createGpioPowerStatusReader`, `createI2cPowerStatusReader`, `createMockPowerStatusReader`, `createPowerMonitorFromConfig`, `getPowerMonitoringConfig`, `isPowerMonitoringEnabled`
- Symbols in `power.power`: `DEFAULT_DISPLAY_DIM_PERCENTAGE`, `DEFAULT_POLLING_INTERVAL_SECONDS`, `DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS`, `MIN_POLLING_INTERVAL_SECONDS`, `POWER_LOG_EVENT_AC_POWER`, `POWER_LOG_EVENT_BATTERY_POWER`, `POWER_LOG_EVENT_POWER_SAVING_DISABLED`, `POWER_LOG_EVENT_POWER_SAVING_ENABLED`, `POWER_LOG_EVENT_TRANSITION_TO_AC`, `POWER_LOG_EVENT_TRANSITION_TO_BATTERY`, `PowerMonitor`, `PowerMonitorState`, `PowerReading`, `PowerSource`, `PowerStats`
- Notes: extra symbols (`PowerError`, `PowerConfigurationError`, `create*PowerStatusReader`, `createPowerMonitorFromConfig`, `getPowerMonitoringConfig`, `isPowerMonitoringEnabled`) live in sibling `power` modules. Safe PURE facade. Orphan — can be deleted outright in Task 7.

## src/obd/calibration_manager.py
- Classification: PURE
- Canonical: `src/calibration/manager.py` (+ `src/calibration` package)
- Orphan: **YES** — no import statements in `src/` or `tests/` outside the facade file itself.
- Lines: 79, def/class count: 0
- Symbols (flat): `CalibrationError`, `CalibrationExportResult`, `CalibrationManager`, `CalibrationNotEnabledError`, `CalibrationReading`, `CalibrationSession`, `CalibrationSessionError`, `CalibrationState`, `CalibrationStats`, `INDEX_CALIBRATION_DATA_SESSION`, `INDEX_CALIBRATION_DATA_TIMESTAMP`, `SCHEMA_CALIBRATION_DATA`, `createCalibrationManagerFromConfig`, `exportCalibrationSession`, `getCalibrationConfig`, `isCalibrationModeEnabled`
- Symbols in `calibration.manager`: `CalibrationError`, `CalibrationExportResult`, `CalibrationManager`, `CalibrationNotEnabledError`, `CalibrationReading`, `CalibrationSession`, `CalibrationSessionError`, `CalibrationState`, `CalibrationStats`, `INDEX_CALIBRATION_DATA_SESSION`, `INDEX_CALIBRATION_DATA_TIMESTAMP`, `SCHEMA_CALIBRATION_DATA`, plus several private helper functions
- Notes: facade-level-only extras (`createCalibrationManagerFromConfig`, `exportCalibrationSession`, `getCalibrationConfig`, `isCalibrationModeEnabled`) are helper functions in sibling `calibration` modules. Safe PURE facade. Orphan — can be deleted outright.

## src/obd/calibration_comparator.py
- Classification: PURE
- Canonical: `src/calibration/comparator.py`
- Orphan: **YES** — no import statements in `src/` or `tests/` outside the facade file itself.
- Lines: 65, def/class count: 0
- Symbols (flat): `CalibrationComparator`, `CalibrationComparisonError`, `CalibrationSessionComparison`, `ComparisonExportResult`, `ParameterSessionStats`, `SIGNIFICANCE_THRESHOLD`, `SessionComparisonResult`, `compareCalibrationSessions`, `createCalibrationComparatorFromConfig`, `exportComparisonReport`
- Symbols in `calibration.comparator`: `CalibrationComparator`, `CalibrationComparisonError`, `CalibrationSessionComparison`, `ComparisonExportResult`, `ParameterSessionStats`, `SIGNIFICANCE_THRESHOLD`, `SessionComparisonResult`
- Notes: extra symbols (`compareCalibrationSessions`, `createCalibrationComparatorFromConfig`, `exportComparisonReport`) are helper functions in sibling `calibration` modules. Safe PURE facade. Orphan — can be deleted outright.

## src/obd/recommendation_ranker.py
- Classification: PURE
- Canonical: `src/ai/ranker.py` (+ `src/ai` package)
- Orphan: **YES** — no import statements in `src/` or `tests/` outside the facade file itself. (Only docstring/comment references in sibling files.)
- Lines: 89, def/class count: 0
- Symbols (flat): `ALL_KEYWORDS`, `DOMAIN_KEYWORDS`, `DUPLICATE_WINDOW_DAYS`, `PRIORITY_KEYWORDS`, `PriorityRank`, `RankedRecommendation`, `RecommendationRanker`, `RecommendationRankerError`, `SIMILARITY_THRESHOLD`, `SimilarityResult`, `calculateTextSimilarity`, `createRecommendationRankerFromConfig`, `extractKeywords`, `rankRecommendation`
- Symbols in `ai.ranker`: `ALL_KEYWORDS`, `DOMAIN_KEYWORDS`, `DUPLICATE_WINDOW_DAYS`, `PRIORITY_KEYWORDS`, `PriorityRank`, `RankedRecommendation`, `RecommendationRanker`, `SIMILARITY_THRESHOLD`, `SimilarityResult`, `calculateTextSimilarity`, `createRecommendationRankerFromConfig`, `extractKeywords`, `getDomainKeywords`, `getPriorityKeywords`, `rankRecommendation`
- Notes: extra symbol `RecommendationRankerError` lives in `ai.exceptions`. Safe PURE facade. Orphan — can be deleted outright.

## src/obd/ai_analyzer.py
- Classification: PURE
- Canonical: `src/ai/analyzer.py` + `src/ai/helpers.py` (via `src/ai` package)
- Orphan: **YES** — no import statements in `src/` or `tests/` outside the facade file itself. (Only docstring/comment references in sibling files.)
- Lines: 96, def/class count: 0
- Symbols (flat): `AiAnalyzer`, `AiAnalyzerError`, `AiAnalyzerGenerationError`, `AiAnalyzerLimitExceededError`, `AiAnalyzerNotAvailableError`, `AiRecommendation`, `AnalysisResult`, `AnalyzerState`, `AnalyzerStats`, `DEFAULT_MAX_ANALYSES_PER_DRIVE`, `OLLAMA_DEFAULT_BASE_URL`, `OLLAMA_GENERATE_TIMEOUT`, `connectAnalyzerToStatisticsEngine`, `createAiAnalyzerFromConfig`, `getAiAnalysisConfig`, `isAiAnalysisEnabled`
- Symbols in `ai.analyzer`: `AiAnalyzer`, `AiAnalyzerGenerationError`, `AiAnalyzerLimitExceededError`, `AiAnalyzerNotAvailableError`, `AiRecommendation`, `AnalysisResult`, `AnalyzerState`, `AnalyzerStats`, `DEFAULT_MAX_ANALYSES_PER_DRIVE`, `OLLAMA_DEFAULT_BASE_URL`, `OLLAMA_GENERATE_TIMEOUT`, plus `prepareDataWindow`
- Notes: extras (`AiAnalyzerError`, `connectAnalyzerToStatisticsEngine`, `createAiAnalyzerFromConfig`, `getAiAnalysisConfig`, `isAiAnalysisEnabled`) live in `ai.exceptions` / `ai.helpers` and are re-exported from `ai.__init__`. Safe PURE facade. Orphan — can be deleted outright.

## src/obd/ai_prompt_template.py
- Classification: PURE
- Canonical: `src/ai/prompt_template.py` (+ `src/ai` package)
- Orphan: **YES** — no import statements in `src/` or `tests/` outside the facade file itself.
- Lines: 98, def/class count: 0
- Symbols (flat): `AiPromptTemplate`, `DEFAULT_PROMPT_TEMPLATE`, `FOCUS_AREA_TEMPLATES`, `FocusArea`, `GeneratedPrompt`, `InvalidTemplateError`, `METRIC_PLACEHOLDERS`, `MissingMetricsError`, `PromptMetrics`, `PromptTemplateError`, `VEHICLE_CONTEXT`, `buildPromptFromMetrics`, `createPromptTemplateFromConfig`, `extractMetricsFromStatistics`, `getDefaultPromptTemplate`, `getDefaultVehicleContext`, `getFocusAreaTemplates`
- Symbols in `ai.prompt_template`: `AiPromptTemplate`, `DEFAULT_PROMPT_TEMPLATE`, `FOCUS_AREA_TEMPLATES`, `FocusArea`, `GeneratedPrompt`, `METRIC_PLACEHOLDERS`, `VEHICLE_CONTEXT`, `buildPromptFromMetrics`, `createPromptTemplateFromConfig`, `extractMetricsFromStatistics`, `getDefaultPromptTemplate`, `getDefaultVehicleContext`, `getFocusAreaTemplates`
- Notes: extras (`InvalidTemplateError`, `MissingMetricsError`, `PromptTemplateError`, `PromptMetrics`) live in `ai.exceptions` / `ai.types` and are re-exported from `ai.__init__`. Safe PURE facade. Orphan — can be deleted outright.

## src/obd/display_manager.py
- Classification: PURE
- Canonical: `src/display` package (flat imports from top-level `display.*` — note: uses `display.drivers` etc., NOT `src.display.drivers`)
- Orphan: No (imported by `src/obd/__init__.py` and `src/obd/orchestrator.py`)
- Lines: 102, def/class count: 0
- Symbols (flat): `AlertInfo`, `BaseDisplayDriver`, `DeveloperDisplayDriver`, `DisplayError`, `DisplayInitializationError`, `DisplayManager`, `DisplayMode`, `DisplayOutputError`, `HeadlessDisplayDriver`, `MinimalDisplayDriver`, `NullDisplayAdapter`, `StatusInfo`, `createDisplayManagerFromConfig`, `getDisplayModeFromConfig`, `isDisplayAvailable`, `logger`, `logging`
- Symbols in `display.manager`: `AlertInfo`, `BaseDisplayDriver`, `DeveloperDisplayDriver`, `DisplayManager`, `DisplayMode`, `HeadlessDisplayDriver`, `MinimalDisplayDriver`, `StatusInfo`
- Notes: extras (`DisplayError`, `DisplayInitializationError`, `DisplayOutputError`, `NullDisplayAdapter`, helper functions) are in `display.exceptions` / `display.drivers` / `display.helpers`. Safe PURE facade. Also aliases `_NullDisplayAdapter = NullDisplayAdapter` for backwards compat with private name — Task 3 wiring should preserve that alias if any callers use it (a grep for `_NullDisplayAdapter` outside the flat file shows no hits, so it can be dropped).

## src/obd/adafruit_display.py
- Classification: PURE
- Canonical: `src/display/adapters/adafruit.py`
- Orphan: No (imported by `src/obd/__init__.py` — wrapped in `try/except (ImportError, NotImplementedError, RuntimeError)` so it can fall back to stubs on non-Pi hosts)
- Lines: 65, def/class count: 0
- Symbols (flat): `ADAFRUIT_AVAILABLE`, `AdafruitDisplayAdapter`, `Colors`, `DISPLAY_HEIGHT`, `DISPLAY_WIDTH`, `DisplayAdapterError`, `DisplayInitializationError`, `DisplayRenderError`, `createAdafruitAdapter`, `isDisplayHardwareAvailable`
- Symbols in `display.adapters.adafruit`: same set (superset: `board`, `digitalio`, `st7789`, `Image`, `ImageDraw`, `ImageFont` are module-level imports)
- Notes: flat file itself does NOT wrap imports in try/except — it imports unconditionally from `display.adapters.adafruit`. The canonical file DOES wrap the hardware library imports internally (via `try: import board; ... except: board = None`) and sets `ADAFRUIT_AVAILABLE` accordingly. The `try/except ImportError` fallback for the facade is provided by `src/obd/__init__.py` itself (lines 135-164), not by the facade. **Flag for Task 3**: when rewriting `__init__.py` to import directly from `display.adapters.adafruit`, preserve the `try/except (ImportError, NotImplementedError, RuntimeError)` wrapper and its stub fallbacks (`AdafruitDisplayAdapter = None`, `Colors = None`, `DisplayAdapterError = Exception`, `AdafruitDisplayInitializationError = Exception`, `DisplayRenderError = Exception`, `DISPLAY_WIDTH = 240`, `DISPLAY_HEIGHT = 240`, and the no-op `isDisplayHardwareAvailable`, `createAdafruitAdapter` functions). Canonical is safe, facade is PURE.

## src/obd/obd_config_loader.py
- Classification: **AMBIGUOUS / LOGIC (BLOCKER)**
- Canonical (as nominated in spec): `src/obd/config/loader.py` — **NOT a superset**
- Canonical (de facto, via package): `src/obd/config` package — IS a superset
- Orphan: No (imported by `src/obd/__init__.py`, `src/obd/simulator_integration.py`, `src/obd/obd_connection.py` (twice, lazy imports), `tests/test_obd_config_loader.py`)
- Lines: 871, def/class count: 24
- Symbols (flat): `Any`, `ConfigValidationError`, `ConfigValidator`, `OBD_DEFAULTS`, `OBD_REQUIRED_FIELDS`, `ObdConfigError`, `Path`, `VALID_DISPLAY_MODES`, `getActiveProfile`, `getConfigSection`, `getLoggedParameters`, `getPollingInterval`, `getRealtimeParameters`, `getSimulatorConfig`, `getSimulatorConnectionDelay`, `getSimulatorFailures`, `getSimulatorProfilePath`, `getSimulatorScenarioPath`, `getSimulatorUpdateInterval`, `getStaticParameters`, `isSimulatorEnabled`, `json`, `loadEnvFile`, `loadObdConfig`, `logger`, `logging`, `os`, `resolveSecrets`, `shouldQueryStaticOnFirstConnection`, `srcPath`, `sys`
- Symbols in `obd.config.loader` module only: `Any`, `ConfigValidationError`, `ConfigValidator`, `OBD_DEFAULTS`, `OBD_REQUIRED_FIELDS`, `ObdConfigError`, `Path`, `VALID_DISPLAY_MODES`, `json`, `loadEnvFile`, `loadObdConfig`, `logger`, `logging`, `os`, `resolveSecrets`, `srcPath`, `sys`, `validateObdConfig`
- Symbols in the flat file but NOT in `obd.config.loader` (excluding stdlib): `getActiveProfile`, `getConfigSection`, `getLoggedParameters`, `getPollingInterval`, `getRealtimeParameters`, `getSimulatorConfig`, `getSimulatorConnectionDelay`, `getSimulatorFailures`, `getSimulatorProfilePath`, `getSimulatorScenarioPath`, `getSimulatorUpdateInterval`, `getStaticParameters`, `isSimulatorEnabled`, `shouldQueryStaticOnFirstConnection` (14 functions)
- Symbols in `obd.config.loader` but NOT in flat: `validateObdConfig` (flat version is private `_validateObdConfig`)
- Same 14 missing functions ARE present in `obd.config.helpers` (7 functions) and `obd.config.simulator` (7 functions), and the `obd.config` package `__init__.py` re-exports all of them.
- Notes: flat file contains REAL IMPLEMENTATION code (24 def/class defs), not re-exports. It is a duplicate of logic that has already been decomposed into `config/loader.py` + `config/helpers.py` + `config/simulator.py`. Per the spec decision tree, this is AMBIGUOUS and the sweep is BLOCKED pending CIO resolution. Tech debt note created at `offices/pm/tech_debt/TD-reorg-sweep1-config-loader-divergence.md`.

## src/obd/shutdown_manager.py
- Classification: **LOGIC**
- Move target: `src/obd/shutdown/manager.py` (currently absent; `src/obd/shutdown/__init__.py` is empty placeholder)
- Orphan: No (imported by `src/obd/__init__.py`)
- Lines: 442, def/class count: 3
- Top-level public symbols (for Task 3 re-export wiring):
  - Constants: `SHUTDOWN_EVENT_TYPE`, `SHUTDOWN_EVENT_SIGTERM`, `SHUTDOWN_EVENT_SIGINT`, `SHUTDOWN_EVENT_GRACEFUL`
  - Classes: `ShutdownManager`
  - Functions: `createShutdownManager`, `installGlobalShutdownHandler`
- Symbols re-exported by current `src/obd/__init__.py`: `ShutdownManager`, `createShutdownManager`, `installGlobalShutdownHandler` (event constants are NOT in the current `__all__` — confirm whether to export them in Task 3)
- Notes: Must be physically moved to `src/obd/shutdown/manager.py` (not deleted) in Task 7. `src/obd/shutdown/__init__.py` currently says `__all__: list[str] = []` — needs to be updated in Task 3 to re-export the above symbols.

## src/obd/shutdown_command.py
- Classification: **LOGIC**
- Move target: `src/obd/shutdown/command.py` (currently absent)
- Orphan: No (imported by `src/obd/__init__.py`)
- Lines: 1158, def/class count: 19
- Top-level public symbols (for Task 3 re-export wiring):
  - Constants: `DEFAULT_SHUTDOWN_TIMEOUT`, `DEFAULT_GPIO_PIN`, `DEFAULT_PID_FILE`, `DEFAULT_SERVICE_NAME`, `SHUTDOWN_REASON_USER_REQUEST`, `SHUTDOWN_REASON_GPIO_BUTTON`, `SHUTDOWN_REASON_LOW_BATTERY`, `SHUTDOWN_REASON_MAINTENANCE`, `SHUTDOWN_REASON_SYSTEM`, `GPIO_AVAILABLE`
  - Classes (Enum / Exceptions / dataclasses): `ShutdownState` (Enum), `ShutdownCommandError` (Exception), `ProcessNotFoundError`, `ShutdownTimeoutError`, `GpioNotAvailableError`, `ShutdownResult`, `ShutdownConfig`, `ShutdownCommand`, `GpioButtonTrigger`
  - Functions: `generateShutdownScript`, `generateGpioTriggerScript`, `createShutdownCommandFromConfig`, `_parseShutdownConfig` (private), `isGpioAvailable`, `sendShutdownSignal`
- Symbols re-exported by current `src/obd/__init__.py`: `ShutdownCommand`, `ShutdownConfig`, `ShutdownResult`, `ShutdownState`, `ShutdownCommandError`, `ProcessNotFoundError`, `ShutdownTimeoutError`, `GpioNotAvailableError`, `GpioButtonTrigger`, `generateShutdownScript`, `generateGpioTriggerScript`, `createShutdownCommandFromConfig`, `isGpioAvailable`, `sendShutdownSignal`, `SHUTDOWN_REASON_USER_REQUEST`, `SHUTDOWN_REASON_GPIO_BUTTON`, `SHUTDOWN_REASON_LOW_BATTERY`, `SHUTDOWN_REASON_MAINTENANCE`, `SHUTDOWN_REASON_SYSTEM`
- Default / gpio / service constants (`DEFAULT_*`, `GPIO_AVAILABLE`) are NOT currently in `src/obd/__init__.py` `__all__` — Task 3 to decide whether to export them.
- Notes: Must be physically moved to `src/obd/shutdown/command.py` in Task 7. Much larger file than manager — contains the full shell script generators (for systemd shutdown and GPIO trigger) inline as heredoc strings.

## src/obd/shutdown/__init__.py (existing placeholder)
- Current state: empty placeholder.
- Contents: standard file header + docstring + `__all__: list[str] = []`. No `ShutdownManager`, `ShutdownCommand`, or related symbols defined or imported. Confirmed safe to rewrite in Task 3.
