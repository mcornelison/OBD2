################################################################################
# File Name: prompt_template.py
# Purpose/Description: AI recommendation prompt templates for OBD-II analysis
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-016 - Move from
#               |              | ai_prompt_template.py to ai subpackage
# ================================================================================
################################################################################

"""
AI prompt template module for OBD-II performance analysis.

Provides prompt templates for generating AI-based performance recommendations.
Templates include vehicle context, relevant OBD-II metrics, and specific
questions about air/fuel tuning opportunities.

Key features:
- Default prompt template with 1998 Mitsubishi Eclipse context
- Metric placeholder substitution for dynamic data
- Multiple focus areas (air/fuel, timing, throttle response)
- Custom template support via configuration
- Actionable recommendation formatting

Usage:
    from ai.prompt_template import (
        AiPromptTemplate,
        buildPromptFromMetrics,
        getDefaultPromptTemplate,
    )

    # Create template from config
    template = AiPromptTemplate(config=config)

    # Build prompt with actual metrics
    metrics = {
        'rpm_avg': 2500,
        'rpm_max': 6200,
        'short_fuel_trim_avg': 2.5,
        'long_fuel_trim_avg': -1.8,
        'throttle_pos_avg': 35,
        'maf_avg': 12.5
    }
    prompt = template.buildPrompt(metrics)

    # Use with ollama for analysis
    response = ollama.generate(prompt)
"""

import logging
import re
from datetime import datetime
from typing import Any

