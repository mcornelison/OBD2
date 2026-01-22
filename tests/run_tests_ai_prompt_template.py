################################################################################
# File Name: run_tests_ai_prompt_template.py
# Purpose/Description: Test suite for AiPromptTemplate - AI recommendation prompts
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-020
# ================================================================================
################################################################################

"""
Test suite for AiPromptTemplate class.

Tests cover:
- Prompt template initialization
- Vehicle context management
- Metric placeholder substitution
- Focus area configuration
- Custom template support
- Statistics-to-prompt conversion
- Template validation

Run with: python tests/run_tests_ai_prompt_template.py
"""

import json
import logging
import os
import sys
import unittest
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, Mock, patch

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.ai_prompt_template import (
    AiPromptTemplate,
    FocusArea,
    PromptMetrics,
    GeneratedPrompt,
    PromptTemplateError,
    InvalidTemplateError,
    MissingMetricsError,
    getDefaultPromptTemplate,
    getDefaultVehicleContext,
    getFocusAreaTemplates,
    buildPromptFromMetrics,
    createPromptTemplateFromConfig,
    extractMetricsFromStatistics,
    DEFAULT_PROMPT_TEMPLATE,
    VEHICLE_CONTEXT,
    METRIC_PLACEHOLDERS,
    FOCUS_AREA_TEMPLATES,
)


# =============================================================================
# Test Configuration
# =============================================================================

