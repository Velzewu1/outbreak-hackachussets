"""Epidemic (SEIR) layer of the Boston hospital cascade model."""
from .adapter import EpiSnapshot, SEIRModule
from .config import (ContactMultiplier, DiseaseParams, Mixing, Population, ScenarioConfig,
                     Seeding, SimConfig)
from .engine import ChainBinomial, DayRecord, Deterministic, SEIREngine, simulate
from .mixing import (MixingOperator, aggregate_contacts, coupling_from_distance, coupling_from_flows,
                     haversine_km, reciprocal_contacts)
from .presets import DISEASES
from .rates import (FEEDBACK, Clip, Constant, Elastic, Piecewise, Product, RateSet, Seasonal,
                    Signal, TimeSeries, default_rates, with_feedback)
from .results import SEIRResult
from .structure import (STRUCTURES, ModelStructure, Transition, seir, seir_h, with_asymptomatic,
                        with_vaccination, with_waning)

__all__ = [
    "EpiSnapshot", "SEIRModule", "ScenarioConfig", "Seeding", "SEIREngine",
    "Deterministic", "ChainBinomial", "Constant", "Product", "RateSet", "Signal",
    "TimeSeries", "SEIRResult", "ModelStructure", "Transition", "seir", "seir_h",
    # added beyond the reference API
    "ContactMultiplier", "DiseaseParams", "Mixing", "Population", "SimConfig", "DayRecord",
    "simulate", "MixingOperator", "coupling_from_distance", "coupling_from_flows", "haversine_km",
    "aggregate_contacts", "reciprocal_contacts",
    "DISEASES", "FEEDBACK", "Clip", "Elastic", "Piecewise", "Seasonal", "default_rates",
    "with_feedback", "STRUCTURES", "with_asymptomatic", "with_vaccination", "with_waning",
]