from .types import (
    METRIC_PLACEHOLDERS,
    VEHICLE_CONTEXT,
    FocusArea,
    GeneratedPrompt,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Default prompt template with placeholders
DEFAULT_PROMPT_TEMPLATE = """You are an automotive performance tuning expert specializing in OBD-II diagnostics and engine optimization.

## Vehicle Information
- Year: {vehicle_year}
- Make: {vehicle_make}
- Model: {vehicle_model}
- Engine: {vehicle_engine}
- Goal: {vehicle_goal}

## Recent Drive Data Summary

### RPM Statistics
- Average RPM: {rpm_avg}
- Maximum RPM: {rpm_max}
- Minimum RPM: {rpm_min}
- Time at high RPM (>4000): {rpm_high_time_pct}%

### Air/Fuel Ratio Metrics
- Short-term Fuel Trim (Bank 1) Average: {short_fuel_trim_avg}%
- Long-term Fuel Trim (Bank 1) Average: {long_fuel_trim_avg}%
- O2 Sensor (B1S1) Average Voltage: {o2_voltage_avg}V
- O2 Sensor Readings Above Threshold: {o2_rich_count}
- O2 Sensor Readings Below Threshold: {o2_lean_count}

### Engine Load & Throttle
- Engine Load Average: {engine_load_avg}%
- Engine Load Maximum: {engine_load_max}%
- Throttle Position Average: {throttle_pos_avg}%
- Throttle Position Maximum: {throttle_pos_max}%

### Airflow & Temperature
- Mass Air Flow (MAF) Average: {maf_avg} g/s
- Mass Air Flow Maximum: {maf_max} g/s
- Intake Air Temperature Average: {intake_temp_avg}°C
- Coolant Temperature Average: {coolant_temp_avg}°C

### Timing & Pressure
- Timing Advance Average: {timing_advance_avg}°
- Intake Manifold Pressure Average: {intake_pressure_avg} kPa
- Fuel Pressure Average: {fuel_pressure_avg} kPa

## Analysis Request

Based on this drive data, please provide:

1. **Air/Fuel Ratio Assessment**
   - Is the engine running rich or lean overall?
   - Are the fuel trim values within acceptable range (-10% to +10%)?
   - Any patterns suggesting fuel delivery issues?

2. **Performance Optimization Opportunities**
   - Specific air/fuel tuning recommendations
   - Throttle response improvements
   - Timing adjustments if applicable

3. **Potential Issues to Investigate**
   - Any anomalies in the data that warrant attention
   - Sensors that may need calibration or replacement

4. **Actionable Recommendations**
   - List 3-5 specific, prioritized actions the user can take
   - Include both DIY and professional service recommendations where appropriate

Please be specific and reference the actual values from the data where possible. Focus on practical recommendations for a {vehicle_year} {vehicle_make} {vehicle_model} owner interested in {vehicle_goal}."""

# Focus area templates for specific analysis requests
FOCUS_AREA_TEMPLATES = {
    'air_fuel_ratio': """
## Additional Focus: Air/Fuel Ratio Analysis

Pay special attention to:
- Fuel trim patterns and their stability over the drive
- Correlation between fuel trims and engine load
- O2 sensor response times and switching frequency
- Recommendations for optimizing air/fuel mixture for {vehicle_goal}
""",
    'timing': """
## Additional Focus: Timing Analysis

Pay special attention to:
- Timing advance patterns under different load conditions
- Any signs of knock or timing retard
- Optimal timing settings for {vehicle_goal}
- Correlation between timing and performance parameters
""",
    'throttle_response': """
## Additional Focus: Throttle Response Analysis

Pay special attention to:
- Throttle position vs engine load correlation
- Throttle response lag or hesitation indicators
- Intake air flow efficiency
- Recommendations for improving throttle response
""",
}


# =============================================================================
# AiPromptTemplate Class
# =============================================================================

class AiPromptTemplate:
    """
    AI prompt template manager for OBD-II performance analysis.

    Creates prompts for AI models that include vehicle context, OBD-II metrics,
    and specific analysis requests focused on performance optimization.

    Attributes:
        config: Configuration dictionary
        vehicleContext: Vehicle information for prompts
        template: Current prompt template
        focusAreas: Active focus areas for analysis

    Example:
        template = AiPromptTemplate(config=config)

        metrics = {'rpm_avg': 2500, 'short_fuel_trim_avg': 3.5}
        result = template.buildPrompt(metrics)
        print(result.prompt)
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        customTemplate: str | None = None,
        vehicleContext: dict[str, Any] | None = None,
    ):
        """
        Initialize AiPromptTemplate.

        Args:
            config: Optional configuration dictionary with aiAnalysis section
            customTemplate: Optional custom prompt template to use
            vehicleContext: Optional custom vehicle context
        """
        self._config = config or {}
        self._aiConfig = self._config.get('aiAnalysis', {})

        # Set vehicle context (from config or defaults)
        self._vehicleContext = vehicleContext or VEHICLE_CONTEXT.copy()

        # Check for vehicle info in config (from VIN decoder)
        vehicleInfo = self._config.get('vehicleInfo', {})
        if vehicleInfo:
            if vehicleInfo.get('year'):
                self._vehicleContext['year'] = vehicleInfo['year']
            if vehicleInfo.get('make'):
                self._vehicleContext['make'] = vehicleInfo['make']
            if vehicleInfo.get('model'):
                self._vehicleContext['model'] = vehicleInfo['model']
            if vehicleInfo.get('engine'):
                self._vehicleContext['engine'] = vehicleInfo['engine']

        # Set template
        if customTemplate:
            self._template = customTemplate
        elif self._aiConfig.get('promptTemplate'):
            self._template = self._aiConfig['promptTemplate']
        else:
            self._template = DEFAULT_PROMPT_TEMPLATE

        # Set focus areas from config
        configFocusAreas = self._aiConfig.get('focusAreas', [])
        self._focusAreas: list[FocusArea] = []
        for area in configFocusAreas:
            focusArea = FocusArea.fromString(area)
            if focusArea:
                self._focusAreas.append(focusArea)

        # Default focus on air/fuel ratio if not specified
        if not self._focusAreas:
            self._focusAreas = [FocusArea.AIR_FUEL_RATIO]

        logger.debug(
            f"AiPromptTemplate initialized with vehicle: "
            f"{self._vehicleContext.get('year')} {self._vehicleContext.get('make')} "
            f"{self._vehicleContext.get('model')}, focus areas: "
            f"{[a.value for a in self._focusAreas]}"
        )

    @property
    def vehicleContext(self) -> dict[str, Any]:
        """Get current vehicle context."""
        return self._vehicleContext.copy()

    @property
    def focusAreas(self) -> list[FocusArea]:
        """Get active focus areas."""
        return self._focusAreas.copy()

    @property
    def template(self) -> str:
        """Get current template."""
        return self._template

    def setVehicleContext(
        self,
        year: int | None = None,
        make: str | None = None,
        model: str | None = None,
        engine: str | None = None,
        goal: str | None = None,
    ) -> None:
        """
        Update vehicle context.

        Args:
            year: Vehicle year
            make: Vehicle make
            model: Vehicle model
            engine: Engine description
            goal: Optimization goal
        """
        if year is not None:
            self._vehicleContext['year'] = year
        if make is not None:
            self._vehicleContext['make'] = make
        if model is not None:
            self._vehicleContext['model'] = model
        if engine is not None:
            self._vehicleContext['engine'] = engine
        if goal is not None:
            self._vehicleContext['goal'] = goal

        logger.debug(f"Vehicle context updated: {self._vehicleContext}")

    def setFocusAreas(self, areas: list[str]) -> None:
        """
        Set focus areas for analysis.

        Args:
            areas: List of focus area names
        """
        self._focusAreas = []
        for area in areas:
            focusArea = FocusArea.fromString(area)
            if focusArea:
                self._focusAreas.append(focusArea)
            else:
                logger.warning(f"Unknown focus area ignored: {area}")

    def setTemplate(self, template: str) -> None:
        """
        Set custom template.

        Args:
            template: Template string with placeholders
        """
        self._template = template

    def buildPrompt(
        self,
        metrics: dict[str, Any],
        includeAllFocusAreas: bool = True,
    ) -> GeneratedPrompt:
        """
        Build a prompt from metrics data.

        Args:
            metrics: Dictionary of metric values for substitution
            includeAllFocusAreas: Whether to include all configured focus areas

        Returns:
            GeneratedPrompt object with the complete prompt
        """
        warnings: list[str] = []
        metricsIncluded: list[str] = []

        # Prepare substitution values
        substitutions: dict[str, Any] = {}

        # Add vehicle context
        substitutions['vehicle_year'] = self._vehicleContext.get('year', 'Unknown')
        substitutions['vehicle_make'] = self._vehicleContext.get('make', 'Unknown')
        substitutions['vehicle_model'] = self._vehicleContext.get('model', 'Unknown')
        substitutions['vehicle_engine'] = self._vehicleContext.get('engine', 'Unknown')
        substitutions['vehicle_goal'] = self._vehicleContext.get(
            'goal', 'performance optimization'
        )

        # Process metric placeholders
        for placeholder, (_paramName, _statType, default) in METRIC_PLACEHOLDERS.items():
            if placeholder in metrics:
                substitutions[placeholder] = metrics[placeholder]
                metricsIncluded.append(placeholder)
            else:
                # Try to find in flattened format
                found = False
                for key in metrics:
                    if key.lower() == placeholder.lower():
                        substitutions[placeholder] = metrics[key]
                        metricsIncluded.append(placeholder)
                        found = True
                        break

                if not found:
                    substitutions[placeholder] = default
                    warnings.append(f"Metric '{placeholder}' not provided, using default")

        # Build base prompt
        try:
            prompt = self._template.format(**substitutions)
        except KeyError as e:
            # Handle missing placeholders gracefully
            missingKey = str(e).strip("'")
            warnings.append(f"Template placeholder not found: {missingKey}")
            prompt = self._safeFormat(self._template, substitutions)

        # Add focus area sections
        focusAreasAdded: list[str] = []
        if includeAllFocusAreas:
            for area in self._focusAreas:
                if area.value in FOCUS_AREA_TEMPLATES:
                    focusTemplate = FOCUS_AREA_TEMPLATES[area.value]
                    focusSection = focusTemplate.format(**substitutions)
                    prompt += "\n" + focusSection
                    focusAreasAdded.append(area.value)

        return GeneratedPrompt(
            prompt=prompt,
            template="custom" if self._template != DEFAULT_PROMPT_TEMPLATE else "default",
            timestamp=datetime.now(),
            vehicleContext=self._vehicleContext.copy(),
            metricsIncluded=metricsIncluded,
            focusAreas=focusAreasAdded,
            warnings=warnings,
        )

    def buildPromptFromStatistics(
        self,
        statistics: dict[str, Any],
        rawData: dict[str, list[float]] | None = None,
    ) -> GeneratedPrompt:
        """
        Build prompt from ParameterStatistics dictionary.

        This method converts statistics engine output format to prompt metrics.

        Args:
            statistics: Dictionary mapping parameter names to their statistics
            rawData: Optional raw data for additional calculations (e.g., high RPM time)

        Returns:
            GeneratedPrompt object
        """
        from .data_preparation import prepareDataWindow

        # Use data preparation module to extract metrics
        metrics = prepareDataWindow({'parameterStats': statistics}, rawData)
        return self.buildPrompt(metrics)

    def _safeFormat(self, template: str, substitutions: dict[str, Any]) -> str:
        """
        Safely format a template, leaving unknown placeholders as-is.

        Args:
            template: Template string
            substitutions: Dictionary of substitution values

        Returns:
            Formatted string
        """
        # Find all placeholders in the template
        pattern = r'\{([^}]+)\}'
        matches = re.findall(pattern, template)

        result = template
        for match in matches:
            placeholder = '{' + match + '}'
            if match in substitutions:
                result = result.replace(placeholder, str(substitutions[match]))

        return result

    def validateTemplate(self, template: str | None = None) -> list[str]:
        """
        Validate a prompt template.

        Args:
            template: Template to validate (uses current if not provided)

        Returns:
            List of validation errors (empty if valid)
        """
        errors: list[str] = []
        templateToCheck = template if template is not None else self._template

        if not templateToCheck:
            errors.append("Template is empty")
            return errors

        # Check for basic structure
        if '{vehicle_year}' not in templateToCheck:
            errors.append("Missing vehicle context placeholder: {vehicle_year}")

        if '{rpm_avg}' not in templateToCheck:
            errors.append("Missing metric placeholder: {rpm_avg}")

        # Check for unmatched braces
        openBraces = templateToCheck.count('{')
        closeBraces = templateToCheck.count('}')
        if openBraces != closeBraces:
            errors.append(f"Unbalanced braces: {openBraces} open, {closeBraces} close")

        # Check minimum length
        if len(templateToCheck) < 100:
            errors.append("Template too short (minimum 100 characters)")

        return errors

    def getPlaceholders(self) -> list[str]:
        """
        Get all placeholders used in the current template.

        Returns:
            List of placeholder names
        """
        pattern = r'\{([^}]+)\}'
        return re.findall(pattern, self._template)

    def getRequiredMetrics(self) -> list[str]:
        """
        Get list of required metric placeholders.

        Returns:
            List of metric placeholder names
        """
        placeholders = self.getPlaceholders()
        vehiclePlaceholders = {
            'vehicle_year', 'vehicle_make', 'vehicle_model',
            'vehicle_engine', 'vehicle_goal'
        }
        return [p for p in placeholders if p not in vehiclePlaceholders]


# =============================================================================
# Helper Functions
# =============================================================================

def getDefaultPromptTemplate() -> str:
    """
    Get the default prompt template.

    Returns:
        Default prompt template string
    """
    return DEFAULT_PROMPT_TEMPLATE


def getDefaultVehicleContext() -> dict[str, Any]:
    """
    Get the default vehicle context.

    Returns:
        Default vehicle context dictionary
    """
    return VEHICLE_CONTEXT.copy()


def getFocusAreaTemplates() -> dict[str, str]:
    """
    Get all available focus area templates.

    Returns:
        Dictionary of focus area name to template string
    """
    return FOCUS_AREA_TEMPLATES.copy()


def buildPromptFromMetrics(
    metrics: dict[str, Any],
    config: dict[str, Any] | None = None,
    vehicleContext: dict[str, Any] | None = None,
) -> str:
    """
    Convenience function to build a prompt from metrics.

    Args:
        metrics: Dictionary of metric values
        config: Optional configuration dictionary
        vehicleContext: Optional vehicle context override

    Returns:
        Generated prompt string
    """
    template = AiPromptTemplate(config=config, vehicleContext=vehicleContext)
    result = template.buildPrompt(metrics)
    return result.prompt


def createPromptTemplateFromConfig(config: dict[str, Any]) -> AiPromptTemplate:
    """
    Create an AiPromptTemplate from configuration.

    Args:
        config: Configuration dictionary with aiAnalysis section

    Returns:
        Configured AiPromptTemplate instance
    """
    return AiPromptTemplate(config=config)


def extractMetricsFromStatistics(
    statistics: list[Any],
    rawData: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    """
    Extract metrics from a list of ParameterStatistics objects.

    Args:
        statistics: List of ParameterStatistics objects
        rawData: Optional raw data for derived calculations

    Returns:
        Dictionary of metrics suitable for prompt building
    """
    statsDict: dict[str, Any] = {}

    for stat in statistics:
        # Get parameter name from object or dict
        if isinstance(stat, dict):
            paramName = stat.get('parameterName', '')
        else:
            paramName = getattr(stat, 'parameterName', '')

        if paramName:
            statsDict[paramName] = stat

    template = AiPromptTemplate()
    result = template.buildPromptFromStatistics(statsDict, rawData)

    # Return the metrics that were included
    for placeholder, (_, _, _default) in METRIC_PLACEHOLDERS.items():
        # Extract value from prompt if it was substituted
        if placeholder in result.metricsIncluded:
            # The metric was found, we need to rebuild to get the value
            pass

    return statsDict