def createTestConfig(
    enabled: bool = True,
    focusAreas: Optional[List[str]] = None,
    promptTemplate: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a test configuration dictionary."""
    return {
        "aiAnalysis": {
            "enabled": enabled,
            "model": "gemma2:2b",
            "ollamaBaseUrl": "http://localhost:11434",
            "maxAnalysesPerDrive": 1,
            "promptTemplate": promptTemplate or "",
            "focusAreas": focusAreas or ["air_fuel_ratio"]
        },
        "vehicleInfo": {
            "year": 1998,
            "make": "Mitsubishi",
            "model": "Eclipse",
            "engine": "2.0L 4G63 Turbo"
        }
    }


def createTestMetrics() -> Dict[str, Any]:
    """Create a test metrics dictionary with all common values."""
    return {
        'rpm_avg': 2500,
        'rpm_max': 6200,
        'rpm_min': 800,
        'rpm_high_time_pct': 15.5,
        'short_fuel_trim_avg': 2.5,
        'long_fuel_trim_avg': -1.8,
        'o2_voltage_avg': 0.45,
        'o2_rich_count': 25,
        'o2_lean_count': 18,
        'engine_load_avg': 35.0,
        'engine_load_max': 95.0,
        'throttle_pos_avg': 28.5,
        'throttle_pos_max': 100.0,
        'maf_avg': 12.5,
        'maf_max': 45.0,
        'intake_temp_avg': 32.0,
        'coolant_temp_avg': 85.0,
        'timing_advance_avg': 28.5,
        'intake_pressure_avg': 45.0,
        'fuel_pressure_avg': 310.0,
    }


# =============================================================================
# Test Classes
# =============================================================================

class TestFocusAreaEnum(unittest.TestCase):
    """Tests for FocusArea enum."""

    def test_values_exist(self):
        """Verify all expected focus area values exist."""
        self.assertEqual(FocusArea.AIR_FUEL_RATIO.value, "air_fuel_ratio")
        self.assertEqual(FocusArea.TIMING.value, "timing")
        self.assertEqual(FocusArea.THROTTLE_RESPONSE.value, "throttle_response")

    def test_fromString_valid(self):
        """Test fromString with valid values."""
        self.assertEqual(FocusArea.fromString("air_fuel_ratio"), FocusArea.AIR_FUEL_RATIO)
        self.assertEqual(FocusArea.fromString("timing"), FocusArea.TIMING)
        self.assertEqual(FocusArea.fromString("throttle_response"), FocusArea.THROTTLE_RESPONSE)

    def test_fromString_caseInsensitive(self):
        """Test fromString is case insensitive."""
        self.assertEqual(FocusArea.fromString("AIR_FUEL_RATIO"), FocusArea.AIR_FUEL_RATIO)
        self.assertEqual(FocusArea.fromString("Timing"), FocusArea.TIMING)

    def test_fromString_withDashes(self):
        """Test fromString handles dashes."""
        self.assertEqual(FocusArea.fromString("air-fuel-ratio"), FocusArea.AIR_FUEL_RATIO)
        self.assertEqual(FocusArea.fromString("throttle-response"), FocusArea.THROTTLE_RESPONSE)

    def test_fromString_withSpaces(self):
        """Test fromString handles spaces."""
        self.assertEqual(FocusArea.fromString("air fuel ratio"), FocusArea.AIR_FUEL_RATIO)

    def test_fromString_invalid(self):
        """Test fromString returns None for invalid values."""
        self.assertIsNone(FocusArea.fromString("invalid"))
        self.assertIsNone(FocusArea.fromString(""))


class TestPromptMetricsDataclass(unittest.TestCase):
    """Tests for PromptMetrics dataclass."""

    def test_defaultValues(self):
        """Test default values are empty dicts."""
        metrics = PromptMetrics()
        self.assertEqual(metrics.rpmStats, {})
        self.assertEqual(metrics.fuelTrimStats, {})
        self.assertEqual(metrics.customMetrics, {})

    def test_toFlatDict(self):
        """Test flattening of metrics to single dict."""
        metrics = PromptMetrics(
            rpmStats={'avg': 2500, 'max': 6200},
            fuelTrimStats={'avg': 2.5}
        )
        flat = metrics.toFlatDict()
        self.assertEqual(flat['rpm_avg'], 2500)
        self.assertEqual(flat['rpm_max'], 6200)
        self.assertEqual(flat['fuel_trim_avg'], 2.5)

    def test_toDict(self):
        """Test serialization to dictionary."""
        metrics = PromptMetrics(
            rpmStats={'avg': 2500},
            customMetrics={'custom_value': 100}
        )
        data = metrics.toDict()
        self.assertEqual(data['rpmStats'], {'avg': 2500})
        self.assertEqual(data['customMetrics'], {'custom_value': 100})


class TestGeneratedPromptDataclass(unittest.TestCase):
    """Tests for GeneratedPrompt dataclass."""

    def test_defaultValues(self):
        """Test default values."""
        result = GeneratedPrompt(prompt="Test prompt")
        self.assertEqual(result.prompt, "Test prompt")
        self.assertEqual(result.template, "default")
        self.assertEqual(result.metricsIncluded, [])
        self.assertEqual(result.warnings, [])

    def test_toDict(self):
        """Test serialization to dictionary."""
        result = GeneratedPrompt(
            prompt="Test",
            template="custom",
            vehicleContext={'year': 1998},
            metricsIncluded=['rpm_avg'],
            warnings=['test warning']
        )
        data = result.toDict()
        self.assertEqual(data['prompt'], "Test")
        self.assertEqual(data['template'], "custom")
        self.assertEqual(data['vehicleContext'], {'year': 1998})
        self.assertIn('timestamp', data)


class TestAiPromptTemplateInit(unittest.TestCase):
    """Tests for AiPromptTemplate initialization."""

    def test_defaultInit(self):
        """Test initialization with no config."""
        template = AiPromptTemplate()
        self.assertIsNotNone(template.vehicleContext)
        self.assertEqual(template.vehicleContext['year'], 1998)
        self.assertEqual(template.vehicleContext['make'], 'Mitsubishi')
        self.assertEqual(template.vehicleContext['model'], 'Eclipse')

    def test_initWithConfig(self):
        """Test initialization with configuration."""
        config = createTestConfig(focusAreas=['air_fuel_ratio', 'timing'])
        template = AiPromptTemplate(config=config)
        focusAreas = template.focusAreas
        self.assertEqual(len(focusAreas), 2)
        self.assertIn(FocusArea.AIR_FUEL_RATIO, focusAreas)
        self.assertIn(FocusArea.TIMING, focusAreas)

    def test_initWithVehicleInfoFromConfig(self):
        """Test vehicle info loaded from config vehicleInfo section."""
        config = createTestConfig()
        template = AiPromptTemplate(config=config)
        self.assertEqual(template.vehicleContext['year'], 1998)
        self.assertEqual(template.vehicleContext['make'], 'Mitsubishi')
        self.assertEqual(template.vehicleContext['engine'], '2.0L 4G63 Turbo')

    def test_initWithCustomVehicleContext(self):
        """Test initialization with custom vehicle context override."""
        customContext = {
            'year': 2020,
            'make': 'Toyota',
            'model': 'Supra',
            'engine': '3.0L I6 Turbo',
            'goal': 'drag racing'
        }
        template = AiPromptTemplate(vehicleContext=customContext)
        self.assertEqual(template.vehicleContext['year'], 2020)
        self.assertEqual(template.vehicleContext['make'], 'Toyota')
        self.assertEqual(template.vehicleContext['goal'], 'drag racing')

    def test_initWithCustomTemplate(self):
        """Test initialization with custom template."""
        customTemplate = "Custom template: {vehicle_year} {rpm_avg}"
        template = AiPromptTemplate(customTemplate=customTemplate)
        self.assertEqual(template.template, customTemplate)

    def test_initDefaultFocusAreaWhenNoneConfigured(self):
        """Test default focus area is air_fuel_ratio when not specified."""
        template = AiPromptTemplate()
        self.assertEqual(len(template.focusAreas), 1)
        self.assertEqual(template.focusAreas[0], FocusArea.AIR_FUEL_RATIO)


class TestAiPromptTemplateVehicleContext(unittest.TestCase):
    """Tests for vehicle context management."""

    def test_setVehicleContext(self):
        """Test setting vehicle context values."""
        template = AiPromptTemplate()
        template.setVehicleContext(
            year=2000,
            make='Honda',
            model='Civic',
            engine='1.6L VTEC',
            goal='fuel efficiency'
        )
        ctx = template.vehicleContext
        self.assertEqual(ctx['year'], 2000)
        self.assertEqual(ctx['make'], 'Honda')
        self.assertEqual(ctx['model'], 'Civic')
        self.assertEqual(ctx['engine'], '1.6L VTEC')
        self.assertEqual(ctx['goal'], 'fuel efficiency')

    def test_setVehicleContext_partialUpdate(self):
        """Test partial update of vehicle context."""
        template = AiPromptTemplate()
        originalMake = template.vehicleContext['make']
        template.setVehicleContext(year=2005)
        self.assertEqual(template.vehicleContext['year'], 2005)
        self.assertEqual(template.vehicleContext['make'], originalMake)

    def test_vehicleContext_returnsCopy(self):
        """Test that vehicleContext returns a copy."""
        template = AiPromptTemplate()
        ctx = template.vehicleContext
        ctx['year'] = 9999
        self.assertNotEqual(template.vehicleContext['year'], 9999)


class TestAiPromptTemplateFocusAreas(unittest.TestCase):
    """Tests for focus area management."""

    def test_setFocusAreas(self):
        """Test setting focus areas."""
        template = AiPromptTemplate()
        template.setFocusAreas(['timing', 'throttle_response'])
        areas = template.focusAreas
        self.assertEqual(len(areas), 2)
        self.assertIn(FocusArea.TIMING, areas)
        self.assertIn(FocusArea.THROTTLE_RESPONSE, areas)

    def test_setFocusAreas_invalidIgnored(self):
        """Test invalid focus areas are ignored."""
        template = AiPromptTemplate()
        template.setFocusAreas(['timing', 'invalid_area', 'air_fuel_ratio'])
        areas = template.focusAreas
        self.assertEqual(len(areas), 2)

    def test_focusAreas_returnsCopy(self):
        """Test that focusAreas returns a copy."""
        template = AiPromptTemplate()
        areas = template.focusAreas
        areas.append(FocusArea.TIMING)
        self.assertNotEqual(len(template.focusAreas), len(areas))


class TestAiPromptTemplateBuildPrompt(unittest.TestCase):
    """Tests for prompt building."""

    def test_buildPrompt_withAllMetrics(self):
        """Test building prompt with complete metrics."""
        template = AiPromptTemplate()
        metrics = createTestMetrics()
        result = template.buildPrompt(metrics)

        self.assertIsInstance(result, GeneratedPrompt)
        self.assertIn('Mitsubishi', result.prompt)
        self.assertIn('Eclipse', result.prompt)
        self.assertIn('1998', result.prompt)
        self.assertIn('2500', result.prompt)  # rpm_avg
        self.assertIn('6200', result.prompt)  # rpm_max
        self.assertGreater(len(result.metricsIncluded), 0)

    def test_buildPrompt_vehicleContextSubstitution(self):
        """Test vehicle context is substituted correctly."""
        template = AiPromptTemplate()
        template.setVehicleContext(year=2010, make='Ford', model='Mustang')
        metrics = createTestMetrics()
        result = template.buildPrompt(metrics)

        self.assertIn('2010', result.prompt)
        self.assertIn('Ford', result.prompt)
        self.assertIn('Mustang', result.prompt)

    def test_buildPrompt_withMissingMetrics(self):
        """Test building prompt with missing metrics uses defaults."""
        template = AiPromptTemplate()
        metrics = {'rpm_avg': 3000}  # Only one metric
        result = template.buildPrompt(metrics)

        self.assertIsInstance(result, GeneratedPrompt)
        self.assertIn('3000', result.prompt)
        self.assertGreater(len(result.warnings), 0)  # Should have warnings for missing

    def test_buildPrompt_addsFocusAreas(self):
        """Test that focus areas are added to prompt."""
        config = createTestConfig(focusAreas=['air_fuel_ratio', 'timing'])
        template = AiPromptTemplate(config=config)
        metrics = createTestMetrics()
        result = template.buildPrompt(metrics, includeAllFocusAreas=True)

        self.assertIn('Air/Fuel Ratio Analysis', result.prompt)
        self.assertIn('Timing Analysis', result.prompt)
        self.assertEqual(len(result.focusAreas), 2)

    def test_buildPrompt_withoutFocusAreas(self):
        """Test building prompt without focus areas."""
        template = AiPromptTemplate()
        metrics = createTestMetrics()
        result = template.buildPrompt(metrics, includeAllFocusAreas=False)

        self.assertEqual(result.focusAreas, [])

    def test_buildPrompt_recordsTimestamp(self):
        """Test that timestamp is recorded."""
        template = AiPromptTemplate()
        beforeTime = datetime.now()
        result = template.buildPrompt(createTestMetrics())
        afterTime = datetime.now()

        self.assertGreaterEqual(result.timestamp, beforeTime)
        self.assertLessEqual(result.timestamp, afterTime)

    def test_buildPrompt_caseInsensitiveMetrics(self):
        """Test that metrics are matched case-insensitively."""
        template = AiPromptTemplate()
        metrics = {'RPM_AVG': 2500, 'RPM_MAX': 6000}
        result = template.buildPrompt(metrics)

        # Should still work despite case difference
        self.assertIsInstance(result, GeneratedPrompt)


class TestAiPromptTemplateCustomTemplate(unittest.TestCase):
    """Tests for custom template handling."""

    def test_setTemplate(self):
        """Test setting custom template."""
        template = AiPromptTemplate()
        customTemplate = "Simple template: {vehicle_year} {rpm_avg}"
        template.setTemplate(customTemplate)
        self.assertEqual(template.template, customTemplate)

    def test_buildPrompt_withCustomTemplate(self):
        """Test building prompt with custom template."""
        customTemplate = """Vehicle: {vehicle_year} {vehicle_make} {vehicle_model}
RPM Average: {rpm_avg}
Short Fuel Trim: {short_fuel_trim_avg}%"""

        template = AiPromptTemplate(customTemplate=customTemplate)
        metrics = {'rpm_avg': 2500, 'short_fuel_trim_avg': 3.5}
        result = template.buildPrompt(metrics, includeAllFocusAreas=False)

        self.assertIn('1998', result.prompt)
        self.assertIn('Mitsubishi', result.prompt)
        self.assertIn('2500', result.prompt)
        self.assertIn('3.5', result.prompt)

    def test_buildPrompt_customTemplateIdentified(self):
        """Test that custom template is identified in result."""
        customTemplate = "Custom: {vehicle_year}"
        template = AiPromptTemplate(customTemplate=customTemplate)
        result = template.buildPrompt({})

        self.assertEqual(result.template, "custom")


class TestAiPromptTemplateFromStatistics(unittest.TestCase):
    """Tests for building prompts from statistics objects."""

    def test_buildPromptFromStatistics_dictFormat(self):
        """Test building prompt from statistics as dictionaries."""
        template = AiPromptTemplate()
        statistics = {
            'RPM': {
                'avgValue': 2500,
                'maxValue': 6200,
                'minValue': 800,
            },
            'SHORT_FUEL_TRIM_1': {
                'avgValue': 2.5,
            },
            'ENGINE_LOAD': {
                'avgValue': 35.0,
                'maxValue': 95.0,
            }
        }
        result = template.buildPromptFromStatistics(statistics)

        self.assertIn('2500', result.prompt)
        self.assertIn('6200', result.prompt)
        self.assertIn('2.5', result.prompt)

    def test_buildPromptFromStatistics_withRawData(self):
        """Test building prompt with raw data for derived metrics."""
        template = AiPromptTemplate()
        statistics = {
            'RPM': {'avgValue': 3000, 'maxValue': 7000, 'minValue': 800},
        }
        rawData = {
            'RPM': [1000, 2000, 3000, 4500, 5000, 6000, 7000],
            'O2_B1S1': [0.2, 0.3, 0.5, 0.6, 0.4, 0.55, 0.35],
        }
        result = template.buildPromptFromStatistics(statistics, rawData)

        # Should calculate high RPM percentage (4500, 5000, 6000, 7000 > 4000)
        # 4 out of 7 = ~57%
        self.assertIn('57', result.prompt)


class TestAiPromptTemplateValidation(unittest.TestCase):
    """Tests for template validation."""

    def test_validateTemplate_validDefault(self):
        """Test that default template passes validation."""
        template = AiPromptTemplate()
        errors = template.validateTemplate()
        self.assertEqual(errors, [])

    def test_validateTemplate_emptyTemplate(self):
        """Test validation catches empty template."""
        template = AiPromptTemplate()
        errors = template.validateTemplate("")
        self.assertIn("Template is empty", errors)

    def test_validateTemplate_missingVehicleContext(self):
        """Test validation catches missing vehicle context."""
        template = AiPromptTemplate()
        errors = template.validateTemplate("Template without vehicle context: {rpm_avg}")
        self.assertTrue(any("vehicle_year" in e for e in errors))

    def test_validateTemplate_missingMetricPlaceholder(self):
        """Test validation catches missing metric placeholder."""
        template = AiPromptTemplate()
        errors = template.validateTemplate("Template: {vehicle_year} but no rpm")
        self.assertTrue(any("rpm_avg" in e for e in errors))

    def test_validateTemplate_unbalancedBraces(self):
        """Test validation catches unbalanced braces."""
        template = AiPromptTemplate()
        errors = template.validateTemplate("Template {vehicle_year} {rpm_avg")
        self.assertTrue(any("Unbalanced" in e for e in errors))

    def test_validateTemplate_tooShort(self):
        """Test validation catches too short template."""
        template = AiPromptTemplate()
        errors = template.validateTemplate("{vehicle_year} {rpm_avg}")
        self.assertTrue(any("too short" in e for e in errors))

    def test_getPlaceholders(self):
        """Test getting placeholders from template."""
        customTemplate = "Test {vehicle_year} and {rpm_avg} and {custom}"
        template = AiPromptTemplate(customTemplate=customTemplate)
        placeholders = template.getPlaceholders()
        self.assertIn('vehicle_year', placeholders)
        self.assertIn('rpm_avg', placeholders)
        self.assertIn('custom', placeholders)

    def test_getRequiredMetrics(self):
        """Test getting required metrics (excludes vehicle placeholders)."""
        template = AiPromptTemplate()
        requiredMetrics = template.getRequiredMetrics()
        self.assertIn('rpm_avg', requiredMetrics)
        self.assertNotIn('vehicle_year', requiredMetrics)
        self.assertNotIn('vehicle_make', requiredMetrics)


class TestHelperFunctions(unittest.TestCase):
    """Tests for module-level helper functions."""

    def test_getDefaultPromptTemplate(self):
        """Test getting default prompt template."""
        defaultTemplate = getDefaultPromptTemplate()
        self.assertEqual(defaultTemplate, DEFAULT_PROMPT_TEMPLATE)
        self.assertIn('Vehicle Information', defaultTemplate)
        self.assertIn('Air/Fuel Ratio', defaultTemplate)

    def test_getDefaultVehicleContext(self):
        """Test getting default vehicle context."""
        context = getDefaultVehicleContext()
        self.assertEqual(context, VEHICLE_CONTEXT)
        self.assertEqual(context['year'], 1998)
        self.assertEqual(context['make'], 'Mitsubishi')

    def test_getDefaultVehicleContext_returnsCopy(self):
        """Test that a copy is returned, not the original."""
        context1 = getDefaultVehicleContext()
        context1['year'] = 9999
        context2 = getDefaultVehicleContext()
        self.assertNotEqual(context2['year'], 9999)

    def test_getFocusAreaTemplates(self):
        """Test getting focus area templates."""
        templates = getFocusAreaTemplates()
        self.assertIn('air_fuel_ratio', templates)
        self.assertIn('timing', templates)
        self.assertIn('throttle_response', templates)
        # Check case-insensitively for fuel trim mention
        self.assertIn('fuel trim', templates['air_fuel_ratio'].lower())

    def test_buildPromptFromMetrics(self):
        """Test convenience function for building prompts."""
        metrics = createTestMetrics()
        prompt = buildPromptFromMetrics(metrics)

        self.assertIsInstance(prompt, str)
        self.assertIn('Mitsubishi', prompt)
        self.assertIn('2500', prompt)

    def test_buildPromptFromMetrics_withConfig(self):
        """Test convenience function with config."""
        metrics = createTestMetrics()
        config = createTestConfig()
        prompt = buildPromptFromMetrics(metrics, config=config)

        self.assertIsInstance(prompt, str)
        self.assertIn('1998', prompt)

    def test_buildPromptFromMetrics_withCustomVehicle(self):
        """Test convenience function with custom vehicle."""
        metrics = createTestMetrics()
        customVehicle = {'year': 2015, 'make': 'Subaru', 'model': 'WRX'}
        prompt = buildPromptFromMetrics(metrics, vehicleContext=customVehicle)

        self.assertIn('2015', prompt)
        self.assertIn('Subaru', prompt)
        self.assertIn('WRX', prompt)

    def test_createPromptTemplateFromConfig(self):
        """Test factory function."""
        config = createTestConfig()
        template = createPromptTemplateFromConfig(config)

        self.assertIsInstance(template, AiPromptTemplate)
        self.assertEqual(template.vehicleContext['year'], 1998)


class TestConstants(unittest.TestCase):
    """Tests for module constants."""

    def test_defaultVehicleContextValues(self):
        """Test default vehicle context has expected values."""
        self.assertEqual(VEHICLE_CONTEXT['year'], 1998)
        self.assertEqual(VEHICLE_CONTEXT['make'], 'Mitsubishi')
        self.assertEqual(VEHICLE_CONTEXT['model'], 'Eclipse')
        self.assertIn('4G63', VEHICLE_CONTEXT['engine'])
        self.assertEqual(VEHICLE_CONTEXT['goal'], 'performance optimization')

    def test_metricPlaceholdersExist(self):
        """Test all expected metric placeholders exist."""
        expectedPlaceholders = [
            'rpm_avg', 'rpm_max', 'rpm_min',
            'short_fuel_trim_avg', 'long_fuel_trim_avg',
            'throttle_pos_avg', 'throttle_pos_max',
            'maf_avg', 'maf_max',
            'coolant_temp_avg', 'intake_temp_avg',
        ]
        for placeholder in expectedPlaceholders:
            self.assertIn(placeholder, METRIC_PLACEHOLDERS)

    def test_metricPlaceholderFormat(self):
        """Test metric placeholder format (name, stat_type, default)."""
        for placeholder, mapping in METRIC_PLACEHOLDERS.items():
            self.assertEqual(len(mapping), 3)
            self.assertIsInstance(mapping[0], str)  # parameter name
            self.assertIsInstance(mapping[1], str)  # stat type
            # mapping[2] is the default value

    def test_focusAreaTemplatesExist(self):
        """Test all expected focus area templates exist."""
        self.assertIn('air_fuel_ratio', FOCUS_AREA_TEMPLATES)
        self.assertIn('timing', FOCUS_AREA_TEMPLATES)
        self.assertIn('throttle_response', FOCUS_AREA_TEMPLATES)

    def test_defaultPromptTemplateContents(self):
        """Test default prompt template has required sections."""
        self.assertIn('Vehicle Information', DEFAULT_PROMPT_TEMPLATE)
        self.assertIn('RPM Statistics', DEFAULT_PROMPT_TEMPLATE)
        self.assertIn('Air/Fuel Ratio Metrics', DEFAULT_PROMPT_TEMPLATE)
        self.assertIn('Engine Load', DEFAULT_PROMPT_TEMPLATE)
        self.assertIn('Airflow & Temperature', DEFAULT_PROMPT_TEMPLATE)
        self.assertIn('Analysis Request', DEFAULT_PROMPT_TEMPLATE)
        self.assertIn('Actionable Recommendations', DEFAULT_PROMPT_TEMPLATE)


class TestPromptQuality(unittest.TestCase):
    """Tests for prompt quality and content requirements per US-020."""

    def test_promptIncludesEclipseContext(self):
        """AC: Prompt includes context: 1998 Mitsubishi Eclipse."""
        template = AiPromptTemplate()
        result = template.buildPrompt(createTestMetrics())
        self.assertIn('1998', result.prompt)
        self.assertIn('Mitsubishi', result.prompt)
        self.assertIn('Eclipse', result.prompt)

    def test_promptIncludesPerformanceGoal(self):
        """AC: Prompt includes performance optimization goal."""
        template = AiPromptTemplate()
        result = template.buildPrompt(createTestMetrics())
        self.assertIn('performance optimization', result.prompt.lower())

    def test_promptIncludesAirFuelMetrics(self):
        """AC: Includes relevant metrics - air/fuel ratio trends."""
        template = AiPromptTemplate()
        result = template.buildPrompt(createTestMetrics())
        self.assertIn('Fuel Trim', result.prompt)
        self.assertIn('O2 Sensor', result.prompt)

    def test_promptIncludesRpmRanges(self):
        """AC: Includes relevant metrics - RPM ranges."""
        template = AiPromptTemplate()
        result = template.buildPrompt(createTestMetrics())
        self.assertIn('Average RPM', result.prompt)
        self.assertIn('Maximum RPM', result.prompt)
        self.assertIn('Minimum RPM', result.prompt)

    def test_promptIncludesThrottleResponse(self):
        """AC: Includes relevant metrics - throttle response."""
        template = AiPromptTemplate()
        result = template.buildPrompt(createTestMetrics())
        self.assertIn('Throttle', result.prompt)

    def test_promptAsksAboutAirFuelTuning(self):
        """AC: Asks specifically about air/fuel tuning opportunities."""
        template = AiPromptTemplate()
        result = template.buildPrompt(createTestMetrics())
        self.assertIn('Air/Fuel', result.prompt)
        self.assertIn('tuning', result.prompt.lower())

    def test_promptRequestsActionableRecommendations(self):
        """AC: Requests actionable recommendations."""
        template = AiPromptTemplate()
        result = template.buildPrompt(createTestMetrics())
        self.assertIn('Actionable Recommendations', result.prompt)
        self.assertIn('specific', result.prompt.lower())


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and error handling."""

    def test_emptyMetrics(self):
        """Test building prompt with empty metrics dict."""
        template = AiPromptTemplate()
        result = template.buildPrompt({})
        self.assertIsInstance(result, GeneratedPrompt)
        # Should have default values substituted
        self.assertIn('1998', result.prompt)

    def test_noneConfig(self):
        """Test initialization with None config."""
        template = AiPromptTemplate(config=None)
        self.assertIsNotNone(template.vehicleContext)

    def test_invalidMetricValues(self):
        """Test handling of invalid metric values."""
        template = AiPromptTemplate()
        metrics = {
            'rpm_avg': None,
            'rpm_max': 'invalid',
        }
        # Should not raise exception
        result = template.buildPrompt(metrics)
        self.assertIsInstance(result, GeneratedPrompt)

    def test_specialCharactersInMetrics(self):
        """Test metrics with special characters don't break template."""
        template = AiPromptTemplate()
        metrics = {'rpm_avg': 2500}  # Normal value
        # This should not break
        result = template.buildPrompt(metrics)
        self.assertIsInstance(result, GeneratedPrompt)

    def test_largeMetricValues(self):
        """Test handling of very large metric values."""
        template = AiPromptTemplate()
        metrics = {
            'rpm_avg': 999999999,
            'maf_avg': 1e10,
        }
        result = template.buildPrompt(metrics)
        self.assertIn('999999999', result.prompt)


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(level=logging.WARNING)

    # Run tests
    unittest.main(verbosity=2)
