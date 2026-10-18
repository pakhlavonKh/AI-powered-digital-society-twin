"""National (Türkiye-wide) synthetic population, cohorts, personas and controlled experiments.

Province is a dimension everywhere in this package: nothing here is written for one province.
The pipeline is

    official aggregate tables -> standard control tables (``controls``)
    -> dependency/constraint model (``model``, ``constraints``) -> generator (``generator``)
    -> source-fit validation (``validation``) -> cohorts -> personas -> experiments -> results.

The geography reference table (``geography``) lists all 81 provinces whether or not any
statistics are loaded for them; coverage is always reported separately from the reference list.
"""

GENERATOR_VERSION = "national-generator-1.0"
