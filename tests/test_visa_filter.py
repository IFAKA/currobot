"""
Tests for backend/scrapers/visa_filter.py

Covers the three hard disqualifiers for the Spanish "canje"
(student stay → work authorization, Reglamento de Extranjería 2025):
  1. Temporal contract
  2. Part-time (media jornada / jornada reducida)
  3. Salary below SMI (€15,876/year gross)

Principle under test: only skip when explicitly disqualified.
Missing info → let through.
"""
import sys
import os

# Allow running from project root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock

# Patch structlog before importing the module so we don't need it installed
mock_structlog = MagicMock()
mock_structlog.get_logger.return_value = MagicMock()
sys.modules.setdefault("structlog", mock_structlog)

from backend.scrapers.visa_filter import (
    is_eligible,
    _check_hours,
    _check_salary,
    _parse_salary_amounts,
    _parse_number,
    SMI_MONTHLY_GROSS,
    SMI_ANNUAL_GROSS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def job(**kwargs) -> dict:
    """Build a minimal job_data dict with sane defaults."""
    return {
        "title": kwargs.get("title", "Cajero"),
        "description": kwargs.get("description", ""),
        "contract_type": kwargs.get("contract_type", ""),
        "salary_raw": kwargs.get("salary_raw", ""),
    }


def assert_eligible(job_data: dict):
    eligible, reason = is_eligible(job_data)
    assert eligible, f"Expected eligible but got skipped: {reason}"


def assert_skipped(job_data: dict, containing: str = ""):
    eligible, reason = is_eligible(job_data)
    assert not eligible, f"Expected skipped but was eligible"
    if containing:
        assert containing.lower() in (reason or "").lower(), (
            f"Expected reason to contain {containing!r}, got: {reason!r}"
        )


# ===========================================================================
# 1. CONTRACT TYPE
# ===========================================================================

class TestContractType:

    # --- Happy path: no contract info or indefinido ---

    def test_no_contract_info_passes(self):
        assert_eligible(job(title="Cajero supermercado"))

    def test_indefinido_in_contract_type_passes(self):
        assert_eligible(job(contract_type="indefinido"))

    def test_indefinido_in_title_passes(self):
        assert_eligible(job(title="Cajero contrato indefinido"))

    def test_indefinido_in_description_passes(self):
        assert_eligible(job(description="Ofrecemos contrato indefinido desde el primer día."))

    # --- Disqualifiers: explicit temporal keywords ---

    def test_temporal_contract_type(self):
        assert_skipped(job(contract_type="temporal"), "temporal")

    def test_temporal_in_title(self):
        assert_skipped(job(title="Cajero temporal campaña verano"), "temporal")

    def test_temporal_in_description(self):
        assert_skipped(job(description="Se ofrece contrato temporal de 3 meses."), "temporal")

    def test_fijo_discontinuo(self):
        assert_skipped(job(contract_type="fijo discontinuo"), "temporal")

    def test_fijo_discontinuo_hyphenated(self):
        assert_skipped(job(contract_type="fijo-discontinuo"), "temporal")

    def test_interinidad(self):
        assert_skipped(job(description="Contrato de interinidad por baja maternal."), "temporal")

    def test_interino_adjective(self):
        assert_skipped(job(title="Dependiente interino"), "temporal")

    def test_interina_adjective(self):
        assert_skipped(job(title="Cajera interina"), "temporal")

    def test_sustitucion(self):
        assert_skipped(job(description="Puesto de sustitución vacaciones verano."), "temporal")

    def test_eventual(self):
        assert_skipped(job(title="Auxiliar eventual campaña navidad"), "temporal")

    def test_por_obra(self):
        assert_skipped(job(contract_type="por obra"), "temporal")

    def test_obra_y_servicio(self):
        assert_skipped(job(description="Contrato por obra y servicio determinado."), "temporal")

    def test_obra_o_servicio(self):
        assert_skipped(job(description="Contrato por obra o servicio."), "temporal")

    def test_fixed_term_english(self):
        assert_skipped(job(contract_type="fixed-term"), "temporal")

    def test_duracion_determinada(self):
        assert_skipped(job(description="Contrato de duración determinada 6 meses."), "temporal")

    # --- Edge cases ---

    def test_word_temporal_inside_longer_word_still_matches(self):
        # "temporalmente" contains "temporal" — conservative, we still skip
        result, reason = is_eligible(job(description="Puesto cubierto temporalmente."))
        # This is expected behaviour: we're conservative and skip it
        assert not result

    def test_empty_strings_pass(self):
        assert_eligible(job(title="", description="", contract_type="", salary_raw=""))


# ===========================================================================
# 2. PART-TIME / WORKING HOURS
# ===========================================================================

class TestPartTime:

    # --- Happy path ---

    def test_no_hours_info_passes(self):
        assert_eligible(job(description="Jornada completa, turno rotativo."))

    def test_jornada_completa_passes(self):
        assert_eligible(job(description="Contrato jornada completa."))

    def test_40h_semana_passes(self):
        assert_eligible(job(description="40 horas semanales."))

    def test_38h_semana_passes(self):
        assert_eligible(job(description="38 horas semanales."))

    def test_35h_semana_passes(self):
        # Exactly 35h — boundary: we consider ≥35h as full-time
        assert_eligible(job(description="35 horas semanales."))

    # --- Disqualifiers: explicit part-time keywords ---

    def test_media_jornada(self):
        assert_skipped(job(description="Se ofrece media jornada mañanas."), "part-time")

    def test_tiempo_parcial(self):
        assert_skipped(job(contract_type="tiempo parcial"), "part-time")

    def test_jornada_parcial(self):
        assert_skipped(job(description="Jornada parcial, 4 horas diarias."), "part-time")

    def test_jornada_reducida(self):
        assert_skipped(job(description="Jornada reducida adaptable."), "part-time")

    def test_part_time_english(self):
        assert_skipped(job(contract_type="part-time"), "part-time")

    def test_part_time_no_hyphen(self):
        assert_skipped(job(description="Trabajo part time, fines de semana."), "part-time")

    # --- Disqualifiers: explicit low-hour counts ---

    def test_20h_semanales(self):
        assert_skipped(job(description="Jornada de 20 horas semanales."), "part-time hours")

    def test_25h_semana(self):
        assert_skipped(job(description="25h/semana, turno de mañana."), "part-time hours")

    def test_30h_semana(self):
        assert_skipped(job(description="30 horas semana."), "part-time hours")

    def test_34h_semana(self):
        assert_skipped(job(description="34 horas semanales."), "part-time hours")

    def test_h_abbreviation(self):
        assert_skipped(job(description="20h semanales."), "part-time hours")

    def test_hrs_abbreviation(self):
        assert_skipped(job(description="20 hrs/semana."), "part-time hours")


# ===========================================================================
# 3. SALARY
# ===========================================================================

class TestSalary:

    # --- Happy path ---

    def test_no_salary_passes(self):
        assert_eligible(job(salary_raw=""))

    def test_none_salary_passes(self):
        assert_eligible(job(salary_raw=None))

    def test_unparseable_salary_passes(self):
        # If we can't parse it, we let it through
        assert_eligible(job(salary_raw="A negociar según valía"))

    def test_salary_above_smi_monthly_passes(self):
        assert_eligible(job(salary_raw="1.200€/mes"))

    def test_salary_at_smi_monthly_passes(self):
        # Exactly at threshold → passes (≥ not >)
        assert_eligible(job(salary_raw=f"{int(SMI_MONTHLY_GROSS)}€/mes"))

    def test_salary_above_smi_annual_passes(self):
        assert_eligible(job(salary_raw="18.000€/año"))

    def test_salary_at_smi_annual_passes(self):
        assert_eligible(job(salary_raw=f"{int(SMI_ANNUAL_GROSS)}€/año"))

    def test_salary_range_max_above_smi_passes(self):
        assert_eligible(job(salary_raw="1000-1600 euros/mes"))

    def test_salary_range_both_above_smi_passes(self):
        assert_eligible(job(salary_raw="1.400-1.800€/mes"))

    def test_high_salary_no_period_passes(self):
        assert_eligible(job(salary_raw="1500€"))

    # --- Disqualifiers ---

    def test_monthly_below_smi(self):
        assert_skipped(job(salary_raw="900€/mes"), "salary too low")

    def test_monthly_just_below_smi(self):
        assert_skipped(job(salary_raw="1.100€/mes"), "salary too low")

    def test_annual_below_smi(self):
        assert_skipped(job(salary_raw="14.000€/año"), "salary too low")

    def test_annual_well_below_smi(self):
        assert_skipped(job(salary_raw="12.000 euros anuales"), "salary too low")

    def test_salary_range_max_still_below_smi(self):
        assert_skipped(job(salary_raw="1000-1100 euros/mes"), "salary too low")

    def test_low_bare_amount_with_currency(self):
        assert_skipped(job(salary_raw="800€"), "salary too low")

    def test_salary_in_description_below_smi(self):
        # Salary mentioned in description when salary_raw is empty
        assert_skipped(
            job(salary_raw="", description="Salario: 900€/mes brutos."),
            "salary too low",
        )


# ===========================================================================
# 4. COMBINED / INTERACTION TESTS
# ===========================================================================

class TestCombined:

    def test_temporal_plus_low_salary_skips_on_contract(self):
        # Contract check runs first; reason should be contract-related
        eligible, reason = is_eligible(job(
            contract_type="temporal",
            salary_raw="800€/mes",
        ))
        assert not eligible
        assert "temporal" in reason

    def test_parttime_plus_low_salary_skips_on_parttime(self):
        eligible, reason = is_eligible(job(
            description="media jornada mañanas",
            salary_raw="600€/mes",
        ))
        assert not eligible
        assert "part-time" in reason

    def test_all_good_passes(self):
        assert_eligible(job(
            title="Desarrollador Frontend React",
            contract_type="indefinido",
            description="Jornada completa 40h semanales. Proyecto estable.",
            salary_raw="2.500€/mes",
        ))

    def test_realistic_good_retail_job(self):
        assert_eligible(job(
            title="Cajero/a supermercado",
            contract_type="indefinido",
            description="Incorporación inmediata. Turnos rotativos. Contrato indefinido.",
            salary_raw="",  # salary not mentioned
        ))

    def test_realistic_bad_seasonal_job(self):
        assert_skipped(job(
            title="Dependiente/a campaña verano",
            contract_type="temporal",
            description="Contrato temporal junio-septiembre. Media jornada tarde.",
            salary_raw="700€/mes",
        ), "temporal")

    def test_realistic_internship_skips(self):
        assert_skipped(job(
            title="Prácticas frontend developer",
            description="Contrato en prácticas, 20 horas semanales.",
            salary_raw="600€/mes",
        ), "part-time hours")

    def test_good_tech_job_passes(self):
        assert_eligible(job(
            title="Frontend Developer React/Next.js",
            contract_type="indefinido",
            description="Posición senior, trabajo remoto. 40h semanales.",
            salary_raw="35.000€/año",
        ))


# ===========================================================================
# 5. UNIT TESTS FOR INTERNAL HELPERS
# ===========================================================================

class TestParseNumber:

    def test_plain_integer(self):
        assert _parse_number("1200") == 1200.0

    def test_european_thousands_dot(self):
        assert _parse_number("1.200") == 1200.0

    def test_european_decimal_comma(self):
        assert _parse_number("1200,50") == 1200.50

    def test_european_full(self):
        assert _parse_number("1.200,50") == 1200.50

    def test_lone_comma_is_decimal_european(self):
        # In Spanish number format a lone comma is a decimal separator:
        # "1,200" = €1.20 (not US €1,200). App targets Spanish job boards only.
        assert _parse_number("1,200") == 1.2

    def test_us_decimal_dot(self):
        assert _parse_number("1,200.50") == 1200.50

    def test_empty_returns_none(self):
        assert _parse_number("") is None

    def test_none_returns_none(self):
        assert _parse_number(None) is None

    def test_non_numeric_returns_none(self):
        assert _parse_number("abc") is None

    def test_large_annual_european(self):
        assert _parse_number("15.876") == 15876.0

    def test_large_annual_plain(self):
        assert _parse_number("15876") == 15876.0


class TestParseSalaryAmounts:

    def test_monthly_euros_symbol(self):
        results = _parse_salary_amounts("1.200€/mes")
        assert any(abs(amt - 1200) < 1 and pt == "monthly" for amt, pt in results)

    def test_annual_euros_symbol(self):
        results = _parse_salary_amounts("18.000€/año")
        assert any(abs(amt - 18000) < 1 and pt == "annual" for amt, pt in results)

    def test_monthly_range(self):
        results = _parse_salary_amounts("1000-1600 euros/mes")
        amounts = [a for a, p in results if p == "monthly"]
        assert 1000.0 in amounts or any(abs(a - 1000) < 1 for a in amounts)
        assert any(abs(a - 1600) < 1 for a in amounts)

    def test_annual_text_keyword(self):
        results = _parse_salary_amounts("12000 euros anuales")
        assert any(abs(amt - 12000) < 1 and pt == "annual" for amt, pt in results)

    def test_no_currency_no_period_ignored(self):
        # Bare numbers without context shouldn't be parsed
        results = _parse_salary_amounts("referencia 1234567")
        assert results == []

    def test_empty_string(self):
        assert _parse_salary_amounts("") == []


class TestCheckHours:

    def test_no_hours_returns_none(self):
        assert _check_hours("jornada completa turno mañana") is None

    def test_40h_returns_none(self):
        assert _check_hours("40 horas semanales") is None

    def test_35h_boundary_returns_none(self):
        assert _check_hours("35h semanales") is None

    def test_34h_returns_reason(self):
        assert _check_hours("34 horas semanales") is not None

    def test_20h_returns_reason(self):
        result = _check_hours("20 horas semanales")
        assert result is not None
        assert "20" in result

    def test_25h_slash_semana(self):
        assert _check_hours("25h/semana") is not None


class TestSMIConstants:

    def test_annual_equals_monthly_times_14(self):
        """SMI_ANNUAL = SMI_MONTHLY × 14 pays (the legal definition)."""
        assert abs(SMI_ANNUAL_GROSS - SMI_MONTHLY_GROSS * 14) < 0.01

    def test_constants_are_positive(self):
        assert SMI_MONTHLY_GROSS > 0
        assert SMI_ANNUAL_GROSS > 0

    def test_annual_greater_than_monthly(self):
        assert SMI_ANNUAL_GROSS > SMI_MONTHLY_GROSS
