"""add_mala_core_tables

Revision ID: v9w0x1y2z3a4
Revises: u8v9w0x1y2z3
Create Date: 2026-04-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "v9w0x1y2z3a4"
down_revision: Union[str, Sequence[str], None] = "u8v9w0x1y2z3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE candidate_puc_profiles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id) ON DELETE CASCADE UNIQUE,
            puc_vector vector(47),
            openness FLOAT, conscientiousness FLOAT, extraversion FLOAT,
            agreeableness FLOAT, emotional_stability FLOAT,
            big_five_confidence FLOAT,
            n_ach FLOAT, n_aff FLOAT, n_pow FLOAT,
            intrinsic_motivation FLOAT, temporal_orientation FLOAT,
            valence_mean FLOAT, arousal_mean FLOAT, dominance_mean FLOAT,
            emotional_intelligence FLOAT, error_management_score FLOAT,
            analytical_thinking FLOAT, cognitive_complexity FLOAT,
            ttr_score FLOAT, narrative_coherence FLOAT, causal_density FLOAT,
            locus_control FLOAT, accountability FLOAT,
            i_we_ratio FLOAT, agency_narrative FLOAT,
            integrity_score FLOAT, task_orientation FLOAT,
            motivator_hierarchy JSONB, deal_breakers JSONB,
            leadership_score FLOAT, collaboration_score FLOAT,
            written_communication FLOAT, adaptability_score FLOAT,
            resilience_score FLOAT,
            narrative_archetype VARCHAR(30),
            future_orientation FLOAT, goal_specificity FLOAT, churn_risk FLOAT,
            preferred_culture VARCHAR(50), ideal_modality VARCHAR(30),
            company_size_preference VARCHAR(30), management_style_compatible VARCHAR(30),
            completeness_score FLOAT DEFAULT 0.0,
            cross_layer_consistency FLOAT,
            social_desirability_flag BOOLEAN DEFAULT FALSE,
            confidence_level VARCHAR(10) DEFAULT 'low',
            questions_answered INTEGER DEFAULT 0,
            primary_archetype VARCHAR(50),
            archetype_probabilities JSONB,
            analysis_version VARCHAR(10) DEFAULT 'v2.0',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_puc_user ON candidate_puc_profiles(user_id)")
    op.execute("""
        CREATE INDEX idx_puc_vector ON candidate_puc_profiles
            USING ivfflat (puc_vector vector_cosine_ops) WITH (lists = 100)
    """)

    op.execute("""
        CREATE TABLE candidate_mala_responses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id) ON DELETE CASCADE,
            question_code VARCHAR(5) NOT NULL,
            question_block VARCHAR(1) NOT NULL,
            response_text TEXT NOT NULL,
            layer1_sentiment JSONB,
            layer2_nlp JSONB,
            layer3_liwc JSONB,
            layer4_neuro JSONB,
            layer5_synthesis JSONB,
            token_count INTEGER,
            word_count INTEGER,
            language VARCHAR(5) DEFAULT 'es',
            quality_score FLOAT,
            processing_status VARCHAR(20) DEFAULT 'pending',
            processing_error TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id, question_code)
        )
    """)
    op.execute("CREATE INDEX idx_mala_user ON candidate_mala_responses(user_id)")
    op.execute("CREATE INDEX idx_mala_status ON candidate_mala_responses(processing_status)")

    op.execute("""
        CREATE TABLE company_org_profiles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id) ON DELETE CASCADE UNIQUE,
            culture_vector vector(20),
            e1_culture_text TEXT,
            e2_no_fit_text TEXT,
            e3_decision_style_text TEXT,
            e4_best_hire_text TEXT,
            culture_valence FLOAT,
            affiliation_vs_achievement FLOAT,
            hierarchy_score FLOAT,
            management_archetype VARCHAR(30),
            org_openness FLOAT, org_conscientiousness FLOAT,
            org_extraversion FLOAT, org_agreeableness FLOAT, org_stability FLOAT,
            cultural_deal_breakers JSONB,
            anti_profile_signals JSONB,
            analysis_version VARCHAR(10) DEFAULT 'v2.0',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE job_match_configs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            job_id UUID REFERENCES jobs(id) ON DELETE CASCADE UNIQUE,
            e5_skills_vs_attitude TEXT,
            e6_team_description TEXT,
            e7_first_90_days TEXT,
            e8_success_signal TEXT,
            e9_failure_profile TEXT,
            req_openness_min FLOAT DEFAULT 0.0,
            req_conscientiousness_min FLOAT DEFAULT 0.0,
            req_extraversion_min FLOAT DEFAULT 0.0,
            req_agreeableness_min FLOAT DEFAULT 0.0,
            req_stability_min FLOAT DEFAULT 0.0,
            ideal_big_five_vector vector(5),
            weight_hard FLOAT DEFAULT 0.50,
            weight_soft FLOAT DEFAULT 0.30,
            weight_predictive FLOAT DEFAULT 0.20,
            min_experience_years INTEGER DEFAULT 0,
            required_education_level VARCHAR(30),
            required_languages JSONB DEFAULT '[]',
            hard_skills_required JSONB DEFAULT '[]',
            hard_skills_desired JSONB DEFAULT '[]',
            ideal_archetype VARCHAR(50),
            anti_profile_vector JSONB,
            interview_type VARCHAR(20) DEFAULT 'conductual',
            portfolio_required BOOLEAN DEFAULT FALSE,
            certification_required BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE match_scores (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            job_id UUID REFERENCES jobs(id),
            application_id UUID REFERENCES applications(id),
            total_score FLOAT,
            confidence_multiplier FLOAT DEFAULT 1.0,
            final_effective_score FLOAT,
            hard_match_score FLOAT,
            soft_match_score FLOAT,
            predictive_match_score FLOAT,
            skills_coverage FLOAT,
            experience_score FLOAT,
            education_score FLOAT,
            language_score FLOAT,
            hard_filter_passed BOOLEAN DEFAULT TRUE,
            big_five_fit FLOAT,
            mcclelland_culture_fit FLOAT,
            appraisal_values_fit FLOAT,
            career_narrative_fit FLOAT,
            top_strengths JSONB,
            top_alerts JSONB,
            interview_guide JSONB,
            explanation_text TEXT,
            recruiter_decision VARCHAR(20),
            recruiter_notes TEXT,
            decision_at TIMESTAMPTZ,
            calculated_at TIMESTAMPTZ DEFAULT NOW(),
            recalculated_at TIMESTAMPTZ,
            UNIQUE(user_id, job_id)
        )
    """)
    op.execute("CREATE INDEX idx_ms_job ON match_scores(job_id)")
    op.execute("CREATE INDEX idx_ms_score ON match_scores(job_id, final_effective_score DESC)")

    op.execute("""
        CREATE TABLE hiring_outcomes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            match_score_id UUID REFERENCES match_scores(id),
            user_id UUID REFERENCES users(id),
            job_id UUID REFERENCES jobs(id),
            company_id UUID REFERENCES companies(id),
            performance_3m FLOAT, retention_3m BOOLEAN, notes_3m TEXT,
            performance_6m FLOAT, retention_6m BOOLEAN, notes_6m TEXT,
            was_successful_hire BOOLEAN,
            tenure_months INTEGER,
            failure_reason VARCHAR(100),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hiring_outcomes")
    op.execute("DROP TABLE IF EXISTS match_scores")
    op.execute("DROP TABLE IF EXISTS job_match_configs")
    op.execute("DROP TABLE IF EXISTS company_org_profiles")
    op.execute("DROP TABLE IF EXISTS candidate_mala_responses")
    op.execute("DROP TABLE IF EXISTS candidate_puc_profiles")
